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
                "competitive_signals": [
                    {
                        "fit_label": "Process mapping",
                        "adjustment": 2,
                        "alignment": "strong",
                    }
                ],
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
    assert result["skill_observations"][0]["skill"] == "Process mapping"
    assert result["suggested_tuning"]["summary"] == {"capability_count": 1, "rule_count": 0}
    capability = result["suggested_tuning"]["capability_suggestions"][0]
    assert capability["skill"] == "Process mapping"
    assert capability["count"] == 1
    assert capability["examples"][0]["url"] == "https://example.test/job-1"


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


def test_apply_capability_tuning_decisions_adds_confirmed_capability():
    profile = {KEY_CAPABILITY_PROFILE_RULES: []}

    updated = apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working", KEY_ALIASES: ["process modelling"]}],
    )

    assert updated[KEY_CAPABILITY_PROFILE_RULES] == [
        {KEY_NAME: "Process mapping", KEY_LEVEL: "working", KEY_ALIASES: ["process modelling"]}
    ]
