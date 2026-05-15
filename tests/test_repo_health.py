from pathlib import Path
import importlib

from job_hunter_agent.global_settings import KEY_LINKEDIN_EASY_APPLY_ONLY
from job_hunter_agent.profile_store import DEFAULT_PROFILE, DEFAULT_SEARCH_SETTINGS, normalize_search_settings
from job_hunter_agent import profile_store


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

    assert normalized["seek_max_pages"] == DEFAULT_SEARCH_SETTINGS["seek_max_pages"]
    assert normalized["linkedin_hours_old"] == profile_store.load_global_settings()["search_limits"]["linkedin_hours_old"]["max"]
    assert normalized["linkedin_results_per_search"] == 5
    assert normalized[KEY_LINKEDIN_EASY_APPLY_ONLY] is False


def test_search_settings_follow_managed_search_limits(monkeypatch):
    monkeypatch.setattr(
        profile_store,
        "load_global_settings",
        lambda: {
            "search_limits": {
                "date_range_days": {"min": 1, "max": 9},
                "seek_max_pages": {"min": 1, "max": 12},
                "linkedin_hours_old": {"min": 1, "max": 72},
                "linkedin_results_per_search": {"min": 5, "max": 40},
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
    assert prefs["work_mode_preference"] == []
    assert prefs["prefer_government"] is False
    assert prefs["prefer_permanent"] is False


def test_active_modules_import():
    modules = [
        "job_hunter_agent.agent_runner",
        "job_hunter_agent.user_settings",
        "job_hunter_agent.config",
        "job_hunter_agent.cv_pipeline",
        "job_hunter_agent.filters",
        "job_hunter_agent.llm_gate",
        "job_hunter_agent.fastapi_app",
        "job_hunter_agent.server_helpers",
        "job_hunter_agent.profile_learning",
        "job_hunter_agent.profile_store",
        "job_hunter_agent.review_insights",
        "job_hunter_agent.scrapers.base",
        "job_hunter_agent.scrapers.linkedin",
        "job_hunter_agent.scrapers.seek",
        "job_hunter_agent.source_connector",
        "job_hunter_agent.source_documents",
        "job_hunter_agent.utils",
    ]
    for module in modules:
        importlib.import_module(module)

