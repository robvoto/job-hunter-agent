from job_hunter_agent.profile_learning import (
    _CURRENT_MONTH,
    _CURRENT_YEAR,
    _extract_year_range,
    extract_title_pattern_suggestions,
)


# ── _extract_year_range: pure date parsing, no LLM ────────────────────────────

def test_extract_year_range_uses_real_month_span_for_current_role():
    date_info = _extract_year_range("Jan 2024 - Present")

    assert date_info is not None
    assert date_info["start_year"] == 2024
    assert date_info["start_month"] == 1
    assert date_info["end_year"] == _CURRENT_YEAR
    assert date_info["end_month"] == _CURRENT_MONTH
    assert date_info["duration_months"] >= 1


def test_extract_year_range_defaults_to_full_year_when_months_missing():
    date_info = _extract_year_range("2018 - 2020")

    assert date_info is not None
    assert date_info["start_year"] == 2018
    assert date_info["start_month"] == 1
    assert date_info["end_year"] == 2020
    assert date_info["end_month"] == 12
    assert date_info["duration_months"] == 36


# ── extract_title_pattern_suggestions: LLM-delegated ─────────────────────────

def test_extract_title_pattern_suggestions_returns_deterministic_patterns():
    cv_text = """
    # Professional Experience
    Senior DevOps Engineer
    Acme Cloud
    2023 - Present
    - Built deployment pipelines.

    Technical Consultant
    Blue Sky Consulting
    2012 - 2015
    - Supported client delivery.
    """
    result = extract_title_pattern_suggestions(cv_text, {"extraction_lookback_years": 8})

    assert "senior devops engineer" in result["primary_job_title_pattern"]
    assert "technical consultant" in result["primary_job_title_pattern"]
    assert result["secondary_title_patterns"] == ["devops engineer"]


def test_extract_title_pattern_suggestions_adds_seniority_base_to_secondary():
    cv_text = """
    # Professional Experience
    Senior Business Analyst
    Acme
    2024 - Present
    - Led requirements workshops.
    """
    result = extract_title_pattern_suggestions(cv_text, {"extraction_lookback_years": 8})

    assert "senior business analyst" in result["primary_job_title_pattern"]
    assert "business analyst" in result["secondary_title_patterns"]


def test_extract_title_pattern_suggestions_empty_when_no_role_headers():
    result = extract_title_pattern_suggestions("some cv")

    assert result == {
        "primary_job_title_pattern": [],
        "secondary_title_patterns": [],
        "suggested_search_keywords": [],
    }


def test_extract_title_pattern_suggestions_respects_max_target_patterns():
    cv_text = """
    # Professional Experience
    Lead Analyst
    Acme
    2024 - Present
    - Current role.

    Project Coordinator
    Beta
    2022 - 2024
    - Previous role.

    Operations Officer
    Gamma
    2018 - 2022
    - Older role.
    """
    result = extract_title_pattern_suggestions(cv_text, {"max_target_patterns": 1, "max_secondary_patterns": 1})

    assert len(result["primary_job_title_pattern"]) <= 1
    assert len(result["secondary_title_patterns"]) <= 1


def test_extract_title_pattern_suggestions_ignores_lookback_years():
    cv_text = """
    # Professional Experience
    Senior DevOps Engineer
    Acme Cloud
    2023 - Present
    - Built deployment pipelines.
    """
    first = extract_title_pattern_suggestions(cv_text, {"extraction_lookback_years": 5})
    second = extract_title_pattern_suggestions(cv_text, {"extraction_lookback_years": 8})

    assert first == second
