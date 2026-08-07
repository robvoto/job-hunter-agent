"""Tests for source documents."""

import pytest

from job_hunter_agent import profile_learning, source_documents


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

def test_run_onboarding_uses_llm_titles_without_parser(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        source_documents,
        "load_profile",
        lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {}},
    )
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(source_documents, "clear_onboarding_runtime_outputs", lambda: None)

    def fake_extract_from_cv(text, lookback_years, alias_limit):
        captured["text"] = text
        captured["lookback_years"] = lookback_years
        captured["alias_limit"] = alias_limit
        return {
            "capabilities": [
                {
                    "name": "agile delivery",
                    "level": "strong",
                    "aliases": ["scrum"],
                    "icon_key": "delivery_project",
                    "needs_review": False,
                },
                {
                    "name": "stakeholder communication",
                    "level": "working",
                    "aliases": [],
                    "icon_key": "communication_stakeholders",
                    "needs_review": False,
                },
            ],
            "role_experience": [
                {
                    "title": "Scrum Master",
                    "duration_months": 24,
                    "end_year": 2026,
                    "is_current": True,
                },
                {"title": "Agile Project Coordinator", "duration_months": 24, "end_year": 2022},
            ],
            "role_titles": ["Scrum Master", "Agile Project Coordinator"],
            "preferred_role_titles": ["Scrum Master"],
            "alternative_role_titles": ["Agile Project Coordinator"],
            "target_occupation_queries": ["Scrum Master", "Agile Project Coordinator"],
            "match_preferences": {},
        }

    monkeypatch.setattr(profile_learning, "_llm_extract_from_cv", fake_extract_from_cv)

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": _CV_CONTENT}]}
    )

    assert result["ok"] is True
    assert "Scrum Master\nCompany Name | 2022 - Present" in str(captured["text"])
    assert result["profile"]["target_roles"] == ["scrum master"]
    assert result["profile"]["also_consider_roles"] == ["agile project coordinator"]
    assert result["profile"]["target_occupation_queries"] == [
        "Scrum Master",
        "Agile Project Coordinator",
    ]
    assert result["profile"]["role_experience"] == [
        {
            "normalized_title": "agile project coordinator",
            "total_duration_months": 24,
            "most_recent_end_year": 2022,
            "title_variants": [
                {
                    "normalized_title": "agile project coordinator",
                    "total_duration_months": 24,
                    "most_recent_end_year": 2022,
                }
            ],
        },
        {
            "normalized_title": "scrum master",
            "total_duration_months": 24,
            "most_recent_end_year": 2026,
            "title_variants": [
                {
                    "normalized_title": "scrum master",
                    "total_duration_months": 24,
                    "most_recent_end_year": 2026,
                }
            ],
        },
    ]
    assert result["profile"]["candidate_capabilities"]
    assert result["profile"]["candidate_capabilities"][0]["name"] == "agile delivery"


@pytest.mark.parametrize(
    "fixture, expected",
    [
        (
            {
                "capabilities": [
                    {
                        "name": "agile delivery",
                        "level": "strong",
                        "aliases": [],
                        "icon_key": "delivery_project",
                        "needs_review": False,
                    },
                ],
                "role_titles": [],
                "preferred_role_titles": [],
                "alternative_role_titles": [],
                "target_occupation_queries": ["Scrum Master"],
                "match_preferences": {},
            },
            "role titles, preferred role titles",
        ),
        (
            {
                "capabilities": [],
                "role_titles": ["Scrum Master"],
                "preferred_role_titles": ["Scrum Master"],
                "alternative_role_titles": [],
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
    monkeypatch.setattr(
        profile_learning,
        "_llm_extract_from_cv",
        lambda text, lookback_years, alias_limit: fixture,
    )

    with pytest.raises(ValueError, match=expected):
        source_documents.run_onboarding(
            {
                "profile_sources": [
                    {"label": "Primary CV", "filename": "cv.txt", "content": _CV_CONTENT}
                ]
            }
        )
