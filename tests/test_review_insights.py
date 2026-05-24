from job_hunter_agent.global_settings import (
    KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT,
    KEY_REVIEW_MAX_EXAMPLES_PER_SKILL,
    KEY_REVIEW_MAX_SAMPLES_PER_REJECTION,
    KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT,
)
from job_hunter_agent.review_insights import apply_capability_tuning_decisions, build_review_data
from job_hunter_agent.profile_store import (
    KEY_ALIASES,
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_LEVEL,
    KEY_NAME,
)


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
                    }
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
        profile={KEY_CAPABILITY_PROFILE_RULES: []},
    )

    assert result["kept_job_urls"] == ["https://example.test/job-1"]
    assert [item["skill"] for item in result["skill_observations"]] == ["Process mapping", "Stakeholder engagement"]
    assert result["suggested_tuning"]["summary"] == {"capability_count": 2, "requirement_count": 0, "rule_count": 0}
    capability_skills = [item["skill"] for item in result["suggested_tuning"]["capability_suggestions"]]
    assert capability_skills == ["Process mapping", "Stakeholder engagement"]
    assert result["suggested_tuning"]["capability_suggestions"][0]["examples"][0]["url"] == "https://example.test/job-1"


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
        profile={KEY_CAPABILITY_PROFILE_RULES: []},
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
                "reject_reason": "TITLE_NOT_TARGET",
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
        profile={KEY_CAPABILITY_PROFILE_RULES: []},
    )

    assert result["suggested_tuning"]["summary"]["rule_count"] == 2
    assert {item["reason"] for item in result["suggested_tuning"]["rule_suggestions"]} == {
        "TITLE_NOT_TARGET",
        "TITLE_BAD_KEYWORD: contractor",
    }


def test_build_review_data_turns_repeated_job_requirements_into_capability_tuning(monkeypatch):
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
                "job_requirements": [
                    "Native or near-native level Chinese language proficiency required",
                    "Minimum 1-2 years of project coordination experience required",
                ],
            },
            {
                "decision": "KEEP",
                "url": "https://example.test/job-2",
                "title": "Program Coordinator",
                "company": "Example Co",
                "search_location": "Sydney",
                "job_requirements": [
                    "Chinese language proficiency required",
                ],
            },
        ],
        skill_observations=[],
        profile={KEY_CAPABILITY_PROFILE_RULES: []},
    )

    requirement_suggestions = result["suggested_tuning"]["requirement_suggestions"]
    assert result["suggested_tuning"]["summary"]["requirement_count"] == 2
    chinese = next(item for item in requirement_suggestions if item["skill"] == "Chinese language proficiency")
    assert chinese["count"] == 2
    assert chinese["recommended_choice"] == "basic"
    assert chinese["aliases"] == [
        "Native or near-native level Chinese language proficiency required",
        "Chinese language proficiency required",
    ]
    assert chinese["prompt"] == "Chinese language proficiency is required in several kept roles. Do you have this capability?"


def test_apply_capability_tuning_decisions_adds_confirmed_capability():
    profile = {KEY_CAPABILITY_PROFILE_RULES: []}

    updated = apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working", KEY_ALIASES: ["process modelling"]}],
    )

    assert updated[KEY_CAPABILITY_PROFILE_RULES] == [
        {KEY_NAME: "Process mapping", KEY_LEVEL: "working", KEY_ALIASES: ["process modelling"]}
    ]
