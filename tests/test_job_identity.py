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
    are_jobs_content_reposts,
    deduplicate_across_sources,
    deduplicate_content_reposts,
    find_confirmed_duplicate,
    find_confirmed_identity_history_entry,
    find_content_repost_history_entry,
    normalize_job_key,
)
from job_hunter_agent.record_schema import (
    RECORD_DUPLICATE_LINKS_KEY,
    RECORD_POTENTIAL_DUPLICATE_LINKS_KEY,
    RECORD_SOURCE_PROVENANCE_KEY,
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


def test_exact_external_apply_url_confirms_cross_source_repost_and_preserves_provenance():
    records = [
        {
            "job_key": "seek:101",
            "source": "seek",
            "source_name": "SEEK",
            "url": "https://seek.com.au/job/101?tracking=old",
            "title": "Business Analyst",
            "company": "Acme",
            "source_metadata": {
                "apply_url": "https://careers.acme.example/jobs/req-7?utm_source=seek",
                "canonical_url": "https://seek.com.au/job/101",
                "platform_job_id": "101",
                "raw_source_fields": {"listing_reference": "seek"},
            },
            "last_applied_at": "2026-08-20T09:00:00+10:00",
        },
        {
            "job_key": "linkedin:202",
            "source": "linkedin",
            "source_name": "LinkedIn",
            "url": "https://linkedin.com/jobs/view/202",
            "title": "Business Analyst (Reposted)",
            "company": "Acme",
            "source_metadata": {
                "apply_url": "https://careers.acme.example/jobs/req-7?utm_source=linkedin",
                "canonical_url": "https://linkedin.com/jobs/view/202",
                "platform_job_id": "202",
                "raw_source_fields": {"listing_reference": "linkedin"},
            },
        },
    ]

    deduped = deduplicate_across_sources(records)

    assert len(deduped) == 1
    survivor = deduped[0]
    assert survivor["job_key"] == "seek:101"
    assert survivor["last_applied_at"] == "2026-08-20T09:00:00+10:00"
    assert {entry["source"] for entry in survivor[RECORD_SOURCE_PROVENANCE_KEY]} == {
        "seek",
        "linkedin",
    }
    assert {entry["url"] for entry in survivor[RECORD_SOURCE_PROVENANCE_KEY]} == {
        "https://seek.com.au/job/101?tracking=old",
        "https://linkedin.com/jobs/view/202",
    }
    linked = survivor[RECORD_DUPLICATE_LINKS_KEY][0]
    assert linked["source"] == "linkedin"
    assert linked["source_metadata"]["raw_source_fields"]["listing_reference"] == "linkedin"


def test_external_apply_query_parameter_carrying_vacancy_identity_stays_distinct():
    first = {
        "job_key": "seek:101",
        "source": "seek",
        "source_metadata": {
            "apply_url": "https://careers.acme.example/apply?job=123",
        },
    }
    second = {
        "job_key": "linkedin:202",
        "source": "linkedin",
        "source_metadata": {
            "apply_url": "https://careers.acme.example/apply?job=456",
        },
    }

    assert not are_jobs_confirmed_duplicates(first, second)


def test_same_ats_requisition_and_ats_authority_confirms_cross_platform_duplicate():
    assert are_jobs_confirmed_duplicates(
        {
            "job_key": "seek:101",
            "source": "seek",
            "source_metadata": {
                "ats_source": "jobs.acme.example",
                "ats_requisition_id": "REQ-7",
            },
        },
        {
            "job_key": "linkedin:202",
            "source": "linkedin",
            "source_metadata": {
                "ats_source": "jobs.acme.example",
                "ats_requisition_id": "req-7",
            },
        },
    )


def test_same_ats_id_from_different_ats_authorities_is_not_a_duplicate():
    assert not are_jobs_confirmed_duplicates(
        {
            "job_key": "seek:101",
            "source": "seek",
            "source_metadata": {
                "ats_source": "jobs.acme.example",
                "ats_requisition_id": "REQ-7",
            },
        },
        {
            "job_key": "linkedin:202",
            "source": "linkedin",
            "source_metadata": {
                "ats_source": "jobs.other.example",
                "ats_requisition_id": "REQ-7",
            },
        },
    )


def test_confirmed_identity_history_lookup_reuses_linked_source_entry():
    entry = {
        "detail_evidence": {
            "source_metadata": {
                "apply_url": "https://careers.acme.example/jobs/req-7",
            }
        }
    }

    assert find_confirmed_identity_history_entry(
        {
            "job_key": "seek:101",
            "source": "seek",
            "source_metadata": {
                "apply_url": "https://careers.acme.example/jobs/req-7?utm_source=seek",
            },
        },
        {"linkedin:202": entry},
    ) is entry


def test_confirmed_identity_history_lookup_tolerates_concurrent_history_mutation(monkeypatch):
    # SEEK reviews title gates across a thread pool while other threads finalize
    # records into the same job_history dict. The lookup must iterate a snapshot
    # so an insert mid-scan cannot raise "dictionary changed size during iteration".
    history = {
        "linkedin:1": {"detail_evidence": {"source_metadata": {}}},
        "linkedin:2": {"detail_evidence": {"source_metadata": {}}},
    }

    real_match = _ji.are_jobs_confirmed_duplicates

    def _mutate_history_then_match(a, b):
        history[f"linkedin:{len(history) + 1}"] = {"detail_evidence": {"source_metadata": {}}}
        return real_match(a, b)

    monkeypatch.setattr(_ji, "are_jobs_confirmed_duplicates", _mutate_history_then_match)

    assert (
        find_confirmed_identity_history_entry(
            {"job_key": "seek:9", "source": "seek", "source_metadata": {}},
            history,
        )
        is None
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


def _cross_source_record(
    job_key: str,
    source: str,
    description: str,
    *,
    location: str = "Sydney NSW",
    posted_age_days: float | None = 1.0,
) -> dict:
    return {
        "job_key": job_key,
        "source": source,
        "source_name": source.title(),
        "title": "System Analyst",
        "company": "HCF Australia",
        "location": location,
        "posted_age_days": posted_age_days,
        "details_text": description,
        "url": f"https://{source}.example/jobs/{job_key.rsplit(':', 1)[-1]}",
        "source_metadata": {"platform_job_id": job_key.rsplit(":", 1)[-1]},
    }


def test_cross_source_same_vacancy_merges_and_preserves_both_sources():
    description = " ".join(
        f"system analysis stakeholder workshop requirement{i} delivery" for i in range(180)
    )
    records = [
        _cross_source_record(
            "linkedin:li-4463010684",
            "linkedin",
            description,
            location="Sydney, New South Wales, Australia",
            posted_age_days=2.0,
        ),
        _cross_source_record(
            "seek:94517731",
            "seek",
            description + " seek formatting",
            posted_age_days=1.0,
        ),
    ]

    deduped = deduplicate_across_sources(records)

    assert [record["job_key"] for record in deduped] == ["seek:94517731"]
    survivor = deduped[0]
    assert survivor[RECORD_DUPLICATE_LINKS_KEY][0]["source"] == "linkedin"
    assert {entry["source"] for entry in survivor[RECORD_SOURCE_PROVENANCE_KEY]} == {
        "seek",
        "linkedin",
    }


def test_cross_source_hcf_same_vacancy_merges_when_linkedin_location_is_missing():
    description_parts = [
        f"system analysis stakeholder workshop requirement{i} delivery" for i in range(180)
    ]
    description = " ".join(description_parts)
    linkedin_description = " ".join(
        description_parts[:-4]
        + [f"system analysis stakeholder workshop vacancy_variation{i} delivery" for i in range(4)]
    )
    records = [
        _cross_source_record(
            "seek:94517731",
            "seek",
            description,
            location="Sydney NSW",
            posted_age_days=1.0,
        ),
        _cross_source_record(
            "linkedin:li-4463010684",
            "linkedin",
            linkedin_description,
            location="",
            posted_age_days=2.0,
        ),
    ]

    deduped = deduplicate_across_sources(records)

    assert [record["job_key"] for record in deduped] == ["seek:94517731"]
    assert deduped[0][RECORD_DUPLICATE_LINKS_KEY][0]["source"] == "linkedin"


def test_cross_source_same_vacancy_merges_when_both_locations_are_missing():
    description = " ".join(
        f"system analysis stakeholder workshop requirement{i} delivery" for i in range(180)
    )
    first = _cross_source_record("seek:100", "seek", description, location="")
    second = _cross_source_record(
        "linkedin:200",
        "linkedin",
        description + " linkedin presentation variation",
        location="",
    )

    assert are_jobs_confirmed_duplicates(first, second)


def test_cross_source_same_vacancy_with_conflicting_locations_does_not_merge():
    description = " ".join(
        f"system analysis stakeholder workshop requirement{i} delivery" for i in range(180)
    )
    first = _cross_source_record("seek:100", "seek", description, location="Sydney NSW")
    second = _cross_source_record(
        "linkedin:200",
        "linkedin",
        description + " linkedin presentation variation",
        location="Melbourne VIC",
    )

    assert not are_jobs_confirmed_duplicates(first, second)


def test_cross_source_same_metadata_with_different_role_content_does_not_merge():
    generic_company_intro = (
        "HCF Australia supports members through reliable services and technology. "
        "This role contributes to a collaborative team and continuous improvement."
    )
    first = _cross_source_record(
        "seek:100",
        "seek",
        generic_company_intro
        + " "
        + " ".join(f"claims platform data governance audit{i}" for i in range(180)),
    )
    second = _cross_source_record(
        "linkedin:200",
        "linkedin",
        generic_company_intro
        + " "
        + " ".join(f"claims clinical systems patient safety nursing{i}" for i in range(180)),
    )

    assert not are_jobs_confirmed_duplicates(first, second)
    assert len(deduplicate_across_sources([first, second])) == 2


def test_cross_source_same_metadata_without_sufficient_description_does_not_merge():
    first = _cross_source_record(
        "seek:100",
        "seek",
        "System Analyst supports stakeholders and delivery priorities.",
    )
    second = _cross_source_record(
        "linkedin:200",
        "linkedin",
        "System Analyst supports stakeholders and delivery priorities.",
    )

    assert not are_jobs_confirmed_duplicates(first, second)
    assert len(deduplicate_across_sources([first, second])) == 2


def test_cross_source_description_match_rejects_incompatible_posting_age():
    description = " ".join(f"system analysis delivery requirement{i}" for i in range(180))
    first = _cross_source_record("seek:100", "seek", description, posted_age_days=1.0)
    second = _cross_source_record("linkedin:200", "linkedin", description, posted_age_days=8.0)

    assert not are_jobs_confirmed_duplicates(first, second)


def test_cross_source_rule_does_not_change_same_source_repost_behaviour():
    description = " ".join(f"system analysis delivery requirement{i}" for i in range(180))
    first = _cross_source_record("seek:100", "seek", description)
    second = _cross_source_record("seek:200", "seek", description)

    assert are_jobs_content_reposts(first, second)
    assert not are_jobs_confirmed_duplicates(first, second)


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


def _content_repost_record(job_key: str, details: str, *, posted_age_days: float = 1.0) -> dict:
    return {
        "job_key": job_key,
        "source": "seek",
        "company": "Acme Consulting Pty Ltd",
        "title": "Senior Business Analyst",
        "location": "Sydney NSW",
        "details_text": details,
        "posted_age_days": posted_age_days,
        "first_seen_at": "2026-09-08T10:00:00+10:00",
    }


def test_content_repost_matches_changed_platform_id_when_description_is_near_identical():
    shared = " ".join(f"requirement{i} analysis{i} stakeholder{i} workshop{i} delivery{i}" for i in range(220))
    first = _content_repost_record("seek:100", shared + "original ending")
    second = _content_repost_record("seek:200", shared + "reposted ending")

    assert are_jobs_content_reposts(first, second) is True


def test_content_repost_does_not_collapse_same_company_and_title_when_role_text_differs():
    first = _content_repost_record(
        "seek:100",
        "university finance performance improvement budgeting reporting " * 120,
    )
    second = _content_repost_record(
        "seek:200",
        "investment banking wealth management trading platforms settlements " * 120,
    )

    assert are_jobs_content_reposts(first, second) is False


def test_content_repost_deduplication_prefers_fresher_repost():
    shared = "technology transformation stakeholder analysis operating model " * 120
    older = _content_repost_record("seek:100", shared, posted_age_days=6.0)
    fresher = _content_repost_record("seek:200", shared, posted_age_days=1.0)

    deduped = deduplicate_content_reposts([older, fresher])

    assert [record["job_key"] for record in deduped] == ["seek:200"]
    assert deduped[0]["is_reposted"] is True


def test_content_repost_history_requires_current_schema_snapshot_identity():
    shared = " ".join(
        f"requirement{i} analysis{i} stakeholder{i} workshop{i} delivery{i}"
        for i in range(220)
    )
    record = {
        "job_key": "linkedin:li-200",
        "source": "linkedin",
        "company": "Acme",
        "title": "Business Analyst",
        "location": "Sydney NSW",
        "details_text": shared + " reposted",
    }
    canonical_history = {
        "linkedin:li-100": {
            "last_kept_snapshot": {
                "job_key": "linkedin:li-100",
                "source": "linkedin",
                "company": "Acme",
                "title": "Business Analyst",
                "location": "Sydney NSW",
                "full_description": shared + " original",
            }
        }
    }
    malformed_history = {
        "linkedin:li-100": {
            "last_kept_snapshot": {
                "job_key": "linkedin:li-100",
                "company": "Acme",
                "title": "Business Analyst",
                "location": "Sydney NSW",
                "full_description": shared + " original",
            }
        }
    }

    assert (
        find_content_repost_history_entry(record, canonical_history, {"linkedin:li-100"})
        is canonical_history["linkedin:li-100"]
    )
    assert find_content_repost_history_entry(record, malformed_history, {"linkedin:li-100"}) is None


def test_content_repost_does_not_treat_placeholder_location_as_missing_identity():
    shared = " ".join(
        f"requirement{i} analysis{i} stakeholder{i} workshop{i} delivery{i}"
        for i in range(220)
    )
    archive_record = {
        "job_key": "linkedin:li-200",
        "source": "linkedin",
        "company": "Acme",
        "title": "Business Analyst",
        "location": "N/A",
        "full_description": shared + " reposted",
    }
    applied_record = {
        "job_key": "linkedin:li-100",
        "source": "linkedin",
        "company": "Acme",
        "title": "Business Analyst",
        "location": "Sydney, New South Wales, Australia",
        "full_description": shared + " original",
    }

    assert are_jobs_content_reposts(archive_record, applied_record) is False
