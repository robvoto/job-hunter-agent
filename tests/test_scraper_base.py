"""Tests for scraper base."""

from datetime import date
from types import SimpleNamespace

from job_hunter_agent.record_schema import (
    POSTING_CHANNEL_CLASSIFIER_VERSION,
    POSTING_CHANNEL_VERSION_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
    RECORD_SOURCE_ADVERTISER_ID_KEY,
    RECORD_SOURCE_ATS_REQUISITION_ID_KEY,
    RECORD_SOURCE_CANONICAL_URL_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_PLATFORM_JOB_ID_KEY,
    SOURCE_METADATA_SCHEMA_VERSION,
    SOURCE_METADATA_VERSION_KEY,
    SOURCE_POSTER_COMPANY_INDUSTRY_KEY,
)
from job_hunter_agent.scrapers.base import normalize_jobspy_record


def test_normalize_jobspy_record_sets_expected_shape():
    row = SimpleNamespace(
        date_posted=date(2026, 5, 6),
        min_amount=100000,
        max_amount=120000,
        interval="yearly",
        currency="AUD",
        is_remote=True,
        job_type="Full Time",
        description="A" * 300,
        id="123",
        title="Senior Analyst",
        company="Acme",
        location="Sydney",
        job_url="https://example.com/job/123",
        job_url_direct="https://jobs.lever.co/acme/123",
        company_url="https://www.linkedin.com/company/acme/",
        company_url_direct="https://acme.com.au",
        company_industry="Software Development",
    )

    record = normalize_jobspy_record(
        row=row,
        source="linkedin",
        search_keywords="analyst",
        search_location="Sydney",
        run_iso="2026-05-07T09:00:00+10:00",
        salary_rules={
            "interval_divisor": {"yearly": 1000},
            "interval_suffix": {"yearly": "p.a."},
            "currencies_with_dollar": ["AUD"],
        },
        job_type_rules={"fulltime": "Full time"},
    )

    assert record["run_started_at"] == "2026-05-07T09:00:00+10:00"
    assert record["search_location"] == "Sydney"
    assert record["search_keywords"] == "analyst"
    assert record["search_classifications"] == ""
    assert record["page"] == 1
    assert record["source"] == "linkedin"
    assert record["job_key"] == "linkedin:123"
    assert record["posted"] == "1d ago"
    assert record["teaser"] == "A" * 240
    assert record["details_length"] == 300
    assert record["decision"] is None
    assert record["role_snapshot"] == ""
    assert record["fit_highlights"] == []
    assert record["competitive_signals"] == []
    assert record["reviewed_signal_matches"] == {
        "matched": [],
        "evidence_only": [],
        "ignored": [],
        "unresolved": [],
    }
    assert record["source_metadata"] == {
        SOURCE_METADATA_VERSION_KEY: SOURCE_METADATA_SCHEMA_VERSION,
        "platform": "linkedin",
        "apply_url": "https://jobs.lever.co/acme/123",
        "apply_domain": "jobs.lever.co",
        RECORD_SOURCE_CANONICAL_URL_KEY: "https://example.com/job/123",
        "company_profile_url": "https://acme.com.au",
        "company_profile_name": "Acme",
        RECORD_SOURCE_ADVERTISER_ID_KEY: "",
        "poster_company": "Acme",
        SOURCE_POSTER_COMPANY_INDUSTRY_KEY: "Software Development",
        "hiring_company": "",
        "ats_source": "jobs.lever.co",
        RECORD_SOURCE_PLATFORM_JOB_ID_KEY: "123",
        "raw_source_fields": {
            "date_posted": "2026-05-06",
            "min_amount": 100000,
            "max_amount": 120000,
            "interval": "yearly",
            "currency": "AUD",
            "is_remote": True,
            "job_type": "Full Time",
            "description": "A" * 300,
            "id": "123",
            "title": "Senior Analyst",
            "company": "Acme",
            "location": "Sydney",
            "job_url": "https://example.com/job/123",
            "job_url_direct": "https://jobs.lever.co/acme/123",
            "company_url": "https://www.linkedin.com/company/acme/",
            "company_url_direct": "https://acme.com.au",
            "company_industry": "Software Development",
        },
    }
    assert RECORD_SOURCE_ATS_REQUISITION_ID_KEY not in record["source_metadata"]
    assert record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] == {
        POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
        "kind": "unknown",
        "source": "insufficient_evidence",
        "trusted_metadata": [],
        "weak_text_matches": [],
        "text_evidence": [],
        "needs_review": False,
    }
    assert RECORD_SOURCE_METADATA_KEY in record
    assert RECORD_REVIEWED_SIGNAL_MATCHES_KEY in record


def test_normalize_jobspy_record_keeps_ats_requisition_id_when_present():
    row = SimpleNamespace(
        date_posted=date(2026, 5, 6),
        min_amount=None,
        max_amount=None,
        interval="yearly",
        currency="AUD",
        job_type="Full Time",
        description="Role description",
        id="123",
        ats_requisition_id="REQ-77",
        title="Senior Analyst",
        company="Acme",
        location="Sydney",
        job_url="https://example.com/job/123",
    )

    record = normalize_jobspy_record(
        row=row,
        source="seek",
        search_keywords="analyst",
        search_location="Sydney",
        run_iso="2026-05-07T09:00:00+10:00",
        salary_rules={
            "interval_divisor": {"yearly": 1000},
            "interval_suffix": {"yearly": "p.a."},
            "currencies_with_dollar": ["AUD"],
        },
        job_type_rules={"fulltime": "Full time"},
    )

    assert record["source_metadata"][RECORD_SOURCE_ATS_REQUISITION_ID_KEY] == "REQ-77"
    assert record["source_metadata"][RECORD_SOURCE_PLATFORM_JOB_ID_KEY] == "123"


def test_normalize_jobspy_record_has_expected_review_state_keys():
    row = SimpleNamespace(
        date_posted=date(2026, 5, 6),
        min_amount=None,
        max_amount=None,
        interval="yearly",
        currency="AUD",
        job_type="Full Time",
        description="Role description",
        id="123",
        title="Senior Analyst",
        company="Acme",
        location="Sydney",
        job_url="https://example.com/job/123",
    )

    record = normalize_jobspy_record(
        row=row,
        source="linkedin",
        search_keywords="analyst",
        search_location="Sydney",
        run_iso="2026-05-07T09:00:00+10:00",
        salary_rules={
            "interval_divisor": {"yearly": 1000},
            "interval_suffix": {"yearly": "p.a."},
            "currencies_with_dollar": ["AUD"],
        },
        job_type_rules={"fulltime": "Full time"},
    )

    assert set(record[RECORD_REVIEWED_SIGNAL_MATCHES_KEY].keys()) == {
        "matched",
        "evidence_only",
        "ignored",
        "unresolved",
    }
