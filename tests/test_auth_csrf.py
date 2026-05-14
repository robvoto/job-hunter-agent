from http.cookies import SimpleCookie

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from job_hunter_agent.auth import (
    GoogleOAuthConfig,
    _get_session_cookie_params,
    issue_csrf_token,
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
