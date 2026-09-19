"""Tests for server-owned run lifecycle and shutdown interruption handling."""

import logging
import signal
from datetime import datetime, timedelta

from job_hunter_agent import run_control, server_helpers


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


def test_shutdown_without_active_run_does_not_log_interruption(caplog):
    caplog.set_level(logging.WARNING, logger="job_hunter_agent.server_helpers")

    server_helpers._handle_server_shutdown(signal.SIGINT)

    assert not any("[RUN_INTERRUPTED]" in record.getMessage() for record in caplog.records)


def test_shutdown_marks_active_run_interrupted_and_persists_truth(caplog, monkeypatch, isolated_db):
    started_at = datetime.now().astimezone() - timedelta(seconds=7)
    monkeypatch.setattr(server_helpers, "_run_in_progress", True)
    monkeypatch.setattr(server_helpers, "_run_started_at", started_at)
    monkeypatch.setattr(server_helpers, "_run_active_id", "run-123")
    monkeypatch.setattr(server_helpers, "_run_active_user_id", "test_user")
    monkeypatch.setattr(server_helpers, "_run_terminal_status", server_helpers.RUN_STATUS_RUNNING)
    monkeypatch.setattr(server_helpers, "_shutdown_interruption_recorded", False)
    run_control.set_run_progress_state(
        "LinkedIn target 4/22",
        stage="source_collection",
        source="linkedin",
        current=4,
        total=22,
    )
    caplog.set_level(logging.WARNING, logger="job_hunter_agent.server_helpers")

    assert server_helpers._handle_server_shutdown(signal.SIGTERM) is True

    assert server_helpers._is_run_in_progress() is False
    assert server_helpers._current_run_status() == server_helpers.RUN_STATUS_INTERRUPTED
    from job_hunter_agent.io_utils import load_run_stats

    persisted = load_run_stats()
    assert persisted["run_status"] == server_helpers.RUN_STATUS_INTERRUPTED
    assert persisted["last_run_error"]
    assert persisted["run_interruption_signal"] == "SIGTERM"
    assert persisted["run_interruption_source"] == "linkedin"
    assert "LinkedIn target 4/22" in str(persisted["run_interruption_progress"])
    assert any("[RUN_INTERRUPTED]" in record.getMessage() for record in caplog.records)

    run_control.clear_run_shutdown_request()
    run_control.clear_run_stop_request()
    run_control.clear_run_progress()


def test_previous_interrupted_run_is_reported_on_startup(caplog, monkeypatch):
    monkeypatch.setattr(server_helpers, "list_user_setting_user_ids", lambda: ["test_user"])
    monkeypatch.setattr(
        server_helpers,
        "load_run_stats",
        lambda: {
            "run_status": server_helpers.RUN_STATUS_INTERRUPTED,
            "last_run_attempt_at": "run-123",
            "run_interrupted_at": "2026-08-17T09:54:13+10:00",
            "run_interruption_signal": "SIGINT",
        },
    )
    caplog.set_level(logging.WARNING, logger="job_hunter_agent.server_helpers")

    server_helpers._log_previous_interrupted_runs()

    assert any("[RUN_INTERRUPTED][PREVIOUS]" in record.getMessage() for record in caplog.records)
