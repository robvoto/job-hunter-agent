from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.fastapi_app import create_app

_FAKE_USER = {"user_id": "test", "email": "test@example.com", "role": "admin"}


def test_fastapi_health_and_unknown_route_json_errors(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_fa, "read_session_username", lambda request: _FAKE_USER["email"])
    client = TestClient(create_app())
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    missing = client.get("/api/no-such-endpoint")
    assert missing.status_code == 404
    assert missing.json() == {"error": "Not found"}


def test_docs_route_returns_docs_payload(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_fa, "read_session_username", lambda request: _FAKE_USER["email"])
    client = TestClient(create_app())
    r = client.get("/docs")
    assert r.status_code == 200
    payload = r.json()
    assert "docs" in payload
    assert isinstance(payload["docs"], list)


def test_settings_redirects_to_start_until_onboarding_is_complete(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_fa, "read_session_username", lambda request: _FAKE_USER["email"])
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: False)

    client = TestClient(create_app())
    response = client.get("/settings", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/start"


def test_logout_redirects_to_login_and_clears_session_cookie():
    client = TestClient(create_app())
    client.cookies.set("job_hunter_session", "stale-session", domain="testserver", path="/")

    response = client.get("/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert "job_hunter_session=" in response.headers.get("set-cookie", "")
