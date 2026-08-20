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


def test_qualification_wording_defers_to_llm_qualification_type():
    result = requirement_classification.classify_requirement_type(
        "CBAP certification",
        "",
        "qualification",
    )
    assert result == "qualification"


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


def test_security_clearance_requirement_preserves_clearance_subtype():
    assert (
        requirement_classification.classify_requirement_subtype(
            "Ability to obtain Baseline security clearance"
        )
        == "clearance"
    )


def test_right_to_work_requirement_preserves_work_rights_subtype():
    assert requirement_classification.classify_requirement_subtype("Right to work in Australia") == "work_rights"


def test_compound_eligibility_subtypes_are_not_guessed():
    assert (
        requirement_classification.classify_requirement_subtype(
            "Must be an Australian citizen and hold NV1 clearance"
        )
        == ""
    )


def test_human_approved_eligibility_subtype_is_persisted(isolated_db):
    text = "Right to work in Australia"
    requirement_classification.upsert_requirement_classification_override(
        text,
        "eligibility",
        "work_rights",
    )

    assert requirement_classification.load_requirement_subtype_overrides()[text.lower()] == "work_rights"
    assert requirement_classification.classify_requirement_subtype(text) == "work_rights"


def test_llm_other_eligibility_subtype_is_kept_when_terms_do_not_resolve_one():
    assert (
        requirement_classification.classify_requirement_subtype(
            "Must satisfy a formal entry condition",
            llm_requirement_subtype="other",
        )
        == "other"
    )


def test_default_eligibility_subtype_is_managed():
    default_subtype = requirement_classification.load_default_eligibility_subtype()
    assert default_subtype == "other"
    assert default_subtype in requirement_classification.load_eligibility_subtypes()
