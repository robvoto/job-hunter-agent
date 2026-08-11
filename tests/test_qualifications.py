from job_hunter_agent import fit_scoring, llm_gate
from job_hunter_agent.profile_gaps import compute_profile_gaps
from job_hunter_agent.profile_store import normalize_full_profile
from job_hunter_agent.qualification_profile import normalize_qualifications


def _record(item):
    return {
        "job_key": "qualification-job",
        "source": "test",
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        "requirement_coverage": [item],
    }


def _profile(qualifications):
    return {
        "candidate_capabilities": [],
        "candidate_qualifications": qualifications,
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }


def test_qualification_profile_discards_raw_requirement_sentences_as_names():
    normalized = normalize_qualifications(
        [
            {
                "name": "CBAP, Agile BA, or equivalent certifications",
                "value": True,
                "evidence": ["CBAP certification held"],
            },
            {"name": "CBAP", "value": True, "evidence": ["CBAP certification held"]},
        ]
    )

    assert [item["name"] for item in normalized] == ["CBAP"]
    assert normalize_full_profile({"candidate_qualifications": normalized})[
        "candidate_qualifications"
    ][0]["name"] == "CBAP"


def test_mandatory_qualification_false_fails_the_gate():
    record = _record(
        {
            "requirement": "CBAP certification",
            "canonical_requirement": "CBAP",
            "importance": "mandatory",
            "requirement_type": "qualification",
            "status": "mismatch",
            "matched_candidate_fact": "CBAP",
            "qualification_name": "CBAP",
        }
    )

    gate = fit_scoring.eligibility_gate_diagnostics(
        record, _profile([{"name": "CBAP", "value": False}])
    )
    assert gate["status"] == fit_scoring.ELIGIBILITY_GATE_FAIL
    assert llm_gate.has_eligibility_mismatch(record["requirement_coverage"])


def test_preferred_qualification_false_does_not_fail_the_gate():
    record = _record(
        {
            "requirement": "CBAP certification is desirable",
            "canonical_requirement": "CBAP",
            "importance": "preferred",
            "requirement_type": "qualification",
            "status": "mismatch",
            "matched_candidate_fact": "CBAP",
            "qualification_name": "CBAP",
        }
    )

    gate = fit_scoring.eligibility_gate_diagnostics(
        record, _profile([{"name": "CBAP", "value": False}])
    )
    assert gate["status"] == fit_scoring.ELIGIBILITY_GATE_NOT_APPLICABLE
    assert not llm_gate.has_eligibility_mismatch(record["requirement_coverage"])


def test_matching_qualification_passes_and_maps_to_canonical_profile_name():
    coverage = llm_gate.normalize_llm_requirement_coverage(
        [
            {
                "requirement": "Demonstrated CBAP certification",
                "canonical_requirement": "CBAP",
                "importance": "mandatory",
                "requirement_type": "qualification",
                "status": "supported",
                "matched_candidate_fact": "CBAP",
                "matched_job_text": "CBAP certification required",
                "profile_support": ["CBAP certification, 2021"],
            }
        ],
        valid_qualification_names={"cbap": "CBAP"},
    )
    record = _record(coverage[0])

    assert coverage[0]["requirement"] == "Demonstrated CBAP certification"
    assert coverage[0]["qualification_name"] == "CBAP"
    assert coverage[0]["matched_candidate_fact"] == "CBAP"
    assert fit_scoring.eligibility_gate_diagnostics(
        record, _profile([{"name": "CBAP", "value": True}])
    )["status"] == fit_scoring.ELIGIBILITY_GATE_PASS


def test_compound_qualification_mapping_stays_unresolved_without_atomic_profile_match():
    coverage = llm_gate.normalize_llm_requirement_coverage(
        [
            {
                "requirement": "CBAP, Agile BA, or equivalent certifications",
                "canonical_requirement": "CBAP, Agile BA, or equivalent certifications",
                "importance": "mandatory",
                "requirement_type": "qualification",
                "status": "supported",
                "matched_candidate_fact": "CBAP, Agile BA, or equivalent certifications",
            }
        ],
        valid_qualification_names={"cbap": "CBAP"},
    )

    assert coverage[0]["status"] == "not_shown"
    assert coverage[0]["matched_candidate_fact"] == ""
    assert coverage[0]["canonical_requirement"] == ""


def test_qualification_gap_keeps_qualification_type_and_canonical_concept():
    gaps = compute_profile_gaps(
        [
            {
                "requirement": "CBAP certification",
                "requirement_type": "qualification",
                "qualification_name": "CBAP",
                "matched_candidate_fact": "CBAP",
                "status": "not_shown",
            }
        ],
        [],
        [],
        candidate_qualifications=[],
    )

    assert gaps[0]["requirement_type"] == "qualification"
    assert gaps[0]["qualification_name"] == "CBAP"
