from job_hunter_agent.cv_pipeline import parse_roles
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



