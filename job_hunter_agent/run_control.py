"""Shared run stop control for background scrape jobs."""

from __future__ import annotations

import logging
import sys
import threading

from job_hunter_agent.logging_utils import format_debug_marker

_RUN_STOP_REQUESTED = threading.Event()
_RUN_PROGRESS_LOCK = threading.Lock()
_RUN_PROGRESS_TEXT = ""
logger = logging.getLogger(__name__)

# Manual job-by-job review debug aid, enabled via --step: pauses the scrape loop
# after every job's human summary is printed so it can be checked against the
# live posting before the next job runs. Continue by pressing Enter in the
# terminal running the server.
_STEP_THROUGH_ENABLED = threading.Event()
_STEP_THROUGH_LOCK = threading.Lock()


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


def set_run_progress(text: str) -> None:
    global _RUN_PROGRESS_TEXT
    with _RUN_PROGRESS_LOCK:
        normalized = str(text or "").strip()
        previous = _RUN_PROGRESS_TEXT
        _RUN_PROGRESS_TEXT = normalized
    if normalized == previous:
        return
    logger.info(
        format_debug_marker(
            "RUN_PROGRESS",
            {"progress": _normalise_progress_for_log(normalized)},
        )
    )


def clear_run_progress() -> None:
    set_run_progress("")


def get_run_progress() -> str:
    with _RUN_PROGRESS_LOCK:
        return _RUN_PROGRESS_TEXT
