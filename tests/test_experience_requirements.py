"""Tests for the deterministic experience-duration helpers.

This module does numeric parsing and month arithmetic only; deciding which job
wording is the same role family stays with the fit-review LLM.
"""

from job_hunter_agent.experience_requirements import (
    extract_required_experience_months,
    resolve_role_experience_requirement,
)


def test_single_value_years_and_months_are_parsed():
    assert extract_required_experience_months("5+ years experience") == 60
    assert extract_required_experience_months("minimum of 3 years") == 36
    assert extract_required_experience_months("at least 24 months in role") == 24


def test_stated_year_range_is_lower_bounded():
    # The upper bound must never become the requirement: "3-5 years" asks for 3.
    assert extract_required_experience_months("3-5 years experience") == 36
    assert extract_required_experience_months("3–5 years experience") == 36
    assert extract_required_experience_months("3 to 5 years experience") == 36
    assert extract_required_experience_months("2.5-4 years experience") == 30


def test_stated_month_range_is_lower_bounded():
    assert extract_required_experience_months("18-24 months experience") == 18
    assert extract_required_experience_months("18–24 months experience") == 18
    assert extract_required_experience_months("18 to 24 months experience") == 18


def test_returns_none_when_no_duration_is_stated():
    assert extract_required_experience_months("experience as a Business Analyst") is None
    assert extract_required_experience_months("") is None


def _duration_components(matched_role_family: str) -> list[dict]:
    return [
        {"kind": "duration", "text": "5+ years"},
        {
            "kind": "role_or_activity",
            "text": "business analysis",
            "matched_role_family": matched_role_family,
        },
    ]


def _ba_family(total_duration_months: int) -> list[dict]:
    """One Business Analyst family whose history spans BA + Senior BA titles."""
    return [
        {
            "normalized_title": "Business Analyst",
            "total_duration_months": total_duration_months,
            "most_recent_end_year": 2025,
            "segments": [{"duration_months": total_duration_months, "is_current": False}],
            "title_variants": [
                {"normalized_title": "Business Analyst"},
                {"normalized_title": "Senior Business Analyst"},
            ],
        }
    ]


def test_subtitle_match_is_credited_and_reported_under_the_canonical_family():
    # The LLM tied the requirement to the "Senior Business Analyst" sub-title,
    # which only exists as a title variant. The combined family total is used
    # and the canonical "Business Analyst" family is reported, so a whole
    # family's history is never mislabelled as senior-only time.
    resolved = resolve_role_experience_requirement(
        _duration_components("Senior Business Analyst"),
        60,
        _ba_family(66),
    )

    assert resolved["role_family_resolved"] is True
    assert resolved["matched_role_family"] == "Business Analyst"
    assert resolved["matched_role_family_months"] == 66
    assert resolved["experience_requirement_met"] is True


def test_range_requirement_resolves_against_the_lower_bound():
    required_months = extract_required_experience_months("3-5 years business analysis")
    resolved = resolve_role_experience_requirement(
        _duration_components("Business Analyst"),
        required_months,
        _ba_family(42),
    )

    assert resolved["required_experience_months"] == 36
    assert resolved["matched_role_family_months"] == 42
    assert resolved["experience_requirement_met"] is True


def test_unresolved_when_llm_ties_no_family():
    resolved = resolve_role_experience_requirement(
        _duration_components(""),
        60,
        _ba_family(66),
    )

    assert resolved["role_family_resolved"] is False
    assert "matched_role_family_months" not in resolved


def test_no_duration_means_no_resolution():
    assert (
        resolve_role_experience_requirement(_duration_components("Business Analyst"), None, _ba_family(66))
        is None
    )


def _ba_family_with_current_segment(stored_months: int, duration_as_of: str) -> list[dict]:
    """A BA family whose only segment is still current, extracted at duration_as_of."""
    return [
        {
            "normalized_title": "Business Analyst",
            "total_duration_months": stored_months,
            "most_recent_end_year": 2026,
            "title_variants": [{"normalized_title": "Business Analyst"}],
            "segments": [
                {
                    "duration_months": stored_months,
                    "is_current": True,
                    "duration_as_of": duration_as_of,
                }
            ],
        }
    ]


def _accrued(stored_months: int, duration_as_of: str) -> int:
    from datetime import date

    from job_hunter_agent.role_experience_duration import whole_months_between

    return stored_months + whole_months_between(
        date.fromisoformat(duration_as_of), date.today()
    )


def test_current_role_accrual_clears_a_threshold_stored_months_alone_would_miss():
    # 56 months captured well over a year ago; the still-current role has since
    # accrued past the 60-month bar even though the stored snapshot is short.
    duration_as_of = "2024-01-01"
    stored_months = 56
    resolved = resolve_role_experience_requirement(
        _duration_components("Business Analyst"),
        60,
        _ba_family_with_current_segment(stored_months, duration_as_of),
    )

    expected = _accrued(stored_months, duration_as_of)
    assert expected >= 60
    assert resolved["matched_role_family_months"] == expected
    assert resolved["experience_requirement_met"] is True


def test_current_role_accrual_still_short_leaves_the_requirement_unmet():
    duration_as_of = "2024-01-01"
    stored_months = 12
    resolved = resolve_role_experience_requirement(
        _duration_components("Business Analyst"),
        120,
        _ba_family_with_current_segment(stored_months, duration_as_of),
    )

    expected = _accrued(stored_months, duration_as_of)
    assert expected < 120
    assert resolved["matched_role_family_months"] == expected
    assert resolved["experience_requirement_met"] is False
