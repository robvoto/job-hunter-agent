from job_hunter_agent.cv_pipeline import parse_roles, run_cv_pipeline
from job_hunter_agent.profile_learning import _CURRENT_YEAR


def test_parse_roles_uses_configured_lookback_years_for_recency():
    cv_text = f"""
# Professional Experience
Acme Corp - Platform Lead ({_CURRENT_YEAR - 7} - {_CURRENT_YEAR - 7})
- Led platform delivery.
"""

    short_roles = parse_roles(cv_text, {"extraction_lookback_years": 5})
    long_roles = parse_roles(cv_text, {"extraction_lookback_years": 8})

    assert short_roles
    assert long_roles
    assert short_roles[0]["is_recent"] is False
    assert long_roles[0]["is_recent"] is True


def test_run_cv_pipeline_uses_plain_paragraphs_after_date_first_role_headers():
    cv_text = """
# Professional Experience
Senior Scrum Master
Contoso
2022 - Present
Led scrum ceremonies and stakeholder workshops.
Produced delivery plans and backlog refinement outcomes.
"""

    output = run_cv_pipeline(cv_text, llm_client=None)

    assert output["capability_profile_rules"]
