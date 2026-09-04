"""Regression coverage for captured job-ad requirement interpretation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from job_hunter_agent import fit_scoring, llm_gate
from job_hunter_agent.profile_gaps import compute_profile_gaps
from job_hunter_agent.requirement_classification import classify_requirement_type


@dataclass(frozen=True)
class CapturedRequirement:
    source_job: str
    wording: str
    expected_type: str
    expected_importance: str
    llm_type: str
    canonical_requirement: str = ""
    matched_candidate_fact: str = ""
    status: str = "not_shown"
    matched_job_text: str = ""
    profile_support: tuple[str, ...] = ()
    canonical_field: str = ""


@pytest.fixture()
def captured_requirements() -> tuple[CapturedRequirement, ...]:
    """Representative rows from the captured Worrells and Unisys SEEK ads."""
    return (
        CapturedRequirement(
            "seek:93806022",
            "A Bachelor Degree or equivalent in Commerce, Finance or Accounting",
            "qualification",
            "mandatory",
            "qualification",
            canonical_requirement="Bachelor Degree",
            matched_candidate_fact="Bachelor Degree",
            canonical_field="qualification_name",
        ),
        CapturedRequirement(
            "seek:93806022",
            "CA or CPA qualified (or willing to obtain)",
            "qualification",
            "mandatory",
            "qualification",
            matched_job_text="CA or CPA qualified (or willing to obtain)",
        ),
        CapturedRequirement(
            "seek:93806022",
            "ARITA Introduction to Insolvency certification",
            "qualification",
            "mandatory",
            "qualification",
            canonical_requirement="ARITA Introduction to Insolvency",
            matched_candidate_fact="ARITA Introduction to Insolvency",
            canonical_field="qualification_name",
        ),
        CapturedRequirement(
            "seek:93806022",
            "ARITA professional qualification (or willing to obtain)",
            "qualification",
            "mandatory",
            "qualification",
            canonical_requirement="ARITA professional qualification",
            matched_candidate_fact="ARITA professional qualification",
            matched_job_text="ARITA professional qualification (or willing to obtain)",
            canonical_field="qualification_name",
        ),
        CapturedRequirement(
            "seek:93806022",
            "Previous experience in insolvency is required",
            "capability",
            "mandatory",
            "capability",
            canonical_requirement="Insolvency experience",
            matched_candidate_fact="Insolvency experience",
            canonical_field="capability_name",
        ),
        CapturedRequirement(
            "seek:93865558",
            "Australian Citizenship is Required",
            "eligibility",
            "mandatory",
            "capability",
            canonical_requirement="Australian Citizenship",
            matched_candidate_fact="Australian Citizenship",
            canonical_field="eligibility_name",
        ),
        CapturedRequirement(
            "seek:93865558",
            "NV2 Security Clearance Required",
            "eligibility",
            "mandatory",
            "capability",
            canonical_requirement="NV2",
            matched_candidate_fact="NV2",
            canonical_field="eligibility_name",
        ),
        CapturedRequirement(
            "seek:93865558",
            "Relevant qualifications in Business Analysis, Information Technology, Project Management, or a related field",
            "qualification",
            "mandatory",
            "qualification",
        ),
        CapturedRequirement(
            "seek:93865558",
            "CBAP, Agile BA, or equivalent certifications are desirable",
            "qualification",
            "preferred",
            "qualification",
        ),
        CapturedRequirement(
            "capability-controls",
            "5+ years supporting client outcomes",
            "capability",
            "mandatory",
            "eligibility",
            canonical_requirement="Client outcomes",
            matched_candidate_fact="Client outcomes",
            canonical_field="capability_name",
        ),
        CapturedRequirement(
            "capability-controls",
            "Strong stakeholder management and communication skills",
            "capability",
            "mandatory",
            "capability",
            canonical_requirement="Stakeholder management",
            matched_candidate_fact="Stakeholder management",
            profile_support=("Led stakeholder management and communication across delivery teams.",),
            status="supported",
            canonical_field="capability_name",
        ),
    )


def _profile_lookups() -> dict[str, dict[str, str]]:
    return {
        "capability": {
            "insolvency experience": "Insolvency experience",
            "client outcomes": "Client outcomes",
            "stakeholder management": "Stakeholder management",
        },
        "eligibility": {
            "australian citizenship": "Australian Citizenship",
            "nv2": "NV2",
        },
        "qualification": {
            "bachelor degree": "Bachelor Degree",
            "arita introduction to insolvency": "ARITA Introduction to Insolvency",
            "arita professional qualification": "ARITA professional qualification",
            "cbap": "CBAP",
        },
    }


def _raw_item(case: CapturedRequirement) -> dict:
    return {
        "requirement": case.wording,
        "importance": case.expected_importance,
        "requirement_type": case.llm_type,
        "canonical_requirement": case.canonical_requirement,
        "status": case.status,
        "matched_candidate_fact": case.matched_candidate_fact,
        "matched_job_text": case.matched_job_text or case.wording,
        "profile_support": list(case.profile_support),
        # Canonical single-concept decomposition. A resolved canonical concept is
        # only trusted when the fixture actually supplies one, matching how a real
        # LLM response would leave canonical_fact_resolved false for an
        # unresolved / compound clause.
        "decomposition": {
            "operator": "single",
            "elements": [
                {
                    "text": case.wording,
                    "capability_judgement": "capability",
                    "canonical_concept": case.canonical_requirement,
                    "canonical_fact_resolved": bool(case.canonical_requirement),
                    "status": case.status,
                    "matched_candidate_fact": case.matched_candidate_fact,
                }
            ],
        },
    }


@pytest.mark.parametrize(
    "wording, llm_type, expected_type",
    [
        ("5+ years supporting client outcomes", "eligibility", "capability"),
        ("Strong stakeholder management and communication skills", "capability", "capability"),
    ],
)
def test_capability_controls_are_capabilities_even_when_llm_proposes_other_type(
    wording, llm_type, expected_type
):
    assert classify_requirement_type(wording, "", llm_type) == expected_type


def test_captured_rows_use_production_normalization_and_preserve_safe_profile_fields(
    captured_requirements,
):
    lookups = _profile_lookups()

    for case in captured_requirements:
        normalized = llm_gate.normalize_llm_requirement_coverage(
            [_raw_item(case)],
            valid_capability_names=lookups["capability"],
            valid_eligibility_names=lookups["eligibility"],
            valid_qualification_names=lookups["qualification"],
        )

        assert len(normalized) == 1, case.wording
        item = normalized[0]
        assert item["requirement_type"] == case.expected_type, case.wording
        assert item["importance"] == case.expected_importance, case.wording
        assert item["requirement"] == case.wording, case.wording

        if case.canonical_field:
            assert item[case.canonical_field] == case.matched_candidate_fact, case.wording
        if case.expected_type == "qualification" and not case.canonical_requirement:
            assert item["canonical_requirement"] == "", case.wording
            assert item["matched_job_text"] == (case.matched_job_text or case.wording), case.wording
        if case.expected_type == "qualification" and case.canonical_requirement:
            assert item["canonical_requirement"] == case.canonical_requirement, case.wording
            assert item["canonical_requirement"] != case.wording, case.wording


def test_raw_captured_ad_sentences_are_not_stored_as_qualification_names(
    captured_requirements,
):
    """The qualification-save boundary (routes/review.py's confirm_have) stores
    canonical_requirement, gated by profile_action_allowed — never the raw
    requirement wording. For every captured qualification-type row, whatever the
    production pipeline would allow into candidate_qualifications must never be
    the raw ad sentence itself.
    """
    qualification_rows = [
        case for case in captured_requirements if case.expected_type == "qualification"
    ]
    assert qualification_rows

    for case in qualification_rows:
        normalized = llm_gate.normalize_llm_requirement_coverage(
            [_raw_item(case)],
            valid_qualification_names=_profile_lookups()["qualification"],
        )
        item = normalized[0]
        if item["profile_action_allowed"]:
            stored_name = item["canonical_requirement"]
            assert stored_name == case.canonical_requirement, case.wording
        else:
            stored_name = ""
        assert stored_name != case.wording, case.wording


def test_unisys_review_rejects_missing_required_nv2_but_not_preferred_cbap():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "EXCELLENT",
            "requirement_coverage": [
                _raw_item(
                    CapturedRequirement(
                        "seek:93865558",
                        "Australian Citizenship is Required",
                        "eligibility",
                        "mandatory",
                        "capability",
                        canonical_requirement="Australian Citizenship",
                        matched_candidate_fact="Australian Citizenship",
                        status="supported",
                    )
                ),
                _raw_item(
                    CapturedRequirement(
                        "seek:93865558",
                        "NV2 Security Clearance Required",
                        "eligibility",
                        "mandatory",
                        "capability",
                        canonical_requirement="NV2",
                        matched_candidate_fact="NV2",
                        status="mismatch",
                    )
                ),
                _raw_item(
                    CapturedRequirement(
                        "seek:93865558",
                        "CBAP, Agile BA, or equivalent certifications are desirable",
                        "qualification",
                        "preferred",
                        "qualification",
                        status="mismatch",
                    )
                ),
            ],
        },
        valid_eligibility_names=_profile_lookups()["eligibility"],
        valid_qualification_names=_profile_lookups()["qualification"],
    )

    assert payload["fit_review"]["decision"] == "REJECT"
    rows = payload["requirement_coverage"]
    assert [row["requirement_type"] for row in rows] == [
        "eligibility",
        "eligibility",
        "qualification",
    ]
    assert rows[2]["importance"] == "preferred"
    assert llm_gate.has_eligibility_mismatch(rows[1:2])
    assert not llm_gate.has_eligibility_mismatch(rows[2:3])


@pytest.mark.parametrize(
    "wording, canonical",
    [
        ("CA or CPA qualified (or willing to obtain)", ""),
        ("ARITA professional qualification (or willing to obtain)", "ARITA professional qualification"),
    ],
)
def test_willing_to_obtain_is_unresolved_not_already_held_requirement(wording, canonical):
    case = CapturedRequirement(
        "seek:93806022",
        wording,
        "qualification",
        "mandatory",
        "qualification",
        canonical_requirement=canonical,
        matched_candidate_fact=canonical,
        matched_job_text=wording,
    )
    normalized = llm_gate.normalize_llm_requirement_coverage(
        [_raw_item(case)], valid_qualification_names=_profile_lookups()["qualification"]
    )
    row = normalized[0]
    record = {"requirement_coverage": normalized}

    assert row["requirement_type"] == "qualification"
    assert row["status"] == "not_shown"
    assert row["requirement"] == wording
    assert fit_scoring.eligibility_gate_diagnostics(record, {"candidate_qualifications": []})[
        "status"
    ] == fit_scoring.ELIGIBILITY_GATE_UNRESOLVED
    assert not llm_gate.has_eligibility_mismatch(normalized)


def test_required_qualification_definitely_absent_rejects():
    case = CapturedRequirement(
        "seek:93865558",
        "Relevant qualification is required",
        "qualification",
        "mandatory",
        "qualification",
        canonical_requirement="CBAP",
        matched_candidate_fact="CBAP",
        status="mismatch",
    )
    normalized = llm_gate.normalize_llm_requirement_coverage(
        [_raw_item(case)], valid_qualification_names={"cbap": "CBAP"}
    )
    payload = llm_gate.normalize_llm_review_payload(
        {"decision": "KEEP", "grade": "STRONG", "requirement_coverage": [_raw_item(case)]},
        valid_qualification_names={"cbap": "CBAP"},
    )

    assert normalized[0]["requirement_type"] == "qualification"
    assert payload["fit_review"]["decision"] == "REJECT"
    assert fit_scoring.eligibility_gate_diagnostics(
        {"requirement_coverage": normalized},
        {"candidate_qualifications": [{"name": "CBAP", "value": False}]},
    )["status"] == fit_scoring.ELIGIBILITY_GATE_FAIL


def test_required_capability_gap_affects_fit_without_becoming_eligibility_gate():
    case = CapturedRequirement(
        "capability-controls",
        "5+ years supporting client outcomes",
        "capability",
        "mandatory",
        "eligibility",
        canonical_requirement="Client outcomes",
        matched_candidate_fact="Client outcomes",
    )
    normalized = llm_gate.normalize_llm_requirement_coverage(
        [_raw_item(case)], valid_capability_names={"client outcomes": "Client outcomes"}
    )
    record = {
        "requirement_coverage": normalized,
        "job_key": "test:capability",
        "llm_decision": "KEEP",
        "llm_fit_grade": "WEAK",
    }
    profile = {
        "candidate_capabilities": [],
        "candidate_eligibility": [],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }

    assert normalized[0]["requirement_type"] == "capability"
    assert normalized[0]["capability_name"] == "Client outcomes"
    assert fit_scoring.fit_score(record, profile) == 0
    assert fit_scoring.eligibility_gate_diagnostics(record, profile)["status"] == (
        fit_scoring.ELIGIBILITY_GATE_NOT_APPLICABLE
    )
    assert compute_profile_gaps(normalized, [], [], candidate_eligibility=[])[0][
        "requirement_type"
    ] == "capability"


def test_compound_preferred_qualification_stays_one_non_gating_row():
    case = CapturedRequirement(
        "seek:93865558",
        "CBAP, Agile BA, or equivalent certifications are desirable",
        "qualification",
        "preferred",
        "qualification",
        status="not_shown",
    )
    normalized = llm_gate.normalize_llm_requirement_coverage(
        [_raw_item(case)], valid_qualification_names={"cbap": "CBAP"}
    )

    assert len(normalized) == 1
    assert normalized[0]["canonical_requirement"] == ""
    assert normalized[0]["matched_candidate_fact"] == ""
    assert "qualification_name" not in normalized[0]
    assert normalized[0]["importance"] == "preferred"
    payload = llm_gate.normalize_llm_review_payload(
        {"decision": "KEEP", "grade": "STRONG", "requirement_coverage": [_raw_item(case)]},
        valid_qualification_names={"cbap": "CBAP"},
    )
    assert payload["fit_review"]["decision"] == "KEEP"
    assert fit_scoring.eligibility_gate_diagnostics(
        {"requirement_coverage": normalized}, {"candidate_qualifications": []}
    )["status"] == fit_scoring.ELIGIBILITY_GATE_NOT_APPLICABLE
