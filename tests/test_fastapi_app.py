"""Tests for fastapi app."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.fastapi_app import create_app, _cors_origin

_FAKE_USER = {"user_id": "test", "email": "test@example.com", "role": "admin"}


def test_fastapi_health_and_unknown_route_json_errors(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    missing = client.get("/api/no-such-endpoint")
    assert missing.status_code == 404
    assert missing.json() == {"error": "Not found"}


def test_docs_route_returns_docs_payload(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    client = TestClient(create_app())
    r = client.get("/docs")
    assert r.status_code == 200
    payload = r.json()
    assert "docs" in payload
    assert isinstance(payload["docs"], list)


def test_settings_redirects_to_start_until_onboarding_is_complete(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: False)

    client = TestClient(create_app())
    response = client.get("/settings", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/start"


def test_workspace_page_bootstrap_includes_user_id(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages.srv, "DEBUG_MODE", True)
    monkeypatch.setattr(_pages, "get_user_id_for_runtime", lambda: "test-user")

    client = TestClient(create_app())
    html = client.get("/").text

    assert 'window.__JOB_HUNTER_USER_ID__ = "test-user"' in html
    assert 'id="job_hunter_account_test_trigger"' in html
    assert '>Test</button>' in html
    assert 'Reset learning' in html
    assert 'Reset Signals' not in html


def test_workspace_template_uses_shared_account_bar_script_only():
    """The workspace must not keep stale inline menu wiring beside account-bar.js."""
    template = Path("templates/workspace.html").read_text(encoding="utf-8")

    assert "/static/common/account-bar.js" in template
    for stale_name in (
        "wsTestPanel",
        "wsTestTrigger",
        "wsTestMenu",
        "wsResetUserBtn",
        "wsResetLearningBtn",
    ):
        assert stale_name not in template


def test_logout_redirects_to_login_and_clears_session_cookie():
    client = TestClient(create_app())
    client.cookies.set("job_hunter_session", "stale-session", domain="testserver", path="/")

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert "job_hunter_session=" in response.headers.get("set-cookie", "")


def _make_request(origin: str | None = None) -> StarletteRequest:
    headers = {}
    if origin:
        headers["origin"] = origin
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [(k.encode(), v.encode()) for k, v in headers.items()], "query_string": b""}
    return StarletteRequest(scope)



def test_configured_cors_origins_includes_base_url(monkeypatch):
    monkeypatch.setattr(_fa, "JOB_HUNTER_BASE_URL", "http://localhost:8765")
    monkeypatch.delenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", raising=False)
    assert _fa._configured_cors_origins() == {"http://localhost:8765"}


def test_cors_origin_base_url_is_echoed_without_extra_allow_list(monkeypatch):
    monkeypatch.setattr(_fa, "JOB_HUNTER_BASE_URL", "http://localhost:8765")
    monkeypatch.delenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", raising=False)
    assert _cors_origin(_make_request("http://localhost:8765")) == "http://localhost:8765"


def test_configured_cors_origins_includes_extra_origins(monkeypatch):
    monkeypatch.setattr(_fa, "JOB_HUNTER_BASE_URL", "http://localhost:8765")
    monkeypatch.setenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", "https://app.example.com,https://other.example.com")
    assert _fa._configured_cors_origins() == {
        "http://localhost:8765",
        "https://app.example.com",
        "https://other.example.com",
    }

def test_cors_origin_no_origin_header_returns_none(monkeypatch):
    monkeypatch.delenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", raising=False)
    assert _cors_origin(_make_request(None)) is None


def test_cors_origin_allowed_origin_is_echoed(monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", "https://app.example.com,https://other.example.com")
    assert _cors_origin(_make_request("https://app.example.com")) == "https://app.example.com"


def test_cors_origin_rejected_origin_returns_none(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", "https://app.example.com")
    with caplog.at_level(logging.WARNING, logger="job_hunter_agent.fastapi_app"):
        result = _cors_origin(_make_request("https://evil.com"))
    assert result is None
    assert "rejected origin" in caplog.text


def test_cors_origin_no_env_var_returns_none(monkeypatch, caplog):
    import logging
    monkeypatch.delenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", raising=False)
    with caplog.at_level(logging.WARNING, logger="job_hunter_agent.fastapi_app"):
        result = _cors_origin(_make_request("https://any.example.com"))
    assert result is None
    assert "rejected origin" in caplog.text


def test_cors_middleware_sets_header_for_allowed_origin(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", "https://app.example.com")
    client = TestClient(create_app())
    r = client.get("/api/health", headers={"origin": "https://app.example.com"})
    assert r.headers.get("access-control-allow-origin") == "https://app.example.com"


def test_cors_middleware_omits_header_for_rejected_origin(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", "https://app.example.com")
    client = TestClient(create_app())
    r = client.get("/api/health", headers={"origin": "https://evil.com"})
    assert "access-control-allow-origin" not in r.headers

