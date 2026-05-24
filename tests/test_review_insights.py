from job_hunter_agent.global_settings import (
    KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT,
    KEY_REVIEW_MAX_EXAMPLES_PER_SKILL,
    KEY_REVIEW_MAX_SAMPLES_PER_REJECTION,
    KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT,
)
from job_hunter_agent.review_insights import (
    apply_capability_tuning_decisions,
    build_suggested_tuning_from_saved_review,
)
from job_hunter_agent.profile_store import (
    KEY_ALIASES,
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_LEVEL,
    KEY_NAME,
)


def test_saved_review_data_builds_capability_and_rule_suggestions(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.review_insights.get_review_settings",
        lambda: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: 2,
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: 2,
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: 2,
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: 3,
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: 3,
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: 2,
        },
    )

    payload = {
        "kept_job_urls": ["https://example.test/job-1", "https://example.test/job-2"],
        "skill_observations": [
            {
                "skill": "Process mapping",
                "title": "Business Analyst",
                "company": "Example Co",
                "url": "https://example.test/job-1",
                "search_location": "Sydney",
            },
            {
                "skill": "Process mapping",
                "title": "Senior Business Analyst",
                "company": "Example Co",
                "url": "https://example.test/job-2",
                "search_location": "Sydney",
            },
            {
                "skill": "Ignored skill from rejected role",
                "url": "https://example.test/rejected",
            },
        ],
        "rejections_by_reason": [
            {
                "reason": "DESC_CAPABILITY_LOW:python",
                "count": 2,
                "samples": [
                    {
                        "title": "Python Developer",
                        "company": "Wrong Co",
                        "url": "https://example.test/reject-1",
                    }
                ],
            }
        ],
    }

    result = build_suggested_tuning_from_saved_review(payload, {KEY_CAPABILITY_PROFILE_RULES: []})

    assert result["summary"] == {"capability_count": 1, "rule_count": 1}
    capability = result["capability_suggestions"][0]
    assert capability["skill"] == "Process mapping"
    assert capability["count"] == 2
    assert capability["recommended_choice"] == "basic"
    assert len(capability["examples"]) == 2

    rule = result["rule_suggestions"][0]
    assert rule["reason"] == "DESC_CAPABILITY_LOW:python"
    assert rule["target"] == "Capability matrix or Requirement Exclusions"


def test_saved_review_data_does_not_suggest_already_classified_capability(monkeypatch):
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
    payload = {
        "kept_job_urls": ["https://example.test/job-1"],
        "skill_observations": [
            {"skill": "Process mapping", "url": "https://example.test/job-1"},
        ],
        "rejections_by_reason": [],
    }
    profile = {
        KEY_CAPABILITY_PROFILE_RULES: [
            {KEY_NAME: "Process mapping", KEY_LEVEL: "working", KEY_ALIASES: []}
        ]
    }

    result = build_suggested_tuning_from_saved_review(payload, profile)

    assert result["capability_suggestions"] == []
    assert result["summary"]["capability_count"] == 0


def test_apply_capability_tuning_decisions_adds_confirmed_capability():
    profile = {KEY_CAPABILITY_PROFILE_RULES: []}

    updated = apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working", KEY_ALIASES: ["process modelling"]}],
    )

    assert updated[KEY_CAPABILITY_PROFILE_RULES] == [
        {KEY_NAME: "Process mapping", KEY_LEVEL: "working", KEY_ALIASES: ["process modelling"]}
    ]
