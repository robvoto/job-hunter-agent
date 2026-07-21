"""Tests for workspace_data record reconstruction from job_history snapshots."""

from datetime import datetime

from job_hunter_agent.llm_review_state import has_complete_llm_keep_data
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EXTERNAL_APPLY,
    ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED,
)
from job_hunter_agent.workspace_data import (
    build_applied_workspace_record,
    build_hidden_workspace_record,
    build_history_workspace_record,
)

_SNAPSHOT = {
    "title": "Business Analyst",
    "company": "Acme Co",
    "url": "https://example.test/job-1",
    "llm_decision": "KEEP",
    "llm_fit_grade": "STRONG",
    "posting_channel_evidence": {
        "kind": "direct_employer",
        "source": "metadata_first",
        "trusted_metadata": ["company profile link = https://example.test/company/acme"],
        "weak_text_matches": [],
        "needs_review": False,
    },
    "apply_method": APPLY_METHOD_EXTERNAL_APPLY,
    "original_posted_date_status": ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED,
    "original_posted_date": "",
    "job_quality_signals": [
        {"kind": "date_mismatch", "evidence": "LinkedIn shows 2d old, external page shows 21d old."}
    ],
    "requirement_coverage": [
        {"capability_name": "Stakeholder engagement", "status": "supported", "importance": "required"}
    ],
}


def test_build_history_workspace_record_carries_requirement_coverage():
    entry = {"times_kept": 1, "last_kept_snapshot": _SNAPSHOT, "last_kept_at": "2026-07-01T00:00:00+10:00"}

    record = build_history_workspace_record(
        "linkedin:li-1",
        entry,
        datetime(2026, 7, 8, tzinfo=None).astimezone(),
        days_since_fn=lambda *_args, **_kwargs: 7,
        archive_stale_after_days=30,
    )

    assert record is not None
    assert record["requirement_coverage"] == _SNAPSHOT["requirement_coverage"]
    assert record["posting_channel_evidence"] == _SNAPSHOT["posting_channel_evidence"]
    assert record["apply_method"] == APPLY_METHOD_EXTERNAL_APPLY
    assert record["original_posted_date_status"] == ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED
    assert record["job_quality_signals"] == _SNAPSHOT["job_quality_signals"]
    assert has_complete_llm_keep_data(record)


def test_build_hidden_workspace_record_carries_requirement_coverage():
    entry = {"last_kept_snapshot": _SNAPSHOT, "last_hidden_at": "2026-07-01T00:00:00+10:00"}

    record = build_hidden_workspace_record(
        "linkedin:li-1",
        entry,
        datetime(2026, 7, 8, tzinfo=None).astimezone(),
        days_since_fn=lambda *_args, **_kwargs: 7,
    )

    assert record["requirement_coverage"] == _SNAPSHOT["requirement_coverage"]
    assert record["posting_channel_evidence"] == _SNAPSHOT["posting_channel_evidence"]
    assert record["apply_method"] == APPLY_METHOD_EXTERNAL_APPLY
    assert record["original_posted_date_status"] == ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED
    assert record["job_quality_signals"] == _SNAPSHOT["job_quality_signals"]
    assert has_complete_llm_keep_data(record)


def test_build_applied_workspace_record_carries_requirement_coverage():
    entry = {"last_kept_snapshot": _SNAPSHOT, "last_applied_at": "2026-07-01T00:00:00+10:00"}

    record = build_applied_workspace_record(
        "linkedin:li-1",
        entry,
        datetime(2026, 7, 8, tzinfo=None).astimezone(),
        days_since_fn=lambda *_args, **_kwargs: 7,
    )

    assert record["requirement_coverage"] == _SNAPSHOT["requirement_coverage"]
    assert record["posting_channel_evidence"] == _SNAPSHOT["posting_channel_evidence"]
    assert record["apply_method"] == APPLY_METHOD_EXTERNAL_APPLY
    assert record["original_posted_date_status"] == ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED
    assert record["job_quality_signals"] == _SNAPSHOT["job_quality_signals"]
    assert has_complete_llm_keep_data(record)
