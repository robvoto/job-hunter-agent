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
    assert "learning_candidates" not in payload
    assert "title_candidate_leading_verb_blockers" not in payload



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
                "contextual_abbreviation_expansions": {
                    "pm": [
                        {"expansion": "project manager", "context_terms": ["delivery", "project"]},
                        {"expansion": "product manager", "context_terms": ["product", "roadmap"]},
                    ]
                },
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
    assert title_normalization_rules.normalize_title_text("PM", "delivery project roadmap") == "project manager"
    assert title_normalization_rules.normalize_title_text("PM", "product roadmap go-to-market") == "product manager"
    assert title_normalization_rules.normalize_title_text("PM", "finance audit") == "pm"


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


def test_classify_title_normalization_candidate_uses_llm_without_writing_rules(tmp_path, monkeypatch):
    rules_path = tmp_path / "title_normalization_rules.json"
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
    monkeypatch.setattr(
        title_normalization_rules,
        "llm_should_consider_learning_candidates",
        lambda text: [
            {
                "signal": "PM",
                "suggested_category": "title_normalization_candidate",
                "suggested_values": ["project manager"],
                "context_terms": ["delivery", "project"],
                "confidence": "high",
                "original_texts": ["PM delivery project"],
            }
        ],
    )

    candidate = title_normalization_rules.classify_title_normalization_candidate("PM", "delivery project")

    assert candidate == {
        "value": "pm",
        "suggested_values": ["project manager"],
        "context_terms": ["delivery", "project"],
        "evidence": ["PM delivery project"],
        "confidence": "high",
        "needs_review": True,
    }
    assert json.loads(rules_path.read_text(encoding="utf-8"))["abbreviation_expansions"] == {}


def test_classify_title_normalization_candidate_skips_already_approved_entries(tmp_path, monkeypatch):
    rules_path = tmp_path / "title_normalization_rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "kind": "rules",
                "name": "title_normalization_rules",
                "version": 1,
                "updated_at": "2026-05-03",
                "seniority_modifiers": ["junior", "senior", "lead"],
                "abbreviation_expansions": {"sr": "senior"},
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
        title_normalization_rules,
        "llm_should_consider_learning_candidates",
        lambda text: [
            {
                "signal": "SR",
                "suggested_category": "title_normalization_candidate",
                "suggested_values": ["senior"],
                "confidence": "high",
                "original_texts": ["SR"],
            },
            {
                "signal": "PM",
                "suggested_category": "title_normalization_candidate",
                "suggested_values": ["project manager"],
                "context_terms": ["delivery", "project"],
                "confidence": "high",
                "original_texts": ["PM delivery project"],
            },
        ],
    )

    candidate = title_normalization_rules.classify_title_normalization_candidate("PM", "delivery project")

    assert candidate == {
        "value": "pm",
        "suggested_values": ["project manager"],
        "context_terms": ["delivery", "project"],
        "evidence": ["PM delivery project"],
        "confidence": "high",
        "needs_review": True,
    }


def test_find_approved_title_normalization_accepts_context_only_match(tmp_path, monkeypatch):
    path = tmp_path / "title_normalization_rules.json"
    path.write_text(
        json.dumps(
            {
                "kind": "rules",
                "name": "title_normalization_rules",
                "version": 1,
                "updated_at": "2026-05-03",
                "abbreviation_expansions": {},
                "contextual_abbreviation_expansions": {
                    "pm": [
                        {"expansion": "project manager", "context_terms": ["delivery", "project"]},
                    ]
                },
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

    assert title_normalization_rules.find_approved_title_normalization("PM", context_terms=["delivery", "project"]) == (True, "project manager")
