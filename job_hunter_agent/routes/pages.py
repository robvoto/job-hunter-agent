import json
from pathlib import Path

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import RedirectResponse

from job_hunter_agent.auth import auth_required_response, is_authenticated, issue_csrf_token
from job_hunter_agent import server_helpers as srv
from job_hunter_agent.locations import default_location_value, load_location_options

from job_hunter_agent.routes.responses import html_response

router = APIRouter()


def _render_template_with_locations(request: Request, template_path: Path, *, page_mode: str, page_title: str, page_heading: str, page_copy: str) -> str:
    csrf_token = issue_csrf_token(request) or ""
    html = srv._render_template(template_path)
    return (
        html
        .replace("__JOB_HUNTER_CSRF_TOKEN__", csrf_token)
        .replace("__JOB_HUNTER_PAGE_MODE__", page_mode)
        .replace("__JOB_HUNTER_PAGE_TITLE__", page_title)
        .replace("__JOB_HUNTER_PAGE_HEADING__", page_heading)
        .replace("__JOB_HUNTER_PAGE_COPY__", page_copy)
        .replace("__JOB_HUNTER_LOCATION_OPTIONS__", json.dumps(load_location_options(), ensure_ascii=True))
        .replace("__JOB_HUNTER_DEFAULT_LOCATION__", default_location_value())
    )


@router.get("/")
@router.get("/workspace")
@router.get("/dashboard")
def page_workspace(request: Request):  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    if srv.WORKSPACE_HTML_PATH.exists():
        csrf_token = issue_csrf_token(request) or ""
        html = srv._render_template(srv.WORKSPACE_HTML_PATH).replace("__JOB_HUNTER_CSRF_TOKEN__", csrf_token)
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/workspace.html</p>")


@router.get("/admin")
def page_admin_profile(request: Request):  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    if not is_authenticated(request):
        return auth_required_response("/admin", True)
    if srv.SETTINGS_HTML_PATH.exists():
        html = _render_template_with_locations(
            request,
            srv.SETTINGS_HTML_PATH,
            page_mode="admin",
            page_title="Admin - Job Hunter",
            page_heading="Admin",
            page_copy="Owner-only global controls and shared learning live here.",
        )
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/settings.html</p>")


@router.get("/profile")
def page_profile():  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    return RedirectResponse("/settings", status_code=302)


@router.get("/dashboard")
def page_dashboard():  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    return RedirectResponse("/", status_code=302)


@router.get("/settings")
def page_settings(request: Request):  # type: ignore[no-untyped-def]
    if not srv.DEBUG_MODE and not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    if srv.SETTINGS_HTML_PATH.exists():
        html = _render_template_with_locations(
            request,
            srv.SETTINGS_HTML_PATH,
            page_mode="settings",
            page_title="Settings - Job Hunter",
            page_heading="Settings",
            page_copy="Configure your candidate search and profile settings here. Owner-only admin controls live on the Admin screen.",
        )
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/settings.html</p>")


@router.get("/start")
@router.get("/onboarding")
def page_onboarding(request: Request):  # type: ignore[no-untyped-def]
    if srv.ONBOARDING_HTML_PATH.exists():
        csrf_token = issue_csrf_token(request) or ""
        html = (
            srv._render_template(srv.ONBOARDING_HTML_PATH)
            .replace("__JOB_HUNTER_CSRF_TOKEN__", csrf_token)
            .replace("__JOB_HUNTER_LOCATION_OPTIONS__", json.dumps(load_location_options(), ensure_ascii=True))
            .replace("__JOB_HUNTER_DEFAULT_LOCATION__", default_location_value())
        )
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/onboarding.html</p>")


@router.get("/demo")
def page_demo():  # type: ignore[no-untyped-def]
    if srv.SHOWCASE_PATH.exists():
        return html_response(srv.SHOWCASE_PATH.read_text(encoding="utf-8", errors="ignore"))
    return html_response("<h1>Demo page not found</h1>")
