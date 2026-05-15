"""Authentication helpers for the workspace server (Google OAuth)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import requests as http_client
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from job_hunter_agent import config as app_config
from job_hunter_agent.config import (
    LOGIN_PATH,
    LOGOUT_PATH,
    HEALTH_CHECK_PATH,
    GOOGLE_AUTH_PATH,
    GOOGLE_AUTH_CALLBACK_PATH,
    AUTH_ALGO_SHA256,
    AUTH_ENCODING,
    CSRF_TOKEN_CONTEXT,
    SESSION_COOKIE_PATH,
    SESSION_COOKIE_DEFAULT_NAME,
)
from job_hunter_agent.paths import AUTH_DIR

OPEN_PATHS = {
    LOGIN_PATH,
    LOGOUT_PATH,
    HEALTH_CHECK_PATH,
    GOOGLE_AUTH_PATH,
    GOOGLE_AUTH_CALLBACK_PATH,
}

USERS_PATH = AUTH_DIR / "users.json"
_users_lock = threading.Lock()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str | None
    client_secret: str | None
    admin_email: str | None
    base_url: str
    session_secret: str | None
    missing_fields: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return not self.missing_fields


def load_google_config() -> GoogleOAuthConfig:
    client_id = os.getenv("JOB_HUNTER_GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("JOB_HUNTER_GOOGLE_CLIENT_SECRET", "").strip()
    admin_email = os.getenv("JOB_HUNTER_ADMIN_EMAIL", "").strip().lower()
    base_url = os.getenv("JOB_HUNTER_BASE_URL", "http://localhost:8765").rstrip("/")
    session_secret = os.getenv("JOB_HUNTER_AUTH_SESSION_SECRET", "").strip()
    missing = tuple(
        field
        for field, value in (
            ("JOB_HUNTER_GOOGLE_CLIENT_ID", client_id),
            ("JOB_HUNTER_GOOGLE_CLIENT_SECRET", client_secret),
            ("JOB_HUNTER_ADMIN_EMAIL", admin_email),
            ("JOB_HUNTER_AUTH_SESSION_SECRET", session_secret),
        )
        if not value
    )
    return GoogleOAuthConfig(
        client_id=client_id or None,
        client_secret=client_secret or None,
        admin_email=admin_email or None,
        base_url=base_url,
        session_secret=session_secret or None,
        missing_fields=missing,
    )


def user_id_from_email(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:16]


def load_user_store() -> dict:
    with _users_lock:
        if not USERS_PATH.exists():
            return {}
        try:
            return json.loads(USERS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}


def _save_user_store_locked(store: dict) -> None:
    """Must be called while holding _users_lock."""
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USERS_PATH.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")


def get_or_create_user(email: str, admin_email: str | None) -> dict:
    email = email.strip().lower()
    user_id = user_id_from_email(email)
    role = "admin" if admin_email and email == admin_email.strip().lower() else "candidate"
    with _users_lock:
        store: dict = {}
        if USERS_PATH.exists():
            try:
                store = json.loads(USERS_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass
        if user_id not in store:
            store[user_id] = build_user_record(user_id, email, role)
            _save_user_store_locked(store)
    # Always re-derive role from env — admin_email may change without a store update.
    return {"user_id": user_id, "email": email, "role": role}


def build_user_record(user_id: str, email: str, role: str) -> dict:
    return {
        "user_id": user_id,
        "email": email,
        "role": role,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def build_google_auth_url(config: GoogleOAuthConfig, state: str) -> str:
    callback_url = f"{config.base_url}{GOOGLE_AUTH_CALLBACK_PATH}"
    params = urlencode({
        "client_id": config.client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
    })
    return f"{GOOGLE_AUTH_URL}?{params}"


def exchange_google_code(config: GoogleOAuthConfig, code: str) -> dict:
    callback_url = f"{config.base_url}{GOOGLE_AUTH_CALLBACK_PATH}"
    token_resp = http_client.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": callback_url,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    token_resp.raise_for_status()
    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise ValueError("No access_token in Google token response")
    info_resp = http_client.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    info_resp.raise_for_status()
    return info_resp.json()


def configure_auth(app) -> None:
    config = load_google_config()
    app.state.auth_config = config


def read_session_user(request: Request) -> dict | None:
    config = getattr(request.app.state, "auth_config", None)
    if not isinstance(config, GoogleOAuthConfig) or not config.session_secret:
        return None
    token = _read_session_cookie_value(request)
    if not token:
        return None
    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(
        config.session_secret.encode(AUTH_ENCODING),
        payload_b64.encode(AUTH_ENCODING),
        AUTH_ALGO_SHA256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(
            base64.urlsafe_b64decode((payload_b64 + padding).encode(AUTH_ENCODING)).decode(AUTH_ENCODING)
        )
    except Exception:
        return None
    user_id = str(payload.get("user_id") or "").strip()
    email = str(payload.get("email") or "").strip()
    if not user_id or not email:
        return None
    # Always re-derive role from env so admin_email changes take effect without re-login.
    role = "admin" if config.admin_email and email.lower() == config.admin_email.strip().lower() else "candidate"
    return {"user_id": user_id, "email": email, "role": role}


def read_session_username(request: Request) -> str | None:
    """Compatibility shim for CSRF middleware — returns the authenticated user's email."""
    user = read_session_user(request)
    return user["email"] if user else None


def is_auth_disabled() -> bool:
    return bool(app_config.AUTH_DISABLED)


def is_authenticated(request: Request) -> bool:
    if is_auth_disabled():
        return True
    return read_session_user(request) is not None


def is_admin(request: Request) -> bool:
    if is_auth_disabled():
        return True
    user = read_session_user(request)
    return user is not None and user.get("role") == "admin"


def set_session_cookie(
    response: RedirectResponse | JSONResponse,
    request: Request,
    config: GoogleOAuthConfig,
    user: dict,
) -> None:
    if not config.session_secret:
        return
    value = _build_session_cookie_value(user, config.session_secret)
    name, secure_flag = _get_session_cookie_params(request)
    response.set_cookie(
        name,
        value,
        httponly=True,
        # OAuth returns from Google via a cross-site redirect, so the session
        # cookie must survive that flow. Lax is the standard fit here.
        samesite="lax",
        secure=secure_flag,
        path=SESSION_COOKIE_PATH,
    )


def clear_session_cookie(
    response: RedirectResponse | JSONResponse,
    request: Request,
) -> None:
    name, _ = _get_session_cookie_params(request)
    response.delete_cookie(name, path=SESSION_COOKIE_PATH)


def issue_csrf_token(request: Request) -> str | None:
    config = getattr(request.app.state, "auth_config", None)
    if not isinstance(config, GoogleOAuthConfig) or not config.session_secret:
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


def auth_required_response(next_path: str, accepts_html: bool) -> RedirectResponse | JSONResponse:
    if accepts_html:
        return RedirectResponse(
            f"{LOGIN_PATH}?next={quote(_safe_next_path(next_path), safe='')}",
            status_code=302,
        )
    return JSONResponse(
        status_code=401,
        content={"ok": False, "error": "Authentication required"},
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ── Internal helpers ────────────────────────────────────────────────────────

def _get_session_cookie_params(request: Request) -> tuple[str, bool]:
    base_name = os.getenv("JOB_HUNTER_SESSION_COOKIE_NAME", SESSION_COOKIE_DEFAULT_NAME)
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


def _build_session_cookie_value(user: dict, secret: str) -> str:
    payload = json.dumps(
        {"user_id": user["user_id"], "email": user["email"], "role": user["role"]},
        separators=(",", ":"),
    ).encode(AUTH_ENCODING)
    payload_b64 = base64.urlsafe_b64encode(payload).decode(AUTH_ENCODING).rstrip("=")
    signature = hmac.new(
        secret.encode(AUTH_ENCODING),
        payload_b64.encode(AUTH_ENCODING),
        AUTH_ALGO_SHA256,
    ).hexdigest()
    return f"{payload_b64}.{signature}"


def _read_session_cookie_value(request: Request) -> str | None:
    name, _ = _get_session_cookie_params(request)
    token = request.cookies.get(name)
    return str(token) if token else None


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


def _build_csrf_token_value(session_cookie_value: str, secret: str) -> str:
    message = f"{CSRF_TOKEN_CONTEXT}:{session_cookie_value}"
    return hmac.new(
        secret.encode(AUTH_ENCODING),
        message.encode(AUTH_ENCODING),
        AUTH_ALGO_SHA256,
    ).hexdigest()
