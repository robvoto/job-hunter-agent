import json

from job_hunter_agent import profile_store


def test_save_profile_normalizes_llm_fit_review_guidance(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(profile_store, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)

    saved = profile_store.save_profile({
        **profile_store.DEFAULT_PROFILE,
        "llm_fit_review_guidance": "  Prefer adjacent roles when responsibilities align.  ",
    })

    assert saved["llm_fit_review_guidance"] == "Prefer adjacent roles when responsibilities align."


def test_load_profile_defaults_llm_fit_review_guidance(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(profile_store, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)

    loaded = profile_store.load_profile()

    assert loaded["llm_fit_review_guidance"] == ""


def test_save_profile_normalizes_llm_capability_naming_guidance(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(profile_store, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)

    saved = profile_store.save_profile({
        **profile_store.DEFAULT_PROFILE,
        "llm_capability_naming_guidance": "  Prefer stable business-analysis style labels.  ",
    })

    assert saved["llm_capability_naming_guidance"] == "Prefer stable business-analysis style labels."


def test_load_profile_defaults_llm_capability_naming_guidance(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    monkeypatch.setattr(profile_store, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)

    loaded = profile_store.load_profile()

    assert loaded["llm_capability_naming_guidance"] == ""


def test_scoring_rules_knowledge_file_contains_sections():
    payload = json.loads(profile_store.SCORING_RULES_PATH.read_text(encoding="utf-8"))

    assert payload["kind"] == "managed_knowledge"
    assert "fit_breakdown" in payload
    assert "salary" in payload
    assert "convergence" in payload


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
