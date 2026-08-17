"""Tests for workspace_data record reconstruction from job_history snapshots."""

from datetime import datetime

from job_hunter_agent.llm_review_state import has_complete_llm_keep_data
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EXTERNAL_APPLY,
    ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED,
    RECORD_SOURCE_METADATA_KEY,
)
from job_hunter_agent.workspace_data import (
    build_applied_workspace_record,
    build_workspace_record_sets,
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
        "text_evidence": [],
        "needs_review": False,
    },
    RECORD_SOURCE_METADATA_KEY: {
        "platform": "linkedin",
        "company_profile_url": "https://example.test/company/acme",
        "company_profile_name": "Acme Co",
        "poster_company": "Acme Co",
        "hiring_company": "Acme Co",
    },
    "apply_method": APPLY_METHOD_EXTERNAL_APPLY,
    "original_posted_date_status": ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED,
    "original_posted_date": "",
    "is_reposted": True,
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
    assert record[RECORD_SOURCE_METADATA_KEY] == _SNAPSHOT[RECORD_SOURCE_METADATA_KEY]
    assert record["apply_method"] == APPLY_METHOD_EXTERNAL_APPLY
    assert record["original_posted_date_status"] == ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED
    assert record["is_reposted"] is True
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
    assert record[RECORD_SOURCE_METADATA_KEY] == _SNAPSHOT[RECORD_SOURCE_METADATA_KEY]
    assert record["apply_method"] == APPLY_METHOD_EXTERNAL_APPLY
    assert record["original_posted_date_status"] == ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED
    assert record["is_reposted"] is True
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
    assert record[RECORD_SOURCE_METADATA_KEY] == _SNAPSHOT[RECORD_SOURCE_METADATA_KEY]
    assert record["apply_method"] == APPLY_METHOD_EXTERNAL_APPLY
    assert record["original_posted_date_status"] == ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED
    assert record["is_reposted"] is True
    assert record["job_quality_signals"] == _SNAPSHOT["job_quality_signals"]
    assert has_complete_llm_keep_data(record)


def test_build_workspace_record_sets_excludes_applied_and_hidden_current_records():
    records = [
        {"job_key": "linkedin:applied", "posted_age_days": 1},
        {"job_key": "seek:hidden", "posted_age_days": 2},
        {"job_key": "seek:current", "posted_age_days": 3},
    ]

    result = build_workspace_record_sets(
        records,
        {},
        {"linkedin:applied"},
        {"seek:hidden"},
        datetime(2026, 7, 8),
        profile={},
        is_workspace_eligible_fn=lambda record, profile: True,
        fit_score_fn=lambda record, profile: 90,
        viewed_by_user_fn=lambda record: False,
        normalize_job_key_fn=lambda value: value.strip().lower(),
        parse_timestamp_fn=lambda value: None,
        build_archive_records_fn=lambda *args: [],
        build_applied_records_fn=lambda keys, history, reference_time: [
            {"job_key": key, "applied": True} for key in sorted(keys)
        ],
        build_hidden_records_fn=lambda keys, history, reference_time: [
            {"job_key": key, "hidden": True} for key in sorted(keys)
        ],
    )

    assert [record["job_key"] for record in result["current_records"]] == ["seek:current"]
    assert [record["job_key"] for record in result["shortlist_records"]] == ["seek:current"]


def test_build_history_workspace_record_preserves_unknown_posting_channel_from_snapshot():
    snapshot = {
        **_SNAPSHOT,
        "posting_channel_evidence": {
            "kind": "unknown",
            "source": "insufficient_evidence",
            "trusted_metadata": [],
            "text_evidence": [],
            "needs_review": False,
        },
        "company": "Hammondcare",
        RECORD_SOURCE_METADATA_KEY: {
            "platform": "linkedin",
            "apply_url": "https://www.linkedin.com/jobs/view/1",
            "apply_domain": "www.linkedin.com",
            "company_profile_url": "",
            "company_profile_name": "Hammondcare",
            "poster_company": "Hammondcare",
            "hiring_company": "Hammondcare",
        },
    }
    entry = {"times_kept": 1, "last_kept_snapshot": snapshot, "last_kept_at": "2026-07-01T00:00:00+10:00"}

    record = build_history_workspace_record(
        "linkedin:li-1",
        entry,
        datetime(2026, 7, 8, tzinfo=None).astimezone(),
        days_since_fn=lambda *_args, **_kwargs: 7,
        archive_stale_after_days=30,
    )

    assert record is not None
    assert record["posting_channel_evidence"]["kind"] == "unknown"
    assert record["posting_channel_evidence"]["source"] == "insufficient_evidence"
