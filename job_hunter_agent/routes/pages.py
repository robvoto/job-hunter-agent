from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from job_hunter_agent.auth import auth_required_response, is_admin, issue_csrf_token
from job_hunter_agent import server_helpers as srv
from job_hunter_agent.config import GLOBAL_SETTINGS_PATH
from job_hunter_agent.locations import default_location_value, load_location_options
from job_hunter_agent.paths import GLOBAL_SETTINGS_HTML_PATH, SETTINGS_HTML_PATH, SETTINGS_PARTIALS_DIR

from job_hunter_agent.routes.responses import html_response

router = APIRouter()

SETTINGS_PARTIALS = {
    "__JOB_HUNTER_SETTINGS_SECTION_SEARCH__": SETTINGS_PARTIALS_DIR / "settings-search.html",
    "__JOB_HUNTER_SETTINGS_SECTION_PROFILE__": SETTINGS_PARTIALS_DIR / "settings-profile.html",
    "__JOB_HUNTER_SETTINGS_SECTION_MATRIX__": SETTINGS_PARTIALS_DIR / "settings-matrix.html",
    "__JOB_HUNTER_SETTINGS_SECTION_RULES__": SETTINGS_PARTIALS_DIR / "settings-rules.html",
    "__JOB_HUNTER_SETTINGS_SECTION_ALERTS__": SETTINGS_PARTIALS_DIR / "settings-alerts.html",
    "__JOB_HUNTER_SETTINGS_SECTION_OPTIMISE__": SETTINGS_PARTIALS_DIR / "settings-optimise.html",
    "__JOB_HUNTER_SETTINGS_SECTION_ADMIN__": SETTINGS_PARTIALS_DIR / "settings-admin.html",
    "__JOB_HUNTER_SETTINGS_SECTION_LEARNING__": SETTINGS_PARTIALS_DIR / "settings-learning.html",
}


def _render_template_with_locations(request: Request, template_path: Path, *, page_mode: str = "default", page_title: str = "Job Hunter", page_heading: str = "", page_copy: str = "", onboarding_defaults: dict | None = None, global_settings: dict | None = None, resume_step: int | None = None) -> str:
    csrf_token = issue_csrf_token(request) or ""
    bootstrap_script = srv.build_bootstrap_script(
        csrf_token=csrf_token,
        location_options=load_location_options(),
        default_location=default_location_value(),
        onboarding_defaults=onboarding_defaults,
        global_settings=global_settings,
        resume_step=resume_step,
    )
    html = srv._render_template(template_path)
    if template_path == SETTINGS_HTML_PATH:
        for token, partial_path in SETTINGS_PARTIALS.items():
            if token in {"__JOB_HUNTER_SETTINGS_SECTION_ADMIN__", "__JOB_HUNTER_SETTINGS_SECTION_LEARNING__"}:
                html = html.replace(token, "")
            else:
                html = html.replace(token, srv._render_template(partial_path))
        html = html.replace(
            "__JOB_HUNTER_ADMIN_BADGE__",
            '<span class="sidebar-admin-badge">Admin</span>' if is_admin(request) else "",
        )
        html = html.replace(
            "__JOB_HUNTER_ADMIN_NAV_LINK__",
            (
                f'<a href="{GLOBAL_SETTINGS_PATH}" class="nav-item nav-item-admin" data-admin-only="true">Global settings</a>'
                if is_admin(request)
                else ""
            ),
        )
    if template_path == GLOBAL_SETTINGS_HTML_PATH:
        for token, partial_path in SETTINGS_PARTIALS.items():
            if token in {"__JOB_HUNTER_SETTINGS_SECTION_ADMIN__", "__JOB_HUNTER_SETTINGS_SECTION_LEARNING__"}:
                html = html.replace(token, srv._render_template(partial_path))
            else:
                html = html.replace(token, "")
    return (
        html
        .replace("__JOB_HUNTER_DEBUG_MODE_BOOL__", "true" if srv.DEBUG_MODE else "false")
        .replace("__JOB_HUNTER_ENGAGEMENT_TYPE_CHOICES__", srv.render_engagement_type_radio_group(name="engagement_pref", selected_value=srv.ENGAGEMENT_TYPE_BOTH))
        .replace("__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__", srv.render_engagement_type_select_options(selected_value=srv.ENGAGEMENT_TYPE_BOTH))
        .replace("__JOB_HUNTER_WORK_MODE_PREFERENCE_CHOICES__", srv.render_work_mode_preference_choices(selected_values=srv.WORK_MODE_PREFERENCE_NONE))
        .replace("__JOB_HUNTER_WORK_MODE_PREFERENCE_HELP__", srv.WORK_MODE_PREFERENCE_HELP_TEXT)
        .replace("__JOB_HUNTER_GOVERNMENT_PREFERENCE_OPTIONS__", srv.render_government_preference_select_options(selected_value=srv.GOVERNMENT_PREFERENCE_ANY))
        .replace("__JOB_HUNTER_GOVERNMENT_PREFERENCE_HELP__", srv.GOVERNMENT_PREFERENCE_HELP_TEXT)
        .replace("__JOB_HUNTER_SALARY_MIN_ANNUAL_LABEL__", srv.SALARY_MIN_ANNUAL_LABEL)
        .replace("__JOB_HUNTER_SALARY_MIN_DAILY_LABEL__", srv.SALARY_MIN_DAILY_LABEL)
        .replace("__JOB_HUNTER_SALARY_ANNUAL_HELP__", srv.SALARY_ANNUAL_HELP_TEXT)
        .replace("__JOB_HUNTER_SALARY_DAILY_HELP__", srv.SALARY_DAILY_HELP_TEXT)
        .replace("__JOB_HUNTER_SETTINGS_SALARY_ANNUAL_HELP__", srv.SETTINGS_SALARY_ANNUAL_HELP_TEXT)
        .replace("__JOB_HUNTER_SETTINGS_SALARY_DAILY_HELP__", srv.SETTINGS_SALARY_DAILY_HELP_TEXT)
        .replace("__JOB_HUNTER_PAGE_MODE__", page_mode)
        .replace("__JOB_HUNTER_PAGE_TITLE__", page_title)
        .replace("__JOB_HUNTER_PAGE_HEADING__", page_heading)
        .replace("__JOB_HUNTER_PAGE_COPY__", page_copy)
        .replace("__JOB_HUNTER_BOOTSTRAP_SCRIPTS__", bootstrap_script)
    )


@router.get("/")
@router.get("/workspace")
def page_workspace(request: Request):  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    if srv.WORKSPACE_HTML_PATH.exists():
        csrf_token = issue_csrf_token(request) or ""
        html = srv._render_template(srv.WORKSPACE_HTML_PATH)
        html = html.replace("__JOB_HUNTER_DEBUG_MODE__", "true" if srv.DEBUG_MODE else "false")
        html = html.replace("__JOB_HUNTER_CSRF_TOKEN__", csrf_token)
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/workspace.html</p>")


@router.get(GLOBAL_SETTINGS_PATH)
def page_admin_profile(request: Request):  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    if not is_admin(request):
        return auth_required_response(GLOBAL_SETTINGS_PATH, True)
    if GLOBAL_SETTINGS_HTML_PATH.exists():
        html = _render_template_with_locations(
            request,
            GLOBAL_SETTINGS_HTML_PATH,
            page_mode="admin",
            page_title="Global settings - Job Hunter",
            page_heading="Global settings",
            page_copy="Shared controls and learning live here.",
            global_settings=srv.load_global_settings(),
        )
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/global-settings.html</p>")


@router.get("/profile")
def page_profile():  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    return RedirectResponse("/settings", status_code=302)


@router.get("/settings")
def page_settings(request: Request):  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse("/start", status_code=302)
    if SETTINGS_HTML_PATH.exists():
        html = _render_template_with_locations(
            request,
            SETTINGS_HTML_PATH,
            page_mode="settings",
            page_title="Settings - Job Hunter",
            page_heading="Settings",
            page_copy="Configure your candidate search and profile settings here. Shared global settings live on the Global settings screen.",
        )
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/settings.html</p>")


@router.get("/start")
def page_onboarding(request: Request):  # type: ignore[no-untyped-def]
    if srv._onboarding_complete():
        return RedirectResponse("/", status_code=302)
    if srv.ONBOARDING_HTML_PATH.exists():
        html = _render_template_with_locations(
            request,
            srv.ONBOARDING_HTML_PATH,
            onboarding_defaults=srv.DEFAULT_ONBOARDING_SETTINGS,
            resume_step=srv._onboarding_resume_step(),
        )
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/onboarding.html</p>")


@router.get("/demo")
def page_demo():  # type: ignore[no-untyped-def]
    if srv.SHOWCASE_PATH.exists():
        return html_response(srv.SHOWCASE_PATH.read_text(encoding="utf-8", errors="ignore"))
    return html_response("<h1>Demo page not found</h1>")
