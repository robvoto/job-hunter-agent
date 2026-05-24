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


def test_parse_roles_uses_configured_lookback_years_for_recency():
    cv_text = f"""
# Professional Experience
Acme Corp - Platform Lead ({_CURRENT_YEAR - 7} - {_CURRENT_YEAR - 7})
- Led platform delivery.
"""
    #hardcoded
    short_roles = parse_roles(cv_text, {"extraction_lookback_years": 5})
    long_roles = parse_roles(cv_text, {"extraction_lookback_years": 8})

    assert short_roles
    assert long_roles
    assert short_roles[0]["is_recent"] is False
    assert long_roles[0]["is_recent"] is True


def test_run_cv_pipeline_uses_plain_paragraphs_after_date_first_role_headers():
    cv_text = """
# Professional Experience
Senior Business Analyst
Contoso
2022 - Present
Led requirements analysis and stakeholder workshops.
Produced delivery plans and backlog refinement outcomes.
"""

    output = run_cv_pipeline(cv_text, llm_client=None)

    assert output["dominant_signal_clusters"]

 

def test_run_cv_pipeline_preserves_questionable_signals_for_review():
    cv_text = f"""
# Professional Experience
Consultant
Contoso
{_CURRENT_YEAR} - Present
Tools: project, tools, technologies
- Project delivery.
"""

    output = run_cv_pipeline(cv_text, llm_client=None)

    assert any("project" in item["name"] for item in output["dominant_signal_clusters"])
    assert any(item["needs_review"] is True for item in output["dominant_signal_clusters"])


def test_run_cv_pipeline_uses_onboarding_signal_cluster_defaults():
    cv_text = f"""
# Professional Experience
Consultant
Contoso
{_CURRENT_YEAR} - Present
Tools: process mapping.
- Process mapping across delivery teams.
- Stakeholder engagement with business leads.
- Process mapping for delivery reviews.
- Stakeholder engagement for planning sessions.
"""

    output = run_cv_pipeline(
        cv_text,
        llm_client=None,
        onboarding_settings={
            "capability_strength_preset": "balanced",
            "capability_alias_limit": 3,
            "signal_cluster_min_alias_hits": 3,
            "signal_cluster_min_snippet_hits": 4,
            "signal_cluster_dense_snippet_alias_hits": 5,
        },
    )

    assert output["dominant_signal_clusters"]
    assert all(len(item["aliases"]) <= 3 for item in output["dominant_signal_clusters"])
    assert all(item["min_alias_hits"] == 3 for item in output["dominant_signal_clusters"])
    assert all(item["min_snippet_hits"] == 4 for item in output["dominant_signal_clusters"])
    assert all(item["dense_snippet_alias_hits"] == 5 for item in output["dominant_signal_clusters"])


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
