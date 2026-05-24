from __future__ import annotations

from job_hunter_agent import filters
from job_hunter_agent import title_normalization_rules


def test_passes_title_filters_normalizes_runtime_abbreviations(isolated_db, monkeypatch):
    from job_hunter_agent.knowledge_store import set_knowledge
    set_knowledge("title_normalization_rules", {
        "kind": "rules",
        "name": "title_normalization_rules",
        "version": 1,
        "updated_at": "2026-05-03",
        "seniority_modifiers": ["junior", "senior", "lead"],
        "abbreviation_expansions": {"sr": "senior", "ba": "business analyst"},
        "normalization": {
            "collapse_spaces": True,
            "strip_outer_punctuation": True,
            "lowercase_for_matching": True,
            "preserve_original_for_display": True,
        },
    }, isolated_db)
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["senior business analyst"],
            "also_consider_roles": [],
            "reject_title_rules": [],
        },
    )

    ok, reason = filters.passes_title_filters("Sr BA")

    assert (ok, reason) == (True, "OK")


def test_passes_title_filters_matches_base_role_family(isolated_db, monkeypatch):
    from job_hunter_agent.knowledge_store import set_knowledge
    set_knowledge("title_normalization_rules", {
        "kind": "rules",
        "name": "title_normalization_rules",
        "version": 1,
        "updated_at": "2026-05-03",
        "seniority_modifiers": ["junior", "senior", "lead"],
        "abbreviation_expansions": {"sr": "senior", "ba": "business analyst"},
        "normalization": {
            "collapse_spaces": True,
            "strip_outer_punctuation": True,
            "lowercase_for_matching": True,
            "preserve_original_for_display": True,
        },
    }, isolated_db)
    set_knowledge("role_title_knowledge", {
        "kind": "managed_knowledge",
        "name": "role_title_knowledge",
        "version": 1,
        "updated_at": "2026-05-03",
        "description": "",
        "entries": [{"value": "analyst"}],
    }, isolated_db)
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["business analyst"],
            "also_consider_roles": ["project coordinator"],
            "reject_title_rules": [],
        },
    )

    ok_primary, reason_primary = filters.passes_title_filters("Senior Business Analyst AI Foundations")
    ok_secondary, reason_secondary = filters.passes_title_filters("Lead Project Coordinator Digital")

    assert (ok_primary, reason_primary) == (True, "OK")
    assert (ok_secondary, reason_secondary) == (True, "TITLE_POTENTIAL_MATCH")


def test_analyze_title_filters_applies_reject_rules_to_primary_matches(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "target_roles": ["business analyst"],
            "also_consider_roles": [],
            "reject_title_rules": [{"pattern": r"\btechnical\b", "reason": "TITLE_BAD_KEYWORD:technical"}],
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
            "reject_title_rules": [{"pattern": r"\btechnical\b", "reason": "TITLE_BAD_KEYWORD:technical"}],
        },
    )

    result = filters.analyze_title_filters("Technical Project Coordinator")

    assert result["ok"] is False
    assert result["reason"] == "TITLE_BAD_KEYWORD:technical"
