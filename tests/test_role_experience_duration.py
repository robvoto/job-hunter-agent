"""Tests for the effective-duration arithmetic on saved role families.

Pure date maths: completed segments contribute their stored months, a still-current
segment also accrues the whole calendar months elapsed since it was extracted.
No role-family semantics live here.
"""

from datetime import date

import pytest

from job_hunter_agent.role_experience_duration import (
    apply_effective_durations,
    effective_family_months,
    whole_months_between,
)


def test_whole_months_between_counts_only_fully_elapsed_months():
    assert whole_months_between(date(2026, 1, 10), date(2026, 3, 5)) == 1
    assert whole_months_between(date(2026, 1, 10), date(2026, 3, 10)) == 2
    assert whole_months_between(date(2024, 6, 1), date(2026, 6, 1)) == 24


def test_whole_months_between_floors_at_zero():
    assert whole_months_between(date(2026, 9, 1), date(2026, 1, 1)) == 0


def test_row_without_segments_is_rejected():
    row = {"normalized_title": "business analyst", "total_duration_months": 48}
    with pytest.raises(ValueError, match="non-empty segments"):
        effective_family_months(row, as_of=date(2030, 1, 1))


def test_historical_only_family_does_not_accrue():
    row = {
        "total_duration_months": 36,
        "segments": [
            {"duration_months": 24, "is_current": False},
            {"duration_months": 12, "is_current": False},
        ],
    }
    assert effective_family_months(row, as_of=date(2020, 1, 1)) == 36
    assert effective_family_months(row, as_of=date(2030, 1, 1)) == 36


def test_current_segment_accrues_whole_elapsed_months():
    row = {
        "total_duration_months": 60,
        "segments": [
            {"duration_months": 60, "is_current": True, "duration_as_of": "2026-03-01"},
        ],
    }
    assert effective_family_months(row, as_of=date(2026, 9, 1)) == 66


def test_current_segment_accrual_respects_day_of_month_boundary():
    row = {
        "segments": [
            {"duration_months": 10, "is_current": True, "duration_as_of": "2026-01-10"},
        ],
    }
    assert effective_family_months(row, as_of=date(2026, 3, 5)) == 11
    assert effective_family_months(row, as_of=date(2026, 3, 10)) == 12


def test_mixed_completed_and_current_ba_family():
    row = {
        "normalized_title": "business analyst",
        "total_duration_months": 54,
        "segments": [
            {"duration_months": 24, "is_current": False},
            {"duration_months": 12, "is_current": False},
            {"duration_months": 18, "is_current": True, "duration_as_of": "2026-06-01"},
        ],
    }
    # 24 + 12 + (18 + 3 whole months from 2026-06-01 to 2026-09-01)
    assert effective_family_months(row, as_of=date(2026, 9, 1)) == 57


def test_current_segment_missing_duration_as_of_is_rejected():
    row = {"segments": [{"duration_months": 30, "is_current": True}]}
    with pytest.raises(ValueError, match="valid duration_as_of"):
        effective_family_months(row, as_of=date(2030, 1, 1))


def test_current_segment_unparseable_duration_as_of_is_rejected():
    row = {
        "segments": [
            {"duration_months": 30, "is_current": True, "duration_as_of": "not-a-date"},
        ],
    }
    with pytest.raises(ValueError, match="valid duration_as_of"):
        effective_family_months(row, as_of=date(2030, 1, 1))


def test_apply_effective_durations_updates_total_without_mutating_input():
    rows = [
        {
            "normalized_title": "business analyst",
            "total_duration_months": 60,
            "segments": [
                {"duration_months": 60, "is_current": True, "duration_as_of": "2026-03-01"},
            ],
            "title_variants": [{"normalized_title": "senior business analyst"}],
        }
    ]
    updated = apply_effective_durations(rows, as_of=date(2026, 9, 1))

    assert updated[0]["total_duration_months"] == 66
    assert updated[0]["title_variants"] == [{"normalized_title": "senior business analyst"}]
    # original row is left untouched
    assert rows[0]["total_duration_months"] == 60


def test_apply_effective_durations_ignores_non_list_input():
    assert apply_effective_durations(None) == []
    assert apply_effective_durations({"normalized_title": "x"}) == []
