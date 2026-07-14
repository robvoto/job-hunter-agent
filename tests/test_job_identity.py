"""Tests for job identity."""

import json

import job_hunter_agent.job_identity as _ji
from job_hunter_agent.company_normalization import (
    company_name_match_tokens,
    company_names_weakly_match,
    normalize_company_name,
)
from job_hunter_agent.job_identity import (
    annotate_potential_duplicate_links,
    are_jobs_confirmed_duplicates,
    deduplicate_across_sources,
    find_confirmed_duplicate,
    normalize_job_key,
)
from job_hunter_agent.record_schema import (
    RECORD_DUPLICATE_LINKS_KEY,
    RECORD_POTENTIAL_DUPLICATE_LINKS_KEY,
)


def test_normalize_job_key_extracts_apsjobs_path_based_id():

    assert (
        normalize_job_key("https://www.apsjobs.gov.au/s/job-details/123", source="apsjobs")
        == "apsjobs:123"
    )


def test_normalize_job_key_extracts_apsjobs_query_param_id_without_collision():

    # Real APSJobs listing URLs carry the unique id in an 'Id=' query param
    # while the path segment ('/s/job-details') is identical for every job.
    # Two different listings must not normalize to the same job_key.

    first = normalize_job_key(
        "https://www.apsjobs.gov.au/s/job-details?title=temporary-employment-register&Id=a05OY00000MGFeLYAX",
        source="apsjobs",
    )
    second = normalize_job_key(
        "https://www.apsjobs.gov.au/s/job-details?title=another-role&Id=a05OY00000ZZZZZZZZ",
        source="apsjobs",
    )

    assert first == "apsjobs:a05oy00000mgfelyax"
    assert second == "apsjobs:a05oy00000zzzzzzzz"
    assert first != second


def test_normalize_job_key_seek_and_linkedin_unaffected():

    assert normalize_job_key("https://www.seek.com.au/job/12345", source="seek") == "seek:12345"
    assert (
        normalize_job_key("https://www.linkedin.com/jobs/view/98765", source="linkedin")
        == "linkedin:98765"
    )


def test_are_jobs_confirmed_duplicates_requires_same_job_key_or_url():

    # Only exact job_key, URL, or canonical source identity matches are duplicates.

    assert are_jobs_confirmed_duplicates(
        {"job_key": "seek:123", "company": "Acme", "title": "Senior Business Analyst"},
        {"job_key": "seek:123", "company": "Acme", "title": "Business Analyst Senior"},
    )

    assert not are_jobs_confirmed_duplicates(
        {"job_key": "seek:1", "company": "Acme", "title": "Senior Business Analyst"},
        {"job_key": "seek:2", "company": "Acme", "title": "Senior Business Analyst"},
    )


def test_find_confirmed_duplicate_returns_first_matching_applied_record():

    # find_confirmed_duplicate only matches confirmed duplicates.

    pool = [
        {
            "job_key": "seek:1",
            "company": "Acme",
            "title": "Senior Business Analyst",
            "source": "seek",
        },
        {
            "job_key": "linkedin:2",
            "company": "Acme",
            "title": "Project Manager",
            "source": "linkedin",
        },
    ]

    match = find_confirmed_duplicate(
        {"job_key": "seek:1", "company": "Acme", "title": "Business Analyst Senior"},
        pool,
    )

    assert match == pool[0]


def test_deduplicate_across_sources_prefers_seek_when_duplicate_appears_later():

    # Confirmed deduplication requires same deterministic identity.

    records = [
        {
            "job_key": "seek:99",
            "company": "Acme",
            "title": "Senior Business Analyst",
            "source": "linkedin",
        },
        {
            "job_key": "seek:99",
            "company": "Acme",
            "title": "Business Analyst Senior",
            "source": "seek",
        },
    ]

    deduped = deduplicate_across_sources(records)

    assert len(deduped) == 1

    assert deduped[0]["job_key"] == "seek:99"

    assert deduped[0][RECORD_DUPLICATE_LINKS_KEY][0]["source"] == "linkedin"


def test_company_name_normalization_strips_only_safe_legal_suffixes():

    assert normalize_company_name("Acme Pty Ltd") == "acme"

    assert normalize_company_name("Acme Holdings Australia") == "acme holdings australia"

    assert company_names_weakly_match("Acme Pty Ltd", "Acme")


def test_company_name_match_tokens_use_managed_stopwords():

    assert company_name_match_tokens("The Acme Group Australia") == {"acme"}

    assert company_name_match_tokens("Acme Solutions Pty Ltd") == {"acme"}


def test_potential_duplicate_links_are_visible_without_merging():

    records = [
        {
            "job_key": "seek:1",
            "company": "Acme Pty Ltd",
            "title": "Business Analyst",
            "source": "seek",
            "url": "https://seek.com.au/job/1",
        },
        {
            "job_key": "linkedin:2",
            "company": "Acme Ltd",
            "title": "Business Analyst",
            "source": "linkedin",
            "url": "https://linkedin.com/jobs/view/2",
        },
    ]

    annotated = annotate_potential_duplicate_links(records)

    assert len(annotated) == 2

    assert annotated[0][RECORD_POTENTIAL_DUPLICATE_LINKS_KEY][0]["related_job_key"] == "linkedin:2"

    assert annotated[0][RECORD_POTENTIAL_DUPLICATE_LINKS_KEY][0]["related_source"] == "linkedin"

    assert annotated[1][RECORD_POTENTIAL_DUPLICATE_LINKS_KEY][0]["related_job_key"] == "seek:1"

    assert RECORD_DUPLICATE_LINKS_KEY not in annotated[0]


def test_potential_duplicate_links_are_omitted_when_none():

    annotated = annotate_potential_duplicate_links(
        [
            {"job_key": "seek:1", "company": "Acme", "title": "Data Engineer", "source": "seek"},
        ]
    )

    assert RECORD_POTENTIAL_DUPLICATE_LINKS_KEY not in annotated[0]


def test_potential_duplicate_detected_is_logged(tmp_path, monkeypatch):

    log_file = tmp_path / "uncertainty.jsonl"

    monkeypatch.setattr(_ji, "UNCERTAINTY_LOG_PATH", log_file)
    warnings = []
    monkeypatch.setattr(
        _ji,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )

    records = [
        {
            "job_key": "seek:1",
            "company": "Acme Pty Ltd",
            "title": "Business Analyst",
            "source": "seek",
            "url": "https://seek.com.au/job/1",
        },
        {
            "job_key": "linkedin:2",
            "company": "Acme Ltd",
            "title": "Business Analyst",
            "source": "linkedin",
            "url": "https://linkedin.com/jobs/view/2",
        },
    ]

    annotate_potential_duplicate_links(records)

    assert log_file.exists()

    entries = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]

    assert any(e.get("reason_code") == "POTENTIAL_DUPLICATE_DETECTED" for e in entries)
    assert warnings
    assert warnings[0]["category"] == "job_identity_uncertainty"


def test_dedup_company_missing_is_logged(tmp_path, monkeypatch):

    log_file = tmp_path / "uncertainty.jsonl"

    monkeypatch.setattr(_ji, "UNCERTAINTY_LOG_PATH", log_file)
    warnings = []
    monkeypatch.setattr(
        _ji,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )

    records = [
        {"job_key": "seek:1", "company": "Acme", "title": "Business Analyst", "source": "seek"},
        {"job_key": "linkedin:2", "company": "", "title": "Business Analyst", "source": "linkedin"},
    ]

    annotate_potential_duplicate_links(records)

    assert log_file.exists()

    entries = [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]

    assert any(e.get("reason_code") == "DEDUP_COMPANY_MISSING" for e in entries)
    assert warnings
    assert warnings[0]["category"] == "job_identity_uncertainty"
