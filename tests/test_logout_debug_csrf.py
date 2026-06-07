"""Tests for logout CSRF behavior in debug mode."""

from __future__ import annotations

import sys
import types

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.testclient import TestClient

import job_hunter_agent.config as _config
import job_hunter_agent.fastapi_app as _fa


def test_logout_in_debug_mode_skips_csrf(monkeypatch):
    def register_routes(app):
        router = APIRouter()

        @router.post("/logout")
        def logout(request: Request):  # type: ignore[no-untyped-def]
            response = RedirectResponse("/login", status_code=302)
            response.delete_cookie("job_hunter_session", path="/")
            return response

        app.include_router(router)

    routes_module = types.ModuleType("job_hunter_agent.routes")
    routes_module.register_routes = register_routes

    responses_module = types.ModuleType("job_hunter_agent.routes.responses")
    responses_module.json_response = lambda content, status_code=200, headers=None: JSONResponse(  # noqa: E731
        content=content,
        status_code=status_code,
        headers=headers or {},
    )

    monkeypatch.setitem(sys.modules, "job_hunter_agent.routes", routes_module)
    monkeypatch.setitem(sys.modules, "job_hunter_agent.routes.responses", responses_module)
    monkeypatch.setattr(_config, "DEBUG_MODE", True)
    monkeypatch.setattr(_fa, "_bootstrap_runtime_knowledge", lambda: None)

    client = TestClient(_fa.create_app())
    client.cookies.set("job_hunter_session", "stale-session", domain="testserver", path="/")

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/login"
    assert "job_hunter_session=" in response.headers.get("set-cookie", "")
