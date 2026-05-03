from __future__ import annotations

import json

from job_hunter_agent import filters
from job_hunter_agent import role_title_knowledge
from job_hunter_agent import title_normalization_rules


def test_load_title_normalization_rules_returns_expected_structure(tmp_path, monkeypatch):
    path = tmp_path / "title_normalization_rules.json"
    path.write_text(
        json.dumps(
            {
                "kind": "rules",
                "name": "title_normalization_rules",
                "version": 1,
                "updated_at": "2026-05-03",
                "seniority_modifiers": ["junior", "senior"],
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
    monkeypatch.setattr(title_normalization_rules, "TITLE_NORMALIZATION_RULES_PATH", path)

    payload = title_normalization_rules.load_title_normalization_rules()

    assert payload["kind"] == "rules"
    assert payload["name"] == "title_normalization_rules"
    assert payload["abbreviation_expansions"]["ba"] == "business analyst"


def test_normalize_title_text_expands_abbreviations(tmp_path, monkeypatch):
    path = tmp_path / "title_normalization_rules.json"
    path.write_text(
        json.dumps(
            {
                "kind": "rules",
                "name": "title_normalization_rules",
                "version": 1,
                "updated_at": "2026-05-03",
                "seniority_modifiers": ["junior", "senior", "lead"],
                "abbreviation_expansions": {"sr": "senior", "jr": "junior", "ba": "business analyst", "po": "product owner"},
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
    monkeypatch.setattr(title_normalization_rules, "TITLE_NORMALIZATION_RULES_PATH", path)

    assert title_normalization_rules.normalize_title_text("Sr BA") == "senior business analyst"
    assert title_normalization_rules.normalize_title_text("PO") == "product owner"


def test_decompose_title_text_extracts_base_role_and_variant_terms(tmp_path, monkeypatch):
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

    decomposition = title_normalization_rules.decompose_title_text("Senior Business Analyst AI Foundations")

    assert decomposition == {
        "normalized_title": "senior business analyst ai foundations",
        "seniority_modifiers": ["senior"],
        "base_role": "business analyst",
        "variant_terms": "ai foundations",
    }
    assert title_normalization_rules.derive_base_title_from_seniority("Senior Business Analyst AI Foundations") == "business analyst"


def test_learn_title_normalization_candidates_promotes_safe_titles_and_reviews_ambiguous(tmp_path, monkeypatch):
    rules_path = tmp_path / "title_normalization_rules.json"
    review_path = tmp_path / "title_normalization_review.json"
    rules_path.write_text(
        json.dumps(
            {
                "kind": "rules",
                "name": "title_normalization_rules",
                "version": 1,
                "updated_at": "2026-05-03",
                "seniority_modifiers": ["junior", "senior", "lead"],
                "abbreviation_expansions": {},
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
    monkeypatch.setattr(title_normalization_rules, "TITLE_NORMALIZATION_REVIEW_PATH", review_path)

    summary = title_normalization_rules.learn_title_normalization_candidates(
        ["Sr", "GP", "PM"],
        source="job title",
        source_text="Community medical clinic",
    )

    saved_rules = json.loads(rules_path.read_text(encoding="utf-8"))
    review = json.loads(review_path.read_text(encoding="utf-8"))

    assert saved_rules["abbreviation_expansions"]["sr"] == "senior"
    assert saved_rules["abbreviation_expansions"]["gp"] == "general practitioner"
    assert review["entries"] == [
        {
            "value": "pm",
            "suggested_values": [
                "project manager",
                "product manager",
                "program manager",
            ],
            "evidence": ["PM"],
            "sources": ["job title"],
            "confidence": "ambiguous",
            "needs_review": True,
        }
    ]
    assert summary == {"promoted": 2, "reviewed": 1}
