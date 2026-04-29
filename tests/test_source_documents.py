from job_hunter_agent import llm_gate
from job_hunter_agent import source_documents


def test_build_llm_profile_brief_ignores_malformed_capability_rules():
    brief = source_documents.build_llm_profile_brief(
        capability_rules=[
            {"name": "process mapping", "level": "strong", "fit": "core"},
            None,
            "bad",
            {"name": "", "level": "working"},
        ]
    )

    assert "process mapping (strong, core)" in brief


def test_build_llm_profile_brief_handles_non_list_input():
    assert source_documents.build_llm_profile_brief(capability_rules="bad") == ""
    assert source_documents.build_llm_profile_brief(capability_rules=None) == ""


def test_run_onboarding_passes_configured_settings_to_pipeline(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("# Professional Experience\nAcme - Platform Lead (2019 - 2024)\n", encoding="utf-8")

    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(source_documents, "extract_location_hint", lambda text: "")
    monkeypatch.setattr(source_documents, "_extract_match_preferences", lambda text: {})
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_title_patterns": [], "secondary_title_patterns": [], "suggested_search_keywords": []},
    )

    def fake_run_cv_pipeline(text, llm_client, onboarding_settings=None):
        captured["text"] = text
        captured["onboarding_settings"] = onboarding_settings
        return {"capability_profile_rules": [{"name": "delivery", "level": "working", "fit": "core"}]}

    monkeypatch.setattr(source_documents, "run_cv_pipeline", fake_run_cv_pipeline)

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "path": str(cv_path)}]},
        onboarding_settings={"extraction_lookback_years": 12, "title_extraction_min_months": 6},
    )

    assert result["ok"] is True
    assert captured["onboarding_settings"] == {"extraction_lookback_years": 12, "title_extraction_min_months": 6}


def test_run_onboarding_does_not_restore_legacy_capability_rules_when_pipeline_returns_none(monkeypatch, tmp_path):
    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("# Professional Experience\nAcme - Platform Lead (2019 - 2024)\n", encoding="utf-8")

    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(source_documents, "extract_location_hint", lambda text: "")
    monkeypatch.setattr(source_documents, "_extract_match_preferences", lambda text: {})
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_title_patterns": [], "secondary_title_patterns": [], "suggested_search_keywords": []},
    )
    monkeypatch.setattr(source_documents, "run_cv_pipeline", lambda text, llm_client, onboarding_settings=None: {})

    result = source_documents.run_onboarding({"profile_sources": [{"label": "Primary CV", "path": str(cv_path)}]})

    assert result["ok"] is True
    assert result["profile"].get("capability_profile_rules") == []


def test_run_onboarding_preserves_non_capability_learning_signals(monkeypatch, tmp_path):
    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("# Professional Experience\nAcme - Platform Lead (2019 - 2024)\n", encoding="utf-8")

    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(source_documents, "extract_location_hint", lambda text: "")
    monkeypatch.setattr(source_documents, "_extract_match_preferences", lambda text: {})
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_title_patterns": [], "secondary_title_patterns": [], "suggested_search_keywords": []},
    )
    monkeypatch.setattr(source_documents, "run_cv_pipeline", lambda text, llm_client, onboarding_settings=None: {})
    monkeypatch.setattr(
        source_documents,
        "build_learning_patch",
        lambda text, onboarding_settings=None: {
            "cv_text": text,
            "capability_profile_rules": [{"name": "delivery", "level": "working"}],
            "match_preferences": {"prefer_permanent": True, "home_location": "Sydney"},
        },
    )

    result = source_documents.run_onboarding({"profile_sources": [{"label": "Primary CV", "path": str(cv_path)}]})

    assert result["ok"] is True
    assert result["profile"].get("capability_profile_rules") == [{"name": "delivery", "level": "working"}]
    assert result["profile"].get("match_preferences", {})["prefer_permanent"] is True
    assert result["profile"].get("match_preferences", {})["home_location"] == "Sydney"


def test_build_profile_prompt_context_ignores_malformed_capability_rules(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "llm_profile_brief": "",
            "star_evidence_text": "",
            "capability_profile_rules": [
                {"name": "process mapping", "level": "strong", "fit": "core", "aliases": ["process design"]},
                "bad",
                {"name": "stakeholder engagement", "level": "working", "aliases": "not-a-list"},
            ],
            "salary_preferences": {},
            "match_preferences": {},
        },
    )
    monkeypatch.setattr(llm_gate, "get_evidence_tiers", lambda profile: {})
    monkeypatch.setattr(llm_gate, "get_evidence_tier_weights", lambda profile: {})

    context = llm_gate.build_profile_prompt_context()

    assert "process mapping: strong, core (process design)" in context
    assert "stakeholder engagement: working" in context


def test_build_system_prompt_includes_user_fit_review_guidance(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "llm_profile_brief": "",
            "llm_fit_review_guidance": "Be open to adjacent delivery roles when the responsibilities are close.",
            "llm_capability_naming_guidance": "",
            "star_evidence_text": "",
            "capability_profile_rules": [],
            "salary_preferences": {},
            "match_preferences": {},
        },
    )
    monkeypatch.setattr(llm_gate, "get_evidence_tiers", lambda profile: {})
    monkeypatch.setattr(llm_gate, "get_evidence_tier_weights", lambda profile: {})

    prompt = llm_gate.build_system_prompt()

    assert "User fit review guidance:" in prompt
    assert "Be open to adjacent delivery roles when the responsibilities are close." in prompt


def test_build_system_prompt_includes_managed_default_fit_review_guidance(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "llm_profile_brief": "",
            "llm_fit_review_guidance": "",
            "llm_capability_naming_guidance": "",
            "star_evidence_text": "",
            "capability_profile_rules": [],
            "salary_preferences": {},
            "match_preferences": {},
        },
    )
    monkeypatch.setattr(llm_gate, "get_evidence_tiers", lambda profile: {})
    monkeypatch.setattr(llm_gate, "get_evidence_tier_weights", lambda profile: {})

    prompt = llm_gate.build_system_prompt()

    assert "Default fit review guidance:" in prompt
    assert "Grade the full description fit, not just keyword overlap." in prompt


def test_build_capability_naming_guidance_includes_user_guidance(monkeypatch):
    monkeypatch.setattr(
        llm_gate,
        "load_profile",
        lambda: {
            "llm_capability_naming_guidance": "Prefer labels close to business analysis and delivery work.",
        },
    )

    prompt = llm_gate.build_capability_naming_guidance()

    assert "Default capability naming guidance:" in prompt
    assert "User capability naming guidance:" in prompt
    assert "Prefer labels close to business analysis and delivery work." in prompt
