"""Tests for cv pipeline."""



from job_hunter_agent.cv_pipeline import _tool_terms, parse_roles, run_cv_pipeline, score_and_promote

from job_hunter_agent.profile_learning import _CURRENT_YEAR

def test_tool_terms_preserves_slash_separated_tools_individually():

    """Regression: 'Jira / Confluence' must produce individual terms, not only a combined phrase."""

    terms = _tool_terms("Tools: Jira / Confluence")

    terms_lower = [t.lower() for t in terms]

    assert "jira" in terms_lower

    assert "confluence" in terms_lower

    assert terms_lower != ["jira confluence"]





def test_tool_terms_preserves_slash_separated_tools_no_spaces():

    terms = _tool_terms("Tools: Jira/Confluence")

    terms_lower = [t.lower() for t in terms]

    assert "jira" in terms_lower

    assert "confluence" in terms_lower







def test_score_and_promote_uses_onboarding_strength_preset():

    strong = score_and_promote(

        [

            {

                "seed": "process mapping",

                "occurrences": 3,

                "role_count": 1,

                "recent_role_count": 3,

                "total_duration_months": 36,

                "most_recent_year": _CURRENT_YEAR - 1,

            }

        ],

        onboarding_settings={"capability_strength_preset": "balanced"},

    )

    working = score_and_promote(

        [

            {

                "seed": "stakeholder engagement",

                "occurrences": 2,

                "role_count": 1,

                "recent_role_count": 1,

                "total_duration_months": 18,

                "most_recent_year": _CURRENT_YEAR - 5,

            }

        ],

        onboarding_settings={"capability_strength_preset": "balanced"},

    )

    basic = score_and_promote(

        [

            {

                "seed": "legacy support",

                "occurrences": 1,

                "role_count": 1,

                "recent_role_count": 0,

                "total_duration_months": 6,

                "most_recent_year": _CURRENT_YEAR - 15,

            }

        ],

        onboarding_settings={"capability_strength_preset": "balanced"},

    )



    assert strong[0]["level"] == "strong"

    assert working[0]["level"] == "working"

    assert basic[0]["level"] == "basic"

