from __future__ import annotations

from job_hunter_agent import capability_knowledge, signal_registry
from job_hunter_agent import hard_blocker_rules
from job_hunter_agent import role_title_knowledge
from job_hunter_agent import title_normalization_rules


def test_load_capability_knowledge_normalizes_entries(isolated_db):
    from job_hunter_agent.knowledge_store import set_knowledge

    set_knowledge("capability_knowledge", {
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
    }, isolated_db)

    entries = capability_knowledge.load_capability_knowledge()

    assert entries == [
        {
            "value": "BPMN 2.0",
            "aliases": ["BPMN", "Business Process Modelling", "workflow mapping"],
        }
    ]


def test_approve_signal_promotes_capability_with_clean_shape(isolated_db):
    from job_hunter_agent.knowledge_store import get_knowledge

    signal_registry.save_registry({
        "bpmn 2.0": {
            "signal": "BPMN 2.0",
            "normalized_key": "bpmn 2.0",
            "original_texts": ["BPMN 2.0", "Business Process Modelling"],
            "aliases": ["BPMN", "Business Process Modelling"],
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
        "aliases": ["BPMN", "Business Process Modelling"],
    }

    assert signal_registry.load_registry() == {}

    knowledge = get_knowledge("capability_knowledge", isolated_db)
    assert {"value": "BPMN 2.0", "aliases": ["BPMN", "Business Process Modelling"]} in knowledge["entries"]


def test_approve_signal_promotes_hard_blocker_pattern_with_clean_shape(isolated_db):
    from job_hunter_agent.knowledge_store import get_knowledge

    signal_registry.save_registry({
        "demonstrated experience in {term}": {
            "signal": "demonstrated experience in {term}",
            "normalized_key": "demonstrated experience in {term}",
            "original_texts": ["demonstrated experience in SAP"],
            "aliases": ["SAP"],
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
        "aliases": ["SAP"],
    }

    assert signal_registry.load_registry() == {}

    knowledge = get_knowledge("hard_blocker_rules", isolated_db)
    assert knowledge["kind"] == "managed_knowledge"
    assert knowledge["name"] == "hard_blocker_rules"
    assert {"value": "demonstrated experience in {term}", "aliases": ["SAP"]} in knowledge["entries"]


def test_approve_signal_promotes_cv_farming_pattern_with_clean_shape(isolated_db):
    from job_hunter_agent.knowledge_store import get_knowledge

    signal_registry.save_registry({
        "send your resume": {
            "signal": "send your resume",
            "normalized_key": "send your resume",
            "original_texts": ["Send your resume"],
            "aliases": ["Send your CV"],
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
        "aliases": ["Send your CV"],
    }

    assert signal_registry.load_registry() == {}

    knowledge = get_knowledge("cv_farming_rules", isolated_db)
    assert knowledge["kind"] == "managed_knowledge"
    assert knowledge["name"] == "cv_farming_rules"
    assert {"value": "send your resume", "aliases": ["Send your CV"]} in knowledge["entries"]


def test_approve_signal_promotes_generic_knowledge_with_aliases(isolated_db):
    from job_hunter_agent.knowledge_store import get_knowledge

    signal_registry.save_registry({
        "nsw health": {
            "signal": "NSW Health",
            "normalized_key": "nsw health",
            "original_texts": ["NSW Health"],
            "aliases": ["state health department"],
            "category": "government_context",
            "history": [{"action": "added", "timestamp": "2026-05-03T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("nsw health", "government_context")

    assert updated == {
        "signal": "NSW Health",
        "normalized_key": "nsw health",
        "original_texts": ["NSW Health"],
        "category": "government_context",
        "aliases": ["state health department"],
    }

    knowledge = get_knowledge("government_context_knowledge", isolated_db)
    assert {"value": "NSW Health", "aliases": ["state health department"]} in knowledge["entries"]


def test_register_signals_preserves_context_and_matches_knowledge(isolated_db):
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

    saved_registry = signal_registry.load_registry()
    record = saved_registry["workflow mapping"]

    assert record["source"] == "CV parsing"
    assert record["context"] == ["Skills section: workflow mapping"]
    assert record["evidence"] == ["workflow mapping"]
    assert record["needs_review"] is True

    matched, label = signal_registry.signal_in_approved_knowledge("capability_concept", "BPMN 2.0")
    assert matched is True
    assert label == "BPMN 2.0"


def test_register_signals_preserves_suggested_category(isolated_db):
    signal_registry.register_signals([
        {
            "signal": "xyzzy_unique_gov_term",
            "original_texts": ["XYZZY Unique Gov Term"],
            "suggested_category": "government_context",
            "source": "job parsing",
            "needs_review": True,
        }
    ])

    saved_registry = signal_registry.load_registry()
    record = saved_registry["xyzzy_unique_gov_term"]

    assert record["signal"] == "xyzzy_unique_gov_term"
    assert record["normalized_key"] == "xyzzy_unique_gov_term"
    assert record["original_texts"] == ["xyzzy_unique_gov_term", "XYZZY Unique Gov Term"]
    assert record["category"] == ""
    assert record["suggested_category"] == "government_context"


def test_filter_registerable_signals_skips_approved_pending_and_ignored(isolated_db):
    from job_hunter_agent.knowledge_store import set_knowledge

    capability_knowledge.save_capability_knowledge([
        {"value": "BPMN 2.0", "aliases": []},
    ])
    signal_registry.register_signals([
        {"signal": "pending term", "category": "role_title_token"},
    ])
    set_knowledge("ignored_signal", {
        "ignored term": {
            "signal": "ignored term",
            "normalized_key": "ignored term",
        }
    })

    filtered = signal_registry.filter_registerable_signals([
        {"signal": "BPMN 2.0", "category": "capability_concept"},
        {"signal": "pending term", "category": "role_title_token"},
        {"signal": "ignored term", "category": "government_context"},
        {"signal": "new term", "category": "government_context"},
    ])

    assert filtered == [
        {"signal": "new term", "category": "government_context"},
    ]


def test_register_signals_skips_approved_pending_and_ignored(isolated_db):
    from job_hunter_agent.knowledge_store import set_knowledge

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
    set_knowledge("ignored_signal", {
        "ignored term": {
            "signal": "ignored term",
            "normalized_key": "ignored term",
        }
    })

    signal_registry.register_signals([
        {"signal": "BPMN 2.0", "category": "capability_concept"},
        {"signal": "pending term", "category": "role_title_token"},
        {"signal": "ignored term", "category": "government_context"},
        {"signal": "new term", "category": "government_context"},
    ])

    saved_registry = signal_registry.load_registry()
    assert set(saved_registry) == {"pending term", "new term"}
    assert saved_registry["pending term"]["signal"] == "pending term"
    assert saved_registry["new term"]["signal"] == "new term"


def test_approve_signal_promotes_role_title_with_clean_shape(isolated_db):
    from job_hunter_agent.knowledge_store import get_knowledge

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

    assert signal_registry.load_registry() == {}

    knowledge = get_knowledge("role_title_knowledge", isolated_db)
    assert {"value": "analyst"} in knowledge["entries"]


def test_load_hard_blocker_rules_normalizes_without_writing(isolated_db):
    from job_hunter_agent.knowledge_store import set_knowledge, get_knowledge
    original_data = {
        "kind": "managed_knowledge",
        "name": "hard_blocker_rules",
        "version": 1,
        "entries": [
            {"value": "  must have {term}  ", "aliases": [""]},
            {"value": "must have {term}", "aliases": ["  "]},
            None,
        ],
    }
    set_knowledge("hard_blocker_rules", original_data, isolated_db)

    entries = hard_blocker_rules.load_hard_blocker_rules()

    assert entries == [
        {
            "value": "must have {term}",
            "aliases": [],
        }
    ]
    saved = get_knowledge("hard_blocker_rules", isolated_db)
    assert saved == original_data


def test_approve_signal_promotes_government_context_with_clean_shape(isolated_db):
    from job_hunter_agent.knowledge_store import get_knowledge

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

    assert signal_registry.load_registry() == {}

    knowledge = get_knowledge("government_context_knowledge", isolated_db)
    assert {"value": "NSW Health", "aliases": []} in knowledge["entries"]


def test_approve_signal_promotes_title_normalization_candidate(isolated_db):
    from job_hunter_agent.knowledge_store import get_knowledge

    signal_registry.save_registry({
        "sr": {
            "signal": "sr",
            "normalized_key": "sr",
            "original_texts": ["Senior Business Analyst"],
            "category": "title_normalization_candidate",
            "suggested_values": ["senior"],
            "context_terms": ["delivery", "project"],
            "history": [{"action": "added", "timestamp": "2026-05-05T00:00:00+00:00"}],
        }
    })

    updated = signal_registry.approve_signal("sr", "title_normalization_candidate", "project manager")

    assert updated == {
        "signal": "project manager",
        "normalized_key": "sr",
        "original_texts": ["sr", "Senior Business Analyst"],
        "category": "title_normalization_candidate",
    }

    assert signal_registry.load_registry() == {}

    rules = get_knowledge("title_normalization_rules", isolated_db)
    entries = rules.get("contextual_abbreviation_expansions", {}).get("sr", [])
    assert {
        "expansion": "project manager",
        "context_terms": ["delivery", "project"],
    } in entries


def test_approve_signal_title_normalization_candidate_no_suggested_values(isolated_db):
    from job_hunter_agent.knowledge_store import get_knowledge

    signal_registry.save_registry({
        "pm": {
            "signal": "pm",
            "normalized_key": "pm",
            "original_texts": ["PM"],
            "category": "title_normalization_candidate",
            "history": [{"action": "added", "timestamp": "2026-05-05T00:00:00+00:00"}],
        }
    })
    original_rules = get_knowledge("title_normalization_rules")

    updated = signal_registry.approve_signal("pm", "title_normalization_candidate")

    assert updated is None
    assert signal_registry.load_registry()["pm"]["signal"] == "pm"
    assert get_knowledge("title_normalization_rules", isolated_db) == original_rules


def test_signal_category_metadata_is_complete_and_user_facing():
    from job_hunter_agent.signal_registry import CATEGORY_METADATA, VALID_SIGNAL_CATEGORIES

    assert set(CATEGORY_METADATA) == set(VALID_SIGNAL_CATEGORIES)
    for category, meta in CATEGORY_METADATA.items():
        assert meta.get("label"), f"Missing label for {category}"
        assert meta.get("description"), f"Missing description for {category}"
        assert isinstance(meta.get("examples"), list), f"Examples must be a list for {category}"
        assert all(isinstance(example, str) and example for example in meta["examples"])
        assert meta.get("warning") is None or isinstance(meta.get("warning"), str)
