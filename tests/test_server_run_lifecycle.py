"""Tests for server-owned run lifecycle and final elapsed totals."""

from datetime import datetime, timedelta

from job_hunter_agent import server_helpers


def test_finish_run_retains_terminal_stopped_state_and_total_elapsed(monkeypatch):
    started_at = datetime.now().astimezone() - timedelta(seconds=42)
    monkeypatch.setattr(server_helpers, "_run_in_progress", True)
    monkeypatch.setattr(server_helpers, "_run_started_at", started_at)
    monkeypatch.setattr(server_helpers, "_run_last_elapsed_seconds", None)
    monkeypatch.setattr(server_helpers, "_run_terminal_status", server_helpers.RUN_STATUS_IDLE)

    server_helpers._finish_run(server_helpers.RUN_STATUS_STOPPED)

    assert server_helpers._is_run_in_progress() is False
    assert server_helpers._current_run_status() == server_helpers.RUN_STATUS_STOPPED
    assert server_helpers._current_run_elapsed_seconds() in {42, 43}
    assert server_helpers._format_current_run_elapsed() in {"42s", "43s"}


def test_starting_new_run_replaces_terminal_stopped_state(monkeypatch):
    monkeypatch.setattr(server_helpers, "_run_in_progress", False)
    monkeypatch.setattr(server_helpers, "_run_started_at", None)
    monkeypatch.setattr(server_helpers, "_run_terminal_status", server_helpers.RUN_STATUS_STOPPED)
    monkeypatch.setattr(server_helpers, "run_stop_requested", lambda: False)

    assert server_helpers._try_mark_run_started() is True
    assert server_helpers._current_run_status() == server_helpers.RUN_STATUS_RUNNING
