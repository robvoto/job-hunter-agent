from job_hunter_agent.profile_learning import (
    _CURRENT_MONTH,
    _CURRENT_YEAR,
    _extract_year_range,
    extract_title_pattern_suggestions,
)


def test_consistent_lookback_logic():
    # Mock CV text with three roles:
    # 1. Recent and long (target)
    # 2. Recent and short (secondary)
    # 3. Old (ignored)
    cv_text = f"""
    # Professional Experience
    Acme - Senior DevOps Engineer ({_CURRENT_YEAR - 1} - {_CURRENT_YEAR})
    Managed cloud infrastructure.

    Beta - Technical Consultant ({_CURRENT_YEAR} - {_CURRENT_YEAR})
    Short contract.

    Gamma - Junior Support (2010 - 2012)
    Old role.
    """

    settings = {
        "extraction_lookback_years": 8,
        "title_extraction_min_months": 18,
    }

    result = extract_title_pattern_suggestions(cv_text, settings)

    assert any("devop" in pattern and "engineer" in pattern for pattern in result["target_title_patterns"])
    assert any("consultant" in pattern for pattern in result["secondary_title_patterns"])
    assert not any("support" in pattern for pattern in result["target_title_patterns"])
    assert not any("support" in pattern for pattern in result["secondary_title_patterns"])


def test_changing_lookback_affects_both_lists():
    cv_text = """
    # Professional Experience
    Delta - Project Manager (2015 - 2016)
    Delivery leadership.
    """

    short_settings = {
        "extraction_lookback_years": 5,
        "title_extraction_min_months": 6,
    }
    res_short = extract_title_pattern_suggestions(cv_text, short_settings)
    assert len(res_short["target_title_patterns"]) == 0

    long_settings = {
        "extraction_lookback_years": 12,
        "title_extraction_min_months": 6,
    }
    res_long = extract_title_pattern_suggestions(cv_text, long_settings)
    assert len(res_long["target_title_patterns"]) > 0
    assert any("project" in pattern for pattern in res_long["target_title_patterns"])


def test_month_aware_duration_sends_short_recent_role_to_secondary():
    cv_text = """
    # Professional Experience
    Acme - Delivery Manager (Jan 2024 - Mar 2024)
    Short transformation contract.
    """

    settings = {
        "extraction_lookback_years": 5,
        "title_extraction_min_months": 6,
    }

    result = extract_title_pattern_suggestions(cv_text, settings)

    assert not any("delivery" in pattern and "manager" in pattern for pattern in result["target_title_patterns"])
    assert any("delivery" in pattern and "manager" in pattern for pattern in result["secondary_title_patterns"])


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


def test_current_cv_like_recent_ba_roles_produce_targets_without_secondary_titles():
    cv_text = """
    # Primary CV
    Department of Employment and Workplace Relations (DEWR) - Industry: Federal Government
    Senior Business Analyst - Payments
    Dec 2024 - Present

    Australian Bureau of Statistics (ABS)
    Senior Business Analyst (EL1)
    Apr 2024 - Dec 2024

    NSW eHealth
    Digital & Infrastructure Business Analyst / Project Coordinator
    May 2022 - Nov 2023

    Department of Health (Federal)
    Digital Business Analyst
    Jul 2021 - May 2022

    Phoenix DX
    Agile Business Analyst / Consultant
    May 2020 - Jul 2021
    """

    settings = {
        "extraction_lookback_years": 6,
        "title_extraction_min_months": 6,
        "max_target_patterns": 8,
        "max_secondary_patterns": 6,
    }

    result = extract_title_pattern_suggestions(cv_text, settings)

    assert result["secondary_title_patterns"] == []
    assert result["target_title_patterns"] == [
        r"\bbusiness\ analyst\b",
        r"\bsenior\ business\ analyst\b",
        r"\bproject\ coordinator\b",
        r"\bdigital\ business\ analyst\b",
        r"\bagile\ business\ analyst\b",
    ]
    assert not any("payment" in pattern for pattern in result["target_title_patterns"])
