"""Local authentication helpers for the dashboard server."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from job_hunter_agent.config import (
    LOGIN_PATH, 
    LOGOUT_PATH, 
    HEALTH_CHECK_PATH,
    AUTH_ALGO_PBKDF2,
    AUTH_ALGO_SHA256,
    AUTH_ENCODING,
    CSRF_TOKEN_CONTEXT,
    SESSION_COOKIE_PATH,
    SESSION_COOKIE_DEFAULT_NAME
)

def _get_session_cookie_params(request: Request) -> tuple[str, bool]:
    """Determine session cookie parameters based on the request transport."""
    # Allow the base cookie name to be changed via environment variable
    base_name = os.getenv("JOB_HUNTER_SESSION_COOKIE_NAME", SESSION_COOKIE_DEFAULT_NAME)
    # Strip existing __Host- prefix to handle it dynamically based on environment
    if base_name.startswith("__Host-"):
        base_name = base_name[7:]

    secure_mode = os.getenv("JOB_HUNTER_SESSION_COOKIE_SECURE", "auto").strip().lower()
    if secure_mode == "true":
        secure_flag = True
    elif secure_mode == "false":
        secure_flag = False
    else:
        secure_flag = request.url.scheme == "https"

    if secure_flag:
        return f"__Host-{base_name}", True
    return base_name, False

OPEN_PATHS = {
    LOGIN_PATH,
    LOGOUT_PATH,
    HEALTH_CHECK_PATH,
}


@dataclass(frozen=True)
class AuthConfig:
    username: str | None
    password_hash: str | None
    session_secret: str | None
    missing_fields: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return not self.missing_fields


def load_auth_config() -> AuthConfig:
    username = os.getenv("JOB_HUNTER_AUTH_USERNAME", "").strip()
    password_hash = os.getenv("JOB_HUNTER_AUTH_PASSWORD_HASH", "").strip()
    session_secret = os.getenv("JOB_HUNTER_AUTH_SESSION_SECRET", "").strip()
    missing = tuple(
        field
        for field, value in (
            ("JOB_HUNTER_AUTH_USERNAME", username),
            ("JOB_HUNTER_AUTH_PASSWORD_HASH", password_hash),
            ("JOB_HUNTER_AUTH_SESSION_SECRET", session_secret),
        )
        if not value
    )
    return AuthConfig(
        username=username or None,
        password_hash=password_hash or None,
        session_secret=session_secret or None,
        missing_fields=missing,
    )


def hash_password(password: str, *, salt_hex: str | None = None, iterations: int = 210_000) -> str:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(AUTH_ALGO_SHA256, password.encode(AUTH_ENCODING), salt, iterations)
    return f"{AUTH_ALGO_PBKDF2}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    parts = str(encoded_hash or "").split("$")
    if len(parts) != 4:
        return False
    algorithm, iterations_text, salt_hex, hash_hex = parts
    if algorithm != AUTH_ALGO_PBKDF2:
        return False
    try:
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(AUTH_ALGO_SHA256, password.encode(AUTH_ENCODING), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def validate_login(config: AuthConfig, username: str, password: str) -> bool:
    if not config.configured:
        return False
    if config.username is None or config.password_hash is None:
        return False
    return hmac.compare_digest(username.strip(), config.username) and verify_password(password, config.password_hash)


def is_authenticated(request: Request) -> bool:
    config = getattr(request.app.state, "auth_config", None)
    if not isinstance(config, AuthConfig) or not config.configured:
        return False
    return read_session_username(request) == config.username


def configure_auth(app) -> None:
    config = load_auth_config()
    app.state.auth_config = config


def login_success_response(request: Request, next_path: str, username: str) -> RedirectResponse:
    target = _safe_next_path(next_path)
    response = RedirectResponse(target, status_code=302)
    set_session_cookie(response, request, request.app.state.auth_config, username)
    return response


def login_error_response(message: str, status_code: int = 401) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": message},
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def auth_disabled_response(request: Request) -> HTMLResponse | JSONResponse:
    message = "Authentication is not configured. Set JOB_HUNTER_AUTH_USERNAME, JOB_HUNTER_AUTH_PASSWORD_HASH, and JOB_HUNTER_AUTH_SESSION_SECRET."
    if request.url.path.startswith("/api/"):
        return login_error_response(message, 503)
    return HTMLResponse(
        status_code=503,
        content=f"<h1>Authentication not configured</h1><p>{message}</p>",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def auth_required_response(next_path: str, accepts_html: bool) -> RedirectResponse | JSONResponse:
    if accepts_html:
        return RedirectResponse(f"{LOGIN_PATH}?next={quote(_safe_next_path(next_path), safe='')}", status_code=302)
    return login_error_response("Authentication required", 401)


def set_session_cookie(response: RedirectResponse | JSONResponse | HTMLResponse, request: Request, config: AuthConfig, username: str) -> None:
    if not config.configured or not config.session_secret:
        return
    value = _build_session_cookie_value(username, config.session_secret)
    name, secure_flag = _get_session_cookie_params(request)
    response.set_cookie(
        name,
        value,
        httponly=True,
        samesite="strict",  # FIX #3 Plan Step 2: Enforce Strict SameSite policy
        secure=secure_flag,
        path=SESSION_COOKIE_PATH,
    )


def clear_session_cookie(response: RedirectResponse | JSONResponse | HTMLResponse, request: Request) -> None:
    name, _ = _get_session_cookie_params(request)
    response.delete_cookie(name, path=SESSION_COOKIE_PATH)



def issue_csrf_token(request: Request) -> str | None:
    config = getattr(request.app.state, "auth_config", None)
    if not isinstance(config, AuthConfig) or not config.configured or not config.session_secret:
        return None
    session_cookie_value = _read_session_cookie_value(request)
    if not session_cookie_value:
        return None
    return _build_csrf_token_value(session_cookie_value, config.session_secret)


def verify_csrf_token(request: Request, presented_token: str | None) -> bool:
    expected = issue_csrf_token(request)
    if expected is None:
        return False
    candidate = str(presented_token or "").strip()
    if not candidate:
        return False
    return hmac.compare_digest(expected, candidate)


def read_session_username(request: Request) -> str | None:
    config = getattr(request.app.state, "auth_config", None)
    if not isinstance(config, AuthConfig) or not config.configured or not config.session_secret:
        return None
    token = _read_session_cookie_value(request)
    if not token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(config.session_secret.encode(AUTH_ENCODING), payload_b64.encode(AUTH_ENCODING), AUTH_ALGO_SHA256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode((payload_b64 + padding).encode(AUTH_ENCODING)).decode(AUTH_ENCODING))
    except Exception:
        return None
    username = str(payload.get("username") or "").strip()
    if not username:
        return None
    return username


def _safe_next_path(next_path: str) -> str:
    candidate = str(next_path or "").strip()
    if not candidate:
        return "/"
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return "/"
    if not candidate.startswith("/"):
        return "/"
    if candidate.startswith("//"):
        return "/"
    return candidate


def _build_session_cookie_value(username: str, secret: str) -> str:
    payload = json.dumps({"username": username}, separators=(",", ":")).encode(AUTH_ENCODING)
    payload_b64 = base64.urlsafe_b64encode(payload).decode(AUTH_ENCODING).rstrip("=")
    signature = hmac.new(secret.encode(AUTH_ENCODING), payload_b64.encode(AUTH_ENCODING), AUTH_ALGO_SHA256).hexdigest()
    return f"{payload_b64}.{signature}"


def _read_session_cookie_value(request: Request) -> str | None:
    name, _ = _get_session_cookie_params(request)
    token = request.cookies.get(name)
    if not token:
        return None
    return str(token)


def _build_csrf_token_value(session_cookie_value: str, secret: str) -> str:
    message = f"{CSRF_TOKEN_CONTEXT}:{session_cookie_value}"
    return hmac.new(secret.encode(AUTH_ENCODING), message.encode(AUTH_ENCODING), AUTH_ALGO_SHA256).hexdigest()
