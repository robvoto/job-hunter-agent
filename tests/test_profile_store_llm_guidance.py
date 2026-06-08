"""Tests for profile store llm guidance."""

import json
import pytest

from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent import profile_store
from job_hunter_agent import review_insights


def test_save_profile_strips_legacy_guidance_key(isolated_db):
    legacy_key = "".join(["llm", "_capability_naming_guidance"])

    saved = profile_store.save_profile({
        **profile_store.DEFAULT_PROFILE,
        legacy_key: "  Prefer stable business-analysis style labels.  ",
    })

    assert legacy_key not in saved
    assert legacy_key not in profile_store.load_profile()


def test_save_profile_does_not_persist_scoring_rules(isolated_db):
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.user_context import get_user_id_for_runtime

    profile_store.save_profile({**profile_store.DEFAULT_PROFILE})

    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM user_profile WHERE user_id = ?", (get_user_id_for_runtime(),)
        ).fetchone()
    persisted = json.loads(row["data"])
    assert "scoring_rules" not in persisted


def test_load_profile_drops_legacy_guidance_key(isolated_db):
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.user_context import get_user_id_for_runtime

    legacy_key = "".join(["llm", "_capability_naming_guidance"])
    user_id = get_user_id_for_runtime()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO user_profile (user_id, data) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data""",
            (user_id, json.dumps({legacy_key: "Prefer labels close to business analysis."})),
        )

    loaded = profile_store.load_profile()

    assert legacy_key not in loaded


def test_load_profile_raises_for_non_object_data(isolated_db):
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.user_context import get_user_id_for_runtime

    user_id = get_user_id_for_runtime()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO user_profile (user_id, data) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data""",
            (user_id, json.dumps([1, 2, 3])),
        )

    with pytest.raises(profile_store.ProfileLoadError):
        profile_store.load_profile()


def test_default_profile_does_not_include_legacy_guidance_key():
    legacy_key = "".join(["llm", "_capability_naming_guidance"])
    assert legacy_key not in profile_store.DEFAULT_PROFILE
    assert "cv_text" not in profile_store.DEFAULT_PROFILE


def test_normalize_capability_rules_preserves_needs_review_when_aliases_exist():
    rules = profile_store.normalize_capability_rules([
        {
            "name": "Agile delivery",
            "level": "working",
            "aliases": ["scrum"],
            "needs_review": False,
        }
    ])

    assert rules[0]["aliases"] == ["scrum"]
    assert rules[0]["needs_review"] is True


def test_capability_level_tokens_and_display_labels_are_standardized():
    labels = load_ui_labels()["level_labels"]

    assert profile_store.LEVEL_STRONG == "strong"
    assert profile_store.LEVEL_WORKING == "working"
    assert profile_store.LEVEL_BASIC == "basic"
    assert labels["strong"] == "Strong"
    assert labels["working"] == "Working"
    assert labels["basic"] == "Basic"


def test_apply_capability_tuning_decisions_uses_internal_level_tokens():
    profile = {"candidate_capabilities": []}

    updated = review_insights.apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working"}],
    )

    assert updated["candidate_capabilities"][0]["level"] == "working"


def test_apply_capability_tuning_decisions_preserves_aliases():
    profile = {"candidate_capabilities": []}

    updated = review_insights.apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "working", "aliases": ["workflow design"]}],
    )

    assert updated["candidate_capabilities"][0]["aliases"] == ["workflow design"]


def test_apply_capability_tuning_decisions_rejects_legacy_low_choice():
    profile = {"candidate_capabilities": []}

    updated = review_insights.apply_capability_tuning_decisions(
        profile,
        [{"skill": "Process mapping", "choice": "low"}],
    )

    assert updated["candidate_capabilities"] == []


_ROUTING_FIXTURE = {
    "candidate_profile_section_routing": {
        "default_bucket": "primary_candidate_profile_context",
        "primary_labels": ["primary", "current", "main"],
        "secondary_labels": ["supporting"],
        "supplementary_labels": ["background", "education"],
    }
}


def test_classify_candidate_profile_section_label_uses_parsing_rules(monkeypatch):
    monkeypatch.setattr(profile_store, "load_parsing_rules", lambda: _ROUTING_FIXTURE)

    assert profile_store.classify_candidate_profile_section_label("Supporting Background") == "secondary_candidate_profile_context"
    assert profile_store.classify_candidate_profile_section_label("Education") == "supplementary_candidate_profile_context"
    assert profile_store.classify_candidate_profile_section_label("Main CV") == "primary_candidate_profile_context"


def test_classify_unknown_section_label_llm_confident(monkeypatch):
    monkeypatch.setattr(profile_store, "load_parsing_rules", lambda: _ROUTING_FIXTURE)

    captured = {}

    def fake_classify(label, llm_client=None):
        captured["label"] = label
        return {"bucket": "secondary", "confident": True}

    def fake_upsert(word, bucket):
        captured["upserted"] = (word, bucket)

    monkeypatch.setattr("job_hunter_agent.llm_gate.llm_classify_section_label", fake_classify)
    monkeypatch.setattr("job_hunter_agent.signal_registry.upsert_profile_section_label", fake_upsert)

    result = profile_store.classify_candidate_profile_section_label("Career History")
    assert result == "secondary_candidate_profile_context"
    assert captured["upserted"] == ("career history", "secondary")


def test_classify_unknown_section_label_llm_uncertain(monkeypatch):
    monkeypatch.setattr(profile_store, "load_parsing_rules", lambda: _ROUTING_FIXTURE)

    registered = []

    def fake_classify(label, llm_client=None):
        return {"bucket": "primary", "confident": False}

    def fake_register(signals):
        registered.extend(signals)

    monkeypatch.setattr("job_hunter_agent.llm_gate.llm_classify_section_label", fake_classify)
    monkeypatch.setattr("job_hunter_agent.signal_registry.register_signals", fake_register)

    result = profile_store.classify_candidate_profile_section_label("Overview")
    assert result == "primary_candidate_profile_context"
    assert len(registered) == 1
    assert registered[0]["category"] == "profile_section_label"
    assert registered[0]["suggested_values"] == ["primary"]


def test_classify_unknown_section_label_llm_unavailable(monkeypatch):
    monkeypatch.setattr(profile_store, "load_parsing_rules", lambda: _ROUTING_FIXTURE)
    monkeypatch.setattr("job_hunter_agent.llm_gate.llm_classify_section_label", lambda label, llm_client=None: None)

    result = profile_store.classify_candidate_profile_section_label("Overview")
    assert result == "primary_candidate_profile_context"
