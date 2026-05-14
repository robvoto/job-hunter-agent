"""FastAPI route modules for ``fastapi_app.create_app``."""

from __future__ import annotations

from fastapi import FastAPI

from job_hunter_agent.routes import (
    agent_telegram,
    auth_google,
    dashboard_api,
    onboarding_api,
    pages,
    profile_materials,
    review,
    scrape_debug,
    signals,
    static_docs,
)


def register_routes(app: FastAPI) -> None:
    """Attach all dashboard / settings HTTP routes."""
    for mod in (
        auth_google,
        static_docs,
        pages,
        dashboard_api,
        profile_materials,
        agent_telegram,
        signals,
        onboarding_api,
        scrape_debug,
        review,
    ):
        app.include_router(mod.router)
