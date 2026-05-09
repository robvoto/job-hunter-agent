from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import RedirectResponse

from job_hunter_agent.auth import issue_csrf_token
from job_hunter_agent import server_helpers as srv

from job_hunter_agent.routes.responses import html_response

router = APIRouter()


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
@router.get("/profile")
def page_admin_profile():  # type: ignore[no-untyped-def]
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
        csrf_token = issue_csrf_token(request) or ""
        html = srv._render_template(srv.SETTINGS_HTML_PATH).replace("__JOB_HUNTER_CSRF_TOKEN__", csrf_token)
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/settings.html</p>")


@router.get("/start")
@router.get("/onboarding")
def page_onboarding(request: Request):  # type: ignore[no-untyped-def]
    if srv.ONBOARDING_HTML_PATH.exists():
        csrf_token = issue_csrf_token(request) or ""
        html = srv._render_template(srv.ONBOARDING_HTML_PATH).replace("__JOB_HUNTER_CSRF_TOKEN__", csrf_token)
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/onboarding.html</p>")


@router.get("/demo")
def page_demo():  # type: ignore[no-untyped-def]
    if srv.SHOWCASE_PATH.exists():
        return html_response(srv.SHOWCASE_PATH.read_text(encoding="utf-8", errors="ignore"))
    return html_response("<h1>Demo page not found</h1>")
