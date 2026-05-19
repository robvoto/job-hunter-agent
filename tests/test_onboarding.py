import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from job_hunter_agent import server_helpers
from job_hunter_agent import server_review
from job_hunter_agent import source_documents
from job_hunter_agent import profile_store
from job_hunter_agent import review_history_service
from job_hunter_agent import workspace_refresh_service
from job_hunter_agent.fastapi_app import create_app
import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.routes import onboarding_api


def test_normalize_onboarding_search_preferences_trims_and_normalizes():
    normalized = server_helpers._normalize_onboarding_search_preferences(
        {
            "keywords": "  business analyst  ",
            "locations": [" Sydney ", "", "Melbourne"],
            "engagement_type": " Permanent ",
        }
    )

    assert normalized == {
        "keywords": "business analyst",
        "locations": ["Sydney", "Melbourne"],
        "engagement_type": ["permanent"],
    }


def test_onboarding_page_uses_shared_choice_strip_widget(monkeypatch):
    monkeypatch.setattr(_fa, "is_auth_disabled", lambda: True)
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: False)
    monkeypatch.setattr(_pages, "get_user_id_for_runtime", lambda: "test-user")

    client = TestClient(create_app())
    html = client.get("/onboarding").text

    assert 'Target roles' in html
    assert 'Also consider' in html
    assert 'Search keyword' in html
    assert 'placeholder="e.g. Business Analyst"' in html
    assert 'Add a target role' in html
    assert 'Add an also-consider role' in html
    assert 'id="engagement_type_label"' in html
    assert 'class="choice-strip"' in html
    assert 'class="choice-card choice-card--work-mode"' in html
    assert 'input type="checkbox" name="engagement_type"' in html
    assert 'input type="checkbox" name="work_mode_preference"' in html
    assert 'window.__JOB_HUNTER_USER_ID__ = "test-user"' in html


def test_onboarding_flow_keyword_helper_uses_single_target_role():
    js_path = Path(__file__).resolve().parents[1] / "templates" / "static" / "onboarding" / "onboarding-page.js"
    js_text = js_path.read_text(encoding="utf-8")

    assert "defaultSearchKeywordFromTargetRoles" in js_text
    assert "reviewTargetTitles.join(', ')" not in js_text
    assert "defaultSearchKeywordsFromReviewedTitles" not in js_text


def test_api_onboarding_import_accepts_supported_text_suffix(monkeypatch):
    monkeypatch.setattr(onboarding_api, "persist_uploaded_source_pack", lambda files: {"profile_sources": [], "cv_variants": []})
    monkeypatch.setattr(onboarding_api, "run_onboarding", lambda materials, search_preferences=None, onboarding_settings=None: {"ok": True, "materials": materials})
    monkeypatch.setattr(onboarding_api.srv, "patch_profile", lambda patch: patch)

    response = onboarding_api.api_onboarding_import(
        {
            "files": [
                {
                    "filename": "cv.csv",
                    "content_base64": base64.b64encode(b"header,value\n").decode("ascii"),
                }
            ],
            "search_preferences": {
                "keywords": "business analyst",
                "locations": ["Sydney"],
                "engagement_type": ["permanent", "contract"],
            },
            "onboarding_settings": {
                "capability_strength_preset": "balanced",
            },
        }
    )

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True


def test_api_onboarding_confirm_allows_no_sector_preference(monkeypatch):
    captured = {}
    monkeypatch.setattr(onboarding_api.srv, "load_profile", lambda: {"match_preferences": {}, "search_settings": {}})
    monkeypatch.setattr(onboarding_api.srv, "patch_profile", lambda patch: captured.setdefault("patch", patch) or patch)
    monkeypatch.setattr(onboarding_api, "normalize_capability_rules", lambda rules, current_onboarding: [])

    response = onboarding_api.api_onboarding_confirm(
        {
            "target_roles": ["Business Analyst"],
            "also_consider_roles": [],
            "search_keyword": "business analyst",
            "search_locations": ["Sydney"],
            "engagement_type": ["permanent", "contract"],
            "prefer_sector": "",
            "minimum_salary_yearly": 0,
            "minimum_daily_rate": 0,
            "capability_profile_rules": [],
        }
    )

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert captured["patch"]["match_preferences"]["prefer_sector"] == profile_store.GovPref.ANY


def test_api_onboarding_confirm_saves_work_mode_preference(monkeypatch):
    captured = {}
    monkeypatch.setattr(onboarding_api.srv, "load_profile", lambda: {"match_preferences": {}, "search_settings": {}})
    monkeypatch.setattr(onboarding_api.srv, "patch_profile", lambda patch: captured.setdefault("patch", patch) or patch)
    monkeypatch.setattr(onboarding_api, "normalize_capability_rules", lambda rules, current_onboarding: [])

    response = onboarding_api.api_onboarding_confirm(
        {
            "target_roles": ["Business Analyst"],
            "also_consider_roles": [],
            "search_keyword": "business analyst",
            "search_locations": ["Sydney"],
            "engagement_type": ["permanent", "contract"],
            "work_mode_preference": ["remote", "hybrid"],
            "prefer_sector": "",
            "minimum_salary_yearly": 0,
            "minimum_daily_rate": 0,
            "capability_profile_rules": [],
        }
    )

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert captured["patch"]["match_preferences"]["work_mode_preference"] == ["remote", "hybrid"]


def test_validate_required_onboarding_inputs_requires_locations_and_engagement():
    try:
        server_helpers._validate_required_onboarding_inputs(
            {
                "keywords": "",
                "locations": [],
                "engagement_type": [],
            },
            {},
        )
    except ValueError as exc:
        assert "location" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for missing onboarding inputs")


def test_validate_required_onboarding_inputs_allows_blank_keywords():
    server_helpers._validate_required_onboarding_inputs(
            {
                "keywords": "",
                "locations": ["Sydney"],
                "engagement_type": ["permanent", "contract"],
            },
        {
            "extraction_lookback_years": 12,
            "title_extraction_min_months": 6,
        },
    )


def test_validate_required_onboarding_inputs_rejects_bad_boundaries():
    try:
        server_helpers._validate_required_onboarding_inputs(
            {
                "keywords": "x",
                "locations": ["Sydney", "!" * 5],
                "engagement_type": ["permanent", "contract"],
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
    normalized = server_helpers._normalize_onboarding_settings_payload(
        {
            "extraction_lookback_years": 12,
            "title_extraction_min_months": 9,
            "max_target_patterns": 10,
            "max_secondary_patterns": 7,
            "capability_alias_limit": 6,
            "signal_cluster_min_alias_hits": 3,
            "signal_cluster_min_snippet_hits": 4,
            "signal_cluster_dense_snippet_alias_hits": 5,
        }
    )

    assert normalized["extraction_lookback_years"] == 12
    assert normalized["title_extraction_min_months"] == 9
    assert normalized["max_target_patterns"] == 10
    assert normalized["max_secondary_patterns"] == 7
    assert normalized["capability_alias_limit"] == 6
    assert normalized["signal_cluster_min_alias_hits"] == 3
    assert normalized["signal_cluster_min_snippet_hits"] == 4
    assert normalized["signal_cluster_dense_snippet_alias_hits"] == 5


def test_normalize_onboarding_settings_payload_clamps_current_keys(monkeypatch):
    monkeypatch.setattr(server_helpers, "load_profile", lambda: {"onboarding_settings": {}})

    normalized = server_helpers._normalize_onboarding_settings_payload(
        {
            "extraction_lookback_years": 999,
            "title_extraction_min_months": 0,
            "max_target_patterns": -1,
            "max_secondary_patterns": 999,
            "capability_alias_limit": 999,
            "signal_cluster_min_alias_hits": 0,
            "signal_cluster_min_snippet_hits": 0,
            "signal_cluster_dense_snippet_alias_hits": 999,
        }
    )

    assert normalized["extraction_lookback_years"] == 20
    assert normalized["title_extraction_min_months"] == 1
    assert normalized["max_target_patterns"] == 1
    assert normalized["max_secondary_patterns"] == 20
    assert normalized["capability_alias_limit"] == 20
    assert normalized["signal_cluster_min_alias_hits"] == 1
    assert normalized["signal_cluster_min_snippet_hits"] == 1
    assert normalized["signal_cluster_dense_snippet_alias_hits"] == 20


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
                "capability_alias_limit": 7,
                "signal_cluster_min_alias_hits": 3,
                "signal_cluster_min_snippet_hits": 4,
                "signal_cluster_dense_snippet_alias_hits": 5,
            },
        },
    )
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(
        source_documents,
        "extract_title_pattern_suggestions",
        lambda text, settings: {"target_roles": [], "also_consider_roles": [], "suggested_search_keywords": []},
    )

    def fake_run_cv_pipeline(text, llm_client, onboarding_settings=None):
        captured["onboarding_settings"] = onboarding_settings
        return {"capability_profile_rules": [{"name": "delivery", "level": "working", "fit": "core"}]}

    monkeypatch.setattr(source_documents, "run_cv_pipeline", fake_run_cv_pipeline)

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "path": str(cv_path)}]}
    )

    assert result["ok"] is True
    assert captured["onboarding_settings"]["extraction_lookback_years"] == 11
    assert captured["onboarding_settings"]["title_extraction_min_months"] == 5
    assert captured["onboarding_settings"]["max_target_patterns"] == 9
    assert captured["onboarding_settings"]["max_secondary_patterns"] == 4
    assert captured["onboarding_settings"]["capability_alias_limit"] == 7
    assert captured["onboarding_settings"]["signal_cluster_min_alias_hits"] == 3
    assert captured["onboarding_settings"]["signal_cluster_min_snippet_hits"] == 4
    assert captured["onboarding_settings"]["signal_cluster_dense_snippet_alias_hits"] == 5


def test_normalize_full_profile_preserves_selected_title_categories():
    normalized = profile_store.normalize_full_profile(
        {
            "target_roles": ["senior business analyst"],
            "also_consider_roles": ["scrum master"],
        }
    )

    assert normalized["target_roles"] == ["senior business analyst"]
    assert normalized["also_consider_roles"] == ["scrum master"]


def test_normalize_full_profile_removes_exact_duplicate_title_from_secondary():
    normalized = profile_store.normalize_full_profile(
        {
            "target_roles": ["senior business analyst"],
            "also_consider_roles": ["Senior Business Analyst", "scrum master"],
        }
    )

    assert normalized["target_roles"] == ["senior business analyst"]
    assert normalized["also_consider_roles"] == ["scrum master"]


def test_normalize_full_profile_mirrors_primary_search_location_into_match_preferences():
    normalized = profile_store.normalize_full_profile(
        {
            "search_settings": {
                "locations": ["Sydney"],
            },
            "match_preferences": {
                "secondary_location": "Melbourne",
            },
        }
    )

    assert normalized["search_settings"]["locations"] == ["Sydney"]
    assert normalized["match_preferences"]["home_location"] == "Sydney"
    assert normalized["match_preferences"]["secondary_location"] == "Melbourne"


def test_user_settings_schedule_payload_is_sanitized_and_exposed():
    sanitized = server_helpers.SettingsHandler._sanitize_user_settings_payload(
        {
            "workspace": {
                "minimum_score": 150,
            },
            "schedule": {
                "daily_time_local": "09:45",
                "loop_sleep_seconds": 30,
            }
        }
    )

    assert sanitized["workspace"] == {
        "minimum_score": 100,
    }
    assert sanitized["schedule"] == {
        "daily_time_local": "09:45",
        "loop_sleep_seconds": 60,
    }

    public_payload = server_helpers.SettingsHandler._public_user_settings_payload(
        {
            "workspace": {
                "minimum_score": 61,
            },
            "schedule": {
                "daily_time_local": "09:45",
                "loop_sleep_seconds": 120,
            }
        }
    )

    assert public_payload["workspace"] == {
        "minimum_score": 61,
    }
    assert public_payload["schedule"] == {
        "daily_time_local": "09:45",
        "loop_sleep_seconds": 120,
    }


def test_user_settings_model_uses_advanced_setting_options(monkeypatch):
    monkeypatch.setattr(
        server_helpers,
        "load_global_settings",
        lambda: {
            "llm_settings": {
                "model_options": ["gpt-4o-mini", "gpt-4o"],
            },
        },
    )

    sanitized = server_helpers.SettingsHandler._sanitize_user_settings_payload(
        {
            "llm": {
                "model": "gpt-4o",
            }
        }
    )

    assert sanitized["llm"] == {"model": "gpt-4o"}

    with pytest.raises(ValueError, match="Global Settings"):
        server_helpers.SettingsHandler._sanitize_user_settings_payload(
            {
                "llm": {
                    "model": "gpt-4.1",
                }
            }
        )


def test_user_settings_schedule_payload_rejects_bad_time_format():
    try:
        server_helpers.SettingsHandler._sanitize_user_settings_payload(
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

    monkeypatch.setattr(review_history_service, "load_profile", lambda: saved_profile)
    monkeypatch.setattr(review_history_service, "save_profile", lambda profile: profile)
    monkeypatch.setattr(review_history_service, "persist_review_event", lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(review_history_service, "rebuild_workspace_after_rule_change", lambda reason="": events.append(((f"rebuild:{reason}",), {})))

    result = review_history_service.remove_review_key("unapply", "job-1")

    assert result["ok"] is True
    assert result["reload_workspace"] is True
    assert saved_profile["review_controls"]["applied_job_keys"] == ["job-2"]
    assert saved_profile["review_controls"]["hidden_job_keys"] == ["job-3"]
    assert events[0][0][0] == "unapply"
    assert str(events[1][0][0]).startswith("rebuild:review action saved: unapply")


def test_patch_affects_matching_rules_includes_capability_matrix():
    assert server_helpers.SettingsHandler._patch_affects_matching_rules({"capability_profile_rules": []}) is True


def test_rebuild_workspace_after_rule_change_runs_in_background(monkeypatch, tmp_path):
    started = []
    rebuilds = []

    class FakeThread:
        def __init__(self, target=None, args=None, daemon=None, name=None):
            self.target = target
            self.args = args or ()
            self.daemon = daemon
            self.name = name

        def start(self):
            started.append({"daemon": self.daemon, "name": self.name})
            if self.target:
                self.target(*self.args)

    monkeypatch.setattr(workspace_refresh_service, "get_workspace_results_path", lambda: tmp_path / "workspace.html")
    monkeypatch.setattr(workspace_refresh_service, "get_run_stats_path", lambda: tmp_path / "run_stats.json")
    monkeypatch.setattr(workspace_refresh_service, "get_audit_records_path", lambda: tmp_path / "audit_records.json")
    (tmp_path / "workspace.html").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(workspace_refresh_service.threading, "Thread", FakeThread)
    monkeypatch.setattr(workspace_refresh_service, "rebuild_workspace_results", lambda reason="": rebuilds.append(reason))

    workspace_refresh_service.rebuild_workspace_after_rule_change("profile matching rules saved")

    assert started == [{"daemon": True, "name": "job-hunter-workspace-rebuild"}]
    assert rebuilds == ["profile matching rules saved; applying saved filters to current results"]


def test_rebuild_workspace_on_startup_runs_when_data_exists(monkeypatch, tmp_path):
    rebuilds = []

    monkeypatch.setattr(server_helpers, "get_workspace_results_path", lambda: tmp_path / "workspace.html")
    monkeypatch.setattr(server_helpers, "get_run_stats_path", lambda: tmp_path / "run_stats.json")
    monkeypatch.setattr(server_helpers, "get_audit_records_path", lambda: tmp_path / "audit_records.json")
    monkeypatch.setattr(server_helpers, "AUTH_DISABLED", True)
    (tmp_path / "run_stats.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server_helpers, "rebuild_workspace_results", lambda reason="": rebuilds.append(reason))

    server_helpers._rebuild_workspace_on_startup()

    assert rebuilds == ["server startup rebuild"]


def test_reset_current_user_state_clears_local_profile_and_feedback(monkeypatch, tmp_path):
    saved_profiles = []
    saved_materials = []

    fake_users_dir = tmp_path / "users"
    fake_local_dir = fake_users_dir / "_local"
    fake_local_dir.mkdir(parents=True, exist_ok=True)
    (fake_local_dir / "profile.json").write_text('{"cv_text": "old"}', encoding="utf-8")

    job_history_path = tmp_path / "job_history.json"
    review_data_path = tmp_path / "review_data.json"
    run_stats_path = tmp_path / "run_stats.json"
    audit_records_path = tmp_path / "audit_records.json"
    workspace_path = tmp_path / "workspace.html"
    source_pack_dir = tmp_path / "source_pack"

    monkeypatch.setattr(server_helpers, "USERS_DIR", fake_users_dir)
    monkeypatch.setattr(server_helpers, "save_profile", lambda profile: saved_profiles.append(profile) or profile)
    monkeypatch.setattr(server_helpers, "save_source_materials", lambda payload: saved_materials.append(payload) or payload)
    monkeypatch.setattr(server_helpers, "get_job_history_path", lambda: job_history_path)
    monkeypatch.setattr(server_helpers, "get_review_data_path", lambda: review_data_path)
    monkeypatch.setattr(server_helpers, "get_run_stats_path", lambda: run_stats_path)
    monkeypatch.setattr(server_helpers, "get_audit_records_path", lambda: audit_records_path)
    monkeypatch.setattr(server_helpers, "get_workspace_results_path", lambda: workspace_path)
    monkeypatch.setattr(server_helpers, "get_source_pack_dir", lambda: source_pack_dir)

    source_pack_dir.mkdir(parents=True, exist_ok=True)
    (source_pack_dir / "primary_cv.txt").write_text("cv", encoding="utf-8")
    workspace_path.write_text("old workspace", encoding="utf-8")

    result = server_helpers.SettingsHandler._reset_current_user_state()

    assert result["ok"] is True
    assert result["redirect_to"] == "/start?fresh=1"
    assert not fake_local_dir.exists()
    assert saved_profiles == [server_helpers.DEFAULT_PROFILE]
    assert saved_materials == [server_helpers.DEFAULT_SOURCE_MATERIALS]
    assert not source_pack_dir.exists()
    assert not workspace_path.exists()
    assert job_history_path.read_text(encoding="utf-8").strip() == "{}"
    assert review_data_path.read_text(encoding="utf-8").strip() == "{}"
    assert run_stats_path.read_text(encoding="utf-8").strip() == "{}"
    assert audit_records_path.read_text(encoding="utf-8").strip() == "[]"


def test_reset_global_learning_clears_shared_signal_registry(monkeypatch):
    calls = []

    def fake_clear_signal_learning_state():
        calls.append(True)

    monkeypatch.setattr("job_hunter_agent.signal_registry.clear_signal_learning_state", fake_clear_signal_learning_state)

    result = server_helpers.SettingsHandler._reset_global_learning()

    assert result["ok"] is True
    assert calls == [True]
