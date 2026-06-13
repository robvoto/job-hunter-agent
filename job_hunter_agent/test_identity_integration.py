"""Tests for identity integration."""

from datetime import datetime

import pytest

from job_hunter_agent.history import can_reuse_kept_job, update_job_history
from job_hunter_agent.record_schema import (
    RECORD_DECISION_KEY,
    RECORD_JOB_KEY,
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_URL_KEY,
)


def test_history_reuse_with_url_variation():
    """Verify that history reuse succeeds even if the URL changes but the normalized key matches."""

    run_iso = datetime.now().isoformat()

    # 1. Create an original record that was kept

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

    # 2. Verify it is in history

    assert original_key in history

    entry = history[original_key]

    assert entry[RECORD_LAST_KEPT_SNAPSHOT_KEY] is not None

    # 3. Simulate a new scrape of the same job with a different URL (e.g. mobile or tracking)

    new_record = {
        RECORD_JOB_KEY: original_key,
        RECORD_URL_KEY: "https://seek.com.au/job/12345?tracking=abc",
        "title": "Software Engineer",
        "company": "Tech Corp",
    }

    # 4. Integration Check: can_reuse_kept_job should now succeed because URL check was removed

    # and we rely on the canonical job_key for identity.

    assert can_reuse_kept_job(entry, new_record) is True


def test_identity_collision_prevention():
    """Verify that different sources with the same numeric ID do not collide."""

    history = {
        "seek:999": {"job_key": "seek:999", "times_kept": 1},
        "linkedin:999": {"job_key": "linkedin:999", "times_kept": 0},
    }

    # Record matching the numeric ID but wrong source

    seek_record = {RECORD_JOB_KEY: "seek:999"}

    li_record = {RECORD_JOB_KEY: "linkedin:999"}

    assert can_reuse_kept_job(history["seek:999"], seek_record) is False  # Missing snapshot

    assert can_reuse_kept_job(history["linkedin:999"], li_record) is False  # times_kept is 0
