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

from job_hunter_agent.config import SERVER_HOST, DEBUG_MODE, LOGIN_PATH, LOGOUT_PATH, HEALTH_CHECK_PATH

# Security and encoding constants
ALGORITHM_PBKDF2 = "pbkdf2_sha256"
ALGORITHM_SHA256 = "sha256"
ENCODING_UTF8 = "utf-8"

def _get_session_cookie_params() -> tuple[str, bool]:
    """Determine session cookie parameters based on the server environment."""
    # Allow the base cookie name to be changed via environment variable
    base_name = os.getenv("JOB_HUNTER_SESSION_COOKIE_NAME", "job_hunter_session")
    # Strip existing __Host- prefix to handle it dynamically based on environment
    if base_name.startswith("__Host-"):
        base_name = base_name[7:]

    is_local = SERVER_HOST in ("127.0.0.1", "localhost")
    
    if DEBUG_MODE or is_local:
        return base_name, False

    # FIX #3 Plan Step 4: Cookie prefixing (__Host- prefix requires secure=True)
    # We ensure the __Host- prefix is applied for secure contexts as it's a browser requirement
    return f"__Host-{base_name}", True

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
    digest = hashlib.pbkdf2_hmac(ALGORITHM_SHA256, password.encode(ENCODING_UTF8), salt, iterations)
    return f"{ALGORITHM_PBKDF2}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    parts = str(encoded_hash or "").split("$")
    if len(parts) != 4:
        return False
    algorithm, iterations_text, salt_hex, hash_hex = parts
    if algorithm != ALGORITHM_PBKDF2:
        return False
    try:
        iterations = int(iterations_text)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac(ALGORITHM_SHA256, password.encode(ENCODING_UTF8), salt, iterations)
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
    set_session_cookie(response, request.app.state.auth_config, username)
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


def set_session_cookie(response: RedirectResponse | JSONResponse | HTMLResponse, config: AuthConfig, username: str) -> None:
    if not config.configured or not config.session_secret:
        return
    value = _build_session_cookie_value(username, config.session_secret)
    name, secure_flag = _get_session_cookie_params()
    response.set_cookie(
        name,
        value,
        httponly=True,
        samesite="strict",  # FIX #3 Plan Step 2: Enforce Strict SameSite policy
        secure=secure_flag,
        path="/",
    )


def clear_session_cookie(response: RedirectResponse | JSONResponse | HTMLResponse) -> None:
    name, _ = _get_session_cookie_params()
    response.delete_cookie(name, path="/")


def read_session_username(request: Request) -> str | None:
    config = getattr(request.app.state, "auth_config", None)
    if not isinstance(config, AuthConfig) or not config.configured or not config.session_secret:
        return None
    name, _ = _get_session_cookie_params()
    token = request.cookies.get(name)
    if not token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(config.session_secret.encode(ENCODING_UTF8), payload_b64.encode(ENCODING_UTF8), ALGORITHM_SHA256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode((payload_b64 + padding).encode(ENCODING_UTF8)).decode(ENCODING_UTF8))
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
    payload = json.dumps({"username": username}, separators=(",", ":")).encode(ENCODING_UTF8)
    payload_b64 = base64.urlsafe_b64encode(payload).decode(ENCODING_UTF8).rstrip("=")
    signature = hmac.new(secret.encode(ENCODING_UTF8), payload_b64.encode(ENCODING_UTF8), ALGORITHM_SHA256).hexdigest()
    return f"{payload_b64}.{signature}"
