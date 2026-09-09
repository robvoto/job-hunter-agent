"""Tests for the deterministic experience-duration helpers.

This module does numeric parsing and month arithmetic only; deciding which job
wording is the same role family stays with the fit-review LLM.
"""

from job_hunter_agent.experience_requirements import (
    extract_required_experience_months,
    resolve_role_experience_requirement,
)
from job_hunter_agent.role_experience_duration import effective_family_months


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


def _ba_family_with_variant_months(
    family_total_months: int, senior_variant_months: int
) -> list[dict]:
    """A Business Analyst family (family_total_months accrued) that also stores a
    "Senior Business Analyst" variant with its own, smaller duration."""
    return [
        {
            "normalized_title": "Business Analyst",
            "total_duration_months": family_total_months,
            "most_recent_end_year": 2025,
            "segments": [{"duration_months": family_total_months, "is_current": False}],
            "title_variants": [
                {
                    "normalized_title": "Business Analyst",
                    "total_duration_months": 48,
                    "most_recent_end_year": 2018,
                },
                {
                    "normalized_title": "Senior Business Analyst",
                    "total_duration_months": senior_variant_months,
                    "most_recent_end_year": 2025,
                },
            ],
        }
    ]


def test_subtitle_match_is_credited_with_its_own_months_not_the_family_total():
    # JH-013 regression: the LLM tied the requirement to the "Senior Business
    # Analyst" sub-title. Only that variant's own 36 months may be credited, not
    # the 216-month Business Analyst family total it sits inside.
    resolved = resolve_role_experience_requirement(
        _duration_components("Senior Business Analyst"),
        60,
        _ba_family_with_variant_months(216, 36),
    )

    assert resolved["role_family_resolved"] is True
    assert resolved["matched_role_family"] == "Senior Business Analyst"
    assert resolved["matched_role_family_months"] == 36
    assert resolved["experience_requirement_met"] is False


def test_canonical_family_match_still_uses_the_whole_family_total():
    # Naming the family itself (not a sub-title) still credits the accrued
    # family total.
    resolved = resolve_role_experience_requirement(
        _duration_components("Business Analyst"),
        60,
        _ba_family_with_variant_months(216, 36),
    )

    assert resolved["role_family_resolved"] is True
    assert resolved["matched_role_family"] == "Business Analyst"
    assert resolved["matched_role_family_months"] == 216
    assert resolved["experience_requirement_met"] is True


def test_subtitle_without_its_own_duration_is_left_unresolved():
    # The "Senior Business Analyst" variant carries no duration of its own, so
    # there is nothing safe to credit and no fall-back to the family total.
    resolved = resolve_role_experience_requirement(
        _duration_components("Senior Business Analyst"),
        60,
        _ba_family(66),
    )

    assert resolved["role_family_resolved"] is False
    assert resolved["matched_role_family"] == "Senior Business Analyst"
    assert "matched_role_family_months" not in resolved


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


def test_matched_variant_stays_at_its_stored_snapshot_while_the_family_accrues():
    # JH-013 architectural note: the canonical family carries a still-current
    # segment and accrues elapsed months forward; the "Senior Business Analyst"
    # sub-title carries only a flat stored snapshot with no timing. A
    # requirement tied to the variant is credited with exactly that snapshot -
    # no accrual - and it must trail the accrued family total. The staleness is
    # one-directional (it can only understate), so it fails safe.
    duration_as_of = "2024-01-01"
    variant_snapshot_months = 24
    family_row = {
        "normalized_title": "Business Analyst",
        "total_duration_months": 60,
        "most_recent_end_year": 2026,
        "segments": [
            {"duration_months": 60, "is_current": True, "duration_as_of": duration_as_of},
        ],
        "title_variants": [
            {"normalized_title": "Business Analyst", "total_duration_months": 36},
            {
                "normalized_title": "Senior Business Analyst",
                "total_duration_months": variant_snapshot_months,
                "most_recent_end_year": 2026,
            },
        ],
    }

    accrued_family_months = effective_family_months(family_row)
    assert accrued_family_months > 60  # the current segment has moved on

    variant_resolved = resolve_role_experience_requirement(
        _duration_components("Senior Business Analyst"), 60, [family_row]
    )
    assert variant_resolved["role_family_resolved"] is True
    assert variant_resolved["matched_role_family"] == "Senior Business Analyst"
    assert variant_resolved["matched_role_family_months"] == variant_snapshot_months
    assert variant_resolved["matched_role_family_months"] < accrued_family_months
    assert variant_resolved["experience_requirement_met"] is False

    family_resolved = resolve_role_experience_requirement(
        _duration_components("Business Analyst"), 60, [family_row]
    )
    assert family_resolved["matched_role_family_months"] == accrued_family_months
    assert family_resolved["experience_requirement_met"] is True


def _skill_components(
    activity_text: str,
    *,
    sustained_months: int | None = None,
    sustained_roles: list[str] | None = None,
) -> list[dict]:
    """A years bar whose subject is a skill/activity narrower than a whole job."""
    role_component: dict = {"kind": "role_or_activity", "text": activity_text}
    if sustained_months is not None:
        role_component["sustained_experience_months"] = sustained_months
    if sustained_roles is not None:
        role_component["sustained_experience_roles"] = sustained_roles
    return [{"kind": "duration", "text": "5+ years"}, role_component]


def _plain_family(normalized_title: str, total_duration_months: int, end_year: int) -> dict:
    return {
        "normalized_title": normalized_title,
        "total_duration_months": total_duration_months,
        "most_recent_end_year": end_year,
        "segments": [{"duration_months": total_duration_months, "is_current": False}],
        "title_variants": [{"normalized_title": normalized_title}],
    }


def test_skill_merely_named_in_a_role_does_not_inherit_the_role_length():
    # JH-013: "5+ years BPMN" tied to a 216-month Business Analyst family, but the
    # LLM established no sustained span. The role length is only a ceiling, so
    # nothing is credited and the row is left for review with no number.
    resolved = resolve_role_experience_requirement(
        _skill_components("BPMN modelling"),
        60,
        [_plain_family("Business Analyst", 216, 2025)],
    )

    assert resolved["role_family_resolved"] is False
    assert "matched_role_family_months" not in resolved
    assert "experience_requirement_met" not in resolved


def test_skill_sustained_span_is_credited_but_capped_at_the_role_length():
    # The LLM read source evidence of ~90 months of sustained BPMN use inside a
    # 216-month Business Analyst history. Only the 90 months are credited, never
    # the whole family total.
    role_experience = [_plain_family("Business Analyst", 216, 2025)]

    resolved = resolve_role_experience_requirement(
        _skill_components(
            "BPMN modelling",
            sustained_months=90,
            sustained_roles=["Business Analyst"],
        ),
        60,
        role_experience,
    )

    assert resolved["role_family_resolved"] is True
    assert resolved["experience_from_sustained_use"] is True
    assert resolved["matched_role_family"] == "Business Analyst"
    assert resolved["matched_role_family_months"] == 90
    assert resolved["experience_requirement_met"] is True

    # A longer bar the sustained span cannot clear stays unmet, even though the
    # bare family total (216) would have passed it.
    still_short = resolve_role_experience_requirement(
        _skill_components(
            "BPMN modelling",
            sustained_months=90,
            sustained_roles=["Business Analyst"],
        ),
        120,
        role_experience,
    )
    assert still_short["matched_role_family_months"] == 90
    assert still_short["experience_requirement_met"] is False


def test_skill_sustained_span_claim_over_the_role_length_is_clamped_down():
    resolved = resolve_role_experience_requirement(
        _skill_components(
            "continuous improvement",
            sustained_months=400,
            sustained_roles=["Business Analyst"],
        ),
        60,
        [_plain_family("Business Analyst", 120, 2025)],
    )

    assert resolved["matched_role_family_months"] == 120


def test_skill_sustained_spans_sum_across_distinct_dated_roles():
    role_experience = [
        _plain_family("Business Analyst", 120, 2020),
        _plain_family("Systems Analyst", 72, 2026),
    ]

    resolved = resolve_role_experience_requirement(
        _skill_components(
            "process modelling",
            sustained_months=150,
            sustained_roles=["Business Analyst", "Systems Analyst"],
        ),
        144,
        role_experience,
    )

    # ceiling is 120 + 72 = 192; the 150-month claim fits under it and is summed.
    assert resolved["matched_role_family"] == "Business Analyst + Systems Analyst"
    assert resolved["matched_role_family_months"] == 150
    assert resolved["matched_role_family_end_year"] == 2026
    assert resolved["experience_requirement_met"] is True


def test_skill_sustained_span_repeated_role_is_only_counted_once():
    resolved = resolve_role_experience_requirement(
        _skill_components(
            "process modelling",
            sustained_months=200,
            sustained_roles=["Business Analyst", "business analyst"],
        ),
        60,
        [_plain_family("Business Analyst", 120, 2025)],
    )

    # The duplicated role does not double the ceiling.
    assert resolved["matched_role_family_months"] == 120


def test_skill_sustained_span_tied_only_to_unheld_roles_is_left_for_review():
    resolved = resolve_role_experience_requirement(
        _skill_components(
            "Kubernetes operations",
            sustained_months=48,
            sustained_roles=["Platform Engineer"],
        ),
        36,
        [_plain_family("Business Analyst", 120, 2025)],
    )

    assert resolved["role_family_resolved"] is False
    assert resolved["matched_role_family"] == "Platform Engineer"
    assert "matched_role_family_months" not in resolved
    assert "experience_requirement_met" not in resolved
