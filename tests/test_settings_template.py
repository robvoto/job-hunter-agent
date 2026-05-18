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
    assert "Read-only. One suffix per line" in html


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

    monkeypatch.setattr(_pages, "is_admin", lambda request: False)
    candidate_html = client.get("/settings").text
    assert 'class="sidebar-admin-badge"' not in candidate_html


def test_settings_search_section_uses_shared_choice_strip_widget(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    monkeypatch.setattr(_fa, "read_session_username", lambda request: "test@example.com")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")

    client = TestClient(create_app())
    html = client.get("/settings").text

    assert 'id="engagement_type_label"' in html
    assert 'class="choice-strip"' in html
    assert 'class="choice-card choice-card--work-mode"' in html
    assert 'input type="checkbox" name="engagement_type"' in html
    assert 'select id="engagement_type"' not in html
    assert 'id="keywords"' in html
    assert 'data-chip-editor="keywords"' not in html
    assert 'Search keyword' in html
    assert 'placeholder="e.g. Business Analyst"' in html
    assert 'id="prefer_government_choices"' in html
    assert 'class="choice-card choice-card--work-mode"' in html
    assert 'select id="prefer_government"' not in html
