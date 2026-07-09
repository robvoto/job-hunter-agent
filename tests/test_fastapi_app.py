"""Tests for fastapi app."""

import hashlib
import importlib
import inspect
import logging
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

import job_hunter_agent.config as _config
import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
import job_hunter_agent.routes.profile_materials as _profile_materials
from job_hunter_agent.fastapi_app import _cors_origin, create_app

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


def test_diagram_viewer_renders_mermaid_source():
    client = TestClient(create_app())
    response = client.get("/static/diagrams/scoring_process_flow")
    assert response.status_code == 200
    assert "mermaid.min.js" in response.text
    assert "scoring_process_flow.mmd" in response.text
    assert "Scoring Process Flow" in response.text


def test_debug_flag_is_resolved_from_cli_args(monkeypatch):
    original_argv = list(sys.argv)
    monkeypatch.setattr(sys, "argv", ["job_hunter_agent.fastapi_app", "--debug"])
    importlib.reload(_config)

    assert _config.DEBUG_MODE is True

    monkeypatch.setattr(sys, "argv", original_argv)
    importlib.reload(_config)


def test_server_step_flag_enables_step_through(monkeypatch):
    called = []

    monkeypatch.setattr(_fa, "enable_step_through", lambda: called.append(True))

    _fa._apply_startup_flags(step=True)

    assert called == [True]


def test_server_step_flag_is_ignored_when_off(monkeypatch):
    called = []

    monkeypatch.setattr(_fa, "enable_step_through", lambda: called.append(True))

    _fa._apply_startup_flags(step=False)

    assert called == []


def test_run_wrapper_forwards_cli_args_to_fastapi_app():
    run_script = Path("run").read_text(encoding="utf-8")

    assert 'exec uv run python -m job_hunter_agent.fastapi_app "$@"' in run_script
    assert "UV_CACHE_DIR" in run_script


def test_run_debug_wrapper_forwards_debug_flag_to_fastapi_app():
    run_debug_script = Path("run-debug").read_text(encoding="utf-8")

    assert 'exec uv run python -m job_hunter_agent.fastapi_app --debug "$@"' in run_debug_script
    assert "UV_CACHE_DIR" in run_debug_script


def test_line_logging_stream_respects_embedded_severity(caplog):
    caplog.set_level(logging.INFO, logger="job_hunter_agent.fastapi_app")
    stream = _fa._LineLoggingStream(logging.getLogger("job_hunter_agent.fastapi_app"), logging.ERROR)

    stream.write("2026-07-06 16:59:34,060 - INFO - JobSpy:Linkedin - finished scraping\n")
    stream.flush()

    assert any(
        record.levelno == logging.INFO and "finished scraping" in record.getMessage()
        for record in caplog.records
    )


def test_line_logging_stream_keeps_plain_stderr_as_error(caplog):
    caplog.set_level(logging.ERROR, logger="job_hunter_agent.fastapi_app")
    stream = _fa._LineLoggingStream(logging.getLogger("job_hunter_agent.fastapi_app"), logging.ERROR)

    stream.write("Traceback (most recent call last):\n")
    stream.write("ValueError: bad thing happened\n")
    stream.flush()

    assert any(
        record.levelno == logging.ERROR and "ValueError: bad thing happened" in record.getMessage()
        for record in caplog.records
    )


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


def test_admin_knowledge_sync_triggers_roundtrip(monkeypatch):
    calls = []
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    monkeypatch.setattr(_profile_materials, "is_admin", lambda request: True)
    monkeypatch.setattr(
        _profile_materials,
        "sync_knowledge_roundtrip",
        lambda: calls.append("sync") or "/tmp/app.db",
    )

    client = TestClient(create_app())

    response = client.post("/api/admin/knowledge-sync", headers={"X-CSRF-Token": "token"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Synced knowledge with AWS."}
    assert calls == ["sync"]


def test_workspace_page_bootstrap_includes_account_scope(monkeypatch):
    legacy_bootstrap_name = "window.__JOB_HUNTER_" + "USER_ID__"

    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(_pages.srv, "DEBUG_MODE", True)
    monkeypatch.setattr(_pages, "get_user_id_for_runtime", lambda: "test-user")

    client = TestClient(create_app())
    html = client.get("/").text
    expected_scope = hashlib.sha256("test-user".encode("utf-8")).hexdigest()[:16]

    assert 'window.__JOB_HUNTER_USER_SCOPE__ = "' in html
    assert expected_scope in html
    assert legacy_bootstrap_name not in html
    assert 'id="job_hunter_account_test_trigger"' in html
    assert ">Test</button>" in html
    assert 'id="job_hunter_clean_search_btn"' in html
    assert 'id="job_hunter_reset_user_btn"' in html
    assert 'account-bar-test-action--danger account-bar-test-action--stacked' in html
    assert "Warning: clears your profile, CV, review feedback, and history." in html
    assert html.index('id="job_hunter_clean_search_btn"') < html.index(
        'id="job_hunter_reset_user_btn"'
    )
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
