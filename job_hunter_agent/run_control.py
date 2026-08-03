"""Shared run stop control and structured progress model for background scrape jobs.

This module is the single owner of run-wide progress state.  It stores both:

* ``text``  — a human-readable progress string for logging and legacy consumers;
* ``detail`` — a typed, validated :class:`ProgressDetail` that the UI renders
  with a source badge, progress bar, and stage information instead of parsing
  arbitrary strings in the browser.

All public mutators are thread-safe via ``_RUN_PROGRESS_LOCK``.
"""

from __future__ import annotations

import logging
import sys
import threading
from dataclasses import asdict, dataclass
from typing import Any

from job_hunter_agent.logging_utils import format_debug_marker

_RUN_STOP_REQUESTED = threading.Event()
_RUN_PROGRESS_LOCK = threading.Lock()
_RUN_PROGRESS_TEXT = ""
_RUN_PROGRESS_DETAIL: ProgressDetail | None = None
logger = logging.getLogger(__name__)

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
    _RUN_STOP_REQUESTED.set()


def clear_run_stop_request() -> None:
    _RUN_STOP_REQUESTED.clear()


def run_stop_requested() -> bool:
    return _RUN_STOP_REQUESTED.is_set()


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
    global _RUN_PROGRESS_TEXT, _RUN_PROGRESS_DETAIL

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

    with _RUN_PROGRESS_LOCK:
        previous_text = _RUN_PROGRESS_TEXT
        previous_detail = _RUN_PROGRESS_DETAIL
        _RUN_PROGRESS_TEXT = normalized_text
        _RUN_PROGRESS_DETAIL = detail_obj

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
    logger.info(format_debug_marker("RUN_PROGRESS", log_parts))


def set_run_progress(text: str) -> None:
    """Set a text-only operational message and clear stale structured detail.

    Use this for exceptional or legacy messages that do not have a trustworthy
    stage model. Normal source and finalisation progress should use
    :func:`set_run_progress_state`.
    """
    set_run_progress_state(text)


def clear_run_progress() -> None:
    """Reset all run-progress state at the start or end of a run."""
    set_run_progress_state("")


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
