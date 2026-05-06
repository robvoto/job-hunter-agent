import pytest

from job_hunter_agent import advance_settings
from job_hunter_agent.advance_settings import KEY_LINKEDIN_EASY_APPLY_ONLY


def test_save_advance_settings_normalizes_values(tmp_path, monkeypatch):
    settings_path = tmp_path / "advance_settings.json"
    monkeypatch.setattr(advance_settings, "ADVANCE_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(advance_settings, "DATA_DIR", tmp_path)
    advance_settings.load_advance_settings.cache_clear()

    saved = advance_settings.save_advance_settings({
        "fit_highlights": {
            "strong_capability_count": "4",
            "working_capability_count": "3",
            "basic_capability_count": "2",
            "reviewed_signal_count": "1",
            "max_highlights": "6",
        },
        "search_settings": {
            "date_range_days": "5",
            "seek_max_pages": "7",
            "linkedin_hours_old": "48",
            "linkedin_results_per_search": "75",
            "enforce_posted_age_limit": "false",
            "sort_newest_first": "true",
            KEY_LINKEDIN_EASY_APPLY_ONLY: "true",
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
            "capability_strength_preset": "recent_focus",
        },
    })

    assert saved["fit_highlights"]["strong_capability_count"] == 4
    assert saved["search_settings"]["date_range_days"] == 5
    assert saved["search_settings"][KEY_LINKEDIN_EASY_APPLY_ONLY] is True
    assert saved["preference_weights"]["salary"] == 1.25
    assert saved["candidate_profile_tier_weights"]["secondary_candidate_profile_context"] == 0.5
    assert saved["onboarding_settings"]["capability_strength_preset"] == "recent_focus"
    assert "capability_strength_presets" in saved["onboarding_settings"]
    assert settings_path.exists()


def test_load_advance_settings_backs_up_invalid_json(tmp_path, monkeypatch):
    settings_path = tmp_path / "advance_settings.json"
    settings_path.write_text("{bad json", encoding="utf-8")
    monkeypatch.setattr(advance_settings, "ADVANCE_SETTINGS_PATH", settings_path)
    monkeypatch.setattr(advance_settings, "DATA_DIR", tmp_path)
    advance_settings.load_advance_settings.cache_clear()

    with pytest.raises(advance_settings.AdvanceSettingsLoadError):
        advance_settings.load_advance_settings()

    backups = sorted(tmp_path.glob("advance_settings.invalid.*.json"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{bad json"
