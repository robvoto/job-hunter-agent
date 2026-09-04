"""Tests for profile_gaps: gap computation and requirement status classification."""

from job_hunter_agent.profile_gaps import (
    PROFILE_GAP_JOB_REQUIREMENT_TEXT_KEY,
    STATUS_CONFIRMED_DO_NOT_HAVE,
    STATUS_CONFIRMED_HAVE,
    STATUS_UNKNOWN,
    classify_requirement_status,
    compute_profile_gaps,
)

_CAPABILITY_RULES = [
    {"name": "stakeholder engagement", "level": "strong", "aliases": ["stakeholder management"]},
    {"name": "process mapping", "level": "working", "aliases": []},
    {
        "name": "requirements analysis",
        "level": "strong",
        "aliases": ["requirements gathering", "business analysis"],
    },
]
_MUST_NOT_REQUIRE = ["payroll systems", "AHPRA registration"]

_REQUIREMENT_COVERAGE = [
    {
        "requirement": "Cloud computing (AWS) experience",
        "status": "not_shown",
        "capability_name": "Cloud computing (AWS)",
        "matched_job_text": "AWS platform experience",
        "profile_action_allowed": True,
        "matched_candidate_fact": "Cloud computing (AWS)",
    },
    {
        "requirement": "Permanent full-time role",
        "status": "not_shown",
        "capability_name": "",
        "matched_job_text": "Permanent full-time role",
        "matched_candidate_fact": "",
    },
    {
        "requirement": "Sydney",
        "status": "not_shown",
        "capability_name": "",
        "matched_job_text": "Sydney",
        "matched_candidate_fact": "",
    },
    {
        "requirement": "Salary package",
        "status": "not_shown",
        "capability_name": "",
        "matched_job_text": "Salary package",
        "matched_candidate_fact": "",
    },
]


# classify_requirement_status


def test_classify_exact_name_match_returns_confirmed_have():
    status = classify_requirement_status("stakeholder engagement", _CAPABILITY_RULES, [])
    assert status == STATUS_CONFIRMED_HAVE


def test_classify_alias_match_returns_confirmed_have():
    status = classify_requirement_status("stakeholder management experience", _CAPABILITY_RULES, [])
    assert status == STATUS_CONFIRMED_HAVE


def test_classify_partial_name_contained_in_requirement_returns_confirmed_have():
    status = classify_requirement_status(
        "Strong process mapping skills required", _CAPABILITY_RULES, []
    )
    assert status == STATUS_CONFIRMED_HAVE


def test_classify_must_not_require_match_returns_confirmed_do_not_have():
    status = classify_requirement_status(
        "Payroll systems experience", _CAPABILITY_RULES, _MUST_NOT_REQUIRE
    )
    assert status == STATUS_CONFIRMED_DO_NOT_HAVE


def test_classify_must_not_require_takes_precedence_over_capability_match():
    rules = [{"name": "payroll systems", "level": "basic", "aliases": []}]
    status = classify_requirement_status("payroll systems", rules, ["payroll systems"])
    assert status == STATUS_CONFIRMED_DO_NOT_HAVE


def test_classify_unknown_requirement_returns_unknown():
    status = classify_requirement_status(
        "exotic platform certification", _CAPABILITY_RULES, _MUST_NOT_REQUIRE
    )
    assert status == STATUS_UNKNOWN


def test_classify_empty_requirement_returns_unknown():
    assert classify_requirement_status("", _CAPABILITY_RULES, _MUST_NOT_REQUIRE) == STATUS_UNKNOWN
    assert (
        classify_requirement_status("   ", _CAPABILITY_RULES, _MUST_NOT_REQUIRE) == STATUS_UNKNOWN
    )


def test_classify_case_insensitive():
    status = classify_requirement_status("REQUIREMENTS ANALYSIS", _CAPABILITY_RULES, [])
    assert status == STATUS_CONFIRMED_HAVE


def test_classify_eligibility_requirement_uses_candidate_eligibility():
    status = classify_requirement_status(
        "PV clearance",
        [],
        [],
        [{"name": "PV clearance", "value": True}],
        requirement_type="eligibility",
    )
    assert status == STATUS_CONFIRMED_HAVE


def test_classify_eligibility_requirement_false_returns_do_not_have():
    status = classify_requirement_status(
        "PV clearance",
        [],
        [],
        [{"name": "PV clearance", "value": False}],
        requirement_type="eligibility",
    )
    assert status == STATUS_CONFIRMED_DO_NOT_HAVE


def test_classify_invalid_requirement_type_returns_unknown():
    status = classify_requirement_status("PV clearance", _CAPABILITY_RULES, _MUST_NOT_REQUIRE, requirement_type="credential")
    assert status == STATUS_UNKNOWN


# compute_profile_gaps


def test_compute_gaps_returns_only_uncertain_capability_requirement_coverage_items():
    gaps = compute_profile_gaps(_REQUIREMENT_COVERAGE, [], [])
    assert len(gaps) == 1
    assert gaps[0]["capability_name"] == "Cloud computing (AWS)"
    assert gaps[0]["raw_requirement"] == "Cloud computing (AWS) experience"
    assert gaps[0]["matched_job_text"] == "AWS platform experience"
    assert gaps[0][PROFILE_GAP_JOB_REQUIREMENT_TEXT_KEY] == "AWS platform experience"
    assert gaps[0]["status"] == "not_shown"


def test_compute_gaps_skips_non_capability_requirement_coverage_items():
    gaps = compute_profile_gaps(_REQUIREMENT_COVERAGE[1:], [], [])
    assert gaps == []


def test_compute_gaps_skips_requirement_coverage_when_capability_already_confirmed():
    confirmed_rules = [{"name": "Cloud computing (AWS)", "level": "strong", "aliases": []}]
    gaps = compute_profile_gaps(_REQUIREMENT_COVERAGE, confirmed_rules, [])
    assert gaps == []


def test_compute_gaps_skips_requirement_coverage_when_capability_is_must_not_require():
    gaps = compute_profile_gaps(_REQUIREMENT_COVERAGE, [], ["Cloud computing (AWS)"])
    assert gaps == []


def test_compute_gaps_empty_input_returns_empty():
    assert compute_profile_gaps([], _CAPABILITY_RULES, _MUST_NOT_REQUIRE) == []


def test_compute_gaps_excludes_item_without_profile_action_allowed():
    # A vague or alternative requirement (e.g. "CBAP or equivalent") never gets
    # profile_action_allowed set to True by the LLM gate. It must stay excluded
    # from confirmable gaps even though it is otherwise a plain, unconfirmed
    # capability-type item with a resolvable capability_name.
    unresolved_item = {
        "requirement": "CBAP or equivalent certification",
        "status": "not_shown",
        "capability_name": "CBAP",
        "matched_job_text": "CBAP or equivalent certification",
        "profile_action_allowed": False,
                          "matched_candidate_fact": "CBAP",
    }
    assert compute_profile_gaps([unresolved_item], [], []) == []

    missing_flag_item = dict(unresolved_item)
    del missing_flag_item["profile_action_allowed"]
    assert compute_profile_gaps([missing_flag_item], [], []) == []


_PARTIAL_MATCH_ITEM = {
    "requirement": "IT systems and infrastructure project management",
    "status": "partially_supported",
    "requirement_type": "capability",
    "capability_name": "Agile delivery management",
    "canonical_requirement": "IT systems and infrastructure project management",
    "matched_job_text": "Lead IT infrastructure projects",
    "profile_action_allowed": True,
    "matched_candidate_fact": "Agile delivery management",
}


def test_compute_gaps_partial_match_is_actionable_for_exact_canonical_requirement():
    # The LLM matched an adjacent capability the candidate holds, so the row is
    # partially_supported. The exact requested concept is still missing, so it
    # must be surfaced as a confirmable gap keyed on the exact canonical
    # requirement -- not the adjacent matched_candidate_fact.
    adjacent_confirmed = [
        {"name": "Agile delivery management", "level": "strong", "aliases": []}
    ]
    gaps = compute_profile_gaps([_PARTIAL_MATCH_ITEM], adjacent_confirmed, [])
    assert len(gaps) == 1
    assert gaps[0]["capability_name"] == "IT systems and infrastructure project management"
    assert gaps[0]["status"] == "partially_supported"
    assert gaps[0]["matched_candidate_fact"] == "Agile delivery management"


def test_compute_gaps_partial_match_skipped_when_exact_canonical_already_confirmed():
    exact_confirmed = [
        {
            "name": "IT systems and infrastructure project management",
            "level": "strong",
            "aliases": ["infrastructure project management"],
        }
    ]
    assert compute_profile_gaps([_PARTIAL_MATCH_ITEM], exact_confirmed, []) == []
