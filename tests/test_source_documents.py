"""Tests for source documents."""

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
        lambda text, settings: {"target_roles": [], "also_consider_roles": []},
    )

    def fake_run_cv_pipeline(text, llm_client, onboarding_settings=None):
        captured["text"] = text
        captured["onboarding_settings"] = onboarding_settings
        return {"candidate_capabilities": [{"name": "delivery", "level": "working", "fit": "core"}]}

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
        lambda text, settings: {"target_roles": [], "also_consider_roles": []},
    )
    monkeypatch.setattr(
        source_documents,
        "run_cv_pipeline",
        lambda text, llm_client, onboarding_settings=None: {"candidate_capabilities": [{"name": "delivery", "level": "working"}]},
    )
    monkeypatch.setattr(
        source_documents,
        "build_learning_patch",
        lambda text, onboarding_settings=None, source_sections=None: {},
    )

    result = source_documents.run_onboarding({"profile_sources": [_CV_SOURCE]})

    assert result["ok"] is True
    assert result["profile"].get("candidate_capabilities") == []
    assert "cv_text" not in result["profile"]
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
        lambda text, settings: {"target_roles": [], "also_consider_roles": []},
    )
    monkeypatch.setattr(source_documents, "run_cv_pipeline", lambda text, llm_client, onboarding_settings=None: {})
    monkeypatch.setattr(
        source_documents,
        "build_learning_patch",
        lambda text, onboarding_settings=None, source_sections=None: {},
    )

    result = source_documents.run_onboarding({"profile_sources": [_CV_SOURCE]})

    assert result["ok"] is True
    assert result["profile"].get("candidate_capabilities") == []


def test_run_onboarding_preserves_non_capability_learning_signals(monkeypatch):
    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_roles": [], "also_consider_roles": []},
    )
    monkeypatch.setattr(source_documents, "run_cv_pipeline", lambda text, llm_client, onboarding_settings=None: {})
    monkeypatch.setattr(
        source_documents,
        "build_learning_patch",
        lambda text, onboarding_settings=None, source_sections=None: {
            "candidate_capabilities": [{"name": "delivery", "level": "working"}],
            "match_preferences": {"prefer_permanent": True, "home_location": "Sydney"},
        },
    )

    result = source_documents.run_onboarding({"profile_sources": [_CV_SOURCE]})

    assert result["ok"] is True
    assert result["profile"].get("candidate_capabilities") == [{"name": "delivery", "level": "working"}]
    assert result["profile"].get("match_preferences", {})["prefer_permanent"] is True
    assert result["profile"].get("match_preferences", {})["home_location"] == "Sydney"
    assert "cv_text" not in result["profile"]
    assert result["profile"].get("candidate_profile_tiers") == {
        "primary_candidate_profile_context": "# Professional Experience\nAcme - Platform Lead (2019 - 2024)",
        "secondary_candidate_profile_context": "",
        "supplementary_candidate_profile_context": "",
    }


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
            "candidate_capabilities": [
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


# ── target_occupation_queries population ──────────────────────────────────────

_AGILE_CV = (
    "# Professional Experience\n"
    "Tech Corp - Scrum Master (2021 - 2024)\n"
    "Led agile ceremonies, managed sprints, coached two delivery teams.\n\n"
    "Gov Agency - Agile Project Coordinator (2018 - 2021)\n"
    "Coordinated delivery across cross-functional agile teams.\n"
)
_AGILE_CV_SOURCE = {"label": "Primary CV", "filename": "cv.txt", "content": _AGILE_CV}

_AGILE_QUERIES = [
    "Scrum Master",
    "Agile Project Coordinator",
    "IT Delivery Coordinator",
    "Software Delivery Coordinator",
    "Agile Coach",
]


def _stub_onboarding(monkeypatch, cv_source, occupation_queries):
    """Wire standard onboarding stubs so tests can control LLM outputs."""
    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}})
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_roles": ["scrum master", "agile project coordinator"], "also_consider_roles": []},
    )
    monkeypatch.setattr(source_documents, "run_cv_pipeline", lambda text, llm_client, onboarding_settings=None: {})
    monkeypatch.setattr(source_documents, "build_learning_patch", lambda text, onboarding_settings=None, source_sections=None: {})
    monkeypatch.setattr(source_documents, "generate_target_occupation_queries", lambda **kwargs: occupation_queries)


def test_run_onboarding_populates_target_occupation_queries(monkeypatch):
    """Onboarding must store LLM-generated occupation queries in the profile patch."""
    _stub_onboarding(monkeypatch, _AGILE_CV_SOURCE, _AGILE_QUERIES)

    result = source_documents.run_onboarding({"profile_sources": [_AGILE_CV_SOURCE]})

    assert result["ok"] is True
    assert result["profile"].get("target_occupation_queries") == _AGILE_QUERIES


def test_run_onboarding_occupation_queries_reset_on_fresh_run(monkeypatch):
    """Each onboarding run must replace any previously stored queries."""
    _stub_onboarding(monkeypatch, _AGILE_CV_SOURCE, ["Business Analyst"])

    result = source_documents.run_onboarding({"profile_sources": [_AGILE_CV_SOURCE]})

    assert result["profile"].get("target_occupation_queries") == ["Business Analyst"]


def test_run_onboarding_stores_empty_list_when_llm_returns_none(monkeypatch):
    """A failed or skipped LLM call must store [] not None."""
    _stub_onboarding(monkeypatch, _AGILE_CV_SOURCE, [])

    result = source_documents.run_onboarding({"profile_sources": [_AGILE_CV_SOURCE]})

    assert result["profile"].get("target_occupation_queries") == []


def test_generate_target_occupation_queries_returns_empty_without_client():
    """Without an LLM client the function must return [] without raising."""
    from job_hunter_agent.llm_gate import generate_target_occupation_queries
    result = generate_target_occupation_queries(
        target_roles=["scrum master"],
        also_consider_roles=[],
        cv_text="Some CV text",
        llm_client=None,
    )
    assert result == []


def test_generate_target_occupation_queries_parses_llm_response():
    """The function must parse a JSON array from the LLM and return cleaned strings."""
    from job_hunter_agent.llm_gate import generate_target_occupation_queries

    class _FakeResp:
        output_text = '["Scrum Master", "Agile Project Coordinator", "IT Delivery Coordinator"]'
        usage = None

    class _FakeClient:
        class responses:
            @staticmethod
            def create(**kwargs):
                return _FakeResp()

    result = generate_target_occupation_queries(
        target_roles=["scrum master"],
        also_consider_roles=[],
        cv_text="",
        llm_client=_FakeClient(),
    )
    assert result == ["Scrum Master", "Agile Project Coordinator", "IT Delivery Coordinator"]


def test_generate_target_occupation_queries_handles_bad_llm_response():
    """A non-JSON or non-list LLM response must return [] without raising."""
    from job_hunter_agent.llm_gate import generate_target_occupation_queries

    class _FakeResp:
        output_text = "Sorry, I cannot help with that."
        usage = None

    class _FakeClient:
        class responses:
            @staticmethod
            def create(**kwargs):
                return _FakeResp()

    result = generate_target_occupation_queries(
        target_roles=["scrum master"],
        also_consider_roles=[],
        cv_text="",
        llm_client=_FakeClient(),
    )
    assert result == []
