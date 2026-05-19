from __future__ import annotations

import json

from job_hunter_agent import capability_knowledge, signal_registry
from job_hunter_agent import hard_blocker_rules
from job_hunter_agent import job_quality
from job_hunter_agent import role_title_knowledge
from job_hunter_agent import title_normalization_rules


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
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
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
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
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
    assert knowledge["kind"] == "managed_knowledge"
    assert knowledge["name"] == "hard_blocker_rules"
    assert knowledge["version"] == 1
    assert knowledge["entries"] == [
        {
            "value": "demonstrated experience in {term}",
            "aliases": [],
        }
    ]


def test_approve_signal_promotes_cv_farming_pattern_with_clean_shape(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    cv_farming_path = tmp_path / "cv_farming_rules.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
    monkeypatch.setattr(signal_registry, "CV_FARMING_RULES_PATH", cv_farming_path)
    monkeypatch.setattr(job_quality, "CV_FARMING_RULES_PATH", cv_farming_path)
    monkeypatch.setitem(signal_registry._CATEGORY_KNOWLEDGE_PATHS, "cv_farming_pattern", cv_farming_path)

    signal_registry.save_registry({
        "send your resume": {
            "signal": "send your resume",
            "normalized_key": "send your resume",
            "original_texts": ["Send your resume"],
            "category": "cv_farming_pattern",
            "history": [{"action": "added", "timestamp": "2026-05-03T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("send your resume", "cv_farming_pattern")

    assert updated == {
        "signal": "send your resume",
        "normalized_key": "send your resume",
        "original_texts": ["send your resume"],
        "category": "cv_farming_pattern",
    }

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert saved_registry == {}

    knowledge = json.loads(cv_farming_path.read_text(encoding="utf-8"))
    assert knowledge["kind"] == "managed_knowledge"
    assert knowledge["name"] == "cv_farming_rules"
    assert knowledge["version"] == 1
    assert knowledge["entries"] == [
        {
            "value": "send your resume",
            "aliases": [],
        }
    ]


def test_register_signals_preserves_context_and_matches_knowledge(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    capability_path = tmp_path / "capability_knowledge.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", capability_path)
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
    monkeypatch.setattr(capability_knowledge, "CAPABILITY_KNOWLEDGE_PATH", capability_path)

    capability_knowledge.save_capability_knowledge([
        {"value": "BPMN 2.0", "aliases": ["Business Process Modelling"]},
    ])

    signal_registry.register_signals([
        {
            "signal": "workflow mapping",
            "category": "capability_concept",
            "source": "CV parsing",
            "context": ["Skills section: workflow mapping"],
            "evidence": ["workflow mapping"],
            "needs_review": True,
        }
    ])

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    record = saved_registry["workflow mapping"]

    assert record["source"] == "CV parsing"
    assert record["context"] == ["Skills section: workflow mapping"]
    assert record["evidence"] == ["workflow mapping"]
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
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
    monkeypatch.setitem(signal_registry._CATEGORY_KNOWLEDGE_PATHS, "government_context", tmp_path / "government_context_knowledge.json")

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


def test_filter_registerable_signals_skips_approved_pending_and_ignored(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    capability_path = tmp_path / "capability_knowledge.json"
    ignored_path = tmp_path / "ignored_signal.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", capability_path)
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", ignored_path)
    monkeypatch.setattr(capability_knowledge, "CAPABILITY_KNOWLEDGE_PATH", capability_path)

    capability_knowledge.save_capability_knowledge([
        {"value": "BPMN 2.0", "aliases": []},
    ])
    signal_registry.register_signals([
        {"signal": "pending term", "category": "role_title_token"},
    ])
    ignored_path.write_text(
        json.dumps({
            "ignored term": {
                "signal": "ignored term",
                "normalized_key": "ignored term",
            }
        }),
        encoding="utf-8",
    )

    filtered = signal_registry.filter_registerable_signals([
        {"signal": "BPMN 2.0", "category": "capability_concept"},
        {"signal": "pending term", "category": "role_title_token"},
        {"signal": "ignored term", "category": "government_context"},
        {"signal": "new term", "category": "government_context"},
    ])

    assert filtered == [
        {"signal": "new term", "category": "government_context"},
    ]


def test_register_signals_skips_approved_pending_and_ignored(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    capability_path = tmp_path / "capability_knowledge.json"
    ignored_path = tmp_path / "ignored_signal.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", capability_path)
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", ignored_path)
    monkeypatch.setattr(capability_knowledge, "CAPABILITY_KNOWLEDGE_PATH", capability_path)

    capability_knowledge.save_capability_knowledge([
        {"value": "BPMN 2.0", "aliases": []},
    ])
    signal_registry.save_registry({
        "pending term": {
            "signal": "pending term",
            "normalized_key": "pending term",
            "original_texts": ["pending term"],
            "category": "role_title_token",
            "history": [{"action": "added", "timestamp": "2026-05-05T00:00:00+00:00"}],
        }
    })
    ignored_path.write_text(
        json.dumps({
            "ignored term": {
                "signal": "ignored term",
                "normalized_key": "ignored term",
            }
        }),
        encoding="utf-8",
    )

    signal_registry.register_signals([
        {"signal": "BPMN 2.0", "category": "capability_concept"},
        {"signal": "pending term", "category": "role_title_token"},
        {"signal": "ignored term", "category": "government_context"},
        {"signal": "new term", "category": "government_context"},
    ])

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert set(saved_registry) == {"pending term", "new term"}
    assert saved_registry["pending term"]["signal"] == "pending term"
    assert saved_registry["new term"]["signal"] == "new term"


def test_approve_signal_promotes_role_title_with_clean_shape(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    role_title_path = tmp_path / "role_title_knowledge.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", role_title_path)
    monkeypatch.setattr(role_title_knowledge, "ROLE_TITLE_KNOWLEDGE_PATH", role_title_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")

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
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
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


def test_approve_signal_promotes_title_normalization_candidate(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    rules_path = tmp_path / "title_normalization_rules.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
    monkeypatch.setitem(signal_registry._CATEGORY_KNOWLEDGE_PATHS, "title_normalization_candidate", rules_path)

    signal_registry.save_registry({
        "sr": {
            "signal": "sr",
            "normalized_key": "sr",
            "original_texts": ["Senior Business Analyst"],
            "category": "title_normalization_candidate",
            "suggested_values": ["senior"],
            "history": [{"action": "added", "timestamp": "2026-05-05T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("sr", "title_normalization_candidate")

    assert updated == {
        "signal": "sr",
        "normalized_key": "sr",
        "original_texts": ["sr", "Senior Business Analyst"],
        "category": "title_normalization_candidate",
    }

    saved_registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert saved_registry == {}

    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    assert rules["abbreviation_expansions"] == {"sr": "senior"}


def test_approve_signal_title_normalization_candidate_no_suggested_values(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    rules_path = tmp_path / "title_normalization_rules.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
    monkeypatch.setitem(signal_registry._CATEGORY_KNOWLEDGE_PATHS, "title_normalization_candidate", rules_path)

    signal_registry.save_registry({
        "pm": {
            "signal": "pm",
            "normalized_key": "pm",
            "original_texts": ["PM"],
            "category": "title_normalization_candidate",
            "history": [{"action": "added", "timestamp": "2026-05-05T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("pm", "title_normalization_candidate")

    assert updated["category"] == "title_normalization_candidate"
    assert not rules_path.exists()

def test_learn_title_normalization_candidates_stores_suggested_values(tmp_path, monkeypatch):
    registry_path = tmp_path / "signal_registry.json"
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", registry_path)
    monkeypatch.setattr(signal_registry, "CAPABILITY_KNOWLEDGE_PATH", tmp_path / "capability_knowledge.json")
    monkeypatch.setattr(signal_registry, "ROLE_TITLE_KNOWLEDGE_PATH", tmp_path / "role_title_knowledge.json")
    monkeypatch.setattr(signal_registry, "HARD_BLOCKER_RULES_PATH", tmp_path / "hard_blocker_rules.json")
    monkeypatch.setattr(signal_registry, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", tmp_path / "government_context_knowledge.json")
    monkeypatch.setattr(signal_registry, "IGNORED_SIGNAL_ARCHIVE_PATH", tmp_path / "ignored_signal.json")
    monkeypatch.setitem(signal_registry._CATEGORY_KNOWLEDGE_PATHS, "title_normalization_candidate", tmp_path / "title_normalization_rules.json")

    result = title_normalization_rules.learn_title_normalization_candidates(["Sr BA"])

    assert result["pending"] == 1
    saved = json.loads(registry_path.read_text(encoding="utf-8"))
    record = saved.get("sr")
    assert record is not None
    assert record["suggested_values"] == ["senior"]
    assert record["suggested_category"] == "title_normalization_candidate"


def test_signal_category_metadata_is_complete_and_user_facing():
    from job_hunter_agent.signal_registry import CATEGORY_METADATA, VALID_SIGNAL_CATEGORIES

    assert set(CATEGORY_METADATA) == set(VALID_SIGNAL_CATEGORIES)
    for category, meta in CATEGORY_METADATA.items():
        assert meta.get("label"), f"Missing label for {category}"
        assert meta.get("description"), f"Missing description for {category}"
        assert isinstance(meta.get("examples"), list), f"Examples must be a list for {category}"
        assert all(isinstance(example, str) and example for example in meta["examples"])
        assert meta.get("warning") is None or isinstance(meta.get("warning"), str)
