"""Tests for settings template."""

import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.fastapi_app import create_app

ROOT_DIR = Path(__file__).resolve().parent.parent

SETTINGS_ADMIN_PARTIAL_PATH = (
    ROOT_DIR / "templates" / "partials" / "settings" / "global" / "settings-admin.html"
)
SETTINGS_PAGE_CSS_PATH = (
    ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-page.css"
)
SIGNAL_REGISTRY_JS_PATH = (
    ROOT_DIR / "templates" / "static" / "settings" / "learning" / "signal-registry.js"
)
THEME_WIDGETS_CSS_PATH = ROOT_DIR / "templates" / "static" / "theme" / "themes.widgets.css"
SETTINGS_TEMPLATE_PATH = ROOT_DIR / "templates" / "settings.html"
ONBOARDING_REVIEW_CSS_PATH = (
    ROOT_DIR / "templates" / "static" / "onboarding" / "onboarding-review.css"
)
SETTINGS_SEARCH_PARTIAL_PATH = (
    ROOT_DIR / "templates" / "partials" / "settings" / "standard" / "settings-search.html"
)
SETTINGS_PROFILE_PARTIAL_PATH = (
    ROOT_DIR / "templates" / "partials" / "settings" / "standard" / "settings-profile.html"
)
SETTINGS_ADMIN_JS_PATH = (
    ROOT_DIR / "templates" / "static" / "settings" / "global" / "settings-admin.js"
)
AWS_BROWSER_SESSION_START_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "start-aws-browser-session.sh"
LEGACY_AWS_BROWSER_SESSION_WRAPPER = ROOT_DIR / "scripts" / "ec2" / "run-jobhunter-browser-session.sh"
JOB_HUNTER_SERVICE_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "job-hunter.service"
JOB_HUNTER_SERVICE_INSTALL_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "install-jobhunter-service.sh"
AWS_BROWSER_SESSION_INSTALL_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "install-aws-browser-session.sh"
AWS_BROWSER_SESSION_SMOKE_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "smoke-seek-aws-browser-session.sh"
AWS_DEPLOY_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "deploy-jobhunter-release.sh"


def test_source_document_suffixes_are_rendered_read_only():

    html = SETTINGS_ADMIN_PARTIAL_PATH.read_text(encoding="utf-8")

    assert 'id="source_document_allowed_suffixes"' in html

    assert 'readonly aria-readonly="true"' in html

    assert "Allowed CV file suffixes" in html

    assert "CV Files" in html


def test_global_settings_admin_exposes_managed_llm_temperature():
    html = SETTINGS_ADMIN_PARTIAL_PATH.read_text(encoding="utf-8")
    js = SETTINGS_ADMIN_JS_PATH.read_text(encoding="utf-8")

    assert 'id="llm_temperature"' in html
    assert "__JOB_HUNTER_GLOBAL_SETTINGS_LLM_TEMPERATURE_LABEL__" in html
    assert "__JOB_HUNTER_GLOBAL_SETTINGS_LLM_TEMPERATURE_HELP__" in html
    assert "setFieldValue('llm_temperature', llmSettings.temperature)" in js
    assert "temperature: readNumber('llm_temperature', currentLlmSettings.temperature)" in js


def test_global_settings_admin_js_handles_seek_assisted_verification_toggle():
    js = SETTINGS_ADMIN_JS_PATH.read_text(encoding="utf-8")

    assert "seek_assisted_verification_enabled" in js
    assert "playwrightSettings.seek_assisted_verification_enabled === true" in js
    assert "document.getElementById('seek_assisted_verification_enabled').checked" in js
    assert "seek_manual_verification_timeout_ms" in js
    assert "playwrightSettings.seek_manual_verification_timeout_ms" in js
    assert "readSecondsAsMilliseconds(" in js
    assert "playwright_browser_mode" in js
    assert "playwrightSettings.playwright_browser_mode || 'persistent'" in js
    assert "playwright_browser_mode:" in js


def test_global_settings_page_renders_admin_partial(monkeypatch):

    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )

    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)

    monkeypatch.setattr(_pages, "is_admin", lambda request: True)

    client = TestClient(create_app())

    html = client.get("/global-settings").text

    assert "Global settings" in html

    assert 'id="knowledge_sync_button"' in html
    assert "Sync knowledge with AWS" in html

    assert 'id="source_document_allowed_suffixes"' in html
    assert 'id="playwright_browser_mode"' in html
    assert 'id="seek_assisted_verification_enabled"' in html
    assert 'id="seek_manual_verification_timeout_ms"' in html
    assert "SEEK manual verification wait (seconds)" in html
    assert "linkedin_fetch_timeout_seconds" not in html
    assert 'id="search_default_linkedin_jobspy_stall_timeout_seconds"' in html
    assert "It does not limit total LinkedIn runtime" in html
    assert 'id="search_default_linkedin_parallel_review_workers"' in html
    assert '<option value="persistent">Persistent</option>' in html
    assert 'href="/aws-browser-session"' in html
    assert "Open AWS browser session instructions" in html

    assert "account-bar-shortcut" not in html

    assert 'class="nav-item nav-item-workspace">↩ Workspace</a>' in html

    assert "__JOB_HUNTER_SETTINGS_SECTION_" not in html


def test_aws_browser_session_page_renders_admin_instructions(monkeypatch):
    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )

    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "is_admin", lambda request: True)

    client = TestClient(create_app())

    html = client.get("/aws-browser-session").text

    assert "AWS browser session" in html
    assert "Open the secure browser tunnel from here when SEEK asks for human verification." in html
    assert "no SSH tunnel or local setup required" in html
    assert "/aws-novnc/vnc.html?autoconnect=1" in html
    assert "websockify" in html


def test_aws_browser_session_scripts_are_committed():
    start_script = AWS_BROWSER_SESSION_START_SCRIPT.read_text(encoding="utf-8")
    install_script = AWS_BROWSER_SESSION_INSTALL_SCRIPT.read_text(encoding="utf-8")
    smoke_script = AWS_BROWSER_SESSION_SMOKE_SCRIPT.read_text(encoding="utf-8")
    deploy_script = AWS_DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "Xvfb" in start_script
    assert "openbox" in start_script
    assert "x11vnc" in start_script
    assert "websockify" in start_script
    assert "playwright_user_data" in start_script
    assert "set -- uv run python -m job_hunter_agent.fastapi_app --rebuild" in start_script
    assert "aws browser-session dependencies" in install_script.lower()
    assert "JOB_HUNTER_SMOKE_SEEK_URL" in smoke_script
    assert "cards=" in smoke_script
    assert "Startup rebuild refreshes saved workspace output" in deploy_script
    assert "curl -fsSI" in deploy_script
    assert not LEGACY_AWS_BROWSER_SESSION_WRAPPER.exists()
    service_text = JOB_HUNTER_SERVICE_SCRIPT.read_text(encoding="utf-8")
    assert "start-aws-browser-session.sh" in service_text
    assert "SuccessExitStatus=143" in service_text
    assert "/home/ubuntu/.local/bin" in service_text
    assert "run-jobhunter-browser-session.sh" not in JOB_HUNTER_SERVICE_SCRIPT.read_text(encoding="utf-8")
    assert "start-aws-browser-session.sh" in JOB_HUNTER_SERVICE_INSTALL_SCRIPT.read_text(encoding="utf-8")


def test_aws_browser_session_page_redirects_non_admin(monkeypatch):
    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {
            "user_id": "test",
            "email": "test@example.com",
            "role": "candidate",
            "access_status": "approved",
        },
    )
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")
    monkeypatch.setattr(_pages, "is_admin", lambda request: False)

    client = TestClient(create_app())

    response = client.get("/aws-browser-session", follow_redirects=False)

    assert response.status_code == 302
    assert "/login?next=%2Faws-browser-session" in response.headers["location"]


def test_signal_registry_value_editor_fills_column_and_auto_grows():
    css = SETTINGS_PAGE_CSS_PATH.read_text(encoding="utf-8")
    js = SIGNAL_REGISTRY_JS_PATH.read_text(encoding="utf-8-sig")

    value_field = re.search(r"\.signal-value-field \{(?P<body>.*?)\n    \}", css, re.S)
    assert value_field is not None
    assert "flex: 1 1 auto;" in value_field.group("body")
    assert "width: 100%;" in value_field.group("body")

    value_input = re.search(r"\.signal-value-input \{(?P<body>.*?)\n    \}", css, re.S)
    assert value_input is not None
    assert "width: 100%;" in value_input.group("body")
    assert "resize: vertical;" in value_input.group("body")
    assert "overflow-y: hidden;" in value_input.group("body")
    assert "overflow-wrap: anywhere;" in value_input.group("body")

    assert "function srResizeSignalValueInput(input)" in js
    assert "input.style.height = 'auto';" in js
    assert "input.style.height = `${input.scrollHeight}px`;" in js
    assert "window.addEventListener('resize', srResizeSignalValueInputs);" in js


def test_signals_requirement_review_uses_consistent_labels_subtype_and_wide_layout():
    css = SETTINGS_PAGE_CSS_PATH.read_text(encoding="utf-8")
    js = SIGNAL_REGISTRY_JS_PATH.read_text(encoding="utf-8-sig")
    tokens = (ROOT_DIR / "templates" / "static" / "theme" / "themes.tokens.css").read_text(
        encoding="utf-8"
    )

    assert "--content-shell-max-width: 1360px;" in tokens
    assert ".settings-content-area:has(#section-learning.is-active)" in css
    assert "max-width: var(--content-shell-max-width);" in css
    assert "signal-requirement-subtype-field" in css
    assert "srRequirementReviewComplete(article, category)" in js
    assert "suggested_requirement_type" in js
    assert "suggested_requirement_subtype" in js
    assert "signal-requirement-subtype-select" in js
    assert "isRequirementReview" in js
    assert "? srRequirementTypeControlHtml(signal, category, isBusy)" in js
    assert "valueFieldLabel = isRequirementReview ? srFieldLabel('requirement') : srFieldLabel('signal')" in js


def test_profile_settings_groups_clearances_under_eligibility_and_keeps_qualifications_separate():
    html = (ROOT_DIR / "templates" / "partials" / "settings" / "standard" / "settings-matrix.html").read_text(
        encoding="utf-8"
    )

    assert html.count('class="subpanel search-settings-subcard eligibility-settings-card"') == 1
    assert 'id="eligibility_group_title"' in html
    assert 'id="clearance_editor"' in html
    assert 'id="eligibility_editor"' in html
    assert 'id="qualification_editor"' in html
    eligibility_start = html.index('id="eligibility_group_title"')
    qualification_start = html.index('id="qualification_editor_title"')
    assert eligibility_start < html.index('id="clearance_editor"') < qualification_start
    assert eligibility_start < html.index('id="eligibility_editor"') < qualification_start


def test_global_settings_layout_css_prevents_panel_overflow():

    css = SETTINGS_PAGE_CSS_PATH.read_text(encoding="utf-8")

    assert ".admin-settings-grid {" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(390px, 1fr));" in css
    assert "gap: var(--surface-gap-lg);" in css
    assert ".admin-settings-grid > .panel {" in css
    assert "min-width: 0;" in css
    assert ".admin-settings-grid > .panel > .panel-header {" in css
    assert ".admin-settings-grid > .panel > .panel-header > h2 {" in css
    assert ".admin-settings-grid > .panel > .panel-header > .panel-copy {" in css
    assert ".panel-copy {" in css
    assert "overflow-wrap: anywhere;" in css
    assert ".subpanel .field-help {" in css


def test_capability_matrix_group_owns_spacing_below_help_copy():

    css = SETTINGS_PAGE_CSS_PATH.read_text(encoding="utf-8")

    assert ".capability-group {" in css
    assert "gap: var(--surface-gap-md);" in css
    assert "margin-top: var(--surface-gap-md);" in css
    assert ".capability-toolbar {" in css
    assert "margin-bottom: 0;" in css


def test_search_settings_location_listbox_uses_shared_dark_multiselect_styles():

    search_html = SETTINGS_SEARCH_PARTIAL_PATH.read_text(encoding="utf-8")
    widgets_css = THEME_WIDGETS_CSS_PATH.read_text(encoding="utf-8")
    settings_css = SETTINGS_PAGE_CSS_PATH.read_text(encoding="utf-8")

    assert 'id="locations" class="checkbox-list-grid location-checkbox-grid" role="group"' in search_html
    assert ".jh-select[multiple] {" in widgets_css
    assert "background-image: none;" in widgets_css
    assert "scrollbar-gutter: stable;" in widgets_css
    assert "color-scheme: dark;" in widgets_css
    assert "scrollbar-width: thin;" in widgets_css
    assert (
        "scrollbar-color: color-mix(in srgb, var(--text-muted) 55%, transparent) transparent;"
        in widgets_css
    )
    assert ".jh-select[multiple]::-webkit-scrollbar {" in widgets_css
    assert ".search-settings-grid .settings-form-grid--search-basics {" in settings_css
    assert "column-gap: var(--surface-gap-lg);" in settings_css


def test_search_settings_stack_does_not_add_extra_top_gap_below_section_head():

    widgets_css = THEME_WIDGETS_CSS_PATH.read_text(encoding="utf-8")

    assert ".settings-section-shell {" in widgets_css
    assert ".search-settings-stack {\n  display: grid;\n  gap: var(--field-stack-gap);\n  margin-top: 0;\n}" in widgets_css


def test_profile_cv_debug_drawer_avoids_duplicate_visible_heading():

    profile_html = SETTINGS_PROFILE_PARTIAL_PATH.read_text(encoding="utf-8")

    assert "<summary>Captured CV text</summary>" in profile_html
    assert 'data-test-only' not in profile_html
    assert '<label for="cv_text_debug">Captured CV text</label>' not in profile_html
    assert 'id="cv_text_debug" class="is-readonly" aria-label="Captured CV text"' in profile_html


def test_onboarding_review_css_documents_final_summary_local_exception():
    css = ONBOARDING_REVIEW_CSS_PATH.read_text(encoding="utf-8")

    assert (
        "Local layout exception: final onboarding summary label/value layout, not a reusable visual component."
        in css
    )


def test_settings_exposes_adjacent_role_exploration_switch():
    html = (
        ROOT_DIR / "templates" / "partials" / "settings" / "standard" / "settings-matrix.html"
    ).read_text(encoding="utf-8")
    js = (ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-page.js").read_text(encoding="utf-8")

    assert 'id="explore_adjacent_roles" type="checkbox" role="switch"' in html
    assert '__JOB_HUNTER_TITLE_TIER_EXPLORE_ADJACENT_ROLES_LABEL__' in html
    assert '__JOB_HUNTER_TITLE_TIER_EXPLORE_ADJACENT_ROLES_HELP__' in html
    assert '<details class="field-info-drawer">' in html
    assert '<span class="field-help">__JOB_HUNTER_TITLE_TIER_EXPLORE_ADJACENT_ROLES_HELP__</span>' not in html
    assert 'toggle-switch-state' not in html
    assert "explore_adjacent_roles: getToggleChecked('explore_adjacent_roles')" in js
    assert "setToggleChecked('explore_adjacent_roles', Boolean(profile.explore_adjacent_roles))" in js


def test_role_history_uses_single_readonly_panel():

    html = (
        ROOT_DIR / "templates" / "partials" / "settings" / "standard" / "settings-matrix.html"
    ).read_text(encoding="utf-8")

    assert 'id="role_experience_readonly" class="capability-editor role-history-editor"' in html


def test_settings_page_renders_admin_link_only_for_admins(monkeypatch):

    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )

    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)

    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())

    monkeypatch.setattr(_pages, "is_admin", lambda request: True)

    admin_html = client.get("/settings").text

    assert "Job Hunter searches each preferred and alternative role separately" in admin_html
    assert "__JOB_HUNTER_TITLE_TIER_ROLE_SEARCH_HELP__" not in admin_html
    assert 'class="sidebar-admin-badge"' in admin_html

    assert 'href="/global-settings"' in admin_html

    assert "sidebar-group-label-global" in admin_html

    assert "__JOB_HUNTER_ADMIN_NAV_GROUP__" not in admin_html

    monkeypatch.setattr(_pages, "is_admin", lambda request: False)

    candidate_html = client.get("/settings").text

    assert 'class="sidebar-admin-badge"' not in candidate_html

    assert 'href="/global-settings"' not in candidate_html

    assert "sidebar-group-label-global" not in candidate_html

    assert "__JOB_HUNTER_ADMIN_NAV_GROUP__" not in candidate_html


def test_settings_search_section_uses_shared_choice_strip_widget(monkeypatch):
    session_user = {"user_id": "test", "email": "test@example.com", "role": "admin"}

    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: session_user,
    )
    monkeypatch.setattr(_pages, "read_session_user", lambda request: session_user)

    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)

    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())

    html = client.get("/settings").text

    assert 'class="section-title"' not in html

    assert 'id="settings_page_title"' not in html

    assert 'id="settings_page_copy"' not in html

    assert '<section class="hero">' not in html

    assert "data-settings-hero-title=" not in html

    assert "data-settings-hero-copy=" not in html

    assert 'class="panel search-settings-shell settings-section-shell"' in html

    assert 'class="settings-section-head"' in html

    assert "Search Settings" in html
    assert "Sydney means a city search on SEEK" in html
    assert "50-mile radius on LinkedIn" in html
    assert "CV data and privacy" in html
    assert "The raw CV is not the long-term source of truth" in html
    assert "Job board search" in html
    assert 'class="panel search-operations-panel"' not in html
    assert 'class="subpanel search-settings-subcard search-operations-panel"' in html
    schedule_panel = html.split('id="schedule-panel"', 1)[1].split('</section>', 1)[0]
    assert 'class="settings-section-head search-operations-head"' in schedule_panel
    assert '<h3>Run & Schedule</h3>' in schedule_panel
    assert 'These controls use your current search settings.' in schedule_panel
    assert schedule_panel.index('settings-section-head search-operations-head') < schedule_panel.index('search-operations-body')

    assert "search-common-panel" not in html

    assert "common-search-grid" not in html

    assert "common-search-field" not in html

    assert "common-search-field--keywords" not in html

    assert "settings-form-grid--three-col" not in html

    assert "settings-form-field--span-2" not in html

    assert 'class="choice-strip jh-choice-group"' in html

    assert 'class="choice-card jh-choice choice-card--work-mode"' in html
    assert 'name="work_mode_preference" value="remote" checked' in html
    assert 'name="work_mode_preference" value="hybrid" checked' in html
    assert 'name="work_mode_preference" value="onsite" checked' in html

    assert 'input type="checkbox" name="engagement_type"' in html

    assert 'select id="engagement_type"' not in html

    assert "Include SEEK in search" in html

    assert "Include LinkedIn in search" in html

    assert ">+<" in html

    assert 'data-chip-editor="keywords"' not in html

    assert 'id="keywords"' not in html

    assert "Search keyword" not in html

    assert "Preferred roles" in html

    assert "Alternative roles" in html

    assert 'id="seek_max_pages_choices"' in html

    assert "field-control-shell" in html

    assert 'id="prefer_sector_choices"' in html

    assert 'class="choice-card jh-choice choice-card--work-mode"' in html

    assert 'select id="sector_preference"' not in html


def test_capability_help_text_explains_matching_weight():
    labels_path = ROOT_DIR / "data" / "knowledge" / "ui_labels.json"
    ui_labels = json.loads(labels_path.read_text(encoding="utf-8"))
    help_text = ui_labels["capability_ui_labels"]["help_text"]

    assert "the strength you choose changes how much each capability influences matching" in help_text.lower()
    assert "strong for your best evidence" in help_text.lower()


def test_settings_review_panel_empty_state_copy_is_defined():

    js_path = ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-review-panel.js"
    labels_path = ROOT_DIR / "data" / "knowledge" / "ui_labels.json"

    js = js_path.read_text(encoding="utf-8")
    ui_labels = json.loads(labels_path.read_text(encoding="utf-8"))

    assert "No new capabilities to verify." in js
    assert "Capabilities to verify" not in js
    assert "Search & filter improvements" in js
    assert "Why Job Hunter suggested this" in js
    assert "review_suggestions_count" in js
    assert "What this choice means" not in js

    assert "const DECLINE_CAPABILITY_LABEL = capabilityLabels.decline_capability_label;" in js
    assert ui_labels["workspace_card_labels"]["gap_confirm_not_have_label"]

    assert "decline-skill-btn" in js

    assert "applyOneSkipDecision(skill, 'dismiss')" in js


def test_settings_matrix_section_omits_outer_panel_wrapper(monkeypatch):

    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )

    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)

    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())

    html = client.get("/settings").text

    assert '<h2 class="section-title" id="capability_matrix_section_title"></h2>' not in html

    assert 'class="panel advanced-shell settings-section-shell"' in html

    assert "data-settings-hero-title=" not in html

    assert "data-settings-hero-copy=" not in html

    assert "Decision Weights" in html
    assert 'id="capability_matrix_copy"' in html
    assert 'id="capability_matrix_actions"' in html


def test_settings_sidebar_has_client_side_section_search():
    html = SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8")
    labels = json.loads((ROOT_DIR / "data" / "knowledge" / "ui_labels.json").read_text(encoding="utf-8"))
    js = (
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-page.js"
    ).read_text(encoding="utf-8")
    css = SETTINGS_PAGE_CSS_PATH.read_text(encoding="utf-8")

    assert 'id="settings_section_search"' in html
    assert "__JOB_HUNTER_SETTINGS_SECTION_SEARCH_LABEL__" in html
    assert "__JOB_HUNTER_SETTINGS_SECTION_SEARCH_PLACEHOLDER__" in html
    assert labels["shared_ui_labels"]["settings_section_search_label"] == "Find setting"
    assert labels["shared_ui_labels"]["settings_section_search_placeholder"] == "Search settings"
    assert labels["shared_ui_labels"]["settings_saved_success"] == "Settings saved successfully."
    assert labels["shared_ui_labels"]["settings_saved_changes_heading"] == "Changed:"
    assert "applySettingsSectionSearch" in js
    assert "settingsSectionSearchHaystack" in js
    assert "group.classList.remove('is-active');" in js
    assert "saveActivePage()" in js
    assert "buildCandidateSettingsSaveMessage" in js
    assert "showStatus(sharedUiLabels.settings_saved_success, 'success');" in js
    assert "settings_saved_no_effective_changes" in js
    assert "el.id === 'settings_section_search'" in js
    assert ".settings-sidebar-search" in css
    assert ".settings-group.is-search-result" in css
    assert ".settings-privacy-note" in css


def test_search_settings_partial_has_privacy_subcards_and_shared_save_bar():
    html = SETTINGS_SEARCH_PARTIAL_PATH.read_text(encoding="utf-8")
    labels = json.loads((ROOT_DIR / "data" / "knowledge" / "ui_labels.json").read_text(encoding="utf-8"))
    js = (
        ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-page.js"
    ).read_text(encoding="utf-8")

    assert 'class="panel search-settings-shell settings-section-shell"' in html
    assert 'class="subpanel search-settings-subcard settings-privacy-note"' in html
    assert "__JOB_HUNTER_SETTINGS_PRIVACY_TITLE__" in html
    assert "__JOB_HUNTER_SETTINGS_PRIVACY_COPY__" in html
    assert labels["shared_ui_labels"]["settings_privacy_title"] == "CV data and privacy"
    assert "raw CV is not the long-term source of truth" in labels["shared_ui_labels"]["settings_privacy_copy"]

    assert "saveActivePage()" in js
    assert 'id="save_search_settings_shortcut"' not in html
    assert 'id="apsjobs_locations"' not in html
    assert 'id="locations"' in html
    assert 'class="checkbox-list-grid location-checkbox-grid" role="group"' in html
    assert 'id="seek_quick_apply_only"' in html
    assert "Quick Apply only" in html
    common_location_js = (
        ROOT_DIR / "templates" / "static" / "common" / "location-options.js"
    ).read_text(encoding="utf-8")
    assert "renderLocationCheckboxOptions" in js
    assert "syncLocationSelectionLimit" in common_location_js

    assert 'class="panel search-operations-panel"' not in html
    assert 'class="subpanel search-settings-subcard search-operations-panel"' in html


def test_settings_alerts_section_uses_shared_settings_shell(monkeypatch):

    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )

    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)

    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())

    html = client.get("/settings").text

    assert 'class="panel alerts-shell settings-section-shell"' in html

    assert 'class="settings-section-head"' in html

    assert 'id="settings_alerts_labels_json"' in html

    assert 'id="telegram_enabled"' in html

    assert 'id="telegram_connect_panel"' in html

    assert 'id="refresh_telegram_connection"' in html

    assert 'id="agent_tokens_panel"' in html

    assert 'id="generate_agent_token"' in html

    assert 'id="agent_token_secret"' in html

    assert 'id="copy_agent_token"' in html

    assert "Notifications" in html

    assert "__JOB_HUNTER_SETTINGS_ALERTS_SECTION_TITLE__" not in html

    assert "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_HEADING__" not in html


def test_global_settings_js_required_elements_exist_in_rendered_page(monkeypatch):
    """Every element ID that settings-admin.js requires must exist in the rendered page.

    This catches the class of bug where requireElement()/setFieldValue()/setFieldText()
    references an ID that was removed or renamed in the HTML partial.
    """
    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "is_admin", lambda request: True)

    js = SETTINGS_ADMIN_JS_PATH.read_text(encoding="utf-8")
    # Extract static string literals passed to requireElement / setFieldValue / setFieldText.
    # Dynamic IDs built with string concatenation (e.g. 'search_default_' + VAR) are excluded
    # because the regex only captures single-quoted literals with no embedded +.
    ids = set(re.findall(r"(?:requireElement|setFieldValue|setFieldText)\('([^']+)'", js))
    # Remove dynamic IDs: only keep clean lowercase identifiers that don't end with '_'
    # (trailing '_' indicates a prefix fragment that gets concatenated with a variable).
    ids = {i for i in ids if re.match(r"^[a-z0-9_]+$", i) and not i.endswith("_")}

    client = TestClient(create_app())
    html = client.get("/global-settings").text

    missing = [i for i in sorted(ids) if f'id="{i}"' not in html]
    assert not missing, (
        f"Elements required by settings-admin.js are missing from /global-settings: {missing}"
    )

def test_admin_hydrates_parallel_worker_limit_inputs_before_save():
    js = SETTINGS_ADMIN_JS_PATH.read_text(encoding="utf-8")

    assert "setFieldValue('search_limit_linkedin_parallel_search_workers_min', searchLimits.linkedin_parallel_search_workers?.min);" in js
    assert "setFieldValue('search_limit_linkedin_parallel_search_workers_max', searchLimits.linkedin_parallel_search_workers?.max);" in js
    assert "min: readNumber('search_limit_linkedin_parallel_search_workers_min'" in js
    assert "max: readNumber('search_limit_linkedin_parallel_search_workers_max'" in js
    assert "setFieldValue('search_limit_linkedin_parallel_review_workers_min', searchLimits.linkedin_parallel_review_workers?.min);" in js
    assert "setFieldValue('search_limit_linkedin_parallel_review_workers_max', searchLimits.linkedin_parallel_review_workers?.max);" in js
    assert "min: readNumber('search_limit_linkedin_parallel_review_workers_min'" in js
    assert "max: readNumber('search_limit_linkedin_parallel_review_workers_max'" in js


def test_settings_review_panel_separates_factual_absence_from_dismiss():
    js = (
        ROOT_DIR
        / "templates"
        / "static"
        / "settings"
        / "shared"
        / "settings-review-panel.js"
    ).read_text(encoding="utf-8")
    ui_labels = json.loads(
        (ROOT_DIR / "data" / "knowledge" / "ui_labels.json").read_text(encoding="utf-8")
    )

    assert "do-not-have-skill-btn" in js
    assert "decline-skill-btn" in js
    assert "applyOneSkipDecision(skill, 'do_not_have')" in js
    assert "applyOneSkipDecision(skill, 'dismiss')" in js
    assert ui_labels["workspace_card_labels"]["gap_confirm_not_have_label"] == "No, I don't have this"
    assert ui_labels["capability_ui_labels"]["dismiss_capability_suggestion_label"] == "Ignore suggestion"
