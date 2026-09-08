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
    # JH-298: the LLM's requirement_kind on a capability row. "" means the fixture
    # does not exercise the axis (row is a professional capability by default).
    llm_kind: str = ""


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
    item = {
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
    # JH-298 correction: a capability row with no requirement_kind now fails
    # closed to `unclassified` (non-scoring). A fixture that does not exercise the
    # kind axis represents an ordinary scored capability, so default it to
    # professional_capability; an explicit llm_kind on the fixture wins.
    if case.llm_kind:
        item["requirement_kind"] = case.llm_kind
    elif "capability" in (
        str(case.llm_type).strip().lower(),
        str(case.expected_type).strip().lower(),
    ):
        item["requirement_kind"] = llm_gate.LLM_REQUIREMENT_KIND_PROFESSIONAL
    return item


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
            if item["status"] in {"supported", "partially_supported"}:
                assert item[case.canonical_field] == case.matched_candidate_fact, case.wording
            elif case.expected_type == "eligibility":
                # Eligibility rows carry the canonical gate identity even when
                # not proven: eligibility_name / matched_candidate_fact name the
                # requirement itself, not a candidate proof. JH-299 evidence
                # integrity is scoped to capability / qualification proof.
                assert item[case.canonical_field] == case.matched_candidate_fact, case.wording
            else:
                # JH-299 AC4: a non-positive capability / qualification row keeps
                # the requirement concept (canonical_requirement / requirement)
                # but never a positive-looking matched candidate fact.
                assert item.get(case.canonical_field, "") == "", case.wording
                assert item["matched_candidate_fact"] == "", case.wording
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
    assert normalized[0]["status"] == "not_shown"
    # JH-299 AC4: the not_shown row carries the requirement concept, not a match.
    assert normalized[0]["capability_name"] == ""
    assert normalized[0]["matched_candidate_fact"] == ""
    assert normalized[0]["canonical_requirement"] == "Client outcomes"
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


# --------------------------------------------------------------------------- #
# JH-298 — behavioural expectation vs professional capability regression (AC-6)
# --------------------------------------------------------------------------- #
#
# Rows mirror the conversation ads that motivated JH-298: generic personal-conduct
# wording must classify as requirement_kind="behavioural_expectation" (capability
# type retained), get forced to not_assessed / non-actionable, partition into
# requirement_coverage_behavioural, and stay out of scoring and profile gaps.
# Observable professional activities in the same ads ("deliver projects",
# "document processes") must stay professional_capability and score as today.

_BEHAVIOURAL = llm_gate.LLM_REQUIREMENT_KIND_BEHAVIOURAL
_PROFESSIONAL = llm_gate.LLM_REQUIREMENT_KIND_PROFESSIONAL
_NOT_ASSESSED = llm_gate.LLM_NOT_ASSESSED_COVERAGE_STATUS


def _kind_case(
    source_job: str,
    wording: str,
    llm_kind: str,
    *,
    canonical_requirement: str = "",
    status: str = "not_shown",
) -> CapturedRequirement:
    return CapturedRequirement(
        source_job,
        wording,
        "capability",
        "preferred",
        "capability",
        canonical_requirement=canonical_requirement,
        matched_candidate_fact=canonical_requirement,
        status=status,
        matched_job_text=wording,
        canonical_field="capability_name" if canonical_requirement else "",
        llm_kind=llm_kind,
    )


_KIND_REGRESSION_CASES: tuple[CapturedRequirement, ...] = (
    # IPH — autonomy / adaptability are dispositions, not capabilities.
    _kind_case("iph", "Works autonomously with minimal supervision", _BEHAVIOURAL),
    _kind_case("iph", "Adaptable and comfortable with change", _BEHAVIOURAL),
    # GM3 — mixed sentence decomposed upstream: the conduct atom is behavioural,
    # "deliver projects" is a professional capability that still scores.
    _kind_case("gm3", "Able to work through ambiguity", _BEHAVIOURAL),
    _kind_case(
        "gm3",
        "Deliver projects end to end",
        _PROFESSIONAL,
        canonical_requirement="Project delivery",
        status="supported",
    ),
    # Tranzformd — documentation is an observable professional activity; "attention
    # to detail / sound judgement" is a personal quality.
    _kind_case(
        "tranzformd",
        "Produce technical process documentation",
        _PROFESSIONAL,
        canonical_requirement="Process documentation",
        status="supported",
    ),
    _kind_case("tranzformd", "Strong attention to detail and sound judgement", _BEHAVIOURAL),
    # Nestlé — curiosity / adaptability / "willingness to embrace AI" are
    # behavioural; the AI clause must never become an AI-development capability.
    _kind_case("nestle", "Naturally curious with a growth mindset", _BEHAVIOURAL),
    _kind_case(
        "nestle",
        "Willingness to embrace new technology including AI",
        _BEHAVIOURAL,
        canonical_requirement="AI development",
        status="supported",
    ),
)


def _kind_lookups() -> dict[str, dict[str, str]]:
    return {
        "capability": {
            "project delivery": "Project delivery",
            "process documentation": "Process documentation",
            "ai development": "AI development",
        }
    }


@pytest.mark.parametrize(
    "case",
    [c for c in _KIND_REGRESSION_CASES if c.llm_kind == _BEHAVIOURAL],
    ids=lambda c: c.wording,
)
def test_ac6_behavioural_ad_wording_is_display_only_capability(case):
    normalized = llm_gate.normalize_llm_requirement_coverage(
        [_raw_item(case)],
        valid_capability_names=_kind_lookups()["capability"],
    )
    assert len(normalized) == 1
    row = normalized[0]
    assert row["requirement_type"] == "capability", case.wording
    assert row["requirement_kind"] == _BEHAVIOURAL, case.wording
    assert row["behavioural_expectation"] is True, case.wording
    assert row["status"] == _NOT_ASSESSED, case.wording
    assert row["profile_action_allowed"] is False, case.wording
    # Over-stated canonical / match fields from the LLM are discarded, so a
    # "willingness to embrace AI" line can never surface as an AI capability.
    assert row["canonical_requirement"] == "", case.wording
    assert row["capability_name"] == "", case.wording
    assert row["matched_candidate_fact"] == "", case.wording


@pytest.mark.parametrize(
    "case",
    [c for c in _KIND_REGRESSION_CASES if c.llm_kind == _PROFESSIONAL],
    ids=lambda c: c.wording,
)
def test_ac6_professional_ad_wording_stays_scored_capability(case):
    normalized = llm_gate.normalize_llm_requirement_coverage(
        [_raw_item(case)],
        valid_capability_names=_kind_lookups()["capability"],
    )
    row = normalized[0]
    assert row["requirement_kind"] == _PROFESSIONAL, case.wording
    assert "behavioural_expectation" not in row, case.wording
    assert row["status"] == "supported", case.wording
    assert row["capability_name"] == case.canonical_requirement, case.wording


def test_ac6_full_ad_payload_partitions_behavioural_and_scores_professional():
    payload = llm_gate.normalize_llm_review_payload(
        {
            "decision": "KEEP",
            "grade": "STRONG",
            "requirement_coverage": [_raw_item(c) for c in _KIND_REGRESSION_CASES],
        },
        valid_capability_names=_kind_lookups()["capability"],
    )

    scored = payload["requirement_coverage"]
    behavioural = payload["requirement_coverage_behavioural"]

    scored_text = {row["requirement"] for row in scored}
    behavioural_text = {row["requirement"] for row in behavioural}

    assert scored_text == {
        "Deliver projects end to end",
        "Produce technical process documentation",
    }
    assert behavioural_text == {
        c.wording for c in _KIND_REGRESSION_CASES if c.llm_kind == _BEHAVIOURAL
    }
    assert all(row["status"] == _NOT_ASSESSED for row in behavioural)
    # No behavioural row leaks an AI-development (or any) capability concept.
    assert all(not row.get("capability_name") for row in behavioural)
    assert all(not row.get("canonical_requirement") for row in behavioural)

    # Scoring and gaps only ever see the scored partition.
    record = {"requirement_coverage": scored}
    record_with_behavioural = {
        "requirement_coverage": scored,
        "requirement_coverage_behavioural": behavioural,
    }
    profile = {"candidate_capabilities": [], "candidate_eligibility": []}
    assert fit_scoring.requirement_fit_diagnostics(record_with_behavioural, profile)[
        "total_requirement_weight"
    ] == fit_scoring.requirement_fit_diagnostics(record, profile)["total_requirement_weight"]

    gaps = compute_profile_gaps(behavioural, [], [], candidate_eligibility=[])
    assert gaps == []


# --- JH-299: evidence integrity for positive professional-capability coverage ---
#
# A positive coverage row must trace to specific candidate evidence that entails
# the same professional concept. A held role / job title proves only explicit
# role-family facts; shared generic tokens ("AI", a vendor name) are transferable
# framing, not proof; and a row that finishes non-positive keeps the requirement
# concept but never a positive-looking matched fact.

_JH299_CAPABILITY_LOOKUPS: dict[str, str] = {
    "data analysis": "Data analysis",
    "miro": "Miro",
    "workshop facilitation": "Workshop facilitation",
    "sap": "SAP",
    "delivery leadership": "Delivery leadership",
}


def _evidence_item(
    *,
    requirement: str,
    matched_candidate_fact: str,
    status: str = "supported",
    resolved_concept: str = "",
    canonical_fact_resolved: bool = True,
    profile_support: tuple[str, ...] = (),
    covered_requirement_elements: tuple[str, ...] = (),
    matched_job_text: str = "",
) -> dict:
    """A single-concept capability row as the fit-review LLM would return it,
    with the evidence fields (profile_support / covered_requirement_elements)
    that JH-299 validates. requirement_kind is set to professional_capability so
    the row is scored — these cases exercise the evidence-integrity axis, not the
    JH-298 requirement_kind fail-closed axis."""
    return {
        "requirement": requirement,
        "importance": "mandatory",
        "requirement_type": "capability",
        "requirement_kind": llm_gate.LLM_REQUIREMENT_KIND_PROFESSIONAL,
        "canonical_requirement": resolved_concept,
        "status": status,
        "matched_candidate_fact": matched_candidate_fact,
        "matched_job_text": matched_job_text or requirement,
        "profile_support": list(profile_support),
        "covered_requirement_elements": list(covered_requirement_elements),
        "decomposition": {
            "operator": "single",
            "elements": [
                {
                    "text": requirement,
                    "capability_judgement": "capability",
                    "canonical_concept": resolved_concept,
                    "canonical_fact_resolved": canonical_fact_resolved,
                    "status": status,
                    "matched_candidate_fact": matched_candidate_fact,
                }
            ],
        },
    }


def _normalize_jh299(raw: dict) -> dict:
    normalized = llm_gate.normalize_llm_requirement_coverage(
        [raw],
        valid_capability_names=_JH299_CAPABILITY_LOOKUPS,
    )
    assert len(normalized) == 1
    return normalized[0]


@pytest.mark.parametrize(
    "requirement",
    [
        "Works autonomously with minimal supervision",
        "Exercises sound professional judgement",
        "Advanced Jira administration",
        "Manages senior stakeholder relationships",
    ],
    ids=lambda text: text,
)
def test_ac6_role_title_alone_cannot_prove_a_professional_capability(requirement):
    row = _normalize_jh299(
        _evidence_item(
            requirement=requirement,
            matched_candidate_fact="Senior Business Analyst",
            canonical_fact_resolved=False,
            profile_support=("15 years as a Senior Business Analyst across finance programs.",),
        )
    )
    assert row["status"] == "not_shown", requirement
    assert row["matched_candidate_fact"] == "", requirement
    assert row["capability_name"] == "", requirement
    assert row["decomposition"]["elements"][0]["matched_candidate_fact"] == ""


def test_ac6_shared_ai_token_cannot_prove_ai_development():
    row = _normalize_jh299(
        _evidence_item(
            requirement="Hands-on contribution to AI model development",
            matched_candidate_fact="Data analysis",
            resolved_concept="Data analysis",
            covered_requirement_elements=("AI",),
            profile_support=("Comfortable adopting AI tools in day-to-day analysis work.",),
        )
    )
    assert row["status"] == "not_shown"
    assert row["matched_candidate_fact"] == ""
    assert row["capability_name"] == ""
    assert "covered_requirement_elements" not in row


def test_ac6_explicit_tool_evidence_stays_supported():
    row = _normalize_jh299(
        _evidence_item(
            requirement="Experience building process maps in Miro",
            matched_candidate_fact="Miro",
            resolved_concept="Miro",
            covered_requirement_elements=("process maps in Miro",),
            profile_support=(
                "Built current-state process maps in Miro for the finance transformation.",
            ),
        )
    )
    assert row["status"] == "supported"
    assert row["capability_name"] == "Miro"
    assert row["matched_candidate_fact"] == "Miro"


def test_ac6_explicit_facilitation_evidence_stays_supported():
    row = _normalize_jh299(
        _evidence_item(
            requirement="Facilitate discovery workshops with stakeholders",
            matched_candidate_fact="Workshop facilitation",
            resolved_concept="Workshop facilitation",
            covered_requirement_elements=("facilitate discovery workshops",),
            profile_support=(
                "Facilitated discovery workshops with stakeholders across three programs.",
            ),
        )
    )
    assert row["status"] == "supported"
    assert row["capability_name"] == "Workshop facilitation"


def test_ac3_vendor_evidence_does_not_prove_versioned_platform():
    row = _normalize_jh299(
        _evidence_item(
            requirement="SAP S/4HANA finance configuration",
            matched_candidate_fact="SAP",
            resolved_concept="SAP",
            covered_requirement_elements=("SAP",),
            profile_support=("Configured SAP finance modules for month-end close.",),
        )
    )
    assert row["status"] == "not_shown"
    assert row["matched_candidate_fact"] == ""
    assert row["capability_name"] == ""


def test_ac4_non_positive_row_from_llm_carries_no_positive_evidence():
    row = _normalize_jh299(
        _evidence_item(
            requirement="Lead a portfolio of concurrent delivery programs",
            matched_candidate_fact="Delivery leadership",
            resolved_concept="Delivery leadership",
            status="not_shown",
            covered_requirement_elements=("concurrent delivery programs",),
            profile_support=("Led concurrent delivery programs across the PMO.",),
        )
    )
    assert row["status"] == "not_shown"
    assert row["matched_candidate_fact"] == ""
    assert row["capability_name"] == ""
    assert row["profile_support"] == []
    assert "covered_requirement_elements" not in row
    assert row["decomposition"]["elements"][0]["matched_candidate_fact"] == ""
    # The requirement concept itself is still available to profile-gap and
    # renderer consumers; only the positive-looking match is gone.
    assert row["canonical_requirement"] == "Delivery leadership"


# AC7: a captured fit-review structured output as a real model returned it, with
# two over-stated positive rows (a role title standing in for a capability, and a
# shared "AI" token standing in for AI development), one genuine explicit match,
# and one not_shown row the model left carrying a positive-looking fact. Run
# through the full production normalization path (normalize_llm_review_payload),
# the two over-claims and the dirty not_shown row must be cleaned; the genuine
# match must survive untouched.
_JH299_CAPTURED_FIT_REVIEW_PAYLOAD: dict = {
    "decision": "KEEP",
    "grade": "WEAK",
    "requirement_coverage": [
        {
            "requirement": "Works autonomously with minimal supervision",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "professional_capability",
            "status": "supported",
            "canonical_requirement": "",
            "matched_candidate_fact": "Senior Business Analyst",
            "matched_job_text": "Works autonomously with minimal supervision",
            "profile_support": ["15 years as a Senior Business Analyst delivering finance change."],
            "covered_requirement_elements": ["autonomously"],
            "decomposition": {
                "operator": "single",
                "elements": [
                    {
                        "text": "Works autonomously with minimal supervision",
                        "capability_judgement": "capability",
                        "canonical_concept": "",
                        "canonical_fact_resolved": False,
                        "status": "supported",
                        "matched_candidate_fact": "Senior Business Analyst",
                    }
                ],
            },
        },
        {
            "requirement": "Hands-on contribution to AI product development",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "professional_capability",
            "status": "supported",
            "canonical_requirement": "Data analysis",
            "matched_candidate_fact": "Data analysis",
            "matched_job_text": "Hands-on contribution to AI product development",
            "profile_support": ["Keen to adopt AI tooling across the analysis workflow."],
            "covered_requirement_elements": ["AI"],
            "decomposition": {
                "operator": "single",
                "elements": [
                    {
                        "text": "Hands-on contribution to AI product development",
                        "capability_judgement": "capability",
                        "canonical_concept": "Data analysis",
                        "canonical_fact_resolved": True,
                        "status": "supported",
                        "matched_candidate_fact": "Data analysis",
                    }
                ],
            },
        },
        {
            "requirement": "Facilitate stakeholder workshops and elicitation sessions",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "professional_capability",
            "status": "supported",
            "canonical_requirement": "Workshop facilitation",
            "matched_candidate_fact": "Workshop facilitation",
            "matched_job_text": "Facilitate stakeholder workshops and elicitation sessions",
            "profile_support": [
                "Facilitated stakeholder workshops and requirements elicitation across three programs.",
            ],
            "covered_requirement_elements": ["facilitate stakeholder workshops"],
            "decomposition": {
                "operator": "single",
                "elements": [
                    {
                        "text": "Facilitate stakeholder workshops and elicitation sessions",
                        "capability_judgement": "capability",
                        "canonical_concept": "Workshop facilitation",
                        "canonical_fact_resolved": True,
                        "status": "supported",
                        "matched_candidate_fact": "Workshop facilitation",
                    }
                ],
            },
        },
        {
            "requirement": "Own the enterprise data governance framework",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "professional_capability",
            "status": "not_shown",
            "canonical_requirement": "Data governance",
            "matched_candidate_fact": "Data analysis",
            "matched_job_text": "Own the enterprise data governance framework",
            "profile_support": ["Ran data analysis for the finance team."],
            "covered_requirement_elements": ["data"],
            "decomposition": {
                "operator": "single",
                "elements": [
                    {
                        "text": "Own the enterprise data governance framework",
                        "capability_judgement": "capability",
                        "canonical_concept": "Data governance",
                        "canonical_fact_resolved": True,
                        "status": "not_shown",
                        "matched_candidate_fact": "Data analysis",
                    }
                ],
            },
        },
    ],
}


def test_ac7_captured_fit_review_output_rejects_unsupported_semantic_evidence():
    payload = llm_gate.normalize_llm_review_payload(
        _JH299_CAPTURED_FIT_REVIEW_PAYLOAD,
        valid_capability_names={
            "data analysis": "Data analysis",
            "workshop facilitation": "Workshop facilitation",
            "data governance": "Data governance",
        },
    )
    rows = {row["requirement"]: row for row in payload["requirement_coverage"]}

    autonomy = rows["Works autonomously with minimal supervision"]
    assert autonomy["status"] == "not_shown"
    assert autonomy["matched_candidate_fact"] == ""
    assert autonomy["capability_name"] == ""

    ai = rows["Hands-on contribution to AI product development"]
    assert ai["status"] == "not_shown"
    assert ai["matched_candidate_fact"] == ""
    assert ai["capability_name"] == ""
    assert "covered_requirement_elements" not in ai

    workshops = rows["Facilitate stakeholder workshops and elicitation sessions"]
    assert workshops["status"] == "supported"
    assert workshops["capability_name"] == "Workshop facilitation"
    assert workshops["matched_candidate_fact"] == "Workshop facilitation"

    governance = rows["Own the enterprise data governance framework"]
    assert governance["status"] == "not_shown"
    assert governance["matched_candidate_fact"] == ""
    assert governance["capability_name"] == ""
    assert governance["profile_support"] == []
    assert governance["decomposition"]["elements"][0]["matched_candidate_fact"] == ""
