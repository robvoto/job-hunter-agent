"""Tests for profile_gaps.resolve_custom_blocker.

Custom "Not For Me" blocker text must resolve to an existing, LLM-vetted
requirement_coverage item for the same job before it can be saved to
must_not_require_skills. See resolve_custom_blocker docstring for the exact
matching rules this enforces.
"""

from job_hunter_agent.profile_gaps import (
    CUSTOM_BLOCKER_REASON_AMBIGUOUS,
    CUSTOM_BLOCKER_REASON_INVALID_INPUT,
    CUSTOM_BLOCKER_REASON_NOT_REQUIRED,
    CUSTOM_BLOCKER_REASON_NO_MATCH,
    CUSTOM_BLOCKER_REASON_RESOLVED,
    list_custom_blocker_candidates,
    resolve_custom_blocker,
)


def _coverage_item(**overrides):
    item = {
        "requirement": "Salesforce experience",
        "requirement_type": "capability",
        "canonical_requirement": "Salesforce",
        "importance": "mandatory",
        "matched_job_text": "Salesforce experience",
        "profile_action_allowed": True,
    }
    item.update(overrides)
    return item


def test_resolves_valid_required_capability():
    coverage = [_coverage_item()]

    result = resolve_custom_blocker("Salesforce", coverage)

    assert result["ok"] is True
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_RESOLVED
    assert result["canonical_requirement"] == "Salesforce"
    assert result["requirement_type"] == "capability"
    assert result["importance"] == "mandatory"


def test_resolves_valid_required_eligibility():
    coverage = [
        _coverage_item(
            requirement="Must hold NV1 clearance",
            requirement_type="eligibility",
            canonical_requirement="NV1 clearance",
            matched_job_text="Must hold NV1 clearance",
        )
    ]

    result = resolve_custom_blocker("NV1 clearance", coverage)

    assert result["ok"] is True
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_RESOLVED
    assert result["canonical_requirement"] == "NV1 clearance"
    assert result["requirement_type"] == "eligibility"


def test_resolves_valid_required_qualification():
    coverage = [
        _coverage_item(
            requirement="CPA qualification required",
            requirement_type="qualification",
            canonical_requirement="CPA",
            matched_job_text="CPA qualification required",
        )
    ]

    result = resolve_custom_blocker("CPA", coverage)

    assert result["ok"] is True
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_RESOLVED
    assert result["canonical_requirement"] == "CPA"
    assert result["requirement_type"] == "qualification"


def test_rejects_broad_term_that_does_not_exact_match():
    coverage = [_coverage_item()]

    result = resolve_custom_blocker("experience", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_NO_MATCH


def test_rejects_nonsense_term():
    coverage = [_coverage_item()]

    result = resolve_custom_blocker("zzqqxx not a real thing", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_NO_MATCH


def test_rejects_expected_importance_requirement():
    coverage = [_coverage_item(importance="strongly_preferred")]

    result = resolve_custom_blocker("Salesforce", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_NOT_REQUIRED
    assert result["importance"] == "strongly_preferred"


def test_rejects_preferred_importance_requirement():
    coverage = [_coverage_item(importance="preferred")]

    result = resolve_custom_blocker("Salesforce", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_NOT_REQUIRED
    assert result["importance"] == "preferred"


def test_resolves_case_and_whitespace_alias_to_canonical_value():
    coverage = [_coverage_item()]

    result = resolve_custom_blocker("  SALESforce  ", coverage)

    assert result["ok"] is True
    assert result["canonical_requirement"] == "Salesforce"


def test_matches_against_matched_job_text_alias():
    coverage = [
        _coverage_item(
            requirement="Familiarity with the Salesforce CRM platform",
            canonical_requirement="Salesforce",
            matched_job_text="Salesforce CRM platform",
        )
    ]

    result = resolve_custom_blocker("Salesforce CRM platform", coverage)

    assert result["ok"] is True
    assert result["canonical_requirement"] == "Salesforce"


def test_rejects_ambiguous_term_matching_multiple_canonical_requirements():
    coverage = [
        _coverage_item(canonical_requirement="Salesforce", matched_job_text="CRM tooling"),
        _coverage_item(canonical_requirement="HubSpot", matched_job_text="CRM tooling"),
    ]

    result = resolve_custom_blocker("CRM tooling", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_AMBIGUOUS


def test_rejects_empty_input():
    coverage = [_coverage_item()]

    result = resolve_custom_blocker("", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_INVALID_INPUT


def test_rejects_single_character_input():
    coverage = [_coverage_item()]

    result = resolve_custom_blocker("a", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_INVALID_INPUT


def test_ignores_items_not_profile_action_allowed():
    coverage = [_coverage_item(profile_action_allowed=False)]

    result = resolve_custom_blocker("Salesforce", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_NO_MATCH


def test_ignores_items_with_disallowed_requirement_type():
    coverage = [_coverage_item(requirement_type="uncertain")]

    result = resolve_custom_blocker("Salesforce", coverage)

    assert result["ok"] is False
    assert result["reason_code"] == CUSTOM_BLOCKER_REASON_NO_MATCH


def test_list_candidates_returns_only_mandatory_actionable_requirements():
    coverage = [
        _coverage_item(canonical_requirement="Salesforce"),
        _coverage_item(canonical_requirement="HubSpot", importance="preferred"),
        _coverage_item(canonical_requirement="Marketo", profile_action_allowed=False),
        _coverage_item(canonical_requirement="Pardot", requirement_type="uncertain"),
        _coverage_item(canonical_requirement=""),
    ]

    candidates = list_custom_blocker_candidates(coverage)

    assert [c["term"] for c in candidates] == ["Salesforce"]
    assert candidates[0]["requirement_type"] == "capability"
    assert candidates[0]["matched_job_text"] == "Salesforce experience"


def test_list_candidates_dedupes_by_normalized_canonical():
    coverage = [
        _coverage_item(canonical_requirement="Salesforce"),
        _coverage_item(canonical_requirement="  salesforce  "),
    ]

    assert [c["term"] for c in list_custom_blocker_candidates(coverage)] == ["Salesforce"]


def test_list_candidates_stay_in_lockstep_with_resolver():
    coverage = [
        _coverage_item(canonical_requirement="Salesforce"),
        _coverage_item(
            canonical_requirement="Workday",
            requirement="Workday HCM administration",
            matched_job_text="Workday HCM",
        ),
    ]

    for candidate in list_custom_blocker_candidates(coverage):
        resolved = resolve_custom_blocker(candidate["term"], coverage)
        assert resolved["ok"] is True
        assert resolved["canonical_requirement"] == candidate["term"]
