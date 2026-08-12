"""Regression coverage for managed eligibility aliases in LLM validation."""

import pytest

from job_hunter_agent import llm_gate


@pytest.mark.parametrize(
    ("canonical", "alias"),
    [
        ("Baseline", "Baseline Security Clearance"),
        ("NV1", "Negative Vetting Level 1"),
    ],
)
def test_managed_clearance_alias_resolves_to_profile_canonical_fact(canonical, alias):
    profile = {
        "candidate_eligibility": [{"name": canonical, "value": True, "evidence": []}],
        "candidate_eligibility_facts": [],
    }

    valid_names = llm_gate._build_profile_eligibility_names(profile)
    coverage = llm_gate.normalize_llm_requirement_coverage(
        [
            {
                "requirement": f"Must hold {alias}",
                "importance": "required",
                "requirement_type": "eligibility",
                "status": "supported",
                "matched_candidate_fact": alias,
                "matched_job_text": f"Must hold {alias}",
                "profile_support": [alias],
            }
        ],
        valid_eligibility_names=valid_names,
    )

    assert coverage[0]["status"] == "supported"
    assert coverage[0]["matched_candidate_fact"] == canonical
    assert coverage[0]["eligibility_name"] == canonical


def test_managed_clearance_alias_is_not_valid_when_fact_is_absent_from_profile():
    profile = {
        "candidate_eligibility": [{"name": "Baseline", "value": True, "evidence": []}],
        "candidate_eligibility_facts": [],
    }

    valid_names = llm_gate._build_profile_eligibility_names(profile)

    assert valid_names["baseline security clearance"] == "Baseline"
    assert "negative vetting level 1" not in valid_names
