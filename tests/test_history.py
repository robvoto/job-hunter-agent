"""Tests for history module (can_reuse_kept_job, update_job_history)."""

from datetime import datetime

from job_hunter_agent.history import (
    apply_detail_evidence_reuse,
    apply_kept_job_reuse,
    build_detail_evidence_snapshot,
    can_reuse_detail_evidence,
    can_reuse_kept_job,
    update_job_history,
)
from job_hunter_agent.record_schema import (
    RECORD_APPLY_METHOD_KEY,
    RECORD_DECISION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_JOB_KEY,
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_SOURCE_METADATA_KEY,
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
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        RECORD_REQUIREMENT_COVERAGE_KEY: [
            {"requirement": "Business analysis", "importance": "required", "status": "supported"}
        ],
        RECORD_POSTING_CHANNEL_EVIDENCE_KEY: {
            "kind": "direct_employer",
            "source": "llm_classifier",
            "text_evidence": ["The ad describes the employer's own team."],
        },
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


def test_history_reuse_rechecks_jobs_with_unclassified_posting_channel():
    entry = {
        "times_kept": 1,
        RECORD_LAST_KEPT_SNAPSHOT_KEY: {
            "job_key": "seek:12345",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            RECORD_REQUIREMENT_COVERAGE_KEY: [
                {"requirement": "Business analysis", "importance": "required", "status": "supported"}
            ],
            RECORD_POSTING_CHANNEL_EVIDENCE_KEY: {
                "kind": "unknown",
                "source": "insufficient_evidence",
                "trusted_metadata": [],
                "text_evidence": [],
            },
        },
    }
    record = {RECORD_JOB_KEY: "seek:12345"}

    assert can_reuse_kept_job(entry, record) is False


def test_history_reuse_requires_complete_llm_keep_data():
    entry = {
        "times_kept": 1,
        RECORD_LAST_KEPT_SNAPSHOT_KEY: {
            "job_key": "seek:12345",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            RECORD_REQUIREMENT_COVERAGE_KEY: [],
        },
    }

    record = {
        RECORD_JOB_KEY: "seek:12345",
        RECORD_URL_KEY: "https://seek.com.au/job/12345",
        "title": "Business Analyst",
        "company": "Acme",
    }

    assert can_reuse_kept_job(entry, record) is False


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


def test_update_job_history_persists_posting_channel_and_source_metadata_in_snapshot():
    history = {}
    run_iso = datetime.now().isoformat()
    record = {
        RECORD_JOB_KEY: "linkedin:li-1",
        RECORD_URL_KEY: "https://www.linkedin.com/jobs/view/1",
        RECORD_DECISION_KEY: "KEEP",
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        RECORD_REQUIREMENT_COVERAGE_KEY: [],
        RECORD_POSTING_CHANNEL_EVIDENCE_KEY: {
            "kind": "direct_employer",
            "source": "metadata_first",
            "trusted_metadata": ["company profile link = https://linkedin.com/company/acme"],
            "text_evidence": [],
            "needs_review": False,
        },
        RECORD_SOURCE_METADATA_KEY: {
            "platform": "linkedin",
            "company_profile_url": "https://linkedin.com/company/acme",
            "hiring_company": "Acme",
        },
        "title": "Business Analyst",
        "company": "Acme",
    }

    update_job_history(history, record, run_iso)

    snapshot = history["linkedin:li-1"][RECORD_LAST_KEPT_SNAPSHOT_KEY]
    assert snapshot[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] == record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY]
    assert snapshot[RECORD_SOURCE_METADATA_KEY] == record[RECORD_SOURCE_METADATA_KEY]


def test_apply_kept_job_reuse_restores_posting_channel_and_source_metadata():
    snapshot = {
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        RECORD_REQUIREMENT_COVERAGE_KEY: [],
        RECORD_POSTING_CHANNEL_EVIDENCE_KEY: {
            "kind": "agency_or_recruiter",
            "source": "metadata_first",
            "trusted_metadata": ["seekPostingSourceCode"],
            "text_evidence": [],
            "needs_review": False,
        },
        RECORD_SOURCE_METADATA_KEY: {
            "platform": "seek",
            "company_profile_name": "Recruiter Co",
        },
    }
    history_entry = {
        "times_kept": 1,
        RECORD_LAST_KEPT_SNAPSHOT_KEY: snapshot,
    }

    record = {
        RECORD_JOB_KEY: "seek:12345",
        RECORD_URL_KEY: "https://seek.com.au/job/12345",
        "title": "Business Analyst",
        "company": "Recruiter Co",
    }

    reused = apply_kept_job_reuse(record, history_entry)

    assert reused[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] == snapshot[RECORD_POSTING_CHANNEL_EVIDENCE_KEY]
    assert reused[RECORD_SOURCE_METADATA_KEY] == snapshot[RECORD_SOURCE_METADATA_KEY]


def _fetched_record(fetched_text: str = "Full role description text.") -> dict:
    return {
        RECORD_JOB_KEY: "seek:12345",
        RECORD_DETAILS_TEXT_KEY: fetched_text,
        RECORD_DETAILS_STATUS_KEY: "ok",
        RECORD_SOURCE_METADATA_KEY: {"platform": "seek"},
        RECORD_DESCRIPTION_SOURCE_KEY: "seek_detail_page",
        RECORD_APPLY_METHOD_KEY: "direct_apply",
        "_raw_source_payload": {"jobDetails": {"id": "12345"}},
    }


def test_build_detail_evidence_snapshot_captures_fetched_fields():
    record = _fetched_record()

    snapshot = build_detail_evidence_snapshot(record, "2026-06-01T00:00:00+10:00")

    assert snapshot[RECORD_DETAILS_TEXT_KEY] == "Full role description text."
    assert snapshot["raw_source_payload"] == {"jobDetails": {"id": "12345"}}
    assert snapshot["fetched_at"] == "2026-06-01T00:00:00+10:00"


def test_can_reuse_detail_evidence_true_within_window():
    entry = {"detail_evidence": build_detail_evidence_snapshot(_fetched_record(), "2026-06-01T00:00:00+10:00")}

    assert can_reuse_detail_evidence(entry, max_age_days=7, run_iso="2026-06-05T00:00:00+10:00") is True


def test_can_reuse_detail_evidence_false_when_stale():
    entry = {"detail_evidence": build_detail_evidence_snapshot(_fetched_record(), "2026-06-01T00:00:00+10:00")}

    assert can_reuse_detail_evidence(entry, max_age_days=7, run_iso="2026-06-20T00:00:00+10:00") is False


def test_can_reuse_detail_evidence_false_when_fetch_produced_no_text():
    entry = {
        "detail_evidence": build_detail_evidence_snapshot(
            _fetched_record(fetched_text=""), "2026-06-01T00:00:00+10:00"
        )
    }

    assert can_reuse_detail_evidence(entry, max_age_days=7, run_iso="2026-06-01T01:00:00+10:00") is False


def test_can_reuse_detail_evidence_false_when_no_evidence_cached():
    assert can_reuse_detail_evidence({}, max_age_days=7, run_iso="2026-06-01T00:00:00+10:00") is False


def test_apply_detail_evidence_reuse_restores_fetched_fields_without_raw_html():
    fetched = _fetched_record()
    entry = {"detail_evidence": build_detail_evidence_snapshot(fetched, "2026-06-01T00:00:00+10:00")}

    record = {RECORD_JOB_KEY: "seek:12345", "_raw_html": "<html>stale from a prior card</html>"}
    reused = apply_detail_evidence_reuse(record, entry)

    assert reused[RECORD_DETAILS_TEXT_KEY] == "Full role description text."
    assert reused[RECORD_DETAILS_STATUS_KEY] == "ok"
    assert reused[RECORD_APPLY_METHOD_KEY] == "direct_apply"
    assert reused["_raw_source_payload"] == {"jobDetails": {"id": "12345"}}
    assert reused["_raw_html"] is None
