"""Tests for fastapi csrf."""

from http.cookies import SimpleCookie

from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response

from job_hunter_agent.auth import _get_session_cookie_params, issue_csrf_token, set_session_cookie
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.routes import profile_materials


def _csrf_request(app, cookie_header: str, scheme: str = "http") -> Request:
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"cookie", cookie_header.encode("utf-8"))],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "app": app,
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive=receive)


def _session_cookie_and_token(app, scheme: str = "http") -> tuple[str, str, str]:
    request = _csrf_request(app, "", scheme=scheme)
    response = Response()
    set_session_cookie(response, request, app.state.auth_config, {"user_id": "alice", "email": "alice@example.com", "role": "candidate"})
    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    session_cookie_name, _ = _get_session_cookie_params(request)
    session_cookie_value = cookie[session_cookie_name].value
    request = _csrf_request(app, f"{session_cookie_name}={session_cookie_value}", scheme=scheme)
    token = issue_csrf_token(request)
    assert token is not None
    return session_cookie_name, session_cookie_value, token


def test_csrf_middleware_blocks_unsafe_session_request(monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_AUTH_USERNAME", "alice")
    monkeypatch.setenv("JOB_HUNTER_AUTH_PASSWORD_HASH", "hash")
    monkeypatch.setenv("JOB_HUNTER_AUTH_SESSION_SECRET", "secret")

    app = create_app()
    session_cookie_name, session_cookie_value, _ = _session_cookie_and_token(app)

    client = TestClient(app)
    client.cookies.set(session_cookie_name, session_cookie_value)

    response = client.patch("/api/profile", json={})

    assert response.status_code == 403
    assert response.json() == {"error": "CSRF token missing or invalid"}


def test_csrf_middleware_allows_valid_token(monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_AUTH_USERNAME", "alice")
    monkeypatch.setenv("JOB_HUNTER_AUTH_PASSWORD_HASH", "hash")
    monkeypatch.setenv("JOB_HUNTER_AUTH_SESSION_SECRET", "secret")

    app = create_app()
    session_cookie_name, session_cookie_value, token = _session_cookie_and_token(app)

    monkeypatch.setattr(profile_materials.srv, "load_profile", lambda: {})
    monkeypatch.setattr(profile_materials.srv, "patch_profile", lambda patch: {"ok": True, "patched": patch})
    monkeypatch.setattr(profile_materials.srv.SettingsHandler, "_normalize_profile_patch_for_save", staticmethod(lambda current, body: {}))
    monkeypatch.setattr(profile_materials.srv.SettingsHandler, "_matching_rules_changed", staticmethod(lambda before, after: False))

    client = TestClient(app)
    client.cookies.set(session_cookie_name, session_cookie_value)

    response = client.patch("/api/profile", json={}, headers={"X-CSRF-Token": token})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "patched": {}}


def test_csrf_middleware_protects_logout(monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_AUTH_USERNAME", "alice")
    monkeypatch.setenv("JOB_HUNTER_AUTH_PASSWORD_HASH", "hash")
    monkeypatch.setenv("JOB_HUNTER_AUTH_SESSION_SECRET", "secret")

    app = create_app()
    session_cookie_name, session_cookie_value, token = _session_cookie_and_token(app)

    client = TestClient(app)
    client.cookies.set(session_cookie_name, session_cookie_value)

    blocked = client.post("/logout", follow_redirects=False)
    assert blocked.status_code == 403
    assert blocked.json() == {"error": "CSRF token missing or invalid"}

    allowed = client.post("/logout", follow_redirects=False, data={"csrf_token": token})
    assert allowed.status_code == 302
    assert allowed.headers["location"] == "/login"
    assert session_cookie_name in allowed.headers.get("set-cookie", "")

