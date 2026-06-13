"""Google OAuth routes: /login, /login/google, /api/auth/google/callback, /logout."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from job_hunter_agent.auth import (
    GoogleOAuthConfig,
    _safe_next_path,
    build_google_auth_url,
    clear_session_cookie,
    exchange_google_code,
    get_or_create_user,
    set_session_cookie,
)
from job_hunter_agent.config import (
    GOOGLE_AUTH_CALLBACK_PATH,
    GOOGLE_AUTH_PATH,
    LOGIN_PATH,
    LOGOUT_PATH,
)
from job_hunter_agent.paths import TEMPLATES_DIR

router = APIRouter()

_OAUTH_STATE_COOKIE = "oauth_state"
_OAUTH_STATE_MAX_AGE = 600  # 10 minutes


def _get_config(request: Request) -> GoogleOAuthConfig | None:
    cfg = getattr(request.app.state, "auth_config", None)
    return cfg if isinstance(cfg, GoogleOAuthConfig) else None


@router.get(LOGIN_PATH)
def page_login(request: Request, error: str | None = None):  # type: ignore[no-untyped-def]
    login_html = TEMPLATES_DIR / "login.html"
    if login_html.exists():
        return HTMLResponse(login_html.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Job Hunter</h1><p><a href='/login/google'>Sign in with Google</a></p>")


@router.get(GOOGLE_AUTH_PATH)
def login_google(request: Request):  # type: ignore[no-untyped-def]
    cfg = _get_config(request)
    if not cfg or not cfg.configured:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")
    state = secrets.token_hex(16)
    auth_url = build_google_auth_url(cfg, state)
    response = RedirectResponse(auth_url, status_code=302)
    response.set_cookie(
        _OAUTH_STATE_COOKIE,
        state,
        httponly=True,
        samesite="lax",
        max_age=_OAUTH_STATE_MAX_AGE,
        path="/",
    )
    return response


@router.get(GOOGLE_AUTH_CALLBACK_PATH)
def google_callback(  # type: ignore[no-untyped-def]
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return RedirectResponse(f"{LOGIN_PATH}?error={error}", status_code=302)

    cfg = _get_config(request)
    if not cfg or not cfg.configured:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")

    expected_state = request.cookies.get(_OAUTH_STATE_COOKIE)
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return RedirectResponse(f"{LOGIN_PATH}?error=state_mismatch", status_code=302)

    if not code:
        return RedirectResponse(f"{LOGIN_PATH}?error=no_code", status_code=302)

    try:
        user_info = exchange_google_code(cfg, code)
    except Exception:
        return RedirectResponse(f"{LOGIN_PATH}?error=token_exchange_failed", status_code=302)

    email = str(user_info.get("email") or "").strip().lower()
    if not email:
        return RedirectResponse(f"{LOGIN_PATH}?error=no_email", status_code=302)

    if user_info.get("email_verified") is False:
        return RedirectResponse(f"{LOGIN_PATH}?error=email_not_verified", status_code=302)

    display_name = str(user_info.get("name") or "").strip() or None
    user = get_or_create_user(email, cfg.admin_email, display_name=display_name)
    next_path = _safe_next_path(request.query_params.get("next", "/"))

    response = RedirectResponse(next_path, status_code=302)
    response.delete_cookie(_OAUTH_STATE_COOKIE, path="/")
    set_session_cookie(response, request, cfg, user)
    return response


@router.post(LOGOUT_PATH)
def logout(request: Request):  # type: ignore[no-untyped-def]
    response = RedirectResponse(LOGIN_PATH, status_code=302)
    clear_session_cookie(response, request)
    return response
