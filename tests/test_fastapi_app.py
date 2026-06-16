"""Tests for fastapi app."""

import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.profile_materials as _profile_materials
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.fastapi_app import _bootstrap_runtime_knowledge, _cors_origin, create_app

_FAKE_USER = {"user_id": "test", "email": "test@example.com", "role": "admin"}
_CANDIDATE_USER = {"user_id": "candidate", "email": "candidate@example.com", "role": "candidate"}


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


def test_global_settings_page_requires_admin(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _CANDIDATE_USER)
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "read_session_user", lambda request: _CANDIDATE_USER)
    monkeypatch.setattr(_pages, "is_admin", lambda request: False)

    client = TestClient(create_app())
    response = client.get("/global-settings", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login?next=%2Fglobal-settings"


def test_global_settings_page_allows_admin(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_pages, "is_admin", lambda request: True)

    client = TestClient(create_app())
    response = client.get("/global-settings")

    assert response.status_code == 200
    assert 'data-page-mode="admin"' in response.text
    assert 'id="section-admin"' in response.text


def test_global_settings_api_requires_admin(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _CANDIDATE_USER)
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    monkeypatch.setattr(_profile_materials, "is_admin", lambda request: False)

    client = TestClient(create_app())

    response = client.get("/api/global-settings")
    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "Authentication required"}

    response = client.patch("/api/global-settings", json={"feature_flag": True})
    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "Authentication required"}


def test_global_settings_api_allows_admin(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    monkeypatch.setattr(_profile_materials, "is_admin", lambda request: True)
    monkeypatch.setattr(_profile_materials.srv, "load_global_settings", lambda: {"enabled": True})
    monkeypatch.setattr(
        _profile_materials,
        "save_global_settings",
        lambda body: {"saved": True, **body},
    )

    client = TestClient(create_app())

    response = client.get("/api/global-settings")
    assert response.status_code == 200
    assert response.json() == {"enabled": True}

    response = client.patch("/api/global-settings", json={"feature_flag": True})
    assert response.status_code == 200
    assert response.json() == {"saved": True, "feature_flag": True}


def test_workspace_page_bootstrap_includes_user_id(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages.srv, "DEBUG_MODE", True)
    monkeypatch.setattr(_pages, "get_user_id_for_runtime", lambda: "test-user")

    client = TestClient(create_app())
    html = client.get("/").text

    assert 'window.__JOB_HUNTER_USER_ID__ = "test-user"' in html
    assert 'id="job_hunter_account_test_trigger"' in html
    assert ">Test</button>" in html
    assert "Reset Signals" not in html


def test_create_app_bootstrap_precedes_routes_import():
    """Regression: _bootstrap_runtime_knowledge() must run before routes are imported.

    match_labels.MATCH_LEVELS and similar module-level constants read from the
    knowledge table at import time.  If bootstrap runs after the routes import,
    a fresh install with an empty DB raises sqlite3.OperationalError.
    """
    src = inspect.getsource(create_app)
    bootstrap_pos = src.index("_bootstrap_runtime_knowledge()")
    routes_pos = src.index("from job_hunter_agent.routes import")
    assert bootstrap_pos < routes_pos, (
        "_bootstrap_runtime_knowledge() must be called before routes are imported in create_app()"
    )


def test_create_app_seeds_fresh_db(tmp_path, monkeypatch):
    """create_app() with a brand-new empty DB path must not raise.

    Simulates the first launch after a clean installer run where the DB file
    does not yet exist.  Bootstrap must create and seed it before any route
    module reads from it.
    """
    from job_hunter_agent.global_settings import load_global_settings

    fresh_db = tmp_path / "bootstrap_test.db"
    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(fresh_db))
    load_global_settings.cache_clear()

    app = create_app()
    assert app is not None
    assert fresh_db.exists()

    from job_hunter_agent.database import db_conn

    with db_conn(fresh_db) as conn:
        n = conn.execute("SELECT count(*) FROM knowledge").fetchone()[0]
    assert n > 0

    load_global_settings.cache_clear()


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
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "query_string": b"",
    }
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
    monkeypatch.setenv(
        "JOB_HUNTER_CORS_ALLOWED_ORIGINS", "https://app.example.com,https://other.example.com"
    )
    assert _fa._configured_cors_origins() == {
        "http://localhost:8765",
        "https://app.example.com",
        "https://other.example.com",
    }


def test_cors_origin_no_origin_header_returns_none(monkeypatch):
    monkeypatch.delenv("JOB_HUNTER_CORS_ALLOWED_ORIGINS", raising=False)
    assert _cors_origin(_make_request(None)) is None


def test_cors_origin_allowed_origin_is_echoed(monkeypatch):
    monkeypatch.setenv(
        "JOB_HUNTER_CORS_ALLOWED_ORIGINS", "https://app.example.com,https://other.example.com"
    )
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
