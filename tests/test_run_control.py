"""Tests for shared run progress control."""

from __future__ import annotations

import contextvars
import logging

import pytest

from job_hunter_agent import run_control


def test_set_run_progress_state_logs_changed_progress(caplog):
    run_control.clear_run_progress()
    caplog.clear()
    caplog.set_level(logging.DEBUG, logger="job_hunter_agent.run_control")

    run_control.set_run_progress_state("Waiting for SEEK\nLinkedIn complete", stage="verification", headline="Waiting for SEEK")

    assert any(
        "RUN_PROGRESS" in record.getMessage()
        and "Waiting for SEEK | LinkedIn complete" in record.getMessage()
        for record in caplog.records
    )


def test_set_run_progress_state_skips_duplicate_progress_log(caplog):
    run_control.clear_run_progress()
    caplog.set_level(logging.DEBUG, logger="job_hunter_agent.run_control")

    run_control.set_run_progress_state("Starting SEEK", stage="starting", source="seek", headline="Starting SEEK")
    caplog.clear()

    run_control.set_run_progress_state("Starting SEEK", stage="starting", source="seek", headline="Starting SEEK")

    assert caplog.records == []


def test_set_run_progress_state_rejects_text_only_progress():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="requires structured detail"):
        run_control.set_run_progress_state("Starting SEEK")


def test_set_run_progress_state_stores_and_returns_text():
    run_control.clear_run_progress()
    run_control.set_run_progress_state(
        "SEEK page 1/3",
        stage="source_collection",
        source="seek",
        headline="SEEK page 1 of 3",
        detail="Scanning job listings",
        current=1,
        total=3,
    )
    assert run_control.get_run_progress() == "SEEK page 1/3"
    detail = run_control.get_run_progress_detail()
    assert detail is not None
    assert detail["source"] == "seek"
    assert detail["stage"] == "source_collection"
    assert detail["current"] == 1
    assert detail["total"] == 3
    assert detail["determinate"] is True


def test_get_run_progress_detail_returns_defensive_copy():
    run_control.clear_run_progress()
    run_control.set_run_progress_state(
        "LinkedIn target 1/2",
        stage="source_collection",
        source="linkedin",
        current=1,
        total=2,
    )
    detail1 = run_control.get_run_progress_detail()
    assert detail1 is not None
    detail1["current"] = 999
    detail1["source"] = "hacked"
    detail2 = run_control.get_run_progress_detail()
    assert detail2 is not None
    assert detail2["current"] == 1
    assert detail2["source"] == "linkedin"


def test_progress_can_be_read_without_cross_source_contamination():
    run_control.clear_run_progress()
    run_control.set_run_progress_state(
        "SEEK page 2/5",
        stage="source_collection",
        source="seek",
        current=2,
        total=5,
    )
    run_control.set_run_progress_state(
        "APSJobs search 1/2",
        stage="source_collection",
        source="apsjobs",
        current=1,
        total=2,
    )

    assert run_control.get_run_progress_for_source("seek") == "SEEK page 2/5"
    assert run_control.get_run_progress_for_source("apsjobs") == "APSJobs search 1/2"
    snapshot = run_control.get_run_progress_by_source()
    assert snapshot["seek"]["progress_detail"]["current"] == 2
    assert snapshot["apsjobs"]["progress_detail"]["current"] == 1

    run_control.clear_run_progress()


def test_set_run_progress_state_rejects_invalid_source():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="Invalid progress source"):
        run_control.set_run_progress_state(
            "test",
            stage="starting",
            source="invalid_source",
        )


def test_set_run_progress_state_rejects_invalid_stage():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="Invalid progress stage"):
        run_control.set_run_progress_state(
            "test",
            stage="invalid_stage",
            source="seek",
        )


def test_set_run_progress_state_rejects_negative_current():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="must be non-negative"):
        run_control.set_run_progress_state(
            "test",
            stage="source_collection",
            source="seek",
            current=-1,
            total=3,
        )


def test_set_run_progress_state_rejects_negative_total():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="must be non-negative"):
        run_control.set_run_progress_state(
            "test",
            stage="source_collection",
            source="seek",
            current=1,
            total=-1,
        )


def test_set_run_progress_state_rejects_current_greater_than_total():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="must not exceed total"):
        run_control.set_run_progress_state(
            "test",
            stage="source_collection",
            source="seek",
            current=5,
            total=3,
        )


def test_set_run_progress_state_requires_item_count_pair():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="must be supplied together"):
        run_control.set_run_progress_state(
            "test",
            stage="source_collection",
            source="linkedin",
            item_current=1,
        )


def test_set_run_progress_state_rejects_determinate_without_valid_totals():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="determinate=True requires valid current and total"):
        run_control.set_run_progress_state(
            "test",
            stage="source_collection",
            source="seek",
            determinate=True,
        )


def test_clear_run_progress_resets_text_and_detail():
    run_control.clear_run_progress()
    run_control.set_run_progress_state(
        "APSJobs complete",
        stage="source_collection",
        source="apsjobs",
        current=1,
        total=1,
    )
    assert run_control.get_run_progress() == "APSJobs complete"
    assert run_control.get_run_progress_detail() is not None
    run_control.clear_run_progress()
    assert run_control.get_run_progress() == ""
    assert run_control.get_run_progress_detail() is None



def test_set_run_progress_state_accepts_all_valid_sources():
    run_control.clear_run_progress()
    for source in ("seek", "linkedin", "apsjobs", "job_market_map", "generic"):
        run_control.set_run_progress_state(
            f"Testing {source}",
            stage="starting",
            source=source,
        )
        detail = run_control.get_run_progress_detail()
        assert detail is not None
        assert detail["source"] == source
    run_control.clear_run_progress()


def test_set_run_progress_state_accepts_all_valid_stages():
    run_control.clear_run_progress()
    for stage in (
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
    ):
        run_control.set_run_progress_state(
            f"Testing {stage}",
            stage=stage,
            source="seek",
        )
        detail = run_control.get_run_progress_detail()
        assert detail is not None
        assert detail["stage"] == stage
    run_control.clear_run_progress()



def test_set_run_progress_state_determinate_false_without_totals():
    run_control.clear_run_progress()
    run_control.set_run_progress_state(
        "Finalising results",
        stage="finalising",
        source=None,
        determinate=False,
    )
    detail = run_control.get_run_progress_detail()
    assert detail is not None
    assert detail["stage"] == "finalising"
    assert detail["determinate"] is False
    assert detail["current"] is None
    assert detail["total"] is None
    run_control.clear_run_progress()


def test_strict_integer_rejects_floats():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="must be an integer"):
        run_control.set_run_progress_state(
            "test",
            stage="source_collection",
            source="seek",
            current=2.0,  # type: ignore[arg-type]
            total=3,
        )


def test_strict_integer_rejects_numeric_strings():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="must be an integer"):
        run_control.set_run_progress_state(
            "test",
            stage="source_collection",
            source="seek",
            current="2",  # type: ignore[arg-type]
            total=3,
        )


def test_strict_integer_rejects_booleans():
    run_control.clear_run_progress()
    with pytest.raises(ValueError, match="must be an integer"):
        run_control.set_run_progress_state(
            "test",
            stage="source_collection",
            source="seek",
            current=True,
            total=3,
        )


def test_detached_worker_keeps_its_scoped_stop_request_after_run_end():
    scope = run_control.begin_run_progress_scope()
    try:
        worker_context = contextvars.copy_context()
        run_control.request_run_stop()
        assert worker_context.run(run_control.run_stop_requested) is True

        run_control.end_run_progress_scope(scope)
        run_control.clear_run_stop_request()

        new_scope = run_control.begin_run_progress_scope()
        try:
            assert run_control.run_stop_requested() is False
            assert worker_context.run(run_control.run_stop_requested) is True
        finally:
            run_control.end_run_progress_scope(new_scope)
    finally:
        run_control.clear_run_stop_request()


def test_detached_worker_cannot_overwrite_new_run_progress():
    old_scope = run_control.begin_run_progress_scope()
    old_context = contextvars.copy_context()
    run_control.end_run_progress_scope(old_scope)

    new_scope = run_control.begin_run_progress_scope()
    try:
        run_control.set_run_progress_state("New run progress", stage="source_collection", source="seek", headline="New run progress")
        old_context.run(run_control.set_run_progress_state, "Late old worker progress", stage="source_collection", source="seek", headline="Late old worker progress")
        assert run_control.get_run_progress() == "New run progress"
    finally:
        run_control.end_run_progress_scope(new_scope)


def test_second_concurrent_run_scope_is_rejected_without_replacing_active_scope():
    scope = run_control.begin_run_progress_scope()
    try:
        with pytest.raises(RuntimeError, match="already owns the active run-control scope"):
            contextvars.Context().run(run_control.begin_run_progress_scope)
        run_control.set_run_progress_state("Active run still owns progress", stage="source_collection", source="seek", headline="Active run still owns progress")
        assert run_control.get_run_progress() == "Active run still owns progress"
    finally:
        run_control.end_run_progress_scope(scope)
