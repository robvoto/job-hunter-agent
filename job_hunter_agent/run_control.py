"""Shared run stop control for background scrape jobs."""

from __future__ import annotations

import threading

_RUN_STOP_REQUESTED = threading.Event()
_RUN_PROGRESS_LOCK = threading.Lock()
_RUN_PROGRESS_TEXT = ""


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
