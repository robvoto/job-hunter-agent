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


def test_analyze_title_filters_unmatched_titles_keep_conservative_fallback(monkeypatch):
    """A title with no obvious overlap should still follow the conservative O*NET/LLM path."""
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
    assert result["reason"] == "TITLE_NOT_TARGET"


def test_analyze_title_filters_keeps_onet_fallback_when_core_keyword_overlaps(monkeypatch):
    """A title that shares a word with a target role should still fall through to the softer O*NET path."""
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


def test_analyze_title_filters_with_no_roles_still_returns_title_not_target(monkeypatch):
    """With no target/adjacent roles configured the conservative fallback path is unchanged."""
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

def test_suggest_title_block_phrase_prefers_parenthetical_qualifier():
    profile = {
        "target_roles": ["business analyst"],
        "also_consider_roles": [],
        "reject_title_rules": [],
    }

    assert (
        filters.suggest_title_block_phrase(
            "Digital Business Analyst (Salesforce)", profile
        )
        == "salesforce"
    )


def test_suggest_title_block_phrase_uses_separator_qualifier():
    profile = {
        "target_roles": ["business analyst"],
        "also_consider_roles": [],
        "reject_title_rules": [],
    }

    assert filters.suggest_title_block_phrase("Business Analyst | Payroll", profile) == "payroll"


def test_suggest_title_block_phrase_never_suggests_base_role():
    profile = {
        "target_roles": ["business analyst"],
        "also_consider_roles": [],
        "reject_title_rules": [],
    }

    assert filters.suggest_title_block_phrase("Digital Business Analyst", profile) == ""


def test_title_block_rule_matches_whole_word_in_title_only():
    profile = {
        "target_roles": ["business analyst"],
        "also_consider_roles": [],
        "reject_title_rules": [filters.build_title_block_rule("salesforce")],
    }

    blocked = filters.analyze_title_filters("Business Analyst (Salesforce)", profile)
    allowed = filters.analyze_title_filters("Business Analyst", profile)
    not_partial = filters.analyze_title_filters("Business Analyst Salesforces", profile)

    assert blocked["reason"] == "TITLE_BAD_KEYWORD:salesforce"
    assert allowed["ok"] is True
    assert not_partial["ok"] is True

