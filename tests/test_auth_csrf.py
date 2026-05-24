from http.cookies import SimpleCookie

import pytest
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from job_hunter_agent.auth import (
    GoogleOAuthConfig,
    _get_session_cookie_params,
    get_or_create_user,
    issue_csrf_token,
    is_admin,
    set_session_cookie,
    verify_csrf_token,
)

_TEST_USER = {"user_id": "abc123", "email": "test@example.com", "role": "candidate"}


def _make_config(secret: str = "secret") -> GoogleOAuthConfig:
    return GoogleOAuthConfig(
        client_id="cid",
        client_secret="csecret",
        admin_email="admin@example.com",
        base_url="http://localhost:8765",
        session_secret=secret,
        missing_fields=(),
    )


def _build_request(app: FastAPI, cookie_header: str | None = None, scheme: str = "http") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("utf-8")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": scheme,
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "app": app,
    }

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive=receive)


def test_issue_csrf_token_derives_from_session_cookie():
    app = FastAPI()
    config = _make_config()
    app.state.auth_config = config

    request = _build_request(app, scheme="http")
    response = Response()
    set_session_cookie(response, request, config, _TEST_USER)

    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    session_cookie_name, _ = _get_session_cookie_params(request)
    session_cookie_value = cookie[session_cookie_name].value
    request = _build_request(app, f"{session_cookie_name}={session_cookie_value}")

    token = issue_csrf_token(request)

    assert token is not None
    assert verify_csrf_token(request, token)
    assert not verify_csrf_token(request, f"{token}x")


def test_session_cookie_secure_flag_tracks_request_scheme():
    app = FastAPI()
    config = _make_config()
    app.state.auth_config = config

    http_request = _build_request(app, scheme="http")
    http_response = Response()
    set_session_cookie(http_response, http_request, config, _TEST_USER)
    http_cookie = http_response.headers["set-cookie"]

    https_request = _build_request(app, scheme="https")
    https_response = Response()
    set_session_cookie(https_response, https_request, config, _TEST_USER)
    https_cookie = https_response.headers["set-cookie"]

    assert "Secure" not in http_cookie
    assert "__Host-" not in http_cookie
    assert "Secure" in https_cookie
    assert "__Host-" in https_cookie


# ── get_or_create_user (DB-backed) ──────────────────────────────────────────

def test_get_or_create_user_returns_user_dict(isolated_db):
    user = get_or_create_user("alice@example.com", admin_email=None)
    assert user["email"] == "alice@example.com"
    assert user["role"] == "candidate"
    assert len(user["user_id"]) == 16


def test_get_or_create_user_admin_role(isolated_db):
    user = get_or_create_user("admin@example.com", admin_email="admin@example.com")
    assert user["role"] == "admin"


def test_get_or_create_user_candidate_when_not_admin(isolated_db):
    user = get_or_create_user("other@example.com", admin_email="admin@example.com")
    assert user["role"] == "candidate"


def test_get_or_create_user_persists_to_db(isolated_db):
    from job_hunter_agent.database import db_conn
    get_or_create_user("alice@example.com", admin_email=None)
    with db_conn(isolated_db) as conn:
        row = conn.execute("SELECT email FROM users WHERE email = 'alice@example.com'").fetchone()
    assert row is not None


def test_get_or_create_user_persists_display_name(isolated_db):
    from job_hunter_agent.database import db_conn
    get_or_create_user("alice@example.com", admin_email=None, display_name="Alice Smith")
    with db_conn(isolated_db) as conn:
        row = conn.execute("SELECT display_name FROM users WHERE email = 'alice@example.com'").fetchone()
    assert row["display_name"] == "Alice Smith"


def test_get_or_create_user_is_idempotent(isolated_db):
    from job_hunter_agent.database import db_conn
    get_or_create_user("alice@example.com", admin_email=None)
    get_or_create_user("alice@example.com", admin_email=None)
    with db_conn(isolated_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM users WHERE email = 'alice@example.com'").fetchone()[0]
    assert count == 1


def test_get_or_create_user_role_re_derived_from_env(isolated_db):
    # First login as candidate; second login with admin email must return admin role.
    user1 = get_or_create_user("alice@example.com", admin_email=None)
    user2 = get_or_create_user("alice@example.com", admin_email="alice@example.com")
    assert user1["role"] == "candidate"
    assert user2["role"] == "admin"


def test_is_admin_uses_admin_role_only(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.auth.read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "candidate"},
    )
    monkeypatch.setattr("job_hunter_agent.auth.is_auth_disabled", lambda: True)

    assert not is_admin(object())

    monkeypatch.setattr(
        "job_hunter_agent.auth.read_session_user",
        lambda request: {"user_id": "test", "email": "admin@example.com", "role": "admin"},
    )
    assert is_admin(object())
