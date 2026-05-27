"""Tests for title extraction."""

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
