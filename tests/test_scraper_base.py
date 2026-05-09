from datetime import date
from types import SimpleNamespace

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
    assert record["source_metadata"] == {
        "platform": "linkedin",
        "apply_url": "https://jobs.lever.co/acme/123",
        "apply_domain": "jobs.lever.co",
        "company_profile_url": "https://acme.com.au",
        "company_profile_name": "Acme",
        "poster_company": "Acme",
        "hiring_company": "Acme",
        "ats_source": "jobs.lever.co",
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
        },
    }
    assert record["posting_channel_evidence"] == {
        "trusted_metadata": [],
        "weak_text_matches": [],
        "needs_review": False,
    }
