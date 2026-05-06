from pathlib import Path
import importlib

from job_hunter_agent.advance_settings import KEY_LINKEDIN_EASY_APPLY_ONLY
from job_hunter_agent.profile_store import DEFAULT_PROFILE, DEFAULT_SEARCH_SETTINGS, normalize_search_settings


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_no_legacy_directory_remains():
    assert not (ROOT_DIR / "legacy").exists()


def test_default_search_settings_are_candidate_agnostic():
    assert DEFAULT_SEARCH_SETTINGS["keywords"] == ""
    assert DEFAULT_SEARCH_SETTINGS["locations"] == []
    assert DEFAULT_SEARCH_SETTINGS["classification_ids"] == []
    assert DEFAULT_SEARCH_SETTINGS["seek_max_pages"] == 10


def test_search_settings_clamp_source_fetch_limits():
    normalized = normalize_search_settings(
        {
            "seek_max_pages": 100,
            "linkedin_hours_old": 999,
            "linkedin_results_per_search": 1,
            KEY_LINKEDIN_EASY_APPLY_ONLY: "false",
        }
    )

    assert normalized["seek_max_pages"] == 10
    assert normalized["linkedin_hours_old"] == 168
    assert normalized["linkedin_results_per_search"] == 5
    assert normalized[KEY_LINKEDIN_EASY_APPLY_ONLY] is False


def test_default_match_preferences_are_neutral():
    prefs = DEFAULT_PROFILE["match_preferences"]
    assert prefs["home_location"] == ""
    assert prefs["secondary_location"] == ""
    assert prefs["prefer_government"] is False
    assert prefs["prefer_permanent"] is False


def test_active_modules_import():
    modules = [
        "job_hunter_agent.agent_runner",
        "job_hunter_agent.agent_settings",
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

