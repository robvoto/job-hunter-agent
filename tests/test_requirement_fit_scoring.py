import json

import pytest

from job_hunter_agent import fit_scoring, llm_gate


def _profile():
    return {
        "candidate_capabilities": [
            {"name": "stakeholder engagement", "level": "strong"},
            {"name": "sql", "level": "working"},
            {"name": "salesforce", "level": "basic"},
            {"name": "legacy coding", "level": "low"},
        ],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }


def _record(coverage, **extra):
    record = {
        "job_key": "test:job",
        "source": "test",
        "title": "Business Analyst",
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        "requirement_coverage": coverage,
    }
    record.update(extra)
    return record


def _capability_lookup(profile):
    lookup = {}
    for rule in profile["candidate_capabilities"]:
        canonical = rule["name"]
        for term in [canonical, *(rule.get("aliases") or [])]:
            lookup[term.lower()] = canonical
    return lookup


def _normalize_capability_row(raw_row, profile, role_experience=None):
    # JH-298 correction: a capability row with no requirement_kind now fails
    # closed to `unclassified` (non-scoring). These fixtures are ordinary scored
    # capabilities, so stamp professional_capability unless the row sets its own.
    if str(raw_row.get("requirement_type") or "capability").strip().lower() == "capability" and not str(
        raw_row.get("requirement_kind") or ""
    ).strip():
        raw_row = {**raw_row, "requirement_kind": "professional_capability"}
    return llm_gate.normalize_llm_requirement_coverage(
        [raw_row],
        valid_capability_names=_capability_lookup(profile),
        role_experience=role_experience,
    )[0]


def test_requirement_fit_all_supported_strong_is_100():
    record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement", "matched_candidate_fact": "stakeholder engagement"}
    ], title_match_metadata={"match_family": "primary"}, salary="$300k", posted_age_days=0)

    assert fit_scoring.fit_score(record, _profile()) == 100
    labels = [entry["label"] for entry in fit_scoring.fit_score_breakdown(record, _profile())]
    assert labels[0].startswith("Requirement Fit: 100%")
    assert not any("Grade band" in label for label in labels)


def test_requirement_fit_audit_exposes_exact_evidence_mapping_and_credit():
    record = _record([
        {
            "requirement": "5–7 years in digital health",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "partially_supported",
            "matched_candidate_fact": "stakeholder engagement",
            "capability_name": "stakeholder engagement",
            "match_source": "related_skill",
            "matched_profile_term": "stakeholder workshops",
            "matched_job_text": "5–7 years' experience in digital health",
            "profile_support": ["Facilitated stakeholders on a health infrastructure program."],
        }
    ])

    rows = fit_scoring.requirement_fit_audit_rows(record, _profile())

    assert rows == [
        {
            "requirement": "5–7 years in digital health",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "partially_supported",
            "matched_candidate_fact": "stakeholder engagement",
            "candidate_level": "strong",
            "match_source": "related_skill",
            "matched_profile_term": "stakeholder workshops",
            "matched_job_text": "5–7 years' experience in digital health",
            "profile_support": ["Facilitated stakeholders on a health infrastructure program."],
            "requirement_weight": 3.0,
            "raw_requirement_weight": 3.0,
            "is_eligibility_gate": False,
            "level_credit": 1.0,
            "status_credit": 0.5,
            "credit_fraction": 0.5,
            "weighted_credit": 1.5,
            "required_experience_months": 0,
            "matched_role_family": "",
            "matched_role_family_months": 0,
            "matched_role_family_end_year": 0,
            "experience_requirement_met": False,
            "experience_duration_gap": False,
            "experience_requirement_review_needed": False,
        }
    ]


def test_requirement_fit_diagnostics_and_formatter_cover_all_status_types():
    profile = {
        "candidate_capabilities": [
            {"name": "stakeholder engagement", "level": "strong"},
            {"name": "sql", "level": "working"},
        ],
        "candidate_eligibility": [{"name": "PV clearance", "value": True}],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }
    record = _record(
        [
            {
                "requirement": "Stakeholder workshops",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "stakeholder engagement",
                "match_source": "capability_name",
                "matched_profile_term": "stakeholder engagement",
                "profile_support": ["Ran stakeholder workshops."],
            },
            {
                "requirement": "SQL analysis",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "partially_supported",
                "matched_candidate_fact": "sql",
                "match_source": "related_skill",
                "matched_profile_term": "sql analysis",
                "profile_support": ["Used SQL for analysis."],
            },
            {
                "requirement": "Hold PV clearance",
                "importance": "mandatory",
                "requirement_type": "eligibility",
                "status": "supported",
                "matched_candidate_fact": "PV clearance",
                "match_source": "eligibility",
                "matched_profile_term": "PV clearance",
                "profile_support": ["PV clearance confirmed."],
            },
            {
                "requirement": "Python engineering",
                "importance": "preferred",
                "requirement_type": "capability",
                "status": "not_shown",
                "matched_candidate_fact": "",
                "profile_support": [],
            },
            {
                "requirement": "Australian citizenship",
                "importance": "preferred",
                "requirement_type": "eligibility",
                "status": "mismatch",
                "matched_candidate_fact": "",
                "profile_support": [],
            },
            {
                "requirement": "Data platform uplift",
                "importance": "mandatory",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "",
                "profile_support": [],
            },
        ]
    )

    diagnostics = fit_scoring.requirement_fit_diagnostics(record, profile)

    assert diagnostics["earned_weighted_credit"] == 4.05
    assert diagnostics["total_requirement_weight"] == 10.0
    assert diagnostics["final_requirement_fit"] == 40
    assert diagnostics["final_calculation_label"] == "4.05 ÷ 10 × 100"
    assert [row["status"] for row in diagnostics["rows"]] == [
        "supported",
        "partially_supported",
        "supported",
        "not_shown",
        "mismatch",
        "supported",
    ]
    assert diagnostics["rows"][0]["calculation_label"] == "3 × 1 × 1 = 3 / 3"
    assert diagnostics["rows"][1]["calculation_label"] == "3 × 0.7 × 0.5 = 1.05 / 3"
    assert diagnostics["rows"][2]["mapping_label"] == "PV clearance (confirmed)"
    assert diagnostics["rows"][2]["calculation_label"] == "Eligibility gate only — no points added"
    assert diagnostics["rows"][0]["match_source_label"] == "Capability Name"
    assert diagnostics["rows"][1]["match_source_label"] == "Related Skill"
    assert diagnostics["rows"][2]["match_source_label"] == "Eligibility"
    assert diagnostics["rows"][3]["mapping_label"] == "Unresolved mapping"
    assert diagnostics["rows"][4]["candidate_level_label"] == "Unresolved"
    assert diagnostics["rows"][5]["profile_support_label"] == "No profile evidence returned"

    lines = fit_scoring.format_requirement_fit_diagnostics_lines(record, profile)

    assert "Requirement: Stakeholder workshops" in lines
    assert "Coverage: In profile" in lines
    assert "Requirement type: Eligibility" in lines
    assert "Mapped to: PV clearance (confirmed)" in lines
    assert "Matched via: Capability Name" in lines
    assert "Matched via: Related Skill" in lines
    assert "Matched term: sql analysis" in lines
    assert "Calculation: Eligibility gate only — no points added" in lines
    assert "Eligibility gate: Pass" in lines
    assert "Mapped to: Unresolved mapping" in lines
    assert "Calculation: 3 × 0.7 × 0.5 = 1.05 / 3 (35%)" in lines
    assert "Profile evidence used: No profile evidence returned" in lines
    assert "Earned weighted credit: 4.05" in lines
    assert "Total requirement weight: 10" in lines
    assert "Calculation: 4.05 ÷ 10 × 100" in lines
    assert "Final Requirement Fit: 40%" in lines


def test_requirement_fit_partially_supported_uses_partial_status_credit():
    record = _record([
        {
            "requirement": "Stakeholder engagement",
            "importance": "mandatory",
            "status": "partially_supported",
            "capability_name": "stakeholder engagement",
            "matched_candidate_fact": "stakeholder engagement",
        }
    ])

    assert fit_scoring.fit_score(record, _profile()) == 50
    label = fit_scoring.fit_score_breakdown(record, _profile())[0]["label"]
    assert "partial 1" in label


def test_requirement_fit_uses_capability_level_not_llm_grade_or_title():
    record = _record([
        {"requirement": "Salesforce configuration", "importance": "mandatory", "status": "supported", "capability_name": "salesforce", "matched_candidate_fact": "salesforce"}
    ], llm_fit_grade="EXCELLENT", title_match_metadata={"match_family": "primary"})

    assert fit_scoring.fit_score(record, _profile()) == 35
    labels = [entry["label"] for entry in fit_scoring.fit_score_breakdown(record, _profile())]
    assert any("Mandatory weak coverage: Salesforce configuration" in label for label in labels)


@pytest.mark.parametrize(
    ("requirement", "candidate_capabilities", "matched_candidate_fact", "profile_support", "status"),
    [
        (
            "5+ years of Salesforce configuration experience required",
            [
                {"name": "Business Analysis", "level": "strong"},
                {"name": "CRM", "level": "strong"},
                {"name": "Stakeholder Management", "level": "strong"},
            ],
            "CRM",
            ["Used CRM to manage customer information."],
            "supported",
        ),
        (
            "Demonstrated SAP S/4HANA implementation experience is required",
            [{"name": "SAP", "level": "basic"}],
            "SAP",
            ["Unrelated historical exposure to generic SAP."],
            "supported",
        ),
        (
            "Experience with BPMN 2.0 required",
            [{"name": "Process Modelling", "level": "strong"}],
            "Process Modelling",
            ["Created process models."],
            "partially_supported",
        ),
    ],
)
def test_required_specific_capability_does_not_credit_adjacent_profile_fact(
    requirement,
    candidate_capabilities,
    matched_candidate_fact,
    profile_support,
    status,
):
    profile = {
        "candidate_capabilities": candidate_capabilities,
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }
    normalized = _normalize_capability_row(
        {
            "requirement": requirement,
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": status,
            "matched_candidate_fact": matched_candidate_fact,
            "matched_job_text": requirement,
            "profile_support": profile_support,
        },
        profile,
    )

    assert normalized["status"] == "not_shown"
    assert normalized["matched_candidate_fact"] == ""
    assert normalized["capability_name"] == ""
    assert fit_scoring.fit_score(_record([normalized]), profile) == 0


def test_exact_capability_match_still_gets_normal_credit():
    profile = {
        "candidate_capabilities": [
            {"name": "Stakeholder Management", "level": "strong"},
        ],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }
    normalized = _normalize_capability_row(
        {
            "requirement": "Strong stakeholder management required",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "supported",
            "matched_candidate_fact": "Stakeholder Management",
            "matched_job_text": "Strong stakeholder management required",
            "profile_support": ["Led stakeholder management across delivery teams."],
        },
        profile,
    )

    assert normalized["status"] == "supported"
    assert normalized["matched_candidate_fact"] == "Stakeholder Management"
    assert fit_scoring.fit_score(_record([normalized]), profile) == 100


def test_exact_capability_with_matching_role_duration_can_be_supported_without_digit_in_profile_support():
    profile = {
        "candidate_capabilities": [
            {"name": "Salesforce", "level": "strong"},
        ],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }
    normalized = _normalize_capability_row(
        {
            "requirement": "5+ years of Salesforce configuration experience required",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "supported",
            "matched_candidate_fact": "Salesforce",
            "matched_job_text": "5+ years of Salesforce configuration experience required",
            "profile_support": ["Configured CRM workflows for internal teams."],
            "experience_components": [
                {"kind": "duration", "text": "5+ years"},
                {
                    "kind": "role_or_activity",
                    "text": "Salesforce configuration",
                    "matched_role_family": "Salesforce Configuration",
                },
            ],
        },
        profile,
        role_experience=[
            {
                "normalized_title": "Salesforce Configuration",
                "total_duration_months": 72,
                "most_recent_end_year": 2025,
                "segments": [{"duration_months": 72, "is_current": False}],
            }
        ],
    )

    assert normalized["status"] == "supported"
    assert normalized["required_experience_months"] == 60
    assert normalized["matched_role_family"] == "Salesforce Configuration"
    assert normalized["matched_role_family_months"] == 72
    assert normalized["experience_requirement_met"] is True
    assert fit_scoring.fit_score(_record([normalized]), profile) == 100


def test_approved_capability_alias_matches_bpmn_but_generic_process_modelling_does_not():
    alias_profile = {
        "candidate_capabilities": [
            {"name": "Process Modelling", "aliases": ["BPMN 2.0"], "level": "strong"},
        ],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }
    aliased = _normalize_capability_row(
        {
            "requirement": "Experience with BPMN 2.0 required",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "supported",
            "matched_candidate_fact": "BPMN 2.0",
            "matched_job_text": "Experience with BPMN 2.0 required",
            "profile_support": ["Designed BPMN 2.0 process models."],
        },
        alias_profile,
    )

    assert aliased["status"] == "supported"
    assert aliased["matched_candidate_fact"] == "Process Modelling"
    assert fit_scoring.fit_score(_record([aliased]), alias_profile) == 100


def test_unknown_required_capability_mapping_is_uncertain_and_zero_credit():
    profile = {
        "candidate_capabilities": [
            {"name": "Business Analysis", "level": "strong"},
            {"name": "CRM", "level": "strong"},
        ],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }
    normalized = _normalize_capability_row(
        {
            "requirement": "5+ years of Salesforce configuration experience required",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "supported",
            "matched_candidate_fact": "Salesforce",
            "matched_job_text": "5+ years of Salesforce configuration experience required",
            "profile_support": ["Business analysis and CRM delivery experience."],
        },
        profile,
    )

    assert normalized["status"] == "not_shown"
    assert fit_scoring.fit_score(_record([normalized]), profile) == 0


def test_required_capability_gap_lowers_fit_without_becoming_eligibility_gate():
    profile = {
        "candidate_capabilities": [
            {"name": "Stakeholder Management", "level": "strong"},
        ],
        "candidate_eligibility": [],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }
    stakeholder = _normalize_capability_row(
        {
            "requirement": "Strong stakeholder management required",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "supported",
            "matched_candidate_fact": "Stakeholder Management",
            "matched_job_text": "Strong stakeholder management required",
            "profile_support": ["Led stakeholder management across delivery teams."],
        },
        profile,
    )
    missing_salesforce = _normalize_capability_row(
        {
            "requirement": "5+ years of Salesforce configuration experience required",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "supported",
            "matched_candidate_fact": "Salesforce",
            "matched_job_text": "5+ years of Salesforce configuration experience required",
            "profile_support": [],
        },
        profile,
    )
    record = _record([stakeholder, missing_salesforce])

    assert fit_scoring.fit_score(record, profile) == 50
    assert fit_scoring.eligibility_gate_diagnostics(record, profile)["status"] == (
        fit_scoring.ELIGIBILITY_GATE_NOT_APPLICABLE
    )


def test_requirement_fit_not_shown_and_mismatch_are_zero_and_counted():
    record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement", "matched_candidate_fact": "stakeholder engagement"},
        {"requirement": "Python engineering", "importance": "mandatory", "status": "not_shown", "capability_name": "", "matched_candidate_fact": ""},
        {"requirement": "NV1 clearance", "importance": "preferred", "status": "mismatch", "capability_name": "", "matched_candidate_fact": ""},
    ])

    assert fit_scoring.fit_score(record, _profile()) == 43
    label = fit_scoring.fit_score_breakdown(record, _profile())[0]["label"]
    assert "not shown 1" in label
    assert "mismatch 1" in label


def test_behavioural_coverage_key_adds_zero_to_numerator_and_denominator():
    """JH-298: fit_scoring reads only requirement_coverage. A populated
    requirement_coverage_behavioural must not move any score component."""
    scored = [
        {
            "requirement": "Stakeholder engagement",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "professional_capability",
            "status": "supported",
            "capability_name": "stakeholder engagement",
            "matched_candidate_fact": "stakeholder engagement",
        }
    ]
    behavioural = [
        {
            "requirement": "Works autonomously",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "behavioural_expectation",
            "behavioural_expectation": True,
            "status": llm_gate.LLM_NOT_ASSESSED_COVERAGE_STATUS,
            "capability_name": "",
            "matched_candidate_fact": "",
        },
        {
            "requirement": "Excellent communication skills",
            "importance": "strongly_preferred",
            "requirement_type": "capability",
            "requirement_kind": "behavioural_expectation",
            "behavioural_expectation": True,
            "status": llm_gate.LLM_NOT_ASSESSED_COVERAGE_STATUS,
            "capability_name": "",
            "matched_candidate_fact": "",
        },
    ]
    baseline = _record(scored)
    with_behavioural = _record(scored, requirement_coverage_behavioural=behavioural)

    base_diag = fit_scoring.requirement_fit_diagnostics(baseline, _profile())
    beh_diag = fit_scoring.requirement_fit_diagnostics(with_behavioural, _profile())

    assert beh_diag["final_requirement_fit"] == base_diag["final_requirement_fit"]
    assert beh_diag["earned_weighted_credit"] == base_diag["earned_weighted_credit"]
    assert beh_diag["total_requirement_weight"] == base_diag["total_requirement_weight"]
    assert fit_scoring.fit_score(with_behavioural, _profile()) == fit_scoring.fit_score(
        baseline, _profile()
    )

    audit = fit_scoring.requirement_fit_audit_rows(with_behavioural, _profile())
    audit_requirements = {row["requirement"] for row in audit}
    assert "Works autonomously" not in audit_requirements
    assert "Excellent communication skills" not in audit_requirements


def test_leaked_non_professional_capability_row_scores_zero_and_seeds_no_uncertainty(
    tmp_path, monkeypatch
):
    """JH-298 correction: scoring credits only requirement_type=capability +
    requirement_kind=professional_capability. A capability row that leaked into
    requirement_coverage with an explicit unclassified / garbled kind adds no
    weight, earns no credit, and logs no mapping uncertainty; a sibling
    professional_capability row still scores normally."""
    uncertainty_log = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(fit_scoring, "UNCERTAINTY_LOG_PATH", uncertainty_log)

    professional_only = _record([
        {
            "requirement": "Stakeholder engagement",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "professional_capability",
            "status": "supported",
            "capability_name": "stakeholder engagement",
            "matched_candidate_fact": "stakeholder engagement",
        }
    ])
    with_leaked = _record([
        {
            "requirement": "Stakeholder engagement",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "professional_capability",
            "status": "supported",
            "capability_name": "stakeholder engagement",
            "matched_candidate_fact": "stakeholder engagement",
        },
        {
            "requirement": "Own the AI platform roadmap",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "unclassified",
            "status": "supported",
            "capability_name": "unknown ai platform capability",
            "matched_job_text": "own the AI platform roadmap",
            "matched_candidate_fact": "unknown ai platform capability",
        },
        {
            "requirement": "Own the data mesh",
            "importance": "mandatory",
            "requirement_type": "capability",
            "requirement_kind": "garbled",
            "status": "supported",
            "capability_name": "unknown data mesh capability",
            "matched_job_text": "own the data mesh",
            "matched_candidate_fact": "unknown data mesh capability",
        },
    ])

    base_diag = fit_scoring.requirement_fit_diagnostics(professional_only, _profile())
    leaked_diag = fit_scoring.requirement_fit_diagnostics(with_leaked, _profile())

    assert base_diag["earned_weighted_credit"] > 0  # the professional row really scores
    assert leaked_diag["total_requirement_weight"] == base_diag["total_requirement_weight"]
    assert leaked_diag["earned_weighted_credit"] == base_diag["earned_weighted_credit"]
    assert fit_scoring.fit_score(with_leaked, _profile()) == fit_scoring.fit_score(
        professional_only, _profile()
    )

    audit_requirements = {
        row["requirement"]
        for row in fit_scoring.requirement_fit_audit_rows(with_leaked, _profile())
    }
    assert audit_requirements == {"Stakeholder engagement"}

    # The leaked rows have unresolved capability names but must not log mapping
    # uncertainty — they are excluded before that check.
    assert not uncertainty_log.exists() or uncertainty_log.read_text(
        encoding="utf-8"
    ).strip() == ""


def test_requirement_fit_unknown_mapped_capability_logs_uncertainty(tmp_path, monkeypatch):
    uncertainty_log = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(fit_scoring, "UNCERTAINTY_LOG_PATH", uncertainty_log)
    record = _record([
        {
            "requirement": "Data platform uplift",
            "importance": "mandatory",
            "status": "supported",
            "capability_name": "unknown data platform capability",
            "matched_job_text": "data platform uplift",
            "matched_candidate_fact": "unknown data platform capability",
        }
    ])

    assert fit_scoring.fit_score(record, _profile()) == 0
    rows = [json.loads(line) for line in uncertainty_log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["reason_code"] == "requirement_capability_mapping_uncertain"
    assert rows[0]["stage"] == "fit_scoring"
    assert rows[0]["job_key"] == "test:job"
    assert "Data platform uplift" in rows[0]["raw_value"]


def test_requirement_fit_eligibility_uses_candidate_eligibility_not_capability():
    record = _record([
        {
            "requirement": "Hold PV security clearance",
            "importance": "mandatory",
            "status": "supported",
            "requirement_type": "eligibility",
            "matched_candidate_fact": "PV clearance",
            "matched_job_text": "Must hold a PV clearance",
        }
    ])
    profile = {
        "candidate_capabilities": [
            {"name": "government environments", "level": "strong"},
        ],
        "candidate_eligibility": [{"name": "PV clearance", "value": True}],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }

    assert fit_scoring.fit_score(record, profile) == 0
    gate = fit_scoring.eligibility_gate_diagnostics(record, profile)
    assert gate["label"] == "Pass"


def test_requirement_fit_false_eligibility_counts_as_mismatch(tmp_path, monkeypatch):
    uncertainty_log = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(fit_scoring, "UNCERTAINTY_LOG_PATH", uncertainty_log)
    record = _record([
        {
            "requirement": "Hold PV security clearance",
            "importance": "mandatory",
            "status": "supported",
            "requirement_type": "eligibility",
            "matched_candidate_fact": "PV clearance",
            "matched_job_text": "Must hold a PV clearance",
        }
    ])
    profile = {
        "candidate_capabilities": [],
        "candidate_eligibility": [{"name": "PV clearance", "value": False}],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }

    assert fit_scoring.fit_score(record, profile) == 0
    gate = fit_scoring.eligibility_gate_diagnostics(record, profile)
    assert gate["label"] == "Fail"
    breakdown = fit_scoring.fit_score_breakdown(record, profile)[0]["label"]
    assert "mismatch 1" in breakdown
    assert "needs review" not in breakdown
    assert not uncertainty_log.exists()


def test_preferred_eligibility_does_not_gate_job():
    record = _record([
        {
            "requirement": "CBAP certification is desirable",
            "canonical_requirement": "CBAP",
            "importance": "preferred",
            "status": "mismatch",
            "requirement_type": "eligibility",
        }
    ])
    profile = {
        "candidate_capabilities": [],
        "candidate_eligibility_facts": [{"name": "CBAP", "value": False}],
    }

    gate = fit_scoring.eligibility_gate_diagnostics(record, profile)
    assert gate["status"] == fit_scoring.ELIGIBILITY_GATE_NOT_APPLICABLE


def test_required_canonical_eligibility_uses_profile_truth_when_llm_says_not_shown():
    record = _record([
        {
            "requirement": "NV2 Security Clearance Required",
            "canonical_requirement": "NV2",
            "importance": "mandatory",
            "status": "not_shown",
            "requirement_type": "eligibility",
        }
    ])
    profile = {
        "candidate_capabilities": [],
        "candidate_eligibility": [{"name": "NV2", "value": False}],
    }

    gate = fit_scoring.eligibility_gate_diagnostics(record, profile)
    assert gate["status"] == fit_scoring.ELIGIBILITY_GATE_FAIL
    assert gate["reason"] == "NV2 Security Clearance Required"


def test_required_canonical_eligibility_passes_when_profile_confirms_it():
    record = _record([
        {
            "requirement": "Australian Citizenship is Required",
            "canonical_requirement": "Australian Citizenship",
            "importance": "mandatory",
            "status": "not_shown",
            "requirement_type": "eligibility",
        }
    ])
    profile = {
        "candidate_capabilities": [],
        "candidate_eligibility_facts": [{"name": "Australian Citizenship", "value": True}],
    }

    gate = fit_scoring.eligibility_gate_diagnostics(record, profile)
    assert gate["status"] == fit_scoring.ELIGIBILITY_GATE_PASS


def test_requirement_fit_invalid_requirement_type_logs_uncertainty(tmp_path, monkeypatch):
    uncertainty_log = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(fit_scoring, "UNCERTAINTY_LOG_PATH", uncertainty_log)
    warnings = []
    monkeypatch.setattr(
        fit_scoring,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    record = _record([
        {
            "requirement": "PV clearance",
            "importance": "mandatory",
            "status": "invalid",
            "requirement_type": "credential",
            "matched_candidate_fact": "",
            "matched_job_text": "Must hold PV clearance",
        }
    ])

    assert fit_scoring.fit_score(record, _profile()) == 0
    rows = [json.loads(line) for line in uncertainty_log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["reason_code"] == "requirement_capability_mapping_uncertain"
    assert rows[0]["stage"] == "fit_scoring"
    assert rows[0]["job_key"] == "test:job"
    assert "not marked as supported" in rows[0]["detail"].lower()
    assert warnings
    assert warnings[0]["category"] == "requirement_coverage_uncertainty"
    assert warnings[0]["job_key"] == "test:job"


def test_requirement_fit_invalid_status_does_not_score_even_with_valid_capability(tmp_path, monkeypatch):
    uncertainty_log = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(fit_scoring, "UNCERTAINTY_LOG_PATH", uncertainty_log)
    warnings = []
    monkeypatch.setattr(
        fit_scoring,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    record = _record([
        {
            "requirement": "SQL experience",
            "importance": "mandatory",
            "status": "invalid",
            "requirement_type": "capability",
            "capability_name": "sql",
            "matched_job_text": "SQL required",
            "matched_candidate_fact": "sql",
        }
    ])

    profile = {
        "candidate_capabilities": [{"name": "sql", "level": "strong"}],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }

    assert fit_scoring.fit_score(record, profile) == 0
    labels = [entry["label"] for entry in fit_scoring.fit_score_breakdown(record, profile)]
    assert any("needs review 1" in label for label in labels)
    assert not any("Requirement Fit: 100%" in label for label in labels)
    rows = [json.loads(line) for line in uncertainty_log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["reason_code"] == "requirement_capability_mapping_uncertain"
    assert "not marked as supported" in rows[0]["detail"].lower()
    assert warnings
    assert warnings[0]["category"] == "requirement_coverage_uncertainty"


def test_requirement_fit_uncertain_classification_does_not_score(tmp_path, monkeypatch):
    uncertainty_log = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(fit_scoring, "UNCERTAINTY_LOG_PATH", uncertainty_log)
    warnings = []
    monkeypatch.setattr(
        fit_scoring,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    record = _record([
        {
            "requirement": "5+ years working in a security clearance environment",
            "importance": "mandatory",
            "status": "invalid",
            "requirement_type": "uncertain",
            "matched_candidate_fact": "",
            "llm_proposed_requirement_type": "capability",
        }
    ])

    assert fit_scoring.fit_score(record, _profile()) == 0
    rows = [json.loads(line) for line in uncertainty_log.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["reason_code"] == "requirement_capability_mapping_uncertain"
    assert "not marked as supported" in rows[0]["detail"].lower()
    assert warnings
    assert warnings[0]["category"] == "requirement_coverage_uncertainty"


def _fully_supported_record(**extra):
    return _record(
        [
            {
                "requirement": "Stakeholder engagement",
                "importance": "mandatory",
                "status": "supported",
                "capability_name": "stakeholder engagement",
                "matched_candidate_fact": "stakeholder engagement",
            }
        ],
        **extra,
    )


def test_occupation_alignment_same_applies_zero_adjustment():
    record = _fully_supported_record(
        occupation_alignment="same", occupation_alignment_reason="Same job family and duties"
    )

    assert fit_scoring.fit_score(record, _profile()) == 100
    breakdown = fit_scoring.fit_score_breakdown(record, _profile())
    entry = next(item for item in breakdown if item["section"] == "occupation_alignment")
    assert entry["value"] == 0
    assert "Same" in entry["label"]


def test_occupation_alignment_adjacent_applies_minus_ten():
    record = _fully_supported_record(
        occupation_alignment="adjacent", occupation_alignment_reason="Related but distinct duties"
    )

    assert fit_scoring.fit_score(record, _profile()) == 90
    breakdown = fit_scoring.fit_score_breakdown(record, _profile())
    entry = next(item for item in breakdown if item["section"] == "occupation_alignment")
    assert entry["value"] == -10
    assert "Adjacent" in entry["label"]


def test_occupation_alignment_different_applies_minus_twenty():
    record = _fully_supported_record(
        occupation_alignment="different", occupation_alignment_reason="Unrelated occupation"
    )

    assert fit_scoring.fit_score(record, _profile()) == 80
    breakdown = fit_scoring.fit_score_breakdown(record, _profile())
    entry = next(item for item in breakdown if item["section"] == "occupation_alignment")
    assert entry["value"] == -20
    assert "Different" in entry["label"]


def test_occupation_alignment_different_clamps_to_zero_not_negative():
    record = _record(
        [
            {
                "requirement": "SQL experience",
                "importance": "mandatory",
                "status": "mismatch",
                "capability_name": "",
                "matched_candidate_fact": "",
            }
        ],
        occupation_alignment="different",
    )

    assert fit_scoring.fit_score(record, _profile()) == 0


def test_occupation_alignment_missing_value_degrades_to_needs_review_zero_adjustment():
    record = _fully_supported_record()

    assert fit_scoring.fit_score(record, _profile()) == 100
    breakdown = fit_scoring.fit_score_breakdown(record, _profile())
    entry = next(item for item in breakdown if item["section"] == "occupation_alignment")
    assert entry["value"] == 0
    assert "needs review" in entry["label"].lower()


def test_occupation_alignment_invalid_value_never_rejects_and_degrades_to_zero():
    record = _fully_supported_record(occupation_alignment="not-a-real-alignment")

    assert fit_scoring.fit_score(record, _profile()) == 100
    breakdown = fit_scoring.fit_score_breakdown(record, _profile())
    entry = next(item for item in breakdown if item["section"] == "occupation_alignment")
    assert entry["value"] == 0
    assert "needs review" in entry["label"].lower()


def test_occupation_alignment_diagnostics_reports_alignment_reason_adjustment_and_calculation():
    record = _fully_supported_record(
        occupation_alignment="adjacent", occupation_alignment_reason="Related discipline"
    )
    profile = _profile()
    scoring_rules = fit_scoring.get_scoring_rules(profile)

    diagnostics = fit_scoring.occupation_alignment_diagnostics(record, scoring_rules)
    assert diagnostics["alignment"] == "adjacent"
    assert diagnostics["reason"] == "Related discipline"
    assert diagnostics["adjustment"] == -10
    assert diagnostics["is_classified"] is True

    final_score = fit_scoring.fit_score(record, profile)
    block = fit_scoring.format_occupation_alignment_diagnostics_block(record, final_score, profile)
    assert "Alignment: Adjacent" in block
    assert "Reason: Related discipline" in block
    assert "Adjustment: -10" in block
    assert f"= {final_score}" in block


def test_role_defining_specialist_gap_caps_generic_high_score():
    profile = _profile()
    profile["scoring_rules"] = {
        "fit_breakdown": {"hard_block_penalty": -100},
        "role_defining_gap_control": {
            "min_group_requirements": 2,
            "uncovered_ratio_threshold": 0.5,
            "max_score_when_uncovered": 54,
        },
    }
    record = _record([
        {
            "requirement": "Stakeholder engagement",
            "importance": "mandatory",
            "requirement_type": "capability",
            "status": "supported",
            "matched_candidate_fact": "stakeholder engagement",
        },
        {
            "requirement": "ICU clinical experience",
            "importance": "preferred",
            "requirement_type": "capability",
            "status": "not_shown",
            "role_defining": True,
            "role_defining_group": "critical care",
        },
        {
            "requirement": "Critical-care patient management",
            "importance": "preferred",
            "requirement_type": "capability",
            "status": "not_shown",
            "role_defining": True,
            "role_defining_group": "critical care",
        },
    ])

    diagnostics = fit_scoring.requirement_fit_diagnostics(record, profile)

    assert diagnostics["final_requirement_fit"] == 54
    assert diagnostics["role_defining_caps"] == [{
        "group": "critical care",
        "requirements": 2,
        "uncovered": 2,
        "uncovered_ratio": 1.0,
        "score_cap": 54,
    }]

    # The protection must govern the real score, not diagnostics only.
    assert fit_scoring.fit_score(record, profile) == 54
    breakdown = fit_scoring.fit_score_breakdown(record, profile)
    assert breakdown[0]["value"] == 54
    assert any(
        entry.get("section") == "requirement_fit_warning"
        and "Role-defining gap cap: critical care" in str(entry.get("label") or "")
        for entry in breakdown
    )
