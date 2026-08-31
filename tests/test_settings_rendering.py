"""Tests for settings rendering."""

import json
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.server_helpers import (
    _SETTINGS_ALERTS_LABEL_KEYS,
    _SETTINGS_CLEARANCES_LABEL_KEYS,
)

_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"


def test_ui_labels_json_contains_all_settings_alerts_keys():

    data = json.loads((_KNOWLEDGE_DIR / "ui_labels.json").read_text(encoding="utf-8"))

    section = data.get("settings_alerts_labels", {})

    # telegram_subscribers_empty is composed at runtime from
    # telegram_connection_status_empty (see load_settings_alerts_labels in
    # server_helpers.py) rather than stored as a second literal copy.
    composed_at_runtime = {"telegram_subscribers_empty"}

    missing = [
        k
        for k in _SETTINGS_ALERTS_LABEL_KEYS
        if k not in composed_at_runtime and not str(section.get(k, "")).strip()
    ]

    assert not missing, f"ui_labels.json is missing settings_alerts_labels keys: {missing}"


def test_ui_labels_json_contains_all_settings_clearances_keys():

    data = json.loads((_KNOWLEDGE_DIR / "ui_labels.json").read_text(encoding="utf-8"))

    section = data.get("settings_clearances_labels", {})

    missing = [k for k in _SETTINGS_CLEARANCES_LABEL_KEYS if not str(section.get(k, "")).strip()]

    assert not missing, f"ui_labels.json is missing settings_clearances_labels keys: {missing}"


def test_settings_page_renders_role_preferences_and_location_field(monkeypatch):

    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {
            "user_id": "test-user",
            "email": "test@example.com",
            "role": "candidate",
            "access_status": "approved",
        },
    )

    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)

    client = TestClient(create_app())

    html = client.get("/settings").text

    assert "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_LABEL__" not in html

    assert "Search keyword" not in html

    assert 'id="keywords"' not in html

    assert "Preferred roles" in html

    assert "Alternative roles" in html

    assert "Include SEEK in search" in html

    assert "Include LinkedIn in search" in html

    assert "Shared search inputs that apply across all enabled sources." in html

    assert "Job board search" in html

    assert "Job Hunter searches each preferred and alternative role separately" in html

    assert ">Add<" not in html

    assert '<label for="locations">Location</label>' in html

    assert 'id="min_contract_months"' in html

    assert "6+ months" in html

    assert "job-hunter-account-bar" in html

    assert 'class="nav-item nav-item-workspace">↩ Workspace</a>' in html

    assert "account-bar-shortcut" not in html

    assert "↩ Workspace" in html

    assert "capability-add-button" not in html

    assert "capability-editor" in html

    assert 'id="capability_matrix_copy"' in html

    assert 'id="capability_matrix_actions"' in html

    assert "window.__JOB_HUNTER_CAPABILITY_UI_LABELS__" in html

    assert "window.__JOB_HUNTER_SHARED_UI_LABELS__" in html

    assert "window.__JOB_HUNTER_SETTINGS_ALERTS_LABELS__" in html
    assert "window.__JOB_HUNTER_SETTINGS_CLEARANCES_LABELS__" in html
    assert "window.__JOB_HUNTER_CLEARANCE_OPTIONS__" in html
    assert 'id="add_clearance_rule"' not in html

    assert "Messaging" in html
    assert "AI / LLM" in html
    assert "Hide link preview" in html
    assert "preview card" in html
    assert "Captured role history" in html
    assert 'id="role_experience_readonly"' in html
    assert 'id="refresh_role_history_from_saved_cv"' in html
    assert "Refresh from saved CV" in html
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert f"v{version}" in html
    assert "Preview" not in html
    assert ">TEST<" not in html
    assert "job-hunter-page-utility__release-stage" not in html


def test_settings_capability_editor_preserves_icon_key_state():
    repo_root = Path(__file__).resolve().parents[1]
    js_text = (
        repo_root / "templates" / "static" / "settings" / "shared" / "settings-capability-editor.js"
    ).read_text(encoding="utf-8")

    assert "icon_key: String(rule?.icon_key || '').trim().toLowerCase()," in js_text
    assert "icon_key: genericCapabilityIconKey" in js_text
    assert "genericCapabilityIconKey = capabilityUi.genericCapabilityIconKey;" in js_text
    assert "Missing generic capability icon key." in js_text
    assert "data-toggle-capability-selection" in js_text
    assert "data-select-visible-capabilities" in js_text
    assert "capability-alias-preview" in js_text
    assert "settings_selected_copy" in js_text
    assert "settings_remove_selected_label" in js_text


def test_settings_page_renders_role_history_readonly_panel_script():
    repo_root = Path(__file__).resolve().parents[1]
    js_text = (
        repo_root / "templates" / "static" / "settings" / "shared" / "settings-page.js"
    ).read_text(encoding="utf-8")

    assert "function renderRoleExperienceReadonly(profile)" in js_text
    assert "function renderCapturedCvText(sourceMaterials)" in js_text
    assert "/api/source-materials" in js_text
    assert "renderCapturedCvText(materials);" in js_text
    assert "profile?.cv_text" not in js_text
    assert "loadSourceMaterials().catch(() => null)" not in js_text
    assert "data-clear-clearance" not in js_text
    assert "clearClearanceRule" not in js_text
    assert "renderRoleExperienceReadonly(profile);" in js_text
    assert "role_experience_readonly" in js_text
    assert "/api/profile/refresh-role-history-from-saved-cv" in js_text
    assert "refresh_role_history_from_saved_cv" in js_text


def test_settings_utils_review_normaliser_preserves_icon_key():
    repo_root = Path(__file__).resolve().parents[1]
    js_text = (
        repo_root / "templates" / "static" / "settings" / "shared" / "settings-utils.js"
    ).read_text(encoding="utf-8")

    assert "const icon_key = normalizeReviewText(rule?.icon_key || '').toLowerCase();" in js_text
    assert "return { name, level, aliases, icon_key };" in js_text


def test_settings_utils_does_not_add_redundant_toggle_state_text():
    repo_root = Path(__file__).resolve().parents[1]
    js_text = (
        repo_root / "templates" / "static" / "settings" / "shared" / "settings-utils.js"
    ).read_text(encoding="utf-8")

    assert "setToggleStateText" not in js_text


def test_admin_settings_script_exposes_system_warnings_controls():
    repo_root = Path(__file__).resolve().parents[1]
    js_text = (
        repo_root / "templates" / "static" / "settings" / "global" / "settings-admin.js"
    ).read_text(encoding="utf-8")

    assert "initRuntimeMaintenanceControls" in js_text
    assert "/api/admin/clear-runtime-caches" in js_text
    assert "/api/admin/clear-candidate-application-history" in js_text
    assert "/api/admin/clear-current-user-search-state" in js_text
    assert "initSystemWarningsControls" in js_text
    assert "/api/admin/system-warnings" in js_text
    assert "window.__JOB_HUNTER_SYSTEM_HEALTH_LABELS__" in js_text
    assert "system_health_diagnostics_show_label" in js_text
    assert "renderSystemDiagnosticGroup" in js_text
    assert "system_health_acknowledge_label" in js_text
    assert "data-system-warning-action=\"acknowledge\"" in js_text
    assert "data-system-warning-action=\"review\"" not in js_text
    assert "data-system-warning-action=\"dismiss\"" not in js_text
    assert "data-system-warning-action=\"resolve\"" not in js_text
    assert "Mark resolved" not in js_text
    assert "Run scraper validation" not in js_text
    assert "initScraperValidationControls" in js_text
    assert "/api/admin/scraper-config-validation" in js_text


def test_global_settings_page_renders_system_warnings_panel(monkeypatch):
    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {"user_id": "test-user", "email": "test@example.com", "role": "admin"},
    )
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "is_admin", lambda request: True)
    monkeypatch.setattr(_pages, "read_session_user", lambda request: {"user_id": "test-user", "email": "test@example.com", "role": "admin"})

    client = TestClient(create_app())
    html = client.get("/global-settings").text

    assert 'id="runtime_maintenance_panel"' in html
    assert 'id="clear_runtime_caches_button"' in html
    assert 'id="clear_current_user_search_state_button"' in html
    assert 'id="clear_candidate_application_history_button"' in html
    assert "The next sync will reprocess the Google Sheet" in html
    assert "It does not delete imported Rejection History" in html
    assert 'id="history_job_history_max_entries"' in html
    assert 'id="history_job_history_max_age_days"' in html
    assert 'id="cache_llm_cache_max_entries"' in html
    assert 'id="cache_llm_cache_max_age_days"' in html
    assert 'id="cache_candidate_application_history_cache_max_age_days"' in html
    assert 'id="cache_occupation_title_cache_max_age_days"' in html
    assert 'id="system_warnings_panel"' in html
    assert 'id="system_warnings_list"' in html
    assert 'id="system_warnings_refresh_button"' in html
    assert 'id="system_diagnostics_toggle_button"' in html
    assert 'id="system_diagnostics_section"' in html
    assert 'id="system_diagnostics_list"' in html
    assert "System health" in html
    assert "Show technical diagnostics" in html
    assert "__JOB_HUNTER_GLOBAL_SETTINGS_SYSTEM_HEALTH_" not in html
    assert "window.__JOB_HUNTER_SYSTEM_HEALTH_LABELS__" in html
    assert 'id="scraper_validation_panel"' in html
    assert 'id="scraper_validation_button"' in html
    assert 'id="scraper_validation_results"' in html
