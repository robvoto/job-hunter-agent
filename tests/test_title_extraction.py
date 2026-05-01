from unittest.mock import patch

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

def test_extract_title_pattern_suggestions_returns_llm_patterns():
    fixture = {
        "capabilities": [],
        "primary_job_title_pattern": ["senior devops engineer", "devops engineer"],
        "secondary_title_patterns": ["technical consultant"],
        "suggested_search_keywords": ["devops", "cloud infrastructure"],
        "match_preferences": {},
    }
    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture):
        result = extract_title_pattern_suggestions("some cv", {"extraction_lookback_years": 8})

    assert "senior devops engineer" in result["primary_job_title_pattern"]
    assert "technical consultant" in result["secondary_title_patterns"]


def test_extract_title_pattern_suggestions_empty_when_llm_returns_nothing():
    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value={}):
        result = extract_title_pattern_suggestions("some cv")

    assert result == {
        "primary_job_title_pattern": [],
        "secondary_title_patterns": [],
        "suggested_search_keywords": [],
    }


def test_extract_title_pattern_suggestions_respects_max_target_patterns():
    fixture = {
        "primary_job_title_pattern": ["a", "b", "c", "d", "e"],
        "secondary_title_patterns": ["x", "y"],
        "suggested_search_keywords": [],
        "capabilities": [],
        "match_preferences": {},
    }
    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", return_value=fixture):
        result = extract_title_pattern_suggestions("cv", {"max_target_patterns": 2, "max_secondary_patterns": 1})

    assert len(result["primary_job_title_pattern"]) <= 2
    assert len(result["secondary_title_patterns"]) <= 1


def test_extract_title_pattern_suggestions_passes_lookback_years_to_llm():
    captured = {}

    def fake_extract(source_text, lookback_years):
        captured["lookback_years"] = lookback_years
        return {}

    with patch("job_hunter_agent.profile_learning._llm_extract_from_cv", side_effect=fake_extract):
        extract_title_pattern_suggestions("cv", {"extraction_lookback_years": 5})

    assert captured["lookback_years"] == 5
