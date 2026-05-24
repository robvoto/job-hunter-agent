import pytest

from job_hunter_agent import llm_gate
from job_hunter_agent import source_documents


@pytest.fixture(autouse=True)
def _stub_cv_chars_per_page(monkeypatch):
    monkeypatch.setattr(source_documents, "get_cv_chars_per_page", lambda: 4000)


def test_build_llm_profile_brief_ignores_malformed_capability_rules():
    brief = source_documents.build_llm_profile_brief(
        capability_rules=[
            {"name": "process mapping", "level": "strong", "fit": "core"},
            None,
            "bad",
            {"name": "", "level": "working"},
        ]
    )

    assert "process mapping (strong)" in brief


def test_build_llm_profile_brief_handles_non_list_input():
    assert source_documents.build_llm_profile_brief(capability_rules="bad") == ""
    assert source_documents.build_llm_profile_brief(capability_rules=None) == ""


_CV_CONTENT = "# Professional Experience\nAcme - Platform Lead (2019 - 2024)\n"
_CV_SOURCE = {"label": "Primary CV", "filename": "cv.txt", "content": _CV_CONTENT}


def test_run_onboarding_passes_configured_settings_to_pipeline(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_roles": [], "also_consider_roles": [], "suggested_search_keywords": []},
    )

    def fake_run_cv_pipeline(text, llm_client, onboarding_settings=None):
        captured["text"] = text
        captured["onboarding_settings"] = onboarding_settings
        return {"capability_profile_rules": [{"name": "delivery", "level": "working", "fit": "core"}]}

    monkeypatch.setattr(source_documents, "run_cv_pipeline", fake_run_cv_pipeline)

    result = source_documents.run_onboarding(
        {"profile_sources": [_CV_SOURCE]},
        onboarding_settings={"extraction_lookback_years": 12, "title_extraction_min_months": 6},
    )

    assert result["ok"] is True
    assert captured["onboarding_settings"]["extraction_lookback_years"] == 12
    assert captured["onboarding_settings"]["title_extraction_min_months"] == 6


def test_run_onboarding_ignores_pipeline_capability_rules(monkeypatch):
    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_roles": [], "also_consider_roles": [], "suggested_search_keywords": []},
    )
    monkeypatch.setattr(
        source_documents,
        "run_cv_pipeline",
        lambda text, llm_client, onboarding_settings=None: {"capability_profile_rules": [{"name": "delivery", "level": "working"}]},
    )
    monkeypatch.setattr(
        source_documents,
        "build_learning_patch",
        lambda text, onboarding_settings=None, source_sections=None: {},
    )

    result = source_documents.run_onboarding({"profile_sources": [_CV_SOURCE]})

    assert result["ok"] is True
    assert result["profile"].get("capability_profile_rules") == []
    assert result["profile"].get("cv_text")
    assert result["profile"].get("candidate_profile_tiers") == {
        "primary_candidate_profile_context": "# Professional Experience\nAcme - Platform Lead (2019 - 2024)",
        "secondary_candidate_profile_context": "",
        "supplementary_candidate_profile_context": "",
    }


def test_run_onboarding_does_not_restore_legacy_capability_rules_when_pipeline_returns_none(monkeypatch):
    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_roles": [], "also_consider_roles": [], "suggested_search_keywords": []},
    )
    monkeypatch.setattr(source_documents, "run_cv_pipeline", lambda text, llm_client, onboarding_settings=None: {})
    monkeypatch.setattr(
        source_documents,
        "build_learning_patch",
        lambda text, onboarding_settings=None, source_sections=None: {},
    )

    result = source_documents.run_onboarding({"profile_sources": [_CV_SOURCE]})

    assert result["ok"] is True
    assert result["profile"].get("capability_profile_rules") == []


def test_run_onboarding_preserves_non_capability_learning_signals(monkeypatch):
    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_roles": [], "also_consider_roles": [], "suggested_search_keywords": []},
    )
    monkeypatch.setattr(source_documents, "run_cv_pipeline", lambda text, llm_client, onboarding_settings=None: {})
    monkeypatch.setattr(
        source_documents,
        "build_learning_patch",
        lambda text, onboarding_settings=None, source_sections=None: {
            "capability_profile_rules": [{"name": "delivery", "level": "working"}],
            "match_preferences": {"prefer_permanent": True, "home_location": "Sydney"},
        },
    )

    result = source_documents.run_onboarding({"profile_sources": [_CV_SOURCE]})

    assert result["ok"] is True
    assert result["profile"].get("capability_profile_rules") == [{"name": "delivery", "level": "working"}]
    assert result["profile"].get("match_preferences", {})["prefer_permanent"] is True
    assert result["profile"].get("match_preferences", {})["home_location"] == "Sydney"
    assert result["profile"].get("cv_text")
    assert result["profile"].get("candidate_profile_tiers") == {
        "primary_candidate_profile_context": "# Professional Experience\nAcme - Platform Lead (2019 - 2024)",
        "secondary_candidate_profile_context": "",
        "supplementary_candidate_profile_context": "",
    }


def test_run_onboarding_routes_uncertain_role_titles_to_signals(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {
            "target_roles": ["platform lead"],
            "also_consider_roles": ["delivery analyst"],
            "suggested_search_keywords": ["platform lead"],
        },
    )
    monkeypatch.setattr(
        source_documents,
        "build_role_title_review_signals",
        lambda titles, source_sections=None: [
            {
                "signal": "Delivery Analyst",
                "category": "role_title_token",
                "source": "CV parsing",
                "context": ["Experience: Delivery Analyst"],
                "evidence": ["Delivery Analyst"],
                "needs_review": True,
            }
        ],
    )
    monkeypatch.setattr(source_documents, "register_signals", lambda items: captured.setdefault("signals", items))
    monkeypatch.setattr(source_documents, "run_cv_pipeline", lambda text, llm_client, onboarding_settings=None: {})
    monkeypatch.setattr(source_documents, "build_learning_patch", lambda text, onboarding_settings=None, source_sections=None: {"capability_profile_rules": []})

    result = source_documents.run_onboarding({"profile_sources": [_CV_SOURCE]})

    assert result["ok"] is True
    assert captured["signals"] == [
        {
            "signal": "Delivery Analyst",
            "category": "role_title_token",
            "source": "CV parsing",
            "context": ["Experience: Delivery Analyst"],
            "evidence": ["Delivery Analyst"],
            "needs_review": True,
        }
    ]


def test_merge_capability_rules_preserves_jira_confluence_cluster_for_review(monkeypatch):
    """Regression: multi-product clusters must not be lost or merged into the wrong product."""
    registered: list = []
    monkeypatch.setattr(source_documents, "register_signals", lambda items: registered.extend(items))

    capability_rules = [{"name": "Jira", "level": "strong", "aliases": ["Jira Software"]}]
    dominant_signal_clusters = [
        {
            "name": "Jira Confluence",
            "aliases": ["jira confluence", "Confluence"],
            "level": "strong",
            "needs_review": True,
        }
    ]

    result = source_documents.merge_capability_rules_with_dominant_signals(
        capability_rules, dominant_signal_clusters
    )

    assert len(result) == 1
    assert result[0]["name"] == "Jira"
    aliases_norm = [a.lower() for a in result[0]["aliases"]]
    assert "confluence" not in aliases_norm
    assert any(r.get("signal") == "Jira Confluence" for r in registered)


def test_merge_capability_rules_registers_unmatched_cluster(monkeypatch):
    registered: list = []
    monkeypatch.setattr(source_documents, "register_signals", lambda items: registered.extend(items))

    capability_rules = [{"name": "Python", "level": "strong", "aliases": []}]
    dominant_signal_clusters = [
        {"name": "Jira Confluence", "aliases": ["Confluence"], "level": "working", "needs_review": True}
    ]

    result = source_documents.merge_capability_rules_with_dominant_signals(
        capability_rules, dominant_signal_clusters
    )

    assert len(result) == 1
    assert result[0]["name"] == "Python"
    assert any(r.get("signal") == "Jira Confluence" for r in registered)


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
    monkeypatch.setattr(llm_gate, "get_candidate_profile_tiers", lambda profile: {})
    monkeypatch.setattr(llm_gate, "get_candidate_profile_tier_weights", lambda profile: {})

    context = llm_gate.build_profile_prompt_context()

    assert "process mapping: strong, core (process design)" in context
    assert "stakeholder engagement: working" in context
