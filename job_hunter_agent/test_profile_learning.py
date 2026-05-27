"""Tests for profile learning."""



import pytest

from datetime import datetime

from job_hunter_agent.profile_learning import (

    _extract_year_range, 

    _parse_role_entries, 

    _looks_like_role_title_line

)



_CURRENT_YEAR = datetime.now().year



def test_extract_year_range_variations():

    """Verify that various date formats are correctly converted to durations."""

    # Standard month-year range

    res = _extract_year_range("January 2020 - December 2020")

    assert res["duration_months"] == 12

    assert res["start_month"] == 1

    assert res["end_month"] == 12



    # Abbreviated months and short dashes

    res = _extract_year_range("Feb 2019-Mar 2019")

    assert res["duration_months"] == 2



    # Year only (should default to Jan -> Dec)

    res = _extract_year_range("2020 - 2021")

    # (2021-2020)*12 + (12-1) + 1 = 24

    assert res["duration_months"] == 24



    # Relative dates

    res = _extract_year_range("2022 to present")

    assert res["is_current"] is True

    assert res["end_year"] == _CURRENT_YEAR



def test_parse_role_entries_formats():

    """Test the parser's ability to handle different structural layouts in CVs."""

    

    # 1. Inline format

    text_inline = "ACME Corp - Lead Developer (Jan 2020 - Present)\nBuilt amazing things."

    roles = _parse_role_entries(text_inline)

    assert len(roles) == 1

    assert roles[0]["employer"] == "ACME Corp"

    assert roles[0]["title"] == "Lead Developer"



    # 2. Pipe separator format

    text_pipe = "Senior Architect | 2015 - 2018\nGlobal Tech Solutions\n* Bullet one"

    roles = _parse_role_entries(text_pipe)

    assert len(roles) == 1

    assert roles[0]["title"] == "Senior Architect"

    assert roles[0]["employer"] == "Global Tech Solutions"

    assert "Bullet one" in roles[0]["bullets"]



    # 3. Multiline header with date range on its own line

    text_block = "Full Stack Engineer\nStartup Inc\n2021 - 2022"

    roles = _parse_role_entries(text_block)

    assert len(roles) == 1

    assert roles[0]["title"] == "Full Stack Engineer"

    assert roles[0]["employer"] == "Startup Inc"



def test_looks_like_role_title_line_blockers():

    """Ensure the blocker keywords correctly prevent generic lines from being seen as titles."""

    # 'Managing' is in the title_candidate_leading_verb_blockers list

    assert _looks_like_role_title_line("Managing Director") is False

    assert _looks_like_role_title_line("Software Engineer") is True

    

    # Too long should fail

    assert _looks_like_role_title_line("This is a very long line that is definitely not a job title even if it contains analyst") is False