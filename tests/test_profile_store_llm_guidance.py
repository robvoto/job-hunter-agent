import json
import pytest

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


def test_load_profile_raises_for_invalid_json_and_backs_up_file(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(profile_store, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)

    with pytest.raises(profile_store.ProfileLoadError):
        profile_store.load_profile()

    backups = sorted(tmp_path.glob("profile.invalid.*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not valid json"
    assert profile_path.read_text(encoding="utf-8") == "{not valid json"


def test_load_profile_raises_for_non_object_json_and_backs_up_file(tmp_path, monkeypatch):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text("[1, 2, 3]", encoding="utf-8")
    monkeypatch.setattr(profile_store, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(profile_store, "DATA_DIR", tmp_path)

    with pytest.raises(profile_store.ProfileLoadError):
        profile_store.load_profile()

    backups = sorted(tmp_path.glob("profile.invalid.*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "[1, 2, 3]"


def test_scoring_rules_knowledge_file_contains_sections():
    payload = json.loads(profile_store.SCORING_RULES_PATH.read_text(encoding="utf-8"))

    assert payload["kind"] == "managed_knowledge"
    assert "fit_breakdown" in payload
    assert "salary" in payload
    assert "convergence" in payload
    assert "capability_evidence" in payload
    assert payload["capability_evidence"]["max_score"] == 20


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
