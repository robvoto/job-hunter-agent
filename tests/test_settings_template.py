from pathlib import Path

from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.fastapi_app import create_app


ROOT_DIR = Path(__file__).resolve().parent.parent
SETTINGS_ADMIN_PARTIAL_PATH = ROOT_DIR / "templates" / "partials" / "settings" / "global" / "settings-admin.html"


def test_source_document_suffixes_are_rendered_read_only():
    html = SETTINGS_ADMIN_PARTIAL_PATH.read_text(encoding="utf-8")

    assert 'id="source_document_allowed_suffixes"' in html
    assert 'readonly aria-readonly="true"' in html
    assert "Allowed CV file suffixes" in html
    assert "CV Files" in html


def test_global_settings_page_renders_admin_partial(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    monkeypatch.setattr(_fa, "read_session_username", lambda request: "test@example.com")
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "is_admin", lambda request: True)

    client = TestClient(create_app())
    html = client.get("/global-settings").text

    assert "Global settings" in html
    assert 'id="source_document_allowed_suffixes"' in html
    assert "__JOB_HUNTER_SETTINGS_SECTION_" not in html


def test_settings_page_renders_admin_link_only_for_admins(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    monkeypatch.setattr(_fa, "read_session_username", lambda request: "test@example.com")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())

    monkeypatch.setattr(_pages, "is_admin", lambda request: True)
    admin_html = client.get("/settings").text
    assert 'class="sidebar-admin-badge"' in admin_html
    assert 'href="/global-settings"' in admin_html
    assert 'sidebar-group-label-global' in admin_html
    assert '__JOB_HUNTER_ADMIN_NAV_GROUP__' not in admin_html

    monkeypatch.setattr(_pages, "is_admin", lambda request: False)
    candidate_html = client.get("/settings").text
    assert 'class="sidebar-admin-badge"' not in candidate_html
    assert 'href="/global-settings"' not in candidate_html
    assert 'sidebar-group-label-global' not in candidate_html
    assert '__JOB_HUNTER_ADMIN_NAV_GROUP__' not in candidate_html


def test_settings_search_section_uses_shared_choice_strip_widget(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    monkeypatch.setattr(_fa, "read_session_username", lambda request: "test@example.com")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())
    html = client.get("/settings").text

    assert 'class="section-title"' not in html
    assert 'id="settings_page_title"' not in html
    assert 'id="settings_page_copy"' not in html
    assert '<section class="hero">' not in html
    assert 'data-settings-hero-title=' not in html
    assert 'data-settings-hero-copy=' not in html
    assert 'class="panel search-settings-shell settings-section-shell"' in html
    assert 'class="settings-section-head"' in html
    assert 'Search Settings' in html
    assert 'Job board search' in html
    assert 'search-common-panel' not in html
    assert 'common-search-grid' not in html
    assert 'common-search-field' not in html
    assert 'common-search-field--keywords' not in html
    assert 'settings-form-grid--three-col' not in html
    assert 'settings-form-field--span-2' not in html
    assert 'class="choice-strip"' in html
    assert 'class="choice-card choice-card--work-mode"' in html
    assert 'input type="checkbox" name="engagement_type"' in html
    assert 'select id="engagement_type"' not in html
    assert 'Include SEEK in search' in html
    assert 'Include LinkedIn in search' in html
    assert '>+<' in html
    assert 'id="keywords"' in html
    assert 'data-chip-editor="keywords"' not in html
    assert 'Search keyword' in html
    assert 'placeholder="e.g. Business Analyst"' in html
    assert 'id="seek_max_pages_choices"' in html
    assert 'field-control-shell' in html
    assert 'id="prefer_sector_choices"' in html
    assert 'class="choice-card choice-card--work-mode"' in html
    assert 'select id="sector_preference"' not in html


def test_settings_review_panel_empty_state_copy_is_defined():
    js_path = ROOT_DIR / "templates" / "static" / "settings" / "shared" / "settings-review-panel.js"
    js = js_path.read_text(encoding="utf-8")

    assert "No capability suggestions yet. We found no saved review data from the latest search. Run a search again so kept jobs can be analysed for new capability signals." in js
    assert "No capability suggestions yet. We found kept jobs, but no new capability observations were extracted from them." in js
    assert "Requirements to address" in js
    assert "Do you have this capability?" in js
    assert "Search/title tuning" in js
    assert "Filters already working correctly" in js


def test_settings_matrix_section_omits_outer_panel_wrapper(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    monkeypatch.setattr(_fa, "read_session_username", lambda request: "test@example.com")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())
    html = client.get("/settings").text

    assert '<h2 class="section-title" id="capability_matrix_section_title"></h2>' not in html
    assert 'class="panel advanced-shell settings-section-shell"' in html
    assert 'data-settings-hero-title=' not in html
    assert 'data-settings-hero-copy=' not in html
    assert 'Decision Weights' in html
    assert 'Capability Matrix' in html
    assert 'Rules' in html
    assert 'Alerts &amp; AI' in html
    assert 'Optimise' in html
    assert 'id="schedule-panel"' in html
    assert 'id="capability_matrix_editor"' in html


def test_settings_alerts_section_uses_shared_settings_shell(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    monkeypatch.setattr(_fa, "read_session_username", lambda request: "test@example.com")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())
    html = client.get("/settings").text

    assert 'class="panel alerts-shell settings-section-shell"' in html
    assert 'class="settings-section-head"' in html
    assert 'id="settings_alerts_labels_json"' in html
    assert 'id="telegram_connect_panel"' in html
    assert 'Alerts &amp; AI' in html
    assert '__JOB_HUNTER_SETTINGS_ALERTS_SECTION_TITLE__' not in html
    assert '__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_HEADING__' not in html
