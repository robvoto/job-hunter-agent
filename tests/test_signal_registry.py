from __future__ import annotations

import json

from job_hunter_agent import capability_knowledge, signal_registry
from job_hunter_agent import hard_blocker_rules
from job_hunter_agent import role_title_knowledge


def test_load_capability_knowledge_normalizes_entries(tmp_path, monkeypatch):
    path = tmp_path / "capability_knowledge.json"
    path.write_text(
        json.dumps(
            {
                "kind": "managed_knowledge",
                "name": "capability_knowledge",
                "entries": [
                    {
                        "value": "  BPMN 2.0  ",
                        "aliases": ["BPMN", "Business Process Modelling", "BPMN", "bpmn 2.0", ""],
                        "enabled": True,
                        "source": "seed",
                    },
                    {
                        "value": "BPMN 2.0",
                        "aliases": ["workflow mapping"],
                    },
                    None,
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(capability_knowledge, "CAPABILITY_KNOWLEDGE_PATH", path)

    entries = capability_knowledge.load_capability_knowledge()

    assert entries == [
        {
            "value": "BPMN 2.0",
            "aliases": ["BPMN", "Business Process Modelling", "workflow mapping"],
        }
    ]


def test_approve_signal_promotes_capability_with_clean_shape(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    capability_path = tmp_path / "capability_knowledge.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", capability_path)
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal_archive.json")
    monkeypatch.setattr(capability_knowledge, "CAPABILITY_KNOWLEDGE_PATH", capability_path)

    signal_registry.save_registry({
        "bpmn 2.0": {
            "signal": "BPMN 2.0",
            "normalized_key": "bpmn 2.0",
            "original_texts": ["BPMN 2.0", "Business Process Modelling"],
            "category": "capability_concept",
            "history": [{"action": "added", "timestamp": "2026-05-03T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("bpmn 2.0", "capability_concept")

    assert updated == {
        "signal": "BPMN 2.0",
        "normalized_key": "bpmn 2.0",
        "original_texts": ["BPMN 2.0", "Business Process Modelling"],
        "category": "capability_concept",
    }

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert saved_registry == {}

    knowledge = json.loads(capability_path.read_text(encoding="utf-8"))
    assert knowledge["entries"] == [
        {
            "value": "BPMN 2.0",
            "aliases": [],
        }
    ]


def test_approve_signal_promotes_hard_blocker_pattern_with_clean_shape(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    hard_blocker_path = tmp_path / "hard_blocker_rules.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", hard_blocker_path)
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal_archive.json")
    monkeypatch.setattr(hard_blocker_rules, "HARD_BLOCKER_RULES_PATH", hard_blocker_path)

    signal_registry.save_registry({
        "demonstrated experience in {term}": {
            "signal": "demonstrated experience in {term}",
            "normalized_key": "demonstrated experience in {term}",
            "original_texts": ["demonstrated experience in SAP"],
            "suggested_category": "hard_blocker_pattern",
            "history": [{"action": "added", "timestamp": "2026-05-03T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("demonstrated experience in {term}", "hard_blocker_pattern")

    assert updated == {
        "signal": "demonstrated experience in {term}",
        "normalized_key": "demonstrated experience in {term}",
        "original_texts": ["demonstrated experience in {term}", "demonstrated experience in SAP"],
        "category": "hard_blocker_pattern",
    }

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert saved_registry == {}

    knowledge = json.loads(hard_blocker_path.read_text(encoding="utf-8"))
    assert knowledge == {
        "kind": "managed_knowledge",
        "name": "hard_blocker_rules",
        "version": 1,
        "description": "Approved reusable patterns that detect when a candidate-specific rejected term is a non-negotiable job requirement.",
        "entries": [
            {
                "value": "demonstrated experience in {term}",
                "aliases": [],
            }
        ],
    }


def test_register_signals_preserves_context_and_matches_knowledge(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    capability_path = tmp_path / "capability_knowledge.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", capability_path)
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal_archive.json")
    monkeypatch.setattr(capability_knowledge, "CAPABILITY_KNOWLEDGE_PATH", capability_path)

    capability_knowledge.save_capability_knowledge([
        {"value": "BPMN 2.0", "aliases": ["Business Process Modelling"]},
    ])

    signal_registry.register_signals([
        {
            "signal": "BPMN 2.0",
            "category": "capability_concept",
            "source": "CV parsing",
            "context": ["Skills section: BPMN 2.0"],
            "evidence": ["BPMN 2.0", "Business Process Modelling"],
            "needs_review": True,
        }
    ])

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    record = saved_registry["bpmn 2.0"]

    assert record["source"] == "CV parsing"
    assert record["context"] == ["Skills section: BPMN 2.0"]
    assert record["evidence"] == ["BPMN 2.0", "Business Process Modelling"]
    assert record["needs_review"] is True

    matched, label = signal_registry.signal_in_approved_knowledge("capability_concept", "BPMN 2.0")
    assert matched is True
    assert label == "BPMN 2.0"


def test_register_signals_preserves_suggested_category(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal_archive.json")

    signal_registry.register_signals([
        {
            "signal": "government",
            "original_texts": ["Australian Government"],
            "suggested_category": "government_context",
            "source": "job parsing",
            "needs_review": True,
        }
    ])

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    record = saved_registry["government"]

    assert record["signal"] == "government"
    assert record["normalized_key"] == "government"
    assert record["original_texts"] == ["government", "Australian Government"]
    assert record["category"] == ""
    assert record["suggested_category"] == "government_context"


def test_approve_signal_promotes_role_title_with_clean_shape(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    role_title_path = tmp_path / "role_title_knowledge.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", role_title_path)
    monkeypatch.setattr(role_title_knowledge, "ROLE_TITLE_KNOWLEDGE_PATH", role_title_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal_archive.json")

    signal_registry.save_registry({
        "analyst": {
            "signal": "analyst",
            "normalized_key": "analyst",
            "original_texts": ["Senior BA", "Business Analyst"],
            "category": "role_title_token",
            "history": [{"action": "added", "timestamp": "2026-05-03T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("analyst", "role_title_token")

    assert updated == {
        "signal": "analyst",
        "normalized_key": "analyst",
        "original_texts": ["analyst", "Senior BA", "Business Analyst"],
        "category": "role_title_token",
    }

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert saved_registry == {}

    knowledge = json.loads(role_title_path.read_text(encoding="utf-8"))
    assert knowledge["entries"] == [
        {
            "value": "analyst",
        }
    ]


def test_load_hard_blocker_rules_normalizes_without_writing(tmp_path, monkeypatch):
    path = tmp_path / "hard_blocker_rules.json"
    raw = json.dumps(
        {
            "kind": "managed_knowledge",
            "name": "hard_blocker_rules",
            "version": 1,
            "entries": [
                {"value": "  must have {term}  ", "aliases": [""]},
                {"value": "must have {term}", "aliases": ["  "]},
                None,
            ],
        }
    )
    path.write_text(raw, encoding="utf-8")
    monkeypatch.setattr(hard_blocker_rules, "HARD_BLOCKER_RULES_PATH", path)

    entries = hard_blocker_rules.load_hard_blocker_rules()

    assert entries == [
        {
            "value": "must have {term}",
            "aliases": [],
        }
    ]
    assert path.read_text(encoding="utf-8") == raw


def test_approve_signal_promotes_government_context_with_clean_shape(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    government_path = tmp_path / "government_context_knowledge.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", government_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal_archive.json")
    monkeypatch.setitem(signal_registry._CATEGORY_KNOWLEDGE_PATHS, "government_context", government_path)

    signal_registry.save_registry({
        "nsw health": {
            "signal": "NSW Health",
            "normalized_key": "nsw health",
            "original_texts": ["NSW Health", "state health department"],
            "category": "government_context",
            "history": [{"action": "added", "timestamp": "2026-05-03T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("nsw health", "government_context")

    assert updated == {
        "signal": "NSW Health",
        "normalized_key": "nsw health",
        "original_texts": ["NSW Health", "state health department"],
        "category": "government_context",
    }

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert saved_registry == {}

    knowledge = json.loads(government_path.read_text(encoding="utf-8"))
    assert knowledge["entries"] == [
        {
            "value": "NSW Health",
            "aliases": ["state health department"],
        }
    ]
