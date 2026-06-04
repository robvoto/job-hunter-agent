"""Tests for source documents."""

import pytest

from job_hunter_agent import profile_learning
from job_hunter_agent import source_documents


@pytest.fixture(autouse=True)
def _stub_cv_chars_per_page(monkeypatch):
    monkeypatch.setattr(source_documents, "get_cv_chars_per_page", lambda: 4000)


_CV_CONTENT = """
# Professional Experience
Scrum Master
Company Name | 2022 - Present
- Facilitated Agile ceremonies and delivery coordination.

Agile Project Coordinator
Company Name | 2020 - 2022
- Supported backlog refinement and sprint reporting.
"""


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


def test_run_onboarding_uses_llm_titles_without_parser(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        source_documents,
        "load_profile",
        lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}},
    )
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(source_documents, "clear_onboarding_runtime_outputs", lambda: None)
    monkeypatch.setattr(source_documents, "clear_capability_debug_log", lambda: None)

    def fake_extract_from_cv(text, lookback_years, alias_limit):
        captured["text"] = text
        captured["lookback_years"] = lookback_years
        captured["alias_limit"] = alias_limit
        return {
            "capabilities": [
                {"name": "agile delivery", "level": "strong", "aliases": ["scrum"], "icon_key": "delivery_project", "needs_review": False},
                {"name": "stakeholder communication", "level": "working", "aliases": [], "icon_key": "communication_stakeholders", "needs_review": False},
            ],
            "role_titles": ["Scrum Master", "Agile Project Coordinator"],
            "target_occupation_queries": ["Scrum Master", "Agile Project Coordinator"],
            "match_preferences": {},
        }

    monkeypatch.setattr(profile_learning, "_llm_extract_from_cv", fake_extract_from_cv)

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": _CV_CONTENT}]}
    )

    assert result["ok"] is True
    assert "Scrum Master\nCompany Name | 2022 - Present" in str(captured["text"])
    assert result["profile"]["target_roles"] == ["scrum master", "agile project coordinator"]
    assert result["profile"]["target_occupation_queries"] == ["Scrum Master", "Agile Project Coordinator"]
    assert result["profile"]["candidate_capabilities"]
    assert result["profile"]["candidate_capabilities"][0]["name"] == "agile delivery"


@pytest.mark.parametrize(
    "fixture, expected",
    [
        (
            {
                "capabilities": [
                    {"name": "agile delivery", "level": "strong", "aliases": [], "icon_key": "delivery_project", "needs_review": False},
                ],
                "role_titles": [],
                "target_occupation_queries": ["Scrum Master"],
                "match_preferences": {},
            },
            "role titles",
        ),
        (
            {
                "capabilities": [],
                "role_titles": ["Scrum Master"],
                "target_occupation_queries": ["Scrum Master"],
                "match_preferences": {},
            },
            "capability groups",
        ),
    ],
)
def test_run_onboarding_fails_when_llm_omits_required_fields(monkeypatch, fixture, expected):
    monkeypatch.setattr(
        source_documents,
        "load_profile",
        lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}},
    )
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(source_documents, "clear_onboarding_runtime_outputs", lambda: None)
    monkeypatch.setattr(source_documents, "clear_capability_debug_log", lambda: None)
    monkeypatch.setattr(
        profile_learning,
        "_llm_extract_from_cv",
        lambda text, lookback_years, alias_limit: fixture,
    )

    with pytest.raises(ValueError, match=expected):
        source_documents.run_onboarding(
            {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": _CV_CONTENT}]}
        )
