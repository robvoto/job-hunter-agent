"""Tests for global settings."""

import json

import pytest

from job_hunter_agent import global_settings
from job_hunter_agent.database import db_conn, init_db
from job_hunter_agent.global_settings import (
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS,
)
from job_hunter_agent.paths import GLOBAL_SETTINGS_PATH
from job_hunter_agent.settings.global_settings_normalization import normalize_global_settings


def test_save_global_settings_normalizes_values(isolated_db):

    global_settings.load_global_settings.cache_clear()

    saved = global_settings.save_global_settings(
        {
            "fit_highlights": {
                "strong_capability_count": "4",
                "working_capability_count": "3",
                "basic_capability_count": "2",
                "reviewed_signal_count": "1",
                "max_highlights": "6",
            },
            "search_settings": {
                "seek_enabled": "false",
                "linkedin_enabled": "true",
                "apsjobs_enabled": "false",
                "date_range_days": "5",
                "seek_max_pages": "12",
                "linkedin_hours_old": "48",
                "linkedin_results_per_search": "40",
                KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS: "75",
                "sort_newest_first": "true",
                KEY_LINKEDIN_EASY_APPLY_ONLY: "true",
            },
            "search_limits": {
                "date_range_days": {"min": 1, "max": 9},
                "seek_max_pages": {"min": 1, "max": 12},
                "linkedin_hours_old": {"min": 1, "max": 72},
                "linkedin_results_per_search": {"min": 5, "max": 40},
                KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS: {"min": 30, "max": 120},
            },
            "preference_weights": {
                "fit": "1.5",
                "salary": "1.25",
                "location": "1.1",
                "work_mode": "0.9",
                "contract": "0.8",
                "government": "0.7",
                "freshness": "1.6",
            },
            "candidate_profile_tier_weights": {
                "primary_candidate_profile_context": "1",
                "secondary_candidate_profile_context": "0.5",
                "supplementary_candidate_profile_context": "0.25",
            },
            "onboarding_settings": {
                "extraction_lookback_years": "9",
                "title_extraction_min_months": "7",
                "max_target_patterns": "9",
                "max_secondary_patterns": "5",
                "capability_alias_limit": "6",
                "signal_cluster_min_alias_hits": "3",
                "signal_cluster_min_snippet_hits": "4",
                "signal_cluster_dense_snippet_alias_hits": "5",
                "capability_strength_preset": "recent_focus",
            },
            "history_settings": {
                "posted_age_badge_threshold_days": ["3", "7", "15"],
                "job_history_max_entries": "1500",
                "job_history_max_age_days": "365",
                "repeated_listing_min_times_seen": "5",
                "repeated_listing_min_span_days": "14",
                "multi_listing_red_flag_min_listings": "4",
                "multi_listing_red_flag_min_span_days": "45",
            },
            "cache_settings": {
                "llm_cache_max_entries": "1900",
                "llm_cache_max_age_days": "45",
                "cv_extraction_cache_max_entries": "300",
                "cv_extraction_cache_max_age_days": "60",
                "candidate_application_history_cache_max_entries": "1750",
                "candidate_application_history_cache_max_age_days": "90",
                "occupation_title_cache_max_entries": "9000",
                "occupation_title_cache_max_age_days": "400",
                "source_discovery_cache_max_age_minutes": "75",
                "search_plan_max_age_minutes": "10080",
            },
            "llm_settings": {
                "model_options": [
                    "gpt-4o-mini",
                    "gpt-4.1-mini",
                    "gpt-4o",
                    "gpt-4o-mini",
                ],
            },
            "playwright_settings": {
                "playwright_browser_mode": "persistent",
                "seek_assisted_verification_enabled": "true",
            },
        }
    )

    assert saved["fit_highlights"]["strong_capability_count"] == 4

    assert saved["search_settings"]["date_range_days"] == 5

    assert saved["search_settings"]["seek_max_pages"] == 12
    assert saved["search_settings"]["seek_enabled"] is False
    assert saved["search_settings"]["linkedin_enabled"] is True
    assert saved["search_settings"]["apsjobs_enabled"] is False
    assert saved["search_settings"][KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS] == 75

    assert saved["search_settings"][KEY_LINKEDIN_EASY_APPLY_ONLY] is True

    assert saved["limits"]["search"]["seek_max_pages"]["max"] == 12
    assert saved["limits"]["search"][KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS]["max"] == 120

    assert saved["preference_weights"]["salary"] == 1.25

    assert saved["candidate_profile_tier_weights"]["secondary_candidate_profile_context"] == 0.5

    assert saved["onboarding_settings"]["capability_strength_preset"] == "recent_focus"

    assert saved["onboarding_settings"]["capability_alias_limit"] == 6

    assert saved["onboarding_settings"]["signal_cluster_min_alias_hits"] == 3

    assert saved["onboarding_settings"]["signal_cluster_min_snippet_hits"] == 4

    assert saved["onboarding_settings"]["signal_cluster_dense_snippet_alias_hits"] == 5

    assert saved["history_settings"]["repeated_listing_min_times_seen"] == 5
    assert saved["history_settings"]["posted_age_badge_threshold_days"] == [3, 7, 15]

    assert saved["history_settings"]["job_history_max_entries"] == 1500

    assert saved["history_settings"]["job_history_max_age_days"] == 365

    assert saved["history_settings"]["repeated_listing_min_span_days"] == 14

    assert saved["history_settings"]["multi_listing_red_flag_min_listings"] == 4

    assert saved["history_settings"]["multi_listing_red_flag_min_span_days"] == 45

    assert saved["cache_settings"]["llm_cache_max_entries"] == 1900

    assert saved["cache_settings"]["llm_cache_max_age_days"] == 45

    assert saved["cache_settings"]["cv_extraction_cache_max_entries"] == 300

    assert saved["cache_settings"]["cv_extraction_cache_max_age_days"] == 60

    assert saved["cache_settings"]["candidate_application_history_cache_max_entries"] == 1750

    assert saved["cache_settings"]["candidate_application_history_cache_max_age_days"] == 90

    assert saved["cache_settings"]["occupation_title_cache_max_entries"] == 9000

    assert saved["cache_settings"]["occupation_title_cache_max_age_days"] == 400

    assert saved["cache_settings"]["source_discovery_cache_max_age_minutes"] == 75

    assert saved["cache_settings"]["search_plan_max_age_minutes"] == 10080

    assert "capability_strength_presets" in saved["onboarding_settings"]

    assert saved["llm_settings"]["model_options"] == ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]

    assert saved["llm_settings"]["max_llm_chars_limits"] == {"min": 1, "max": 20000}

    assert saved["llm_settings"]["pricing_per_1m"]["gpt-4o"]["output"] == 10.0

    assert saved["llm_settings"]["llm_prompt_settings"]["learning_candidates_max_items"] == 6

    assert (
        saved["llm_settings"]["llm_prompt_settings"]["rejection_blocker_suggestions_max_items"] == 6
    )

    assert (
        saved["llm_settings"]["llm_prompt_settings"]["rejection_blocker_suggestions_max_words"] == 6
    )
    assert (
        saved["llm_settings"]["llm_prompt_settings"][
            "fit_review_debug_match_diagnostics_enabled"
        ]
        is False
    )

    assert saved["source_document_settings"]["allowed_suffixes"] == [
        ".docx",
        ".md",
        ".txt",
    ]

    assert saved["playwright_settings"]["seek_assisted_verification_enabled"] is True
    assert saved["playwright_settings"]["playwright_browser_mode"] == "persistent"


def test_save_global_settings_normalizes_source_document_suffixes(isolated_db):

    global_settings.load_global_settings.cache_clear()

    saved = global_settings.save_global_settings(
        {
            "source_document_settings": {
                "allowed_suffixes": [".DOCX", ".txt", ".docx", ".md"],
            },
        }
    )

    assert saved["source_document_settings"]["allowed_suffixes"] == [".docx", ".txt", ".md"]

    assert global_settings.get_allowed_source_document_suffixes() == frozenset(
        {".docx", ".txt", ".md"}
    )

    assert global_settings.get_allowed_source_document_suffixes_label() == ".docx, .md, .txt"


def test_save_global_settings_preserves_unedited_top_level_sections(isolated_db):
    global_settings.load_global_settings.cache_clear()

    before = global_settings.load_global_settings()
    before_history = before["candidate_application_history"]

    saved = global_settings.save_global_settings(
        {
            "playwright_settings": {
                "headless": False,
            },
        }
    )

    assert saved["playwright_settings"]["headless"] is False
    assert saved["candidate_application_history"] == before_history


def test_repeated_global_settings_saves_update_single_document_row(isolated_db):
    global_settings.load_global_settings.cache_clear()

    global_settings.save_global_settings(
        {"playwright_settings": {"headless": False}}
    )
    global_settings.save_global_settings(
        {"playwright_settings": {"headless": True}}
    )

    with db_conn(isolated_db) as conn:
        rows = conn.execute(
            "SELECT key, value FROM global_settings ORDER BY key"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["key"] == "global_settings"
    assert json.loads(rows[0]["value"])["playwright_settings"]["headless"] is True


def test_load_global_settings_requires_seeded_table(tmp_path, monkeypatch):

    db = tmp_path / "empty.db"

    init_db(db)

    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(db))

    global_settings.load_global_settings.cache_clear()

    with pytest.raises(
        global_settings.GlobalSettingsLoadError, match="global_settings table is empty"
    ):
        global_settings.load_global_settings()


def test_get_globally_enabled_sources_respects_admin_source_toggles(isolated_db):
    global_settings.load_global_settings.cache_clear()
    global_settings.save_global_settings(
        {
            "search_settings": {
                "seek_enabled": False,
                "linkedin_enabled": True,
                "apsjobs_enabled": False,
            }
        }
    )

    assert global_settings.get_globally_enabled_sources() == ["linkedin"]


def test_load_global_settings_repairs_missing_managed_limits(tmp_path, monkeypatch):
    db = tmp_path / "stale.db"
    init_db(db)

    stale_payload = {
        "fit_highlights": {
            "strong_capability_count": 3,
            "working_capability_count": 2,
            "basic_capability_count": 1,
            "reviewed_signal_count": 3,
            "max_highlights": 8,
        },
        "search_settings": {
            "keywords": "",
            "locations": [],
            "classification_ids": [],
            "date_range_days": 3,
            "seek_max_pages": 3,
            "sort_newest_first": True,
            "linkedin_hours_old": 24,
            "linkedin_results_per_search": 25,
        },
        "limits": {
            "search": {
                "date_range_days": {"min": 1, "max": 30},
                "seek_max_pages": {"min": 1, "max": 10},
                "linkedin_hours_old": {"min": 1, "max": 720},
                "linkedin_results_per_search": {"min": 5, "max": 100},
            },
            "salary": {
                "minimum_salary_yearly": {"min": 0, "max": 1000000},
                "minimum_daily_rate": {"min": 0, "max": 10000},
            },
            "onboarding": {},
            "history": {},
            "cache": {},
        },
        "preference_weights": {
            "fit": 1.0,
            "salary": 1.0,
            "location": 1.0,
            "freshness": 1.0,
        },
        "candidate_profile_tier_weights": {
            "primary_candidate_profile_context": 1.0,
            "secondary_candidate_profile_context": 0.55,
            "supplementary_candidate_profile_context": 0.25,
        },
        "onboarding_settings": {},
        "llm_settings": {"model_options": ["gpt-4o-mini"]},
        "review_settings": {},
        "history_settings": {},
        "cache_settings": {},
        "description_trust_settings": {},
        "description_compaction_settings": {},
        "source_document_settings": {},
        "default_country_suffix": ".com.au",
        "playwright_settings": {},
        "candidate_application_history": {},
    }

    with db_conn(db) as conn:
        conn.execute(
            "INSERT INTO global_settings (key, value) VALUES (?, ?)",
            ("global_settings", json.dumps(stale_payload)),
        )

    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(db))
    global_settings.load_global_settings.cache_clear()

    loaded = global_settings.load_global_settings()

    assert loaded["limits"]["search"]["locations_max_selected"]["max"] == 3

    with db_conn(db) as conn:
        repaired = json.loads(
            conn.execute(
                "SELECT value FROM global_settings WHERE key = ?", ("global_settings",)
            ).fetchone()["value"]
        )
    assert repaired["limits"]["search"]["locations_max_selected"]["max"] == 3


def test_normalize_global_settings_defaults_source_toggles_when_runtime_seed_is_stale(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.settings.global_settings_normalization.DEFAULT_SEARCH_SETTINGS",
        {
            "keywords": "",
            "locations": [],
            "classification_ids": [],
            "date_range_days": 3,
            "seek_max_pages": 3,
            "sort_newest_first": True,
            "linkedin_hours_old": 24,
            "linkedin_results_per_search": 25,
            "linkedin_jobspy_stall_timeout_seconds": 90,
            "apsjobs_results_per_search": 25,
        },
    )

    normalized = normalize_global_settings({"search_settings": {}}, strict_managed=False)

    assert normalized["search_settings"]["seek_enabled"] is True
    assert normalized["search_settings"]["linkedin_enabled"] is True
    assert normalized["search_settings"]["apsjobs_enabled"] is True
    assert normalized["search_settings"][KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS] == 90


def test_upgrade_global_settings_from_file_preserves_existing_admin_values(
    tmp_path, monkeypatch
):
    db = tmp_path / "upgrade.db"
    init_db(db)

    current = normalize_global_settings(
        {
            "playwright_settings": {
                "headless": False,
                "playwright_browser_mode": "ephemeral",
            },
        }
    )
    current["playwright_settings"].pop("session_max_age_days", None)

    with db_conn(db) as conn:
        conn.execute(
            "INSERT INTO global_settings (key, value) VALUES (?, ?)",
            ("global_settings", json.dumps(current)),
        )

    managed_payload = _load_managed_global_settings_payload()
    managed_payload["playwright_settings"]["headless"] = True
    managed_payload["playwright_settings"]["session_max_age_days"] = 30

    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(db))
    monkeypatch.setattr(
        global_settings,
        "_load_managed_global_settings",
        lambda: managed_payload,
    )
    global_settings.load_global_settings.cache_clear()

    updated = global_settings.upgrade_global_settings_from_file(db)

    assert updated is True

    with db_conn(db) as conn:
        saved = json.loads(
            conn.execute(
                "SELECT value FROM global_settings WHERE key = ?", ("global_settings",)
            ).fetchone()["value"]
        )

    assert saved["playwright_settings"]["headless"] is False
    assert saved["playwright_settings"]["session_max_age_days"] == 30


def _load_managed_global_settings_payload() -> dict:
    return json.loads(GLOBAL_SETTINGS_PATH.read_text(encoding="utf-8-sig"))


def test_managed_global_settings_requires_requirement_coverage_max_items():
    payload = _load_managed_global_settings_payload()
    del payload["llm_settings"]["llm_prompt_settings"]["requirement_coverage_max_items"]

    with pytest.raises(ValueError, match=r"requirement_coverage_max_items is required"):
        normalize_global_settings(payload, strict_managed=True)


def test_managed_global_settings_rejects_invalid_requirement_coverage_max_items():
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["llm_prompt_settings"]["requirement_coverage_max_items"] = 0

    with pytest.raises(
        ValueError, match=r"requirement_coverage_max_items must be between 1 and 20"
    ):
        normalize_global_settings(payload, strict_managed=True)


def test_managed_global_settings_accepts_valid_requirement_coverage_max_items():
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["llm_prompt_settings"]["requirement_coverage_max_items"] = 8

    normalized = normalize_global_settings(payload, strict_managed=True)

    assert (
        normalized["llm_settings"]["llm_prompt_settings"]["requirement_coverage_max_items"]
        == 8
    )


def test_managed_global_settings_accepts_valid_temperature():
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["temperature"] = 0.3

    normalized = normalize_global_settings(payload, strict_managed=True)

    assert normalized["llm_settings"]["temperature"] == 0.3


@pytest.mark.parametrize("temperature", [-0.1, 2.1])
def test_managed_global_settings_rejects_temperature_outside_api_range(temperature):
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["temperature"] = temperature

    with pytest.raises(ValueError, match=r"temperature must be between 0.0 and 2.0"):
        normalize_global_settings(payload, strict_managed=True)


def test_managed_global_settings_rejects_invalid_fit_decision_output_tokens():
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["llm_prompt_settings"]["fit_decision_max_output_tokens"] = 0

    with pytest.raises(
        ValueError, match=r"fit_decision_max_output_tokens must be between 100 and 4000"
    ):
        normalize_global_settings(payload, strict_managed=True)


def test_managed_global_settings_accepts_valid_fit_decision_output_tokens():
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["llm_prompt_settings"]["fit_decision_max_output_tokens"] = 3000

    normalized = normalize_global_settings(payload, strict_managed=True)

    assert (
        normalized["llm_settings"]["llm_prompt_settings"]["fit_decision_max_output_tokens"]
        == 3000
    )


def test_managed_global_settings_normalizes_fit_review_debug_match_diagnostics_enabled():
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["llm_prompt_settings"][
        "fit_review_debug_match_diagnostics_enabled"
    ] = "true"

    normalized = normalize_global_settings(payload, strict_managed=True)

    assert (
        normalized["llm_settings"]["llm_prompt_settings"][
            "fit_review_debug_match_diagnostics_enabled"
        ]
        is True
    )
