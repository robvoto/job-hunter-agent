"""Tests for review insights."""

from job_hunter_agent.global_settings import (
    KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT,
    KEY_REVIEW_MAX_EXAMPLES_PER_SKILL,
    KEY_REVIEW_MAX_SAMPLES_PER_REJECTION,
    KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT,
)
from job_hunter_agent.profile_store import (
    KEY_ALIASES,
    KEY_CANDIDATE_CAPABILITIES,
    KEY_LEVEL,
    KEY_MUST_NOT_REQUIRED_SKILLS,
    KEY_NAME,
)
from job_hunter_agent.review_insights import apply_capability_tuning_decisions, build_review_data


def test_build_review_data_uses_kept_audit_rows_for_capability_suggestions(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 3,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 2,
        },
    )

    result = build_review_data(
        audit_rows=[
            {
                "decision": "KEEP",
                "url": "https://example.test/job-1",
                "title": "Business Analyst",
                "company": "Example Co",
                "search_location": "Sydney",
                "reviewed_signal_matches": {
                    "matched": ["Process mapping"],
                    "evidence_only": ["Stakeholder engagement"],
                    "ignored": ["Ignore me"],
                    "unresolved": ["Still unknown"],
                },
                "competitive_signals": [
                    {
                        "fit_label": "Process mapping",
                        "adjustment": 2,
                        "alignment": "strong",
                    },
                    {
                        "fit_label": "Stakeholder engagement",
                        "adjustment": 1,
                        "alignment": "strong",
                    },
                    {
                        "fit_label": "Do not keep me",
                        "adjustment": -1,
                        "alignment": "weak",
                    },
                ],
                "fit_highlights": [
                    "Strong capability match: Process mapping",
                    "Capability match: Stakeholder engagement",
                    "Work mode: Remote",
                ],
                "role_snapshot": "Strong capability match: Process mapping",
                "reject_reason": "",
            }
        ],
        skill_observations=[
            {
                "skill": "Ignored skill from source observations",
                "title": "Wrong role",
                "company": "Wrong Co",
                "url": "https://example.test/rejected",
                "search_location": "Sydney",
            }
        ],
        profile={KEY_CANDIDATE_CAPABILITIES: []},
    )

    assert result["kept_job_urls"] == ["https://example.test/job-1"]
    assert [item["skill"] for item in result["skill_observations"]] == [
        "Process mapping",
        "Stakeholder engagement",
    ]
    assert result["suggested_tuning"]["summary"] == {
        "capability_count": 2,
        "requirement_count": 0,
        "optimization_count": 0,
        "rule_count": 0,
    }
    capability_skills = [
        item["skill"] for item in result["suggested_tuning"]["capability_suggestions"]
    ]
    assert capability_skills == ["Process mapping", "Stakeholder engagement"]
    assert (
        result["suggested_tuning"]["capability_suggestions"][0]["examples"][0]["url"]
        == "https://example.test/job-1"
    )


def test_build_review_data_ignores_rejected_job_capabilities(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 3,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 2,
        },
    )
    result = build_review_data(
        audit_rows=[
            {
                "decision": "REJECT",
                "reject_reason": "LLM_REJECT",
                "url": "https://example.test/job-1",
                "title": "Business Analyst",
                "company": "Example Co",
                "search_location": "Sydney",
                "competitive_signals": [
                    {
                        "fit_label": "Process mapping",
                        "adjustment": 2,
                        "alignment": "strong",
                    }
                ],
            }
        ],
        skill_observations=[],
        profile={KEY_CANDIDATE_CAPABILITIES: []},
    )

    assert result["skill_observations"] == []
    assert result["suggested_tuning"]["capability_suggestions"] == []
    assert result["suggested_tuning"]["summary"]["capability_count"] == 0


def test_build_review_data_exposes_title_tuning_rules(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 1,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 1,
        },
    )

    result = build_review_data(
        audit_rows=[
            {
                "decision": "REJECT",
                "reject_reason": "ONET_FAR_OCCUPATION",
                "title_reason": "TITLE_NOT_TARGET",
                "onet_classification": {
                    "result": "far",
                    "matched_occupation_code": "1234",
                    "confidence": 0.9,
                    "reason": "match",
                },
                "url": "https://example.test/job-1",
                "title": "Unrelated Role",
                "company": "Example Co",
                "search_location": "Sydney",
            },
            {
                "decision": "REJECT",
                "reject_reason": "TITLE_BAD_KEYWORD: contractor",
                "url": "https://example.test/job-2",
                "title": "Contractor Role",
                "company": "Example Co",
                "search_location": "Sydney",
            },
        ],
        skill_observations=[],
        profile={KEY_CANDIDATE_CAPABILITIES: []},
    )

    assert result["suggested_tuning"]["summary"]["rule_count"] == 2
    assert {item["reason"] for item in result["suggested_tuning"]["rule_suggestions"]} == {
        "ONET_FAR_OCCUPATION",
        "TITLE_BAD_KEYWORD: contractor",
    }


def test_build_review_data_exposes_uncertain_title_optimisation_suggestions(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 2,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 1,
        },
    )

    result = build_review_data(
        audit_rows=[
            {
                "decision": "REJECT",
                "reject_reason": "LLM_REJECT",
                "title_reason": "TITLE_REASON_POTENTIAL_MATCH",
                "onet_classification": {
                    "result": "uncertain",
                    "matched_occupation_code": None,
                    "confidence": 0.4,
                    "reason": "no_match",
                },
                "url": "https://example.test/job-1",
                "title": "AI Core Platform Engineer AWS",
                "company": "Example Co",
                "search_location": "Sydney",
            },
            {
                "decision": "REJECT",
                "reject_reason": "LLM_REJECT",
                "title_reason": "TITLE_REASON_POTENTIAL_MATCH",
                "onet_classification": {
                    "result": "uncertain",
                    "matched_occupation_code": None,
                    "confidence": 0.4,
                    "reason": "no_match",
                },
                "url": "https://example.test/job-2",
                "title": "AI Core Platform Engineer AWS",
                "company": "Another Co",
                "search_location": "Sydney",
            },
        ],
        skill_observations=[],
        profile={KEY_CANDIDATE_CAPABILITIES: []},
    )

    optimisation = result["suggested_tuning"]["optimization_suggestions"]
    assert result["suggested_tuning"]["summary"]["optimization_count"] == 1
    assert result["suggested_tuning"]["summary"]["rule_count"] == 0
    assert len(optimisation) == 1
    assert optimisation[0]["reason"] == "ONET_UNCERTAIN_TITLE"
    assert optimisation[0]["headline"] == "Repeated uncertain title: AI Core Platform Engineer AWS"
    assert optimisation[0]["samples"][0]["url"] == "https://example.test/job-1"


def test_build_review_data_keeps_clear_title_hard_block_suggestions_when_bucket_is_mixed(
    monkeypatch,
):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 1,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 1,
        },
    )

    result = build_review_data(
        audit_rows=[
            {
                "decision": "REJECT",
                "reject_reason": "LLM_REJECT",
                "title_reason": "TITLE_REASON_POTENTIAL_MATCH",
                "onet_classification": {
                    "result": "uncertain",
                    "matched_occupation_code": None,
                    "confidence": 0.4,
                    "reason": "no_match",
                },
                "url": "https://example.test/job-1",
                "title": "AI Core Platform Engineer AWS",
                "company": "Example Co",
                "search_location": "Sydney",
            },
            {
                "decision": "REJECT",
                "reject_reason": "ONET_FAR_OCCUPATION",
                "title_reason": "TITLE_NOT_TARGET",
                "onet_classification": {
                    "result": "far",
                    "matched_occupation_code": "2345",
                    "confidence": 0.9,
                    "reason": "match",
                },
                "url": "https://example.test/job-2",
                "title": "Chef",
                "company": "Another Co",
                "search_location": "Sydney",
            },
        ],
        skill_observations=[],
        profile={KEY_CANDIDATE_CAPABILITIES: []},
    )

    optimisation = result["suggested_tuning"]["optimization_suggestions"]
    rules = result["suggested_tuning"]["rule_suggestions"]
    assert result["suggested_tuning"]["summary"]["optimization_count"] == 1
    assert result["suggested_tuning"]["summary"]["rule_count"] == 1
    assert optimisation[0]["headline"] == "Repeated uncertain title: AI Core Platform Engineer AWS"
    assert rules[0]["reason"] == "ONET_FAR_OCCUPATION"
    assert rules[0]["count"] == 1


def test_build_review_data_turns_repeated_requirement_coverage_into_capability_tuning(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 3,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 2,
        },
    )

    result = build_review_data(
        audit_rows=[
            {
                "decision": "KEEP",
                "url": "https://example.test/job-1",
                "title": "Operations Lead",
                "company": "Example Co",
                "search_location": "Sydney",
                "requirement_coverage": [
                    {"requirement": "Native or near-native level Chinese language proficiency required", "requirement_type": "capability"},
                    {"requirement": "Minimum 1-2 years of project coordination experience required", "requirement_type": "capability"},
                ],
            },
            {
                "decision": "KEEP",
                "url": "https://example.test/job-2",
                "title": "Program Coordinator",
                "company": "Example Co",
                "search_location": "Sydney",
                "requirement_coverage": [
                    {"requirement": "Chinese language proficiency required", "requirement_type": "capability"},
                ],
            },
        ],
        skill_observations=[],
        profile={KEY_CANDIDATE_CAPABILITIES: []},
    )

    requirement_suggestions = result["suggested_tuning"]["requirement_suggestions"]
    assert result["suggested_tuning"]["summary"]["requirement_count"] == 2
    chinese = next(
        item for item in requirement_suggestions if item["skill"] == "Chinese language proficiency"
    )
    assert chinese["count"] == 2
    assert chinese["recommended_choice"] == "basic"
    assert chinese["aliases"] == [
        "Native or near-native level Chinese language proficiency required",
        "Chinese language proficiency required",
    ]
    assert (
        chinese["prompt"]
        == "Chinese language proficiency is required in several kept roles. Do you have this capability?"
    )


def test_apply_capability_tuning_decisions_adds_confirmed_capability():
    profile = {KEY_CANDIDATE_CAPABILITIES: []}

    updated = apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working", KEY_ALIASES: ["process modelling"]}],
    )

    assert updated[KEY_CANDIDATE_CAPABILITIES] == [
        {
            KEY_NAME: "Process mapping",
            KEY_LEVEL: "working",
            KEY_ALIASES: ["process modelling"],
            "icon_key": "generic_capability",
        }
    ]


def test_apply_capability_tuning_decisions_preserves_existing_icon_key():
    profile = {
        KEY_CANDIDATE_CAPABILITIES: [
            {
                KEY_NAME: "Process mapping",
                KEY_LEVEL: "basic",
                KEY_ALIASES: [],
                "icon_key": "operations_process",
            }
        ]
    }

    updated = apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working", KEY_ALIASES: ["workflow design"]}],
    )

    assert updated[KEY_CANDIDATE_CAPABILITIES] == [
        {
            KEY_NAME: "Process mapping",
            KEY_LEVEL: "working",
            KEY_ALIASES: ["workflow design"],
            "icon_key": "operations_process",
        }
    ]


def test_apply_capability_tuning_decisions_can_ignore_capability_suggestion():
    profile = {KEY_CANDIDATE_CAPABILITIES: [], "review_controls": {"applied_job_keys": []}}

    updated = apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "dismiss"}],
    )

    assert updated[KEY_CANDIDATE_CAPABILITIES] == []
    assert updated["review_controls"]["ignored_capability_suggestions"] == ["Process mapping"]


def test_build_review_data_skips_ignored_capability_suggestions(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 3,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 2,
        },
    )

    result = build_review_data(
        audit_rows=[
            {
                "decision": "KEEP",
                "url": "https://example.test/job-1",
                "title": "Business Analyst",
                "company": "Example Co",
                "search_location": "Sydney",
            }
        ],
        skill_observations=[
            {
                "skill": "Process mapping",
                "url": "https://example.test/job-1",
                "title": "Business Analyst",
                "company": "Example Co",
                "search_location": "Sydney",
            }
        ],
        profile={
            KEY_CANDIDATE_CAPABILITIES: [],
            "review_controls": {
                "ignored_capability_suggestions": ["Process mapping"],
            },
        },
    )

    assert result["suggested_tuning"]["capability_suggestions"] == []
    assert result["suggested_tuning"]["summary"]["capability_count"] == 0


def test_build_review_data_does_not_fall_back_to_raw_signal_label(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 2,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 1,
        },
    )

    result = build_review_data(
        audit_rows=[
            {
                "decision": "KEEP",
                "url": "https://example.test/job-1",
                "title": "Business Analyst",
                "company": "Example Co",
                "search_location": "Sydney",
                "competitive_signals": [
                    {
                        "label": "Internal taxonomy label",
                        "fit_label": "",
                        "adjustment": 2,
                        "alignment": "strong",
                    }
                ],
            }
        ],
        skill_observations=[],
        profile={KEY_CANDIDATE_CAPABILITIES: []},
    )

    assert result["skill_observations"] == []


def test_apply_capability_tuning_decisions_records_factual_absence_separately_from_dismiss():
    factual = apply_capability_tuning_decisions(
        {KEY_CANDIDATE_CAPABILITIES: [], KEY_MUST_NOT_REQUIRED_SKILLS: []},
        [{"skill": "Power BI", "choice": "do_not_have"}],
    )

    assert factual[KEY_MUST_NOT_REQUIRED_SKILLS] == ["Power BI"]
    assert factual["review_controls"]["ignored_capability_suggestions"] == []

    dismissed = apply_capability_tuning_decisions(
        {KEY_CANDIDATE_CAPABILITIES: [], KEY_MUST_NOT_REQUIRED_SKILLS: []},
        [{"skill": "Power BI", "choice": "dismiss"}],
    )
    assert dismissed[KEY_MUST_NOT_REQUIRED_SKILLS] == []
    assert dismissed["review_controls"]["ignored_capability_suggestions"] == ["Power BI"]


def test_apply_capability_tuning_decisions_positive_choice_reverses_exact_absence():
    updated = apply_capability_tuning_decisions(
        {
            KEY_CANDIDATE_CAPABILITIES: [],
            KEY_MUST_NOT_REQUIRED_SKILLS: ["Power BI", "SAP"],
        },
        [{"skill": "Power BI", "choice": "working"}],
    )

    assert [item[KEY_NAME] for item in updated[KEY_CANDIDATE_CAPABILITIES]] == ["Power BI"]
    assert updated[KEY_MUST_NOT_REQUIRED_SKILLS] == ["SAP"]


def test_build_review_data_skips_explicitly_absent_capability_suggestions(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 1,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 3,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 2,
        },
    )
    result = build_review_data(
        audit_rows=[
            {
                "decision": "KEEP",
                "url": "https://example.test/job-1",
                "title": "Business Analyst",
                "company": "Example Co",
            }
        ],
        skill_observations=[
            {
                "skill": "Power BI",
                "url": "https://example.test/job-1",
                "title": "Business Analyst",
            }
        ],
        profile={
            KEY_CANDIDATE_CAPABILITIES: [],
            KEY_MUST_NOT_REQUIRED_SKILLS: ["Power BI"],
        },
    )

    assert result["suggested_tuning"]["capability_suggestions"] == []
