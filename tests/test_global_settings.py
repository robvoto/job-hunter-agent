"""Tests for global settings."""



import json

import pytest



from job_hunter_agent import global_settings

from job_hunter_agent.database import init_db

from job_hunter_agent.global_settings import KEY_LINKEDIN_EASY_APPLY_ONLY
from job_hunter_agent.paths import GLOBAL_SETTINGS_PATH
from job_hunter_agent.settings.global_settings_normalization import normalize_global_settings





def test_save_global_settings_normalizes_values(isolated_db):

    global_settings.load_global_settings.cache_clear()



    saved = global_settings.save_global_settings({

        "fit_highlights": {

            "strong_capability_count": "4",

            "working_capability_count": "3",

            "basic_capability_count": "2",

            "reviewed_signal_count": "1",

            "max_highlights": "6",

        },

        "search_settings": {

            "date_range_days": "5",

            "seek_max_pages": "12",

            "linkedin_hours_old": "48",

            "linkedin_results_per_search": "40",

            "sort_newest_first": "true",

            KEY_LINKEDIN_EASY_APPLY_ONLY: "true",

        },

        "search_limits": {

            "date_range_days": {"min": 1, "max": 9},

            "seek_max_pages": {"min": 1, "max": 12},

            "linkedin_hours_old": {"min": 1, "max": 72},

            "linkedin_results_per_search": {"min": 5, "max": 40},

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

            "repeated_listing_min_times_seen": "5",

            "repeated_listing_min_span_days": "14",

            "multi_listing_red_flag_min_listings": "4",

            "multi_listing_red_flag_min_span_days": "45",

        },

        "llm_settings": {

            "model_options": [

                "gpt-4o-mini",

                "gpt-4.1-mini",

                "gpt-4o",

                "gpt-4o-mini",

            ],

        },

    })



    assert saved["fit_highlights"]["strong_capability_count"] == 4

    assert saved["search_settings"]["date_range_days"] == 5

    assert saved["search_settings"]["seek_max_pages"] == 12

    assert saved["search_settings"][KEY_LINKEDIN_EASY_APPLY_ONLY] is True

    assert saved["limits"]["search"]["seek_max_pages"]["max"] == 12

    assert saved["preference_weights"]["salary"] == 1.25

    assert saved["candidate_profile_tier_weights"]["secondary_candidate_profile_context"] == 0.5

    assert saved["onboarding_settings"]["capability_strength_preset"] == "recent_focus"

    assert saved["onboarding_settings"]["capability_alias_limit"] == 6

    assert saved["onboarding_settings"]["signal_cluster_min_alias_hits"] == 3

    assert saved["onboarding_settings"]["signal_cluster_min_snippet_hits"] == 4

    assert saved["onboarding_settings"]["signal_cluster_dense_snippet_alias_hits"] == 5

    assert saved["history_settings"]["repeated_listing_min_times_seen"] == 5

    assert saved["history_settings"]["repeated_listing_min_span_days"] == 14

    assert saved["history_settings"]["multi_listing_red_flag_min_listings"] == 4

    assert saved["history_settings"]["multi_listing_red_flag_min_span_days"] == 45

    assert "capability_strength_presets" in saved["onboarding_settings"]

    assert saved["llm_settings"]["model_options"] == ["gpt-4o-mini", "gpt-4.1-mini", "gpt-4o"]

    assert saved["llm_settings"]["max_llm_chars_limits"] == {"min": 1, "max": 20000}

    assert saved["llm_settings"]["pricing_per_1m"]["gpt-4o"]["output"] == 10.0

    assert saved["llm_settings"]["llm_prompt_settings"]["learning_candidates_max_items"] == 6

    assert saved["llm_settings"]["llm_prompt_settings"]["rejection_blocker_suggestions_max_items"] == 6

    assert saved["llm_settings"]["llm_prompt_settings"]["rejection_blocker_suggestions_max_words"] == 6

    assert saved["source_document_settings"]["allowed_suffixes"] == [

        ".docx",

        ".md",

        ".txt",

    ]





def test_save_global_settings_normalizes_source_document_suffixes(isolated_db):

    global_settings.load_global_settings.cache_clear()



    saved = global_settings.save_global_settings({

        "source_document_settings": {

            "allowed_suffixes": [".DOCX", ".txt", ".docx", ".md"],

        },

    })



    assert saved["source_document_settings"]["allowed_suffixes"] == [".docx", ".txt", ".md"]

    assert global_settings.get_allowed_source_document_suffixes() == frozenset({".docx", ".txt", ".md"})

    assert global_settings.get_allowed_source_document_suffixes_label() == ".docx, .md, .txt"





def test_load_global_settings_requires_seeded_table(tmp_path, monkeypatch):

    db = tmp_path / "empty.db"

    init_db(db)

    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(db))

    global_settings.load_global_settings.cache_clear()



    with pytest.raises(global_settings.GlobalSettingsLoadError, match="global_settings table is empty"):

        global_settings.load_global_settings()


def _load_managed_global_settings_payload() -> dict:
    return json.loads(GLOBAL_SETTINGS_PATH.read_text(encoding="utf-8-sig"))


def test_managed_global_settings_requires_job_requirements_output_tokens():
    payload = _load_managed_global_settings_payload()
    del payload["llm_settings"]["llm_prompt_settings"]["job_requirements_max_output_tokens"]

    with pytest.raises(ValueError, match=r"job_requirements_max_output_tokens is required"):
        normalize_global_settings(payload, strict_managed=True)


def test_managed_global_settings_rejects_invalid_job_requirements_output_tokens():
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["llm_prompt_settings"]["job_requirements_max_output_tokens"] = 0

    with pytest.raises(ValueError, match=r"job_requirements_max_output_tokens must be between 50 and 1000"):
        normalize_global_settings(payload, strict_managed=True)


def test_managed_global_settings_accepts_valid_job_requirements_output_tokens():
    payload = _load_managed_global_settings_payload()
    payload["llm_settings"]["llm_prompt_settings"]["job_requirements_max_output_tokens"] = 300

    normalized = normalize_global_settings(payload, strict_managed=True)

    assert normalized["llm_settings"]["llm_prompt_settings"]["job_requirements_max_output_tokens"] == 300

