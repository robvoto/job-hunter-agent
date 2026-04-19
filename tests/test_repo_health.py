from pathlib import Path
import importlib

from profile_store import DEFAULT_PROFILE, DEFAULT_SEARCH_SETTINGS


ROOT_DIR = Path(__file__).resolve().parent.parent


def test_no_legacy_directory_remains():
    assert not (ROOT_DIR / "legacy").exists()


def test_default_search_settings_are_candidate_agnostic():
    assert DEFAULT_SEARCH_SETTINGS["keywords"] == ""
    assert DEFAULT_SEARCH_SETTINGS["locations"] == []
    assert DEFAULT_SEARCH_SETTINGS["classification_ids"] == []


def test_default_match_preferences_are_neutral():
    prefs = DEFAULT_PROFILE["match_preferences"]
    assert prefs["home_location"] == ""
    assert prefs["secondary_location"] == ""
    assert prefs["prefer_government"] is False
    assert prefs["prefer_permanent"] is False


def test_active_modules_import():
    modules = [
        "agent_runner",
        "agent_settings",
        "config",
        "cv_pipeline",
        "filters",
        "llm_gate",
        "local_server",
        "profile_learning",
        "profile_store",
        "review_insights",
        "scraper_base",
        "scraper_linkedin",
        "scraper_seek",
        "source_connector",
        "source_documents",
        "utils",
    ]
    for module in modules:
        importlib.import_module(module)
