"""Tests for deterministic capability/eligibility requirement classification."""

from job_hunter_agent import requirement_classification
from job_hunter_agent.llm_protocol import LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE


def test_years_of_experience_requirement_is_capability_even_if_llm_said_eligibility():
    result = requirement_classification.classify_requirement_type(
        "5+ years supporting client outcomes",
        "",
        "eligibility",
    )
    assert result == "capability"


def test_security_clearance_requirement_is_eligibility_even_if_llm_said_capability():
    result = requirement_classification.classify_requirement_type(
        "Ability to obtain Baseline security clearance",
        "",
        "capability",
    )
    assert result == "eligibility"


def test_eligibility_term_match_checks_matched_job_text_too():
    result = requirement_classification.classify_requirement_type(
        "Must be eligible",
        "Australian citizenship is required for this role",
        "capability",
    )
    assert result == "eligibility"


def test_plain_capability_requirement_defers_to_valid_llm_answer():
    result = requirement_classification.classify_requirement_type(
        "Strong stakeholder engagement skills",
        "",
        "capability",
    )
    assert result == "capability"


def test_conflicting_signals_are_uncertain_not_guessed():
    result = requirement_classification.classify_requirement_type(
        "5+ years working in a security clearance environment",
        "",
        "capability",
    )
    assert result == LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE


def test_blank_requirement_text_is_uncertain():
    assert (
        requirement_classification.classify_requirement_type("", "", "capability")
        == LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE
    )


def test_human_approved_override_wins_over_deterministic_terms(isolated_db):
    requirement_classification.upsert_requirement_classification_override(
        "5+ years working in a security clearance environment",
        "capability",
    )
    result = requirement_classification.classify_requirement_type(
        "5+ years working in a security clearance environment",
        "",
        "eligibility",
    )
    assert result == "capability"


def test_upsert_requirement_classification_override_rejects_invalid_classification(isolated_db):
    try:
        requirement_classification.upsert_requirement_classification_override(
            "some requirement",
            "not_a_real_type",
        )
        assert False, "expected ValueError"
    except ValueError:
        pass
