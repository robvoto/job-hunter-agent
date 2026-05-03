from __future__ import annotations

import json

from job_hunter_agent import filters
from job_hunter_agent import role_title_knowledge
from job_hunter_agent import title_normalization_rules


def test_passes_title_filters_normalizes_runtime_abbreviations(tmp_path, monkeypatch):
    rules_path = tmp_path / "title_normalization_rules.json"
    rules_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(title_normalization_rules, "TITLE_NORMALIZATION_RULES_PATH", rules_path)
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "primary_job_title_pattern": ["senior business analyst"],
            "secondary_title_patterns": [],
            "reject_title_rules": [],
        },
    )

    ok, reason = filters.passes_title_filters("Sr BA")

    assert (ok, reason) == (True, "OK")


def test_passes_title_filters_matches_base_role_family(tmp_path, monkeypatch):
    rules_path = tmp_path / "title_normalization_rules.json"
    role_path = tmp_path / "role_title_knowledge.json"
    rules_path.write_text(
        json.dumps(
            {
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
            }
        ),
        encoding="utf-8",
    )
    role_path.write_text(
        json.dumps(
            {
                "kind": "managed_knowledge",
                "name": "role_title_knowledge",
                "version": 1,
                "updated_at": "2026-05-03",
                "description": "",
                "entries": [{"value": "analyst"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(title_normalization_rules, "TITLE_NORMALIZATION_RULES_PATH", rules_path)
    monkeypatch.setattr(role_title_knowledge, "ROLE_TITLE_KNOWLEDGE_PATH", role_path)
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "primary_job_title_pattern": ["business analyst"],
            "secondary_title_patterns": ["project coordinator"],
            "reject_title_rules": [],
        },
    )

    ok_primary, reason_primary = filters.passes_title_filters("Senior Business Analyst AI Foundations")
    ok_secondary, reason_secondary = filters.passes_title_filters("Lead Project Coordinator Digital")

    assert (ok_primary, reason_primary) == (True, "OK")
    assert (ok_secondary, reason_secondary) == (True, "TITLE_POTENTIAL_MATCH")
