"""Tests for repo health."""

import importlib
from pathlib import Path

from job_hunter_agent import profile_store
from job_hunter_agent.global_settings import KEY_LINKEDIN_EASY_APPLY_ONLY
from job_hunter_agent.profile_store import (
    DEFAULT_PROFILE,
    DEFAULT_SEARCH_SETTINGS,
    normalize_search_settings,
    normalize_work_mode_preferences,
)

ROOT_DIR = Path(__file__).resolve().parent.parent


def test_no_legacy_directory_remains():

    assert not (ROOT_DIR / "legacy").exists()


def test_default_search_settings_are_candidate_agnostic():

    assert DEFAULT_SEARCH_SETTINGS["keywords"] == ""

    assert DEFAULT_SEARCH_SETTINGS["locations"] == []

    assert DEFAULT_SEARCH_SETTINGS["classification_ids"] == []

    assert DEFAULT_SEARCH_SETTINGS["seek_max_pages"] > 0


def test_search_settings_clamp_source_fetch_limits():

    normalized = normalize_search_settings(
        {
            "seek_max_pages": 100,
            "linkedin_hours_old": 999,
            "linkedin_results_per_search": 1,
            KEY_LINKEDIN_EASY_APPLY_ONLY: "false",
        }
    )

    assert (
        normalized["seek_max_pages"]
        == profile_store.load_global_settings()["limits"]["search"]["seek_max_pages"]["max"]
    )

    assert (
        normalized["linkedin_hours_old"]
        == profile_store.load_global_settings()["limits"]["search"]["linkedin_hours_old"]["max"]
    )

    assert normalized["linkedin_results_per_search"] == 5

    assert normalized[KEY_LINKEDIN_EASY_APPLY_ONLY] is False


def test_search_settings_follow_managed_search_limits(monkeypatch):

    monkeypatch.setattr(
        profile_store,
        "load_global_settings",
        lambda: {
            "limits": {
                "search": {
                    "date_range_days": {"min": 1, "max": 9},
                    "seek_max_pages": {"min": 1, "max": 12},
                    "linkedin_hours_old": {"min": 1, "max": 72},
                    "linkedin_results_per_search": {"min": 5, "max": 40},
                }
            }
        },
    )

    normalized = profile_store.normalize_search_settings(
        {
            "seek_max_pages": 100,
            "date_range_days": 99,
            "linkedin_hours_old": 999,
            "linkedin_results_per_search": 1,
        }
    )

    assert normalized["seek_max_pages"] == 12

    assert normalized["date_range_days"] == 9

    assert normalized["linkedin_hours_old"] == 72

    assert normalized["linkedin_results_per_search"] == 5


def test_default_match_preferences_are_neutral():

    prefs = DEFAULT_PROFILE["match_preferences"]

    assert prefs["home_location"] == ""

    assert prefs["secondary_location"] == ""

    assert prefs["work_mode_preference"] == ["remote", "hybrid", "onsite"]

    assert prefs["prefer_sector"] == []

    assert prefs["prefer_permanent"] is False

    assert normalize_work_mode_preferences([]) == []


def test_candidate_application_history_defaults_do_not_ship_personal_sheet_config():

    import json

    settings_path = ROOT_DIR / "data" / "config" / "global_settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8-sig"))
    history_settings = settings["candidate_application_history"]

    assert history_settings["enabled"] is True
    assert history_settings["source_type"] == "local_runtime_json"
    assert history_settings["sync_before_run"] is False
    assert history_settings["spreadsheet_id"] == ""
    assert history_settings["tab_name"] == ""


def test_active_modules_import():

    modules = [
        "job_hunter_agent.agent_runner",
        "job_hunter_agent.capability_matching",
        "job_hunter_agent.config",
        "job_hunter_agent.cv_pipeline",
        "job_hunter_agent.description_trust",
        "job_hunter_agent.fastapi_app",
        "job_hunter_agent.filters",
        "job_hunter_agent.fit_scoring",
        "job_hunter_agent.history",
        "job_hunter_agent.llm_gate",
        "job_hunter_agent.preferences",
        "job_hunter_agent.profile_learning",
        "job_hunter_agent.profile_store",
        "job_hunter_agent.review_insights",
        "job_hunter_agent.salary",
        "job_hunter_agent.scrape_finalize",
        "job_hunter_agent.scrapers.base",
        "job_hunter_agent.scrapers.linkedin",
        "job_hunter_agent.scrapers.seek",
        "job_hunter_agent.scrapers.seek_runner",
        "job_hunter_agent.server_helpers",
        "job_hunter_agent.signal_registry",
        "job_hunter_agent.source_connector",
        "job_hunter_agent.source_documents",
        "job_hunter_agent.user_settings",
        "job_hunter_agent.utils",
        "job_hunter_agent.workspace_rebuild_service",
        "job_hunter_agent.workspace_refresh_service",
        "job_hunter_agent.workspace_service",
        "job_hunter_agent.routes.onboarding_api",
        "job_hunter_agent.routes.pages",
        "job_hunter_agent.routes.signals",
        "job_hunter_agent.routes.workspace_api",
    ]

    for module in modules:
        importlib.import_module(module)
