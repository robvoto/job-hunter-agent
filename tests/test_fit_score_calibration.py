"""Calibration tests for Requirement Fit % scoring."""

import pytest

from job_hunter_agent import fit_scoring
from job_hunter_agent.record_schema import APPLY_METHOD_EASY_APPLY, APPLY_METHOD_QUICK_APPLY, RECORD_APPLY_METHOD_KEY


def _profile(extra=None):
    base = {
        "candidate_capabilities": [
            {"name": "stakeholder engagement", "level": "strong"},
            {"name": "sql", "level": "working"},
            {"name": "salesforce", "level": "basic"},
            {"name": "legacy coding", "level": "low"},
        ],
        "must_not_require_skills": [],
        "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}},
    }
    if extra:
        base.update(extra)
    return base


def _record(coverage, **extra):
    record = {
        "job_key": "test:job",
        "title": "Business Analyst",
        "title_reason": "OK",
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        "requirement_coverage": coverage,
    }
    record.update(extra)
    return record


def _score(record, profile=None):
    return fit_scoring.fit_score(record, profile or _profile())


def test_all_supported_strong_requirements_score_100():
    record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement"},
        {"requirement": "Stakeholder workshops", "importance": "preferred", "status": "supported", "capability_name": "stakeholder engagement"},
    ])
    assert _score(record) == 100


@pytest.mark.parametrize("overrides", [
    {"title_match_metadata": {"match_family": "primary"}},
    {"llm_fit_grade": "EXCELLENT"},
    {RECORD_APPLY_METHOD_KEY: APPLY_METHOD_EASY_APPLY},
    {RECORD_APPLY_METHOD_KEY: APPLY_METHOD_QUICK_APPLY},
    {"location": "Canberra ACT"},
    {"salary": "$250k"},
    {"posted_age_days": 0.1},
    {"posted_age_days": 14},
    {"times_viewed": 4},
])
def test_non_requirement_noise_signals_do_not_change_fit_score(overrides):
    base_record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement"},
        {"requirement": "SQL analysis", "importance": "preferred", "status": "supported", "capability_name": "sql"},
    ])
    assert _score({**base_record, **overrides}) == _score(base_record)


def test_capability_level_controls_requirement_fit_percentage():
    record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement"},
        {"requirement": "SQL analysis", "importance": "mandatory", "status": "supported", "capability_name": "sql"},
        {"requirement": "Salesforce configuration", "importance": "mandatory", "status": "supported", "capability_name": "salesforce"},
        {"requirement": "Legacy coding", "importance": "mandatory", "status": "supported", "capability_name": "legacy coding"},
    ])
    assert _score(record) == 55


def test_not_shown_and_mismatch_contribute_zero():
    record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement"},
        {"requirement": "Python engineering", "importance": "mandatory", "status": "not_shown", "capability_name": ""},
        {"requirement": "NV1 clearance", "importance": "preferred", "status": "mismatch", "capability_name": ""},
    ])
    assert _score(record) == 43
    label = fit_scoring.fit_score_breakdown(record, _profile())[0]["label"]
    assert "not shown 1" in label
    assert "mismatch 1" in label


def test_required_basic_or_low_coverage_is_flagged_not_hidden():
    record = _record([
        {"requirement": "Salesforce configuration", "importance": "mandatory", "status": "supported", "capability_name": "salesforce"}
    ])
    breakdown = fit_scoring.fit_score_breakdown(record, _profile())
    assert _score(record) == 35
    assert any(entry["label"] == "Mandatory weak coverage: Salesforce configuration" for entry in breakdown)


def test_hard_blocker_overrides_requirement_fit_to_zero():
    record = _record(
        [{"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement"}],
        hard_block_reasons=["requires NV1 security clearance"],
        must_not_require_skills=["NV1 security clearance"],
        full_description="requires NV1 security clearance",
    )
    profile = _profile({"must_not_require_skills": ["NV1 security clearance"]})
    assert _score(record, profile) == 0
    assert any("Hard blocker" in entry["label"] for entry in fit_scoring.fit_score_breakdown(record, profile))


def test_breakdown_does_not_include_grade_band_entries():
    record = _record([
        {"requirement": "Stakeholder engagement", "importance": "mandatory", "status": "supported", "capability_name": "stakeholder engagement"}
    ], llm_fit_grade="MISMATCH")
    labels = [entry["label"] for entry in fit_scoring.fit_score_breakdown(record, _profile())]
    assert not any("Grade band" in label for label in labels)
