import json

from job_hunter_agent import fit_scoring


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


def test_requirement_fit_all_supported_strong_is_100():
    record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement"}
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
            "profile_name": "stakeholder engagement",
            "capability_name": "stakeholder engagement",
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
            "profile_name": "stakeholder engagement",
            "candidate_level": "strong",
            "matched_job_text": "5–7 years' experience in digital health",
            "profile_support": ["Facilitated stakeholders on a health infrastructure program."],
            "requirement_weight": 3.0,
            "credit_fraction": 0.5,
            "weighted_credit": 1.5,
        }
    ]


def test_requirement_fit_partially_supported_uses_partial_status_credit():
    record = _record([
        {
            "requirement": "Stakeholder engagement",
            "importance": "mandatory",
            "status": "partially_supported",
            "capability_name": "stakeholder engagement",
        }
    ])

    assert fit_scoring.fit_score(record, _profile()) == 50
    label = fit_scoring.fit_score_breakdown(record, _profile())[0]["label"]
    assert "partial 1" in label


def test_requirement_fit_uses_capability_level_not_llm_grade_or_title():
    record = _record([
        {"requirement": "Salesforce configuration", "importance": "mandatory", "status": "supported", "capability_name": "salesforce"}
    ], llm_fit_grade="EXCELLENT", title_match_metadata={"match_family": "primary"})

    assert fit_scoring.fit_score(record, _profile()) == 35
    labels = [entry["label"] for entry in fit_scoring.fit_score_breakdown(record, _profile())]
    assert any("Mandatory weak coverage: Salesforce configuration" in label for label in labels)


def test_requirement_fit_not_shown_and_mismatch_are_zero_and_counted():
    record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement"},
        {"requirement": "Python engineering", "importance": "mandatory", "status": "not_shown", "capability_name": ""},
        {"requirement": "NV1 clearance", "importance": "preferred", "status": "mismatch", "capability_name": ""},
    ])

    assert fit_scoring.fit_score(record, _profile()) == 43
    label = fit_scoring.fit_score_breakdown(record, _profile())[0]["label"]
    assert "not shown 1" in label
    assert "mismatch 1" in label


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
            "profile_name": "PV clearance",
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

    assert fit_scoring.fit_score(record, profile) == 100


def test_requirement_fit_false_eligibility_counts_as_mismatch(tmp_path, monkeypatch):
    uncertainty_log = tmp_path / "uncertainty.jsonl"
    monkeypatch.setattr(fit_scoring, "UNCERTAINTY_LOG_PATH", uncertainty_log)
    record = _record([
        {
            "requirement": "Hold PV security clearance",
            "importance": "mandatory",
            "status": "supported",
            "requirement_type": "eligibility",
            "profile_name": "PV clearance",
            "matched_job_text": "Must hold a PV clearance",
        }
    ])
    profile = {
        "candidate_capabilities": [],
        "candidate_eligibility": [{"name": "PV clearance", "value": False}],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }

    assert fit_scoring.fit_score(record, profile) == 0
    breakdown = fit_scoring.fit_score_breakdown(record, profile)[0]["label"]
    assert "mismatch 1" in breakdown
    assert "needs review" not in breakdown
    assert not uncertainty_log.exists()


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
            "profile_name": "",
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
