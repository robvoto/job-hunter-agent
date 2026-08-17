"""Tests for shared search-term planning helpers."""

from job_hunter_agent.search_terms import direct_profile_title_match_job_keys


def test_direct_profile_title_match_job_keys_uses_existing_title_tiers():
    profile = {
        "target_roles": ["Business Analyst"],
        "also_consider_roles": ["Scrum Master"],
    }
    records = [
        {"job_key": "seek:1", "title": "Senior Business Analyst"},
        {"job_key": "seek:2", "title": "Scrum Master"},
        {"job_key": "seek:3", "title": "Network Engineer"},
    ]

    assert direct_profile_title_match_job_keys(records, profile) == {"seek:1", "seek:2"}


def test_direct_profile_title_match_job_keys_ignores_missing_identity_or_title():
    profile = {"target_roles": ["Business Analyst"], "also_consider_roles": []}
    records = [
        {"job_key": "", "title": "Business Analyst"},
        {"job_key": "seek:2", "title": ""},
    ]

    assert direct_profile_title_match_job_keys(records, profile) == set()
