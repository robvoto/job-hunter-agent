"""Tests for desktop privacy boundaries."""

from job_hunter_agent import llm_gate, profile_learning, profile_store, source_learning


def test_openai_api_key_is_ignored_in_desktop_runtime_path(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-ignored")
    monkeypatch.setenv("JOB_HUNTER_DESKTOP_MODE", "1")
    monkeypatch.setattr(llm_gate, "client", None)

    assert llm_gate._build_openai_client() is None
    assert llm_gate.llm_is_enabled() is False


def test_llm_is_disabled_when_no_user_provider_key_exists(monkeypatch):
    monkeypatch.setattr(llm_gate, "client", None)

    assert llm_gate.client is None
    assert llm_gate.llm_is_enabled() is False


def test_desktop_mode_blocks_pending_learning_signal_registration(monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_DESKTOP_MODE", "1")

    called = []
    monkeypatch.setattr(
        source_learning,
        "register_signals",
        lambda items, category="": called.append((items, category)),
    )

    source_learning.register_pending_learning_signals(
        [
            {
                "signal": "python",
                "suggested_category": "capability_concept",
                "original_texts": ["python"],
            }
        ]
    )

    assert called == []


def test_desktop_mode_blocks_cv_learning_signal_registration(monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_DESKTOP_MODE", "1")

    fixture = {
        "capabilities": [
            {
                "name": "business analysis",
                "level": "strong",
                "aliases": [],
                "icon_key": "analysis_requirements",
                "atomic_concept": True,
                "needs_review": False,
            },
            {
                "name": "unknown platform",
                "level": "working",
                "aliases": ["mystery platform"],
                "icon_key": "systems_platforms",
                "atomic_concept": True,
                "needs_review": True,
            }
        ],
        "role_titles": ["Delivery Lead"],
        "preferred_role_titles": ["Delivery Lead"],
        "alternative_role_titles": [],
        "target_occupation_queries": ["Delivery Lead"],
        "match_preferences": {},
    }

    called = []
    monkeypatch.setattr(
        profile_learning,
        "_llm_extract_from_cv",
        lambda *_args, **_kwargs: fixture,
    )
    monkeypatch.setattr(
        profile_learning,
        "signal_in_approved_knowledge",
        lambda *_args, **_kwargs: (False, ""),
    )
    monkeypatch.setattr(
        profile_learning,
        "register_signals",
        lambda items: called.append(items),
    )

    result = profile_learning.build_learning_patch("CV text")

    assert result["target_occupation_queries"] == ["Delivery Lead"]
    assert called == []


def test_desktop_mode_skips_profile_section_learning_classification(monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_DESKTOP_MODE", "1")

    assert profile_store._classify_unknown_section_label("summary", "secondary") == "secondary"
