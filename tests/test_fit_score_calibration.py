"""Calibration tests for band-anchored fit scoring.

Design contract:
- LLM grade anchors the band (floor / ceiling).
- Other signals (title, capability evidence, preferences, freshness) move the score within the band.
- Grade and score cannot contradict: MISMATCH ≤ 7, STRONG ∈ [68, 87], etc.
- Hard block penalties (-100 each) override the band floor and can push the score to zero.

These tests do NOT rely on the DB being seeded — they pass scoring_rules from the JSON file
directly through the profile so the bands are always present.
"""

import json
import pytest

from job_hunter_agent import fit_scoring
from job_hunter_agent.paths import SCORING_RULES_PATH


def _scoring_rules() -> dict:
    return json.loads(SCORING_RULES_PATH.read_text(encoding="utf-8"))


def _profile(extra: dict | None = None) -> dict:
    base = {
        "candidate_capabilities": [],
        "dominant_signal_clusters": [],
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_sector": False,
            "engagement_type": ["permanent"],
            "preferred_contract_months": 12,
            "short_contract_months": 6,
        },
        "preference_weights": {},
        "salary_preferences": {},
        "scoring_rules": _scoring_rules(),
    }
    if extra:
        base.update(extra)
    return base


def _band(grade: str) -> dict:
    """Return the floor/ceiling dict for a grade from the live JSON."""
    return _scoring_rules()["llm_grade_bands"][grade]


# ── helpers ───────────────────────────────────────────────────────────────────


def _score(record: dict, profile: dict | None = None) -> int:
    return fit_scoring.fit_score(record, profile or _profile())


def _breakdown_labels(record: dict, profile: dict | None = None) -> list[str]:
    return [e["label"] for e in fit_scoring.fit_score_breakdown(record, profile or _profile())]


# ── Scenario 1: STRONG LLM + clean title + content + capability evidence ─────

_DESCRIPTION_TEXT = "Business analyst role supporting delivery and stakeholder engagement."


def test_strong_with_supporting_evidence_reaches_upper_strong_band():
    """STRONG + clean title + content OK + description → above the STRONG floor.

    Without supporting signals, STRONG floors at 68. A clean primary title match and content
    OK push the score above the floor, confirming that supporting signals matter within the band.
    full_description is required to avoid the description_capture_incomplete (-8) penalty,
    which would otherwise mask the title/content advantage.
    """
    band = _band("STRONG")
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary"},
        "content_reason": "OK",
        "full_description": _DESCRIPTION_TEXT,
        "llm_fit_grade": "STRONG",
        "contextual_capability_matches": [],
    }
    score = _score(record)
    assert band["floor"] <= score <= band["ceiling"], (
        f"STRONG + clean signals should be in [{band['floor']}, {band['ceiling']}], got {score}"
    )
    # Must be above the floor — supporting signals must make a positive difference
    assert score > band["floor"], (
        f"STRONG + clean title + content should exceed the floor {band['floor']}, got {score}"
    )


# ── Scenario 2: STRONG LLM + weak title + missing preferences ─────────────────


def test_strong_with_weak_signals_floors_at_strong_minimum():
    """STRONG + no title match + no content + no preferences → floors at STRONG band minimum."""
    band = _band("STRONG")
    record = {
        "title": "Accounts Payable Officer",
        "title_reason": "TITLE_NOT_TARGET",
        "content_reason": "NO_MATCH",
        "llm_fit_grade": "STRONG",
    }
    score = _score(record)
    # Must not reach old STRONG=95 baseline; must be within the STRONG band
    assert score == band["floor"], (
        f"STRONG + minimal signals should floor at {band['floor']}, got {score}"
    )
    assert score < 88, "STRONG with no supporting evidence must not reach the EXCELLENT band"


def test_strong_grade_cannot_produce_95_without_evidence():
    """The specific overcorrection that prompted the redesign: STRONG ≠ 95 automatically."""
    record = {
        "title": "Any Title",
        "title_reason": "TITLE_NOT_TARGET",
        "content_reason": "NO_MATCH",
        "llm_fit_grade": "STRONG",
    }
    score = _score(record)
    assert score < 90, f"STRONG without supporting evidence must not auto-produce 90+, got {score}"


# ── Scenario 3: SOLID LLM + good supporting signals ──────────────────────────


def test_solid_with_good_signals_stays_in_solid_band():
    """SOLID + good supporting signals must stay within the SOLID band ceiling."""
    band = _band("SOLID")
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary"},
        "content_reason": "OK",
        "full_description": _DESCRIPTION_TEXT,
        "llm_fit_grade": "SOLID",
        "contextual_capability_matches": [],
    }
    score = _score(record)
    assert band["floor"] <= score <= band["ceiling"], (
        f"SOLID + good signals must stay in [{band['floor']}, {band['ceiling']}], got {score}"
    )
    # Must never bleed into STRONG territory regardless of supporting signals
    strong_floor = _band("STRONG")["floor"]
    assert score < strong_floor, (
        f"SOLID grade must not reach STRONG territory ({strong_floor}+), got {score}"
    )


def test_solid_with_weak_signals_floors_at_solid_minimum():
    band = _band("SOLID")
    record = {
        "title": "Unrelated",
        "title_reason": "TITLE_NOT_TARGET",
        "content_reason": "NO_MATCH",
        "llm_fit_grade": "SOLID",
    }
    score = _score(record)
    assert score == band["floor"], (
        f"SOLID + minimal signals should floor at {band['floor']}, got {score}"
    )


# ── Scenario 4: MISMATCH cannot be rescued by small bonuses ───────────────────


def test_mismatch_capped_regardless_of_title_and_content():
    """MISMATCH grade must stay ≤ 7 even with clean title and content OK."""
    band = _band("MISMATCH")
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary"},
        "content_reason": "OK",
        "full_description": _DESCRIPTION_TEXT,
        "llm_fit_grade": "MISMATCH",
        "contextual_capability_matches": [],
    }
    score = _score(record)
    assert score <= band["ceiling"], f"MISMATCH must be capped at {band['ceiling']}, got {score}"


def test_poor_capped_below_solid():
    """POOR grade must stay below the SOLID floor even with all bonuses."""
    poor_band = _band("POOR")
    solid_floor = _band("SOLID")["floor"]
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary"},
        "content_reason": "OK",
        "full_description": _DESCRIPTION_TEXT,
        "llm_fit_grade": "POOR",
        "contextual_capability_matches": [],
    }
    score = _score(record)
    assert score <= poor_band["ceiling"], (
        f"POOR must be capped at {poor_band['ceiling']}, got {score}"
    )
    assert score < solid_floor, f"POOR must not reach SOLID territory ({solid_floor}+), got {score}"


# ── Scenario 5: Hard blocker forces near-zero ─────────────────────────────────


def test_hard_blocker_overrides_strong_grade_to_near_zero():
    """A hard blocker (-100) must override the STRONG band floor and push score to near-zero."""
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary"},
        "content_reason": "OK",
        "fit_confidence": "HIGH",
        "llm_fit_grade": "STRONG",
        "hard_block_reasons": ["requires NV1 security clearance"],
        "must_not_require_skills": ["NV1 security clearance"],
        "contextual_capability_matches": [],
    }
    profile = _profile(
        {
            "candidate_capabilities": [],
            "must_not_require_skills": ["NV1 security clearance"],
        }
    )
    score = _score(record, profile)
    assert score <= 10, f"Hard blocker + STRONG must score near-zero, got {score}"


def test_hard_blocker_overrides_any_grade():
    """Hard blocker penalty must push score to near-zero regardless of grade."""
    for grade in ("STRONG", "SOLID", "EXCELLENT"):
        record = {
            "title": "Business Analyst",
            "title_reason": "OK",
            "title_match_metadata": {"match_family": "primary"},
            "content_reason": "OK",
            "fit_confidence": "HIGH",
            "llm_fit_grade": grade,
            "hard_block_reasons": ["requires SAP certification"],
            "must_not_require_skills": ["SAP certification"],
            "contextual_capability_matches": [],
        }
        profile = _profile({"must_not_require_skills": ["SAP certification"]})
        score = _score(record, profile)
        assert score <= 10, f"{grade} + hard blocker must score near-zero, got {score}"


# ── Band transparency: clamping is visible in the breakdown ───────────────────


def test_band_ceiling_adjustment_appears_in_breakdown_when_clamped():
    """When supporting signals push above the ceiling, a breakdown entry must appear."""
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary"},
        "content_reason": "OK",
        "full_description": _DESCRIPTION_TEXT,
        "llm_fit_grade": "MISMATCH",  # MISMATCH ceiling = 7, so title+content will exceed it
        "contextual_capability_matches": [],
    }
    breakdown = fit_scoring.fit_score_breakdown(record, _profile())
    labels = [e["label"] for e in breakdown]
    assert any("Grade band ceiling" in label for label in labels), (
        f"Expected a 'Grade band ceiling' entry when clamped; got labels: {labels}"
    )


def test_band_floor_adjustment_appears_in_breakdown_when_lifted():
    """When the raw score falls below the floor, a breakdown entry must appear."""
    record = {
        "title": "Unrelated",
        "title_reason": "TITLE_NOT_TARGET",
        "content_reason": "NO_MATCH",
        "llm_fit_grade": "STRONG",  # base 52 - 8 desc penalty = 44 < STRONG floor 68
    }
    breakdown = fit_scoring.fit_score_breakdown(record, _profile())
    labels = [e["label"] for e in breakdown]
    assert any("Grade band floor" in label for label in labels), (
        f"Expected a 'Grade band floor' entry when lifted; got labels: {labels}"
    )


# ── Grade bands are non-overlapping and cover 0-100 ──────────────────────────


def test_grade_bands_are_non_overlapping_and_complete():
    """The grade bands must be non-overlapping and cover 0-100 without gaps."""
    rules = _scoring_rules()
    bands = rules["llm_grade_bands"]
    grade_order = ["MISMATCH", "POOR", "WEAK", "SOLID", "STRONG", "EXCELLENT"]
    sorted_bands = [(g, bands[g]) for g in grade_order if g in bands]
    assert sorted_bands, "llm_grade_bands must define at least some grades"

    prev_ceiling = -1
    for grade, band in sorted_bands:
        floor = band["floor"]
        ceiling = band["ceiling"]
        assert floor >= 0 and ceiling <= 100, f"{grade} band out of 0-100 range"
        assert floor <= ceiling, f"{grade} has floor > ceiling"
        assert floor == prev_ceiling + 1, (
            f"{grade} floor {floor} does not start one above previous ceiling {prev_ceiling}"
        )
        prev_ceiling = ceiling

    assert prev_ceiling == 100, f"Highest band ceiling must be 100, got {prev_ceiling}"


def test_score_bounds_are_derived_from_grade_bands():
    bounds = fit_scoring._score_bounds(
        {
            "llm_grade_bands": {
                "LOW": {"floor": 3, "ceiling": 19},
                "HIGH": {"floor": 20, "ceiling": 88},
            }
        }
    )
    assert bounds == (3, 88)
