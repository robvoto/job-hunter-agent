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
SETTINGS_TEMPLATE_PATH = ROOT_DIR / "templates" / "settings.html"
SETTINGS_SEARCH_PARTIAL_PATH = (
    ROOT_DIR / "templates" / "partials" / "settings" / "standard" / "settings-search.html"
)
SETTINGS_ADMIN_JS_PATH = (
    ROOT_DIR / "templates" / "static" / "settings" / "global" / "settings-admin.js"
)
AWS_BROWSER_SESSION_START_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "start-aws-browser-session.sh"
AWS_BROWSER_SESSION_INSTALL_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "install-aws-browser-session.sh"
AWS_BROWSER_SESSION_SMOKE_SCRIPT = ROOT_DIR / "scripts" / "ec2" / "smoke-seek-aws-browser-session.sh"


def test_source_document_suffixes_are_rendered_read_only():

    html = SETTINGS_ADMIN_PARTIAL_PATH.read_text(encoding="utf-8")

    assert 'id="source_document_allowed_suffixes"' in html

    assert 'readonly aria-readonly="true"' in html

    assert "Allowed CV file suffixes" in html

    assert "CV Files" in html


def test_global_settings_admin_js_handles_seek_assisted_verification_toggle():
    js = SETTINGS_ADMIN_JS_PATH.read_text(encoding="utf-8")

    assert "seek_assisted_verification_enabled" in js
    assert "playwrightSettings.seek_assisted_verification_enabled === true" in js
    assert "document.getElementById('seek_assisted_verification_enabled').checked" in js
    assert "playwright_browser_mode" in js
    assert "playwrightSettings.playwright_browser_mode || 'ephemeral'" in js
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

    assert "Xvfb" in start_script
    assert "openbox" in start_script
    assert "x11vnc" in start_script
    assert "websockify" in start_script
    assert "playwright_user_data" in start_script
    assert "aws browser-session dependencies" in install_script.lower()
    assert "JOB_HUNTER_SMOKE_SEEK_URL" in smoke_script
    assert "cards=" in smoke_script


def test_aws_browser_session_page_redirects_non_admin(monkeypatch):
    monkeypatch.setattr(
        _fa,
        "read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "candidate"},
    )
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")
    monkeypatch.setattr(_pages, "is_admin", lambda request: False)

    client = TestClient(create_app())

    response = client.get("/aws-browser-session", follow_redirects=False)

    assert response.status_code == 302
    assert "/login?next=%2Faws-browser-session" in response.headers["location"]


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
    assert "CV data and privacy" in html
    assert "The raw CV is not the long-term source of truth" in html
    assert "Job board search" in html
    assert 'class="panel search-operations-panel"' not in html
    assert 'class="subpanel search-settings-subcard search-operations-panel"' in html

    assert "search-common-panel" not in html

    assert "common-search-grid" not in html

    assert "common-search-field" not in html

    assert "common-search-field--keywords" not in html

    assert "settings-form-grid--three-col" not in html

    assert "settings-form-field--span-2" not in html

    assert 'class="choice-strip"' in html

    assert 'class="choice-card choice-card--work-mode"' in html
    assert 'name="work_mode_preference" value="remote" checked' in html
    assert 'name="work_mode_preference" value="hybrid" checked' in html
    assert 'name="work_mode_preference" value="onsite" checked' in html

    assert 'input type="checkbox" name="engagement_type"' in html

    assert 'select id="engagement_type"' not in html

    assert "Include SEEK in search" in html

    assert "Include LinkedIn in search" in html

    assert ">+<" in html

    assert 'id="keywords"' in html

    assert 'data-chip-editor="keywords"' not in html

    assert "Search keyword" in html

    assert 'placeholder="e.g. Business Analyst"' in html

    assert 'id="seek_max_pages_choices"' in html

    assert "field-control-shell" in html

    assert 'id="prefer_sector_choices"' in html

    assert 'class="choice-card choice-card--work-mode"' in html

    assert 'select id="sector_preference"' not in html


def test_capability_help_text_explains_matching_weight():
    labels_path = ROOT_DIR / "data" / "knowledge" / "ui_labels.json"
    ui_labels = json.loads(labels_path.read_text(encoding="utf-8"))
    help_text = ui_labels["capability_ui_labels"]["help_text"]

    assert "the strength you choose changes how much each capability influences matching" in help_text.lower()
    assert "strong for your best evidence" in help_text.lower()


def test_settings_review_panel_empty_state_copy_is_defined():

    js_path = ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-review-panel.js"

    js = js_path.read_text(encoding="utf-8")

    assert (
        "No capability suggestions yet. We found no saved review data from the latest search. Run a search again so kept jobs can be analysed for new capability signals."
        in js
    )

    assert (
        "No capability suggestions yet. We found kept jobs, but no new capability observations were extracted from them."
        in js
    )

    assert "Requirements to address" in js

    assert "Do you have this capability?" in js

    assert "Search/title tuning" in js

    assert "Filters already working correctly" in js


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
    assert "applySettingsSectionSearch" in js
    assert "settingsSectionSearchHaystack" in js
    assert "group.classList.remove('is-active');" in js
    assert "saveActivePage()" in js
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

    assert "Alerts &amp; AI" in html

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
