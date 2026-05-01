from job_hunter_agent import local_server
from job_hunter_agent import source_documents


def test_normalize_onboarding_search_preferences_trims_and_normalizes():
    normalized = local_server._normalize_onboarding_search_preferences(
        {
            "keywords": "  business analyst  ",
            "locations": [" Sydney NSW ", "", "Melbourne VIC"],
            "engagement_type": " Permanent ",
        }
    )

    assert normalized == {
        "keywords": "business analyst",
        "locations": ["Sydney NSW", "Melbourne VIC"],
        "engagement_type": "permanent",
    }


def test_validate_required_onboarding_inputs_requires_locations_and_engagement():
    try:
        local_server._validate_required_onboarding_inputs(
            {
                "keywords": "",
                "locations": [],
                "engagement_type": "",
            },
            {},
        )
    except ValueError as exc:
        assert "location" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for missing onboarding inputs")


def test_validate_required_onboarding_inputs_allows_blank_keywords():
    local_server._validate_required_onboarding_inputs(
        {
            "keywords": "",
            "locations": ["Sydney NSW"],
            "engagement_type": "both",
        },
        {
            "extraction_lookback_years": 12,
            "title_extraction_min_months": 6,
        },
    )


def test_validate_required_onboarding_inputs_rejects_bad_boundaries():
    try:
        local_server._validate_required_onboarding_inputs(
            {
                "keywords": "x",
                "locations": ["Sydney NSW", "!" * 5],
                "engagement_type": "both",
            },
            {
                "extraction_lookback_years": 99,
                "title_extraction_min_months": 0,
            },
        )
    except ValueError as exc:
        assert str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid onboarding boundaries")


def test_normalize_onboarding_settings_payload_supports_current_key():
    normalized = local_server._normalize_onboarding_settings_payload(
        {
            "extraction_lookback_years": 12,
            "title_extraction_min_months": 9,
            "max_target_patterns": 10,
            "max_secondary_patterns": 7,
        }
    )

    assert normalized == {
        "extraction_lookback_years": 12,
        "title_extraction_min_months": 9,
        "max_target_patterns": 10,
        "max_secondary_patterns": 7,
    }


def test_normalize_onboarding_settings_payload_clamps_current_keys(monkeypatch):
    monkeypatch.setattr(local_server, "load_profile", lambda: {"onboarding_settings": {}})

    normalized = local_server._normalize_onboarding_settings_payload(
        {
            "extraction_lookback_years": 999,
            "title_extraction_min_months": 0,
            "max_target_patterns": -1,
                "max_secondary_patterns": 999,
        }
    )

    assert normalized == {
        "extraction_lookback_years": 20,
        "title_extraction_min_months": 1,
        "max_target_patterns": 1,
            "max_secondary_patterns": 20,
    }


def test_run_onboarding_uses_saved_onboarding_settings_when_argument_missing(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("# Professional Experience\nAcme - Delivery Lead (2020 - 2024)\n", encoding="utf-8")

    monkeypatch.setattr(
        source_documents,
        "load_profile",
        lambda: {
            "search_settings": {},
            "match_preferences": {},
            "onboarding_settings": {
                "extraction_lookback_years": 11,
                "title_extraction_min_months": 5,
                "max_target_patterns": 9,
                "max_secondary_patterns": 4,
            },
        },
    )
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(source_documents, "extract_location_hint", lambda text: "")
    monkeypatch.setattr(source_documents, "_extract_match_preferences", lambda text: {})
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"primary_job_title_pattern": [], "secondary_title_patterns": [], "suggested_search_keywords": []},
    )

    def fake_run_cv_pipeline(text, llm_client, onboarding_settings=None):
        captured["onboarding_settings"] = onboarding_settings
        return {"capability_profile_rules": [{"name": "delivery", "level": "working", "fit": "core"}]}

    monkeypatch.setattr(source_documents, "run_cv_pipeline", fake_run_cv_pipeline)

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "path": str(cv_path)}]}
    )

    assert result["ok"] is True
    assert captured["onboarding_settings"] == {
        "extraction_lookback_years": 11,
        "title_extraction_min_months": 5,
        "max_target_patterns": 9,
        "max_secondary_patterns": 4,
    }


def test_agent_settings_schedule_payload_is_sanitized_and_exposed():
    sanitized = local_server.AdminHandler._sanitize_agent_settings_payload(
        {
            "schedule": {
                "daily_time_local": "09:45",
                "loop_sleep_seconds": 30,
            }
        }
    )

    assert sanitized["schedule"] == {
        "daily_time_local": "09:45",
        "loop_sleep_seconds": 60,
    }

    public_payload = local_server.AdminHandler._public_agent_settings_payload(
        {
            "schedule": {
                "daily_time_local": "09:45",
                "loop_sleep_seconds": 120,
            }
        }
    )

    assert public_payload["schedule"] == {
        "daily_time_local": "09:45",
        "loop_sleep_seconds": 120,
    }


def test_agent_settings_schedule_payload_rejects_bad_time_format():
    try:
        local_server.AdminHandler._sanitize_agent_settings_payload(
            {
                "schedule": {
                    "daily_time_local": "9:45 am",
                }
            }
        )
    except ValueError as exc:
        assert "HH:MM" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid schedule time")


def test_remove_review_key_supports_unapply(monkeypatch):
    saved_profile = {
        "review_controls": {
            "applied_job_keys": ["job-1", "job-2"],
            "hidden_job_keys": ["job-3"],
        }
    }
    events = []

    monkeypatch.setattr(local_server, "load_profile", lambda: saved_profile)
    monkeypatch.setattr(local_server, "save_profile", lambda profile: profile)
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_persist_review_event",
        classmethod(lambda cls, *args, **kwargs: events.append((args, kwargs))),
    )
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_rebuild_dashboard_after_rule_change",
        staticmethod(lambda reason="": events.append(((f"rebuild:{reason}",), {}))),
    )

    result = local_server.SettingsHandler._remove_review_key("unapply", "job-1")

    assert result["ok"] is True
    assert result["reload_dashboard"] is True
    assert saved_profile["review_controls"]["applied_job_keys"] == ["job-2"]
    assert saved_profile["review_controls"]["hidden_job_keys"] == ["job-3"]
    assert events[0][0][0] == "unapply"
    assert str(events[1][0][0]).startswith("rebuild:review action saved: unapply")


def test_patch_affects_matching_rules_includes_capability_matrix():
    assert local_server.SettingsHandler._patch_affects_matching_rules({"capability_profile_rules": []}) is True


def test_rebuild_dashboard_after_rule_change_runs_in_background(monkeypatch, tmp_path):
    started = []
    rebuilds = []

    class FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            started.append({"daemon": self.daemon, "name": self.name})
            if self.target:
                self.target()

    monkeypatch.setattr(local_server, "DASHBOARD_PATH", tmp_path / "dashboard.html")
    monkeypatch.setattr(local_server, "RUN_STATS_PATH", tmp_path / "run_stats.json")
    monkeypatch.setattr(local_server, "AUDIT_RECORDS_PATH", tmp_path / "audit_records.json")
    (tmp_path / "dashboard.html").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(local_server.threading, "Thread", FakeThread)
    monkeypatch.setattr(local_server, "rebuild_html_dashboard", lambda reason="": rebuilds.append(reason))

    local_server.SettingsHandler._rebuild_dashboard_after_rule_change("profile matching rules saved")

    assert started == [{"daemon": True, "name": "job-hunter-dashboard-rebuild"}]
    assert rebuilds == ["profile matching rules saved; applying saved filters to current dashboard"]


def test_reset_current_user_state_clears_local_profile_and_feedback(monkeypatch, tmp_path):
    saved_profiles = []
    saved_materials = []

    monkeypatch.setattr(local_server, "save_profile", lambda profile: saved_profiles.append(profile) or profile)
    monkeypatch.setattr(local_server, "save_source_materials", lambda payload: saved_materials.append(payload) or payload)
    monkeypatch.setattr(local_server, "JOB_HISTORY_PATH", tmp_path / "job_history.json")
    monkeypatch.setattr(local_server, "REVIEW_DATA_PATH", tmp_path / "review_data.json")
    monkeypatch.setattr(local_server, "RUN_STATS_PATH", tmp_path / "run_stats.json")
    monkeypatch.setattr(local_server, "AUDIT_RECORDS_PATH", tmp_path / "audit_records.json")
    monkeypatch.setattr(local_server, "REJECTION_RULES_PATH", tmp_path / "rejection_rules.json")
    monkeypatch.setattr(local_server, "DASHBOARD_PATH", tmp_path / "dashboard.html")
    monkeypatch.setattr(local_server, "SOURCE_PACK_DIR", tmp_path / "source_pack")

    local_server.SOURCE_PACK_DIR.mkdir(parents=True, exist_ok=True)
    (local_server.SOURCE_PACK_DIR / "primary_cv.txt").write_text("cv", encoding="utf-8")
    local_server.DASHBOARD_PATH.write_text("old dashboard", encoding="utf-8")

    result = local_server.SettingsHandler._reset_current_user_state()

    assert result["ok"] is True
    assert result["redirect_to"] == "/start"
    assert saved_profiles == [local_server.DEFAULT_PROFILE]
    assert saved_materials == [local_server.DEFAULT_SOURCE_MATERIALS]
    assert not local_server.SOURCE_PACK_DIR.exists()
    assert not local_server.DASHBOARD_PATH.exists()
    assert local_server.JOB_HISTORY_PATH.read_text(encoding="utf-8").strip() == "{}"
    assert local_server.REVIEW_DATA_PATH.read_text(encoding="utf-8").strip() == "{}"
    assert local_server.RUN_STATS_PATH.read_text(encoding="utf-8").strip() == "{}"
    assert local_server.AUDIT_RECORDS_PATH.read_text(encoding="utf-8").strip() == "[]"
    assert local_server.REJECTION_RULES_PATH.read_text(encoding="utf-8").strip() == "[]"


def test_reset_global_learning_clears_shared_signal_registry(monkeypatch):
    calls = []

    def fake_save_registry(payload):
        calls.append(payload)

    monkeypatch.setattr("job_hunter_agent.signal_registry.save_registry", fake_save_registry)

    result = local_server.SettingsHandler._reset_global_learning()

    assert result["ok"] is True
    assert calls == [{}]
