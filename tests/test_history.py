"""Tests for history module (can_reuse_kept_job, update_job_history)."""

from datetime import datetime

from job_hunter_agent.history import can_reuse_kept_job, update_job_history
from job_hunter_agent.record_schema import (
    RECORD_DECISION_KEY,
    RECORD_JOB_KEY,
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_URL_KEY,
)


def test_history_reuse_with_url_variation():
    """History reuse succeeds when URL changes but the normalized job_key matches."""
    run_iso = datetime.now().isoformat()
    original_key = "seek:12345"
    original_record = {
        RECORD_JOB_KEY: original_key,
        RECORD_URL_KEY: "https://www.seek.com.au/job/12345",
        RECORD_DECISION_KEY: "KEEP",
        "title": "Software Engineer",
        "company": "Tech Corp",
    }
    history = {}
    update_job_history(history, original_record, run_iso)

    assert original_key in history
    entry = history[original_key]
    assert entry[RECORD_LAST_KEPT_SNAPSHOT_KEY] is not None

    new_record = {
        RECORD_JOB_KEY: original_key,
        RECORD_URL_KEY: "https://seek.com.au/job/12345?tracking=abc",
        "title": "Software Engineer",
        "company": "Tech Corp",
    }
    assert can_reuse_kept_job(entry, new_record) is True


def test_identity_collision_prevention():
    """Different sources with the same numeric ID do not collide."""
    history = {
        "seek:999": {"job_key": "seek:999", "times_kept": 1},
        "linkedin:999": {"job_key": "linkedin:999", "times_kept": 0},
    }
    seek_record = {RECORD_JOB_KEY: "seek:999"}
    li_record = {RECORD_JOB_KEY: "linkedin:999"}

    assert can_reuse_kept_job(history["seek:999"], seek_record) is False
    assert can_reuse_kept_job(history["linkedin:999"], li_record) is False
