import pytest
from profile_learning import extract_title_pattern_suggestions, _CURRENT_YEAR

def test_consistent_lookback_logic():
    # Mock CV text with three roles:
    # 1. Recent & Long (Target)
    # 2. Recent & Short (Adjacent)
    # 3. Old (Should be ignored)
    cv_text = f"""
    # Professional Experience
    Acme - Senior DevOps Engineer ({_CURRENT_YEAR - 1} - {_CURRENT_YEAR})
    Managed cloud infrastructure.

    Beta - Technical Consultant ({_CURRENT_YEAR} - {_CURRENT_YEAR})
    Short contract.

    Gamma - Junior Support (2010 - 2012)
    Old role.
    """
    
    # Scenario 1: Default 8-year lookback
    settings = {
        "extraction_lookback_years": 8,
        "title_extraction_min_months": 18
    }
    
    result = extract_title_pattern_suggestions(cv_text, settings)
    
    # Prove Recent Long Role => Target
    assert any("devops" in p for p in result["target_title_patterns"])
    
    # Prove Recent Short Role => Adjacent
    assert any("consultant" in p for p in result["adjacent_title_patterns"])
    
    # Prove Old Role => Ignored (The Junior Support role is ~14 years old)
    assert not any("support" in p for p in result["target_title_patterns"])
    assert not any("support" in p for p in result["adjacent_title_patterns"])

def test_changing_lookback_affects_both_lists():
    cv_text = """
    # Professional Experience
    Delta - Project Manager (2015 - 2016)
    Delivery leadership.
    """
    
    # If lookback is 5 years, 2016 is too old.
    short_settings = {
        "extraction_lookback_years": 5,
        "title_extraction_min_months": 6
    }
    res_short = extract_title_pattern_suggestions(cv_text, short_settings)
    assert len(res_short["target_title_patterns"]) == 0

    # If lookback is 12 years, 2016 is inside the window.
    long_settings = {
        "extraction_lookback_years": 12,
        "title_extraction_min_months": 6
    }
    res_long = extract_title_pattern_suggestions(cv_text, long_settings)
    assert len(res_long["target_title_patterns"]) > 0
    assert any("project" in p for p in res_long["target_title_patterns"])
