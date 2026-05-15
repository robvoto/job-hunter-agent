from pathlib import Path

from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.fastapi_app import create_app


ROOT_DIR = Path(__file__).resolve().parent.parent
SETTINGS_ADMIN_PARTIAL_PATH = ROOT_DIR / "templates" / "partials" / "settings-admin.html"
_FAKE_USER = {"user_id": "test", "email": "test@example.com", "role": "admin"}


def test_source_document_suffixes_are_rendered_read_only():
    html = SETTINGS_ADMIN_PARTIAL_PATH.read_text(encoding="utf-8")

    assert 'id="source_document_allowed_suffixes"' in html
    assert 'readonly aria-readonly="true"' in html
    assert "Read-only. One suffix per line" in html


def test_settings_page_renders_admin_partial(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_fa, "read_session_username", lambda request: _FAKE_USER["email"])
    monkeypatch.setattr(_pages, "issue_csrf_token", lambda request: "csrf-token")
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)

    client = TestClient(create_app())
    html = client.get("/settings").text

    assert "Capability Matrix" in html
    assert 'id="source_document_allowed_suffixes"' in html
    assert "__JOB_HUNTER_SETTINGS_SECTION_" not in html
