"""Tests for shared run progress control."""

from __future__ import annotations

import logging

from job_hunter_agent import run_control


def test_set_run_progress_logs_changed_progress(caplog):
    run_control.clear_run_progress()
    caplog.clear()
    caplog.set_level(logging.INFO, logger="job_hunter_agent.run_control")

    run_control.set_run_progress("Waiting for SEEK\nLinkedIn complete")

    assert any(
        "RUN_PROGRESS" in record.getMessage()
        and "Waiting for SEEK | LinkedIn complete" in record.getMessage()
        for record in caplog.records
    )


def test_set_run_progress_skips_duplicate_progress_log(caplog):
    run_control.clear_run_progress()
    caplog.set_level(logging.INFO, logger="job_hunter_agent.run_control")

    run_control.set_run_progress("Starting SEEK")
    caplog.clear()

    run_control.set_run_progress("Starting SEEK")

    assert caplog.records == []
