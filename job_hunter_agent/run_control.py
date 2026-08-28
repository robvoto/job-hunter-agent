"""Shared run stop control and structured progress model for background scrape jobs.

This module is the single owner of run-wide progress state.  It stores both:

* ``text``  — a human-readable progress string for logging and legacy consumers;
* ``detail`` — a typed, validated :class:`ProgressDetail` that the UI renders
  with a source badge, progress bar, and stage information instead of parsing
  arbitrary strings in the browser.

All public mutators are thread-safe via ``_RUN_PROGRESS_LOCK``.
"""

from __future__ import annotations

import contextvars
import logging
import sys
import threading
from dataclasses import asdict, dataclass
from typing import Any

from job_hunter_agent.logging_utils import format_debug_marker

_RUN_STOP_REQUESTED = threading.Event()
_RUN_SHUTDOWN_REQUESTED = threading.Event()
_RUN_PROGRESS_LOCK = threading.Lock()
_RUN_PROGRESS_TEXT = ""
_RUN_PROGRESS_DETAIL: ProgressDetail | None = None
_RUN_PROGRESS_SCOPE: contextvars.ContextVar[object | None] = contextvars.ContextVar(
    "job_hunter_run_progress_scope", default=None
)
_RUN_STOP_EVENT_SCOPE: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "job_hunter_run_stop_event", default=None
)
_RUN_SOURCE_TIMEOUT_EVENT_SCOPE: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "job_hunter_source_timeout_event", default=None
)
_RUN_ACTIVE_PROGRESS_SCOPE: object | None = None
_RUN_ACTIVE_STOP_EVENT: threading.Event | None = None
_RUN_PROGRESS_BY_SOURCE: dict[str, tuple[str, ProgressDetail | None]] = {}
logger = logging.getLogger(__name__)


class RunInterruptedError(RuntimeError):
    """Raised when server shutdown interrupts the active scrape lifecycle."""


def request_run_shutdown() -> None:
    """Mark the active run as interrupted and request cooperative source cleanup."""
    _RUN_SHUTDOWN_REQUESTED.set()
    request_run_stop()


def clear_run_shutdown_request() -> None:
    """Clear the process-local shutdown marker after the run worker has exited."""
    _RUN_SHUTDOWN_REQUESTED.clear()


def run_shutdown_requested() -> bool:
    """Return whether server shutdown interrupted the current run."""
    return _RUN_SHUTDOWN_REQUESTED.is_set()

# Manual job-by-job review debug aid, enabled via --step: pauses the scrape loop
# after every job's human summary is printed so it can be checked against the
# live posting before the next job runs.  Continue by pressing Enter in the
# terminal running the server.
_STEP_THROUGH_ENABLED = threading.Event()
_STEP_THROUGH_LOCK = threading.Lock()

# Stable source identifiers used across the structured progress model and the
# UI source-badge mapping.  Add new sources here — never invent ad-hoc strings
# in scrapers or templates.
VALID_SOURCES = frozenset({"seek", "linkedin", "apsjobs", "generic", None})

# Stage types describe *what kind* of work is happening. A current/total pair
# represents only that bounded stage; it must never be presented as overall-run progress.
VALID_STAGES = frozenset(
    {
        "starting",
        "source_collection",
        "job_detail",
        "deduplication",
        "relevance_analysis",
        "scoring",
        "saving",
        "finalising",
        "verification",
        "error",
    }
)


@dataclass(frozen=True)
class ProgressDetail:
    """Immutable, validated structured progress descriptor.

    Instances are created only through :func:`_validate_progress_detail`,
    which enforces source/stage validity and integer-range rules.
    """

    stage: str | None = None
    source: str | None = None
    headline: str = ""
    detail: str = ""
    current: int | None = None
    total: int | None = None
    item_current: int | None = None
    item_total: int | None = None
    determinate: bool = False


def enable_step_through() -> None:
    _STEP_THROUGH_ENABLED.set()


def step_through_enabled() -> bool:
    return _STEP_THROUGH_ENABLED.is_set()


def pause_for_step_through(label: str) -> None:
    """Block on stdin until the operator presses Enter. No-op unless --step is set."""
    if not _STEP_THROUGH_ENABLED.is_set():
        return
    with _STEP_THROUGH_LOCK:
        print(f"\n>>> [--step] {label} — press Enter in this terminal to continue... ", flush=True)
        sys.stdin.readline()


def request_run_stop() -> None:
    """Signal the active run, or the legacy global event when no run is scoped."""
    with _RUN_PROGRESS_LOCK:
        active_event = _RUN_ACTIVE_STOP_EVENT
    if active_event is not None:
        active_event.set()
    else:
        _RUN_STOP_REQUESTED.set()


def clear_run_stop_request() -> None:
    """Clear only currently active/legacy stop events, never detached worker events."""
    _RUN_STOP_REQUESTED.clear()
    with _RUN_PROGRESS_LOCK:
        active_event = _RUN_ACTIVE_STOP_EVENT
    if active_event is not None:
        active_event.clear()


def run_stop_requested() -> bool:
    source_timeout_event = _RUN_SOURCE_TIMEOUT_EVENT_SCOPE.get()
    if source_timeout_event is not None and source_timeout_event.is_set():
        return True
    scoped_event = _RUN_STOP_EVENT_SCOPE.get()
    if scoped_event is not None:
        return scoped_event.is_set()
    with _RUN_PROGRESS_LOCK:
        active_event = _RUN_ACTIVE_STOP_EVENT
    if active_event is not None:
        return active_event.is_set()
    return _RUN_STOP_REQUESTED.is_set()


def run_control_scope_active() -> bool:
    """Return whether the current execution context already owns run state."""
    return _RUN_PROGRESS_SCOPE.get() is not None


def begin_run_progress_scope() -> object:
    """Start isolated stop/progress state for one background run.

    Source workers inherit both values through ``contextvars.copy_context()``.
    A detached late worker therefore keeps its own stop event and cannot resume
    merely because a later run clears or replaces the active event.
    """
    global _RUN_ACTIVE_PROGRESS_SCOPE, _RUN_ACTIVE_STOP_EVENT
    global _RUN_PROGRESS_TEXT, _RUN_PROGRESS_DETAIL, _RUN_PROGRESS_BY_SOURCE

    scope = object()
    stop_event = threading.Event()
    with _RUN_PROGRESS_LOCK:
        if _RUN_ACTIVE_PROGRESS_SCOPE is not None:
            raise RuntimeError("Another scrape run already owns the active run-control scope.")
        _RUN_ACTIVE_PROGRESS_SCOPE = scope
        _RUN_ACTIVE_STOP_EVENT = stop_event
        _RUN_PROGRESS_TEXT = ""
        _RUN_PROGRESS_DETAIL = None
        _RUN_PROGRESS_BY_SOURCE = {}
    _RUN_PROGRESS_SCOPE.set(scope)
    _RUN_STOP_EVENT_SCOPE.set(stop_event)
    return scope


def end_run_progress_scope(scope: object) -> None:
    """Close *scope* while leaving detached workers' scoped stop events intact."""
    global _RUN_ACTIVE_PROGRESS_SCOPE, _RUN_ACTIVE_STOP_EVENT
    global _RUN_PROGRESS_TEXT, _RUN_PROGRESS_DETAIL, _RUN_PROGRESS_BY_SOURCE

    with _RUN_PROGRESS_LOCK:
        if _RUN_ACTIVE_PROGRESS_SCOPE is scope:
            _RUN_ACTIVE_PROGRESS_SCOPE = None
            _RUN_ACTIVE_STOP_EVENT = None
            _RUN_PROGRESS_TEXT = ""
            _RUN_PROGRESS_DETAIL = None
            _RUN_PROGRESS_BY_SOURCE = {}
    if _RUN_PROGRESS_SCOPE.get() is scope:
        _RUN_PROGRESS_SCOPE.set(None)
        _RUN_STOP_EVENT_SCOPE.set(None)


def _normalise_progress_for_log(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return "(cleared)"
    return " | ".join(lines)


def _validate_nonneg_int(field_name: str, value: Any) -> int | None:
    """Validate *value* is a non-negative int or ``None``; raise ``ValueError`` on bad input."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(
            f"progress detail field '{field_name}' must be an integer, got bool {value!r}"
        )
    if not isinstance(value, int):
        raise ValueError(
            f"progress detail field '{field_name}' must be an integer, got {type(value).__name__} {value!r}"
        )
    if value < 0:
        raise ValueError(f"progress detail field '{field_name}' must be non-negative, got {value}")
    return value


def _validate_progress_detail(
    *,
    stage: str | None = None,
    source: str | None = None,
    headline: str = "",
    detail: str = "",
    current: int | None = None,
    total: int | None = None,
    item_current: int | None = None,
    item_total: int | None = None,
    determinate: bool | None = None,
) -> ProgressDetail:
    """Validate and normalise raw progress-detail keyword arguments.

    Raises ``ValueError`` for any malformed value — never silently coerces.
    """
    if stage is not None and stage not in VALID_STAGES:
        raise ValueError(
            f"Invalid progress stage: {stage!r}; expected one of "
            f"{sorted(s for s in VALID_STAGES if s)}"
        )

    if source is not None and source not in VALID_SOURCES:
        raise ValueError(
            f"Invalid progress source: {source!r}; expected one of "
            f"{sorted(s for s in VALID_SOURCES if s)}"
        )

    headline_str = str(headline or "").strip()
    detail_str = str(detail or "").strip()

    current_int = _validate_nonneg_int("current", current)
    total_int = _validate_nonneg_int("total", total)
    item_current_int = _validate_nonneg_int("item_current", item_current)
    item_total_int = _validate_nonneg_int("item_total", item_total)

    if current_int is not None and total_int is not None and current_int > total_int:
        raise ValueError(f"current ({current_int}) must not exceed total ({total_int})")

    if (item_current_int is None) != (item_total_int is None):
        raise ValueError("item_current and item_total must be supplied together")
    if (
        item_current_int is not None
        and item_total_int is not None
        and item_current_int > item_total_int
    ):
        raise ValueError(
            f"item_current ({item_current_int}) must not exceed item_total ({item_total_int})"
        )

    # Determinate bars represent this stage only, never the entire multi-source run.
    computed_determinate = current_int is not None and total_int is not None and total_int > 0
    if determinate is not None:
        if determinate and not computed_determinate:
            raise ValueError(
                "determinate=True requires valid current and total (both non-None, total > 0)"
            )
        final_determinate = bool(determinate)
    else:
        final_determinate = computed_determinate

    return ProgressDetail(
        stage=stage,
        source=source,
        headline=headline_str,
        detail=detail_str,
        current=current_int,
        total=total_int,
        item_current=item_current_int,
        item_total=item_total_int,
        determinate=final_determinate,
    )


def set_run_progress_state(
    text: str,
    *,
    stage: str | None = None,
    source: str | None = None,
    headline: str = "",
    detail: str = "",
    current: int | None = None,
    total: int | None = None,
    item_current: int | None = None,
    item_total: int | None = None,
    determinate: bool | None = None,
) -> None:
    """Set both human-readable progress text and a typed, validated structured detail.

    This is the preferred entry point for scrapers and runners.  Pass structured
    fields explicitly rather than embedding them in a text string.

    When *no* structured fields are supplied the stored detail is cleared (set
    to ``None``) so the UI knows there is no structured data to render.
    """
    global _RUN_PROGRESS_TEXT, _RUN_PROGRESS_DETAIL, _RUN_PROGRESS_BY_SOURCE

    normalized_text = str(text or "").strip()

    has_detail = (
        stage is not None
        or source is not None
        or bool(headline)
        or bool(detail)
        or current is not None
        or total is not None
        or item_current is not None
        or item_total is not None
        or determinate is not None
    )

    if has_detail:
        detail_obj = _validate_progress_detail(
            stage=stage,
            source=source,
            headline=headline,
            detail=detail,
            current=current,
            total=total,
            item_current=item_current,
            item_total=item_total,
            determinate=determinate,
        )
    else:
        detail_obj = None

    caller_scope = _RUN_PROGRESS_SCOPE.get()
    with _RUN_PROGRESS_LOCK:
        if caller_scope is not None and caller_scope is not _RUN_ACTIVE_PROGRESS_SCOPE:
            return
        previous_text = _RUN_PROGRESS_TEXT
        previous_detail = _RUN_PROGRESS_DETAIL
        _RUN_PROGRESS_TEXT = normalized_text
        _RUN_PROGRESS_DETAIL = detail_obj
        if source is not None:
            _RUN_PROGRESS_BY_SOURCE[source] = (normalized_text, detail_obj)

    if normalized_text == previous_text and detail_obj == previous_detail:
        return

    log_parts: dict[str, Any] = {"progress": _normalise_progress_for_log(normalized_text)}
    if detail_obj is not None:
        if detail_obj.source:
            log_parts["source"] = detail_obj.source
        if detail_obj.stage:
            log_parts["stage"] = detail_obj.stage
        if detail_obj.headline:
            log_parts["headline"] = detail_obj.headline
        if (
            detail_obj.determinate
            and detail_obj.current is not None
            and detail_obj.total is not None
        ):
            log_parts["pct"] = round(detail_obj.current / detail_obj.total * 100, 1)
    logger.debug(format_debug_marker("RUN_PROGRESS", log_parts))


def set_run_progress(text: str) -> None:
    """Set a text-only operational message and clear stale structured detail.

    Use this for exceptional or legacy messages that do not have a trustworthy
    stage model. Normal source and finalisation progress should use
    :func:`set_run_progress_state`.
    """
    set_run_progress_state(text)


def clear_run_progress() -> None:
    """Reset all run-progress state at the start or end of a run."""
    global _RUN_PROGRESS_BY_SOURCE
    set_run_progress_state("")
    with _RUN_PROGRESS_LOCK:
        _RUN_PROGRESS_BY_SOURCE = {}


def get_run_progress() -> str:
    """Return the current human-readable progress text, or ``""`` if none."""
    with _RUN_PROGRESS_LOCK:
        return _RUN_PROGRESS_TEXT


def get_run_progress_detail() -> dict[str, Any] | None:
    """Return a defensive copy of the current structured detail, or ``None``."""
    with _RUN_PROGRESS_LOCK:
        if _RUN_PROGRESS_DETAIL is None:
            return None
        return asdict(_RUN_PROGRESS_DETAIL)


def get_run_progress_for_source(source: str) -> str:
    """Return the latest progress emitted by *source*, without cross-source bleed."""
    source_key = str(source or "").strip().lower()
    with _RUN_PROGRESS_LOCK:
        value = _RUN_PROGRESS_BY_SOURCE.get(source_key)
        return value[0] if value is not None else ""


def get_run_progress_by_source() -> dict[str, dict[str, Any]]:
    """Return defensive per-source progress snapshots for diagnostics and the UI."""
    with _RUN_PROGRESS_LOCK:
        result: dict[str, dict[str, Any]] = {}
        for source, (text, detail) in _RUN_PROGRESS_BY_SOURCE.items():
            result[source] = {
                "progress": text,
                "progress_detail": asdict(detail) if detail is not None else None,
            }
        return result


def set_source_timeout_event(event: threading.Event | None) -> object:
    """Bind a cooperative source-timeout event to the current worker context."""
    return _RUN_SOURCE_TIMEOUT_EVENT_SCOPE.set(event)


def reset_source_timeout_event(token: object) -> None:
    """Remove a worker's cooperative source-timeout binding."""
    _RUN_SOURCE_TIMEOUT_EVENT_SCOPE.reset(token)
