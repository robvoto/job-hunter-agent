from http.cookies import SimpleCookie

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from job_hunter_agent.auth import (
    AuthConfig,
    _get_session_cookie_params,
    issue_csrf_token,
    set_session_cookie,
    verify_csrf_token,
)


def _build_request(app: FastAPI, cookie_header: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("utf-8")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
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
    app.state.auth_config = AuthConfig(
        username="alice",
        password_hash="hash",
        session_secret="secret",
        missing_fields=(),
    )

    response = Response()
    set_session_cookie(response, app.state.auth_config, "alice")

    cookie = SimpleCookie()
    cookie.load(response.headers["set-cookie"])
    session_cookie_name, _ = _get_session_cookie_params()
    session_cookie_value = cookie[session_cookie_name].value
    request = _build_request(app, f"{session_cookie_name}={session_cookie_value}")

    token = issue_csrf_token(request)

    assert token is not None
    assert verify_csrf_token(request, token)
    assert not verify_csrf_token(request, f"{token}x")
