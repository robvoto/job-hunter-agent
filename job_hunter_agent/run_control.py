"""Shared run stop control for background scrape jobs."""

from __future__ import annotations

import sys
import threading

_RUN_STOP_REQUESTED = threading.Event()
_RUN_PROGRESS_LOCK = threading.Lock()
_RUN_PROGRESS_TEXT = ""

# TEMPORARY (manual job-by-job review debug aid, enabled via --step): pauses the
# scrape loop after every job's human summary is printed so it can be checked
# against the live posting before the next job runs. Continue by pressing Enter
# in the terminal running the server. Remove once no longer needed.
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


def set_run_progress(text: str) -> None:
    global _RUN_PROGRESS_TEXT
    with _RUN_PROGRESS_LOCK:
        _RUN_PROGRESS_TEXT = str(text or "").strip()


def clear_run_progress() -> None:
    set_run_progress("")


def get_run_progress() -> str:
    with _RUN_PROGRESS_LOCK:
        return _RUN_PROGRESS_TEXT
