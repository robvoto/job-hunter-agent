"""Tests for profile_gaps: gap computation and requirement status classification."""

import pytest

from job_hunter_agent.profile_gaps import (
    STATUS_CONFIRMED_DO_NOT_HAVE,
    STATUS_CONFIRMED_HAVE,
    STATUS_UNKNOWN,
    classify_requirement_status,
    compute_profile_gaps,
)


_CAPABILITY_RULES = [
    {"name": "stakeholder engagement", "level": "strong", "aliases": ["stakeholder management"]},
    {"name": "process mapping", "level": "working", "aliases": []},
    {"name": "requirements analysis", "level": "strong", "aliases": ["requirements gathering", "business analysis"]},
]
_MUST_NOT_REQUIRE = ["payroll systems", "AHPRA registration"]


# ── classify_requirement_status ────────────────────────────────────────────────

def test_classify_exact_name_match_returns_confirmed_have():
    status = classify_requirement_status("stakeholder engagement", _CAPABILITY_RULES, [])
    assert status == STATUS_CONFIRMED_HAVE


def test_classify_alias_match_returns_confirmed_have():
    status = classify_requirement_status("stakeholder management experience", _CAPABILITY_RULES, [])
    assert status == STATUS_CONFIRMED_HAVE


def test_classify_partial_name_contained_in_requirement_returns_confirmed_have():
    status = classify_requirement_status("Strong process mapping skills required", _CAPABILITY_RULES, [])
    assert status == STATUS_CONFIRMED_HAVE


def test_classify_must_not_require_match_returns_confirmed_do_not_have():
    status = classify_requirement_status("Payroll systems experience", _CAPABILITY_RULES, _MUST_NOT_REQUIRE)
    assert status == STATUS_CONFIRMED_DO_NOT_HAVE


def test_classify_must_not_require_takes_precedence_over_capability_match():
    rules = [{"name": "payroll systems", "level": "basic", "aliases": []}]
    status = classify_requirement_status("payroll systems", rules, ["payroll systems"])
    assert status == STATUS_CONFIRMED_DO_NOT_HAVE


def test_classify_unknown_requirement_returns_unknown():
    status = classify_requirement_status("exotic platform certification", _CAPABILITY_RULES, _MUST_NOT_REQUIRE)
    assert status == STATUS_UNKNOWN


def test_classify_empty_requirement_returns_unknown():
    assert classify_requirement_status("", _CAPABILITY_RULES, _MUST_NOT_REQUIRE) == STATUS_UNKNOWN
    assert classify_requirement_status("   ", _CAPABILITY_RULES, _MUST_NOT_REQUIRE) == STATUS_UNKNOWN


def test_classify_case_insensitive():
    status = classify_requirement_status("REQUIREMENTS ANALYSIS", _CAPABILITY_RULES, [])
    assert status == STATUS_CONFIRMED_HAVE


# ── compute_profile_gaps ───────────────────────────────────────────────────────

def test_compute_gaps_returns_only_unknown_requirements():
    requirements = [
        "stakeholder engagement",          # matched — confirmed_have
        "payroll systems",                  # in must_not_require — confirmed_do_not_have
        "specialist platform certification",  # unmatched — unknown
    ]
    gaps = compute_profile_gaps(requirements, _CAPABILITY_RULES, _MUST_NOT_REQUIRE)
    assert len(gaps) == 1
    assert gaps[0]["requirement"] == "specialist platform certification"
    assert gaps[0]["status"] == STATUS_UNKNOWN


def test_compute_gaps_returns_empty_when_all_confirmed():
    requirements = ["stakeholder engagement", "process mapping"]
    gaps = compute_profile_gaps(requirements, _CAPABILITY_RULES, [])
    assert gaps == []


def test_compute_gaps_returns_all_when_no_profile():
    requirements = ["term a", "term b"]
    gaps = compute_profile_gaps(requirements, [], [])
    assert len(gaps) == 2
    assert all(g["status"] == STATUS_UNKNOWN for g in gaps)


def test_compute_gaps_skips_empty_strings():
    gaps = compute_profile_gaps(["", "  ", "real requirement"], [], [])
    assert len(gaps) == 1
    assert gaps[0]["requirement"] == "real requirement"


def test_compute_gaps_result_includes_evidence_equal_to_requirement():
    gaps = compute_profile_gaps(["some requirement"], [], [])
    assert gaps[0]["evidence"] == gaps[0]["requirement"]


def test_compute_gaps_empty_input_returns_empty():
    assert compute_profile_gaps([], _CAPABILITY_RULES, _MUST_NOT_REQUIRE) == []
