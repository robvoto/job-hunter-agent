"""Tests for title matching."""

from __future__ import annotations

from job_hunter_agent import filters, title_normalization_rules


def test_passes_title_filters_abbreviations_are_not_expanded(monkeypatch):
    """Abbreviations like 'Sr BA' are no longer expanded. They must match profiles literally."""
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["sr ba"],
            "also_consider_roles": [],
            "reject_title_rules": [],
        },
    )

    ok, reason = filters.passes_title_filters("Sr BA")

    assert (ok, reason) == (True, "OK")


def test_passes_title_filters_matches_normalized_title_substring(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["business analyst"],
            "also_consider_roles": ["project coordinator"],
            "reject_title_rules": [],
        },
    )

    ok_primary, reason_primary = filters.passes_title_filters(
        "Senior Business Analyst AI Foundations"
    )
    ok_secondary, reason_secondary = filters.passes_title_filters(
        "Lead Project Coordinator Digital"
    )

    assert (ok_primary, reason_primary) == (True, "OK")
    assert (ok_secondary, reason_secondary) == (True, "TITLE_POTENTIAL_MATCH")


def test_analyze_title_filters_applies_reject_rules_to_primary_matches(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["business analyst"],
            "also_consider_roles": [],
            "reject_title_rules": [
                {"pattern": r"\btechnical\b", "reason": "TITLE_BAD_KEYWORD:technical"}
            ],
        },
    )

    result = filters.analyze_title_filters("Technical Business Analyst")

    assert result["ok"] is False
    assert result["reason"] == "TITLE_BAD_KEYWORD:technical"


def test_analyze_title_filters_applies_reject_rules_to_secondary_matches(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["business analyst"],
            "also_consider_roles": ["project coordinator"],
            "reject_title_rules": [
                {"pattern": r"\btechnical\b", "reason": "TITLE_BAD_KEYWORD:technical"}
            ],
        },
    )

    result = filters.analyze_title_filters("Technical Project Coordinator")

    assert result["ok"] is False
    assert result["reason"] == "TITLE_BAD_KEYWORD:technical"


def test_analyze_title_filters_rejects_titles_with_no_core_keyword_overlap(monkeypatch):
    """A title sharing no significant word with any target/adjacent role should be
    rejected outright rather than falling through to the O*NET near/far fallback."""
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["senior business analyst", "technical business analyst"],
            "also_consider_roles": ["scrum master"],
            "reject_title_rules": [],
        },
    )

    result = filters.analyze_title_filters("TamblaWFM Consultant")

    assert result["ok"] is False
    assert result["reason"] == "TITLE_NO_CORE_KEYWORD_OVERLAP"


def test_analyze_title_filters_keeps_onet_fallback_when_core_keyword_overlaps(monkeypatch):
    """A title that shares a significant word with a target role (but isn't an
    exact/synonym match) should still fall through to the softer O*NET path."""
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["senior business analyst", "technical business analyst"],
            "also_consider_roles": [],
            "reject_title_rules": [],
        },
    )

    result = filters.analyze_title_filters("Change Analyst")

    assert result["ok"] is False
    assert result["reason"] == "TITLE_NOT_TARGET"


def test_analyze_title_filters_skips_core_keyword_gate_when_profile_has_no_roles(monkeypatch):
    """With no target/adjacent roles configured there are no core keywords to derive,
    so behaviour must fall back to the original TITLE_NOT_TARGET path unchanged."""
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": [],
            "also_consider_roles": [],
            "reject_title_rules": [],
        },
    )

    result = filters.analyze_title_filters("TamblaWFM Consultant")

    assert result["ok"] is False
    assert result["reason"] == "TITLE_NOT_TARGET"
