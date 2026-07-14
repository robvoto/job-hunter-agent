"""Tests for history module (can_reuse_kept_job, update_job_history)."""

from datetime import datetime

from job_hunter_agent.history import apply_kept_job_reuse, can_reuse_kept_job, update_job_history
from job_hunter_agent.record_schema import (
    RECORD_DECISION_KEY,
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
            {"requirement": "Business analysis", "importance": "mandatory", "status": "supported"}
        ],
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
            "weak_text_matches": [],
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
            "weak_text_matches": ["company name = Recruiter Co"],
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
