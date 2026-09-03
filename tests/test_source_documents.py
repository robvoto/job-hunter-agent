"""Tests for source documents."""

import pytest

from job_hunter_agent import profile_learning, source_documents
from job_hunter_agent.utils import deep_merge


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
                    "atomic_concept": True,
                    "needs_review": False,
                },
                {
                    "name": "stakeholder communication",
                    "level": "working",
                    "aliases": [],
                    "icon_key": "communication_stakeholders",
                    "atomic_concept": True,
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
            "match_preferences": {},
        }

    monkeypatch.setattr(profile_learning, "_llm_extract_from_cv", fake_extract_from_cv)

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": _CV_CONTENT}]}
    )

    assert result["ok"] is True
    assert "Scrum Master\nCompany Name | 2022 - Present" in str(captured["text"])
    assert result["profile"].get("target_roles", []) == []
    assert result["profile"].get("also_consider_roles", []) == []
    assert result["role_suggestions"] == {
        "target_roles": ["scrum master"],
        "also_consider_roles": ["agile project coordinator"],
    }
    assert result["profile"]["role_experience"] == [
                    {
                        "normalized_title": "agile project coordinator",
            "total_duration_months": 24,
            "most_recent_end_year": 2022,
            "segments": [{"duration_months": 24, "is_current": False}],
            "title_variants": [
                {
                    "title": "Agile Project Coordinator",
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
            "segments": [{"duration_months": 24, "is_current": True}],
            "title_variants": [
                {
                    "title": "Scrum Master",
                    "normalized_title": "scrum master",
                    "total_duration_months": 24,
                    "most_recent_end_year": 2026,
                }
            ],
        },
    ]
    assert result["profile"]["candidate_capabilities"]
    assert result["profile"]["candidate_capabilities"][0]["name"] == "agile delivery"


def test_cv_role_suggestions_do_not_become_targets_before_user_selection(monkeypatch):
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
        lambda text, lookback_years, alias_limit: {
            "capabilities": [
                {
                    "name": "data analysis",
                    "level": "working",
                    "aliases": [],
                    "icon_key": "data_reporting",
                    "atomic_concept": True,
                    "needs_review": False,
                }
            ],
            "role_titles": ["Data Analyst"],
            "preferred_role_titles": ["Data Analyst"],
            "alternative_role_titles": [],
            "match_preferences": {},
        },
    )

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": "Data Analyst"}]}
    )

    assert result["role_suggestions"]["target_roles"] == ["data analyst"]
    assert result["profile"].get("target_roles", []) == []
    assert result["profile"].get("also_consider_roles", []) == []


def test_onboarding_rebuild_preserves_confirmed_roles_until_review_confirm(monkeypatch):
    current_profile = {
        "target_roles": ["business analyst"],
        "also_consider_roles": ["systems analyst"],
        "search_settings": {},
        "match_preferences": {},
        "onboarding_settings": {},
    }

    def fake_patch_profile(patch):
        nonlocal current_profile
        current_profile = deep_merge(current_profile, patch)
        return current_profile

    monkeypatch.setattr(source_documents, "load_profile", lambda: current_profile)
    monkeypatch.setattr(source_documents, "patch_profile", fake_patch_profile)
    monkeypatch.setattr(source_documents, "clear_onboarding_runtime_outputs", lambda: None)
    monkeypatch.setattr(
        profile_learning,
        "_llm_extract_from_cv",
        lambda text, lookback_years, alias_limit: {
            "capabilities": [
                {
                    "name": "data analysis",
                    "level": "working",
                    "aliases": [],
                    "icon_key": "data_reporting",
                    "atomic_concept": True,
                    "needs_review": False,
                }
            ],
            "role_titles": ["Data Analyst"],
            "preferred_role_titles": ["Data Analyst"],
            "alternative_role_titles": [],
            "match_preferences": {},
        },
    )

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": "Data Analyst"}]}
    )

    assert result["role_suggestions"] == {
        "target_roles": ["data analyst"],
        "also_consider_roles": [],
    }
    assert result["profile"]["target_roles"] == ["business analyst"]
    assert result["profile"]["also_consider_roles"] == ["systems analyst"]


def test_onboarding_extraction_failure_does_not_erase_confirmed_roles(monkeypatch):
    current_profile = {
        "target_roles": ["business analyst"],
        "also_consider_roles": ["systems analyst"],
        "search_settings": {},
        "match_preferences": {},
        "onboarding_settings": {},
    }
    applied_patches = []

    def fake_patch_profile(patch):
        nonlocal current_profile
        applied_patches.append(patch)
        current_profile = deep_merge(current_profile, patch)
        return current_profile

    def fail_learning_patch(*args, **kwargs):
        raise RuntimeError("simulated extraction failure")

    monkeypatch.setattr(source_documents, "load_profile", lambda: current_profile)
    monkeypatch.setattr(source_documents, "patch_profile", fake_patch_profile)
    monkeypatch.setattr(source_documents, "clear_onboarding_runtime_outputs", lambda: None)
    monkeypatch.setattr(source_documents, "build_learning_patch", fail_learning_patch)

    with pytest.raises(RuntimeError, match="simulated extraction failure"):
        source_documents.run_onboarding(
            {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": "CV"}]}
        )

    assert len(applied_patches) == 1
    assert "target_roles" not in applied_patches[0]
    assert "also_consider_roles" not in applied_patches[0]
    assert current_profile["target_roles"] == ["business analyst"]
    assert current_profile["also_consider_roles"] == ["systems analyst"]


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
                        "atomic_concept": True,
                        "needs_review": False,
                    },
                ],
                "role_titles": [],
                "preferred_role_titles": [],
                "alternative_role_titles": [],
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


def test_refresh_role_history_from_saved_cv_only_touches_role_experience(monkeypatch):
    """The targeted refresh re-extracts role_experience with segments and leaves
    every other profile section exactly as it was."""
    starting_profile = {
        "candidate_capabilities": [
            {"name": "stakeholder engagement", "level": "strong", "aliases": []}
        ],
        "candidate_eligibility": [{"name": "PV clearance", "value": True}],
        "candidate_qualifications": [{"name": "CBAP", "held": True}],
        "match_preferences": {"work_mode_preference": "hybrid"},
        "onboarding_settings": {},
        "role_experience": [
            {
                "normalized_title": "business analyst",
                "total_duration_months": 24,
                "segments": [{"duration_months": 24, "is_current": False}],
            }
        ],
    }
    applied_patches: list[dict] = []

    def fake_patch_profile(patch):
        applied_patches.append(patch)
        return deep_merge(starting_profile, patch)

    monkeypatch.setattr(
        source_documents,
        "load_source_materials",
        lambda create_if_missing=False: {
            "profile_sources": [
                {"label": "Primary CV", "filename": "cv.txt", "content": _CV_CONTENT}
            ]
        },
    )
    monkeypatch.setattr(source_documents, "normalize_source_materials", lambda payload: payload)
    monkeypatch.setattr(source_documents, "load_profile", lambda: starting_profile)
    monkeypatch.setattr(source_documents, "patch_profile", fake_patch_profile)
    monkeypatch.setattr(
        profile_learning,
        "_llm_extract_from_cv",
        lambda text, lookback_years, alias_limit: {
            "capabilities": [
                {
                    "name": "agile delivery",
                    "level": "strong",
                    "aliases": [],
                    "icon_key": "delivery_project",
                    "atomic_concept": True,
                    "needs_review": False,
                }
            ],
            "role_experience": [
                {"title": "Business Analyst", "duration_months": 30, "end_year": 2022},
                {
                    "title": "Business Analyst",
                    "duration_months": 18,
                    "end_year": 2026,
                    "is_current": True,
                },
            ],
            "role_titles": ["Business Analyst"],
            "preferred_role_titles": ["Business Analyst"],
            "alternative_role_titles": [],
            "match_preferences": {},
        },
    )

    result = source_documents.refresh_role_history_from_saved_cv()

    assert result["ok"] is True
    # Only role_experience is patched.
    assert [set(patch) for patch in applied_patches] == [{"role_experience"}]

    rows = result["role_experience"]
    assert len(rows) == 1
    assert rows[0]["normalized_title"] == "business analyst"
    assert rows[0]["segments"] == [
        {"duration_months": 30, "is_current": False},
        {"duration_months": 18, "is_current": True},
    ]

    # Every other section is untouched.
    updated = result["profile"]
    assert updated["candidate_capabilities"] == starting_profile["candidate_capabilities"]
    assert updated["candidate_eligibility"] == starting_profile["candidate_eligibility"]
    assert updated["candidate_qualifications"] == starting_profile["candidate_qualifications"]
    assert updated["match_preferences"] == starting_profile["match_preferences"]
