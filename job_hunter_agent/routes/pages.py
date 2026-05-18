from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from job_hunter_agent.auth import auth_required_response, is_admin, issue_csrf_token
from job_hunter_agent import server_helpers as srv
from job_hunter_agent.config import GLOBAL_SETTINGS_PATH, ONBOARDING_PATH, ONBOARDING_DEBUG_ALIAS_PATH
from job_hunter_agent.locations import default_location_value, load_location_options
from job_hunter_agent.profile_store import (
    ENGAGEMENT_TYPE_DEFAULT_VALUES,
    GovPref,
    WorkMode,
    SECTOR_PREFERENCE_HELP_TEXT,
    SALARY_MIN_ANNUAL_LABEL,
    SALARY_MIN_DAILY_LABEL,
    SALARY_MIN_COMPENSATION_HELP_TEXT,
    SETTINGS_SALARY_ANNUAL_HELP_TEXT,
    SETTINGS_SALARY_DAILY_HELP_TEXT,
    WORK_MODE_PREFERENCE_HELP_TEXT,
)
from job_hunter_agent.global_settings import KEY_SEEK_MAX_PAGES
from job_hunter_agent.paths import (
    GLOBAL_SETTINGS_HTML_PATH,
    ONBOARDING_HTML_PATH,
    SETTINGS_GLOBAL_PARTIALS_DIR,
    SETTINGS_HTML_PATH,
    SETTINGS_STANDARD_PARTIALS_DIR,
    WORKSPACE_HTML_PATH,
)

from job_hunter_agent.routes.responses import html_response

router = APIRouter()

SETTINGS_PARTIALS = {
    "__JOB_HUNTER_SETTINGS_SECTION_SEARCH__": SETTINGS_STANDARD_PARTIALS_DIR / "settings-search.html",
    "__JOB_HUNTER_SETTINGS_SECTION_PROFILE__": SETTINGS_STANDARD_PARTIALS_DIR / "settings-profile.html",
    "__JOB_HUNTER_SETTINGS_SECTION_MATRIX__": SETTINGS_STANDARD_PARTIALS_DIR / "settings-matrix.html",
    "__JOB_HUNTER_SETTINGS_SECTION_RULES__": SETTINGS_STANDARD_PARTIALS_DIR / "settings-rules.html",
    "__JOB_HUNTER_SETTINGS_SECTION_ALERTS__": SETTINGS_STANDARD_PARTIALS_DIR / "settings-alerts.html",
    "__JOB_HUNTER_SETTINGS_SECTION_OPTIMISE__": SETTINGS_STANDARD_PARTIALS_DIR / "settings-optimise.html",
    "__JOB_HUNTER_SETTINGS_SECTION_ADMIN__": SETTINGS_GLOBAL_PARTIALS_DIR / "settings-admin.html",
    "__JOB_HUNTER_SETTINGS_SECTION_LEARNING__": SETTINGS_GLOBAL_PARTIALS_DIR / "settings-learning.html",
}


def _render_template_with_locations(request: Request, template_path: Path, *, page_mode: str = "default", page_title: str = "Job Hunter", page_heading: str = "", page_copy: str = "", onboarding_defaults: dict | None = None, onboarding_copy: dict | None = None, global_settings: dict | None = None, resume_step: int | None = None) -> str:
    csrf_token = issue_csrf_token(request) or ""
    bootstrap_script = srv.build_bootstrap_script(
        csrf_token=csrf_token,
        location_options=load_location_options(),
        default_location=default_location_value(),
        onboarding_defaults=onboarding_defaults,
        onboarding_copy=onboarding_copy,
        global_settings=global_settings,
        resume_step=resume_step,
    )
    html = srv._render_template(template_path)
    if template_path == SETTINGS_HTML_PATH:
        title_tier_labels = srv.load_onboarding_title_tier_labels()
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
        html = html.replace("__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_LABEL__", title_tier_labels["search_keyword_label"])
        html = html.replace("__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_HELP__", title_tier_labels["search_keyword_help"])
        html = html.replace("__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_EXAMPLE__", title_tier_labels["search_keyword_example"])
    if template_path == GLOBAL_SETTINGS_HTML_PATH:
        for token, partial_path in SETTINGS_PARTIALS.items():
            if token in {"__JOB_HUNTER_SETTINGS_SECTION_ADMIN__", "__JOB_HUNTER_SETTINGS_SECTION_LEARNING__"}:
                html = html.replace(token, srv._render_template(partial_path))
            else:
                html = html.replace(token, "")
    if template_path == ONBOARDING_HTML_PATH:
        title_tier_labels = srv.load_onboarding_title_tier_labels()
        onboarding_replacements = {
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_LABEL__": title_tier_labels["target_roles_label"],
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_HELP__": title_tier_labels["target_roles_help"],
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_PLACEHOLDER__": title_tier_labels["target_roles_input_placeholder"],
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_EMPTY_TEXT__": title_tier_labels["target_roles_empty_text"],
            "__JOB_HUNTER_TITLE_TIER_MOVE_TO_TARGET_ROLES_LABEL__": title_tier_labels["move_to_target_roles_label"],
            "__JOB_HUNTER_TITLE_TIER_KEEP_TARGET_ROLES_CONTINUE_ERROR__": title_tier_labels["keep_target_roles_continue_error"],
            "__JOB_HUNTER_TITLE_TIER_KEEP_TARGET_ROLES_FINISH_ERROR__": title_tier_labels["keep_target_roles_finish_error"],
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_LABEL__": title_tier_labels["also_consider_roles_label"],
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_HELP__": title_tier_labels["also_consider_roles_help"],
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_PLACEHOLDER__": title_tier_labels["also_consider_roles_input_placeholder"],
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_EMPTY_TEXT__": title_tier_labels["also_consider_roles_empty_text"],
            "__JOB_HUNTER_TITLE_TIER_MOVE_TO_ALSO_CONSIDER_LABEL__": title_tier_labels["move_to_also_consider_label"],
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_LABEL__": title_tier_labels["search_keyword_label"],
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_HELP__": title_tier_labels["search_keyword_help"],
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_EXAMPLE__": title_tier_labels["search_keyword_example"],
        }
        for token, value in onboarding_replacements.items():
            html = html.replace(token, value)
    return (
        html
        .replace("__JOB_HUNTER_DEBUG_MODE_BOOL__", "true" if srv.DEBUG_MODE else "false")
        .replace("__JOB_HUNTER_ENGAGEMENT_TYPE_CHOICES__", srv.render_engagement_type_choices(name="engagement_type", selected_values=ENGAGEMENT_TYPE_DEFAULT_VALUES))
        .replace("__JOB_HUNTER_WORK_MODE_PREFERENCE_CHOICES__", srv.render_work_mode_preference_choices(selected_values=WorkMode.NONE))
        .replace("__JOB_HUNTER_WORK_MODE_PREFERENCE_HELP__", WORK_MODE_PREFERENCE_HELP_TEXT)
        .replace("__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__", srv.render_sector_preference_select_options(selected_value=GovPref.ANY))
        .replace("__JOB_HUNTER_SECTOR_PREFERENCE_CHOICES__", srv.render_sector_preference_choices(selected_values=GovPref.ANY))
        .replace("__JOB_HUNTER_SECTOR_PREFERENCE_HELP__", SECTOR_PREFERENCE_HELP_TEXT)
        .replace("__JOB_HUNTER_SEEK_MAX_PAGES_CHOICES__", srv.render_seek_max_pages_choices(label_id="seek_max_pages_label"))
        .replace(
            "__JOB_HUNTER_SEARCH_DEFAULT_SEEK_MAX_PAGES_CHOICES__",
            srv.render_seek_max_pages_choices(
                selected_value=(
                    global_settings.get("search_settings", {}).get(KEY_SEEK_MAX_PAGES)
                    if isinstance(global_settings, dict)
                    else None
                ),
                label_id="search_default_seek_max_pages_label",
            ),
        )
        .replace("__JOB_HUNTER_SALARY_MIN_ANNUAL_LABEL__", SALARY_MIN_ANNUAL_LABEL)
        .replace("__JOB_HUNTER_SALARY_MIN_DAILY_LABEL__", SALARY_MIN_DAILY_LABEL)
        .replace("__JOB_HUNTER_SALARY_MIN_COMPENSATION_HELP__", SALARY_MIN_COMPENSATION_HELP_TEXT)
        .replace("__JOB_HUNTER_SALARY_ANNUAL_HELP__", SETTINGS_SALARY_ANNUAL_HELP_TEXT)
        .replace("__JOB_HUNTER_SALARY_DAILY_HELP__", SETTINGS_SALARY_DAILY_HELP_TEXT)
        .replace("__JOB_HUNTER_SETTINGS_SALARY_ANNUAL_HELP__", SETTINGS_SALARY_ANNUAL_HELP_TEXT)
        .replace("__JOB_HUNTER_SETTINGS_SALARY_DAILY_HELP__", SETTINGS_SALARY_DAILY_HELP_TEXT)
        .replace("__JOB_HUNTER_ONBOARDING_STEP_1_TITLE__", srv.ONBOARDING_PAGE_COPY["steps"]["1"]["title"])
        .replace("__JOB_HUNTER_ONBOARDING_STEP_1_SECTION_COPY__", srv.ONBOARDING_PAGE_COPY["steps"]["1"]["section_copy"])
        .replace("__JOB_HUNTER_ONBOARDING_STEP_2_TITLE__", srv.ONBOARDING_PAGE_COPY["steps"]["2"]["title"])
        .replace("__JOB_HUNTER_ONBOARDING_STEP_2_SECTION_COPY__", srv.ONBOARDING_PAGE_COPY["steps"]["2"]["section_copy"])
        .replace("__JOB_HUNTER_ONBOARDING_STEP_3_TITLE__", srv.ONBOARDING_PAGE_COPY["steps"]["3"]["title"])
        .replace("__JOB_HUNTER_ONBOARDING_STEP_3_SECTION_COPY__", srv.ONBOARDING_PAGE_COPY["steps"]["3"]["section_copy"])
        .replace("__JOB_HUNTER_ONBOARDING_STEP_4_TITLE__", srv.ONBOARDING_PAGE_COPY["steps"]["4"]["title"])
        .replace("__JOB_HUNTER_ONBOARDING_STEP_4_SECTION_COPY__", srv.ONBOARDING_PAGE_COPY["steps"]["4"]["section_copy"])
        .replace("__JOB_HUNTER_ONBOARDING_HERO_TITLE__", srv.ONBOARDING_PAGE_COPY["steps"]["1"]["hero_title"])
        .replace("__JOB_HUNTER_ONBOARDING_HERO_COPY__", srv.ONBOARDING_PAGE_COPY["steps"]["1"]["hero_copy"])
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
        return RedirectResponse(ONBOARDING_PATH, status_code=302)
    if WORKSPACE_HTML_PATH.exists():
        csrf_token = issue_csrf_token(request) or ""
        html = srv._render_template(WORKSPACE_HTML_PATH)
        html = html.replace("__JOB_HUNTER_DEBUG_MODE__", "true" if srv.DEBUG_MODE else "false")
        html = html.replace("__JOB_HUNTER_CSRF_TOKEN__", csrf_token)
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/workspace.html</p>")


@router.get(GLOBAL_SETTINGS_PATH)
def page_admin_profile(request: Request):  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse(ONBOARDING_PATH, status_code=302)
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
        return RedirectResponse(ONBOARDING_PATH, status_code=302)
    return RedirectResponse("/settings", status_code=302)


@router.get("/settings")
def page_settings(request: Request):  # type: ignore[no-untyped-def]
    if not srv._onboarding_complete():
        return RedirectResponse(ONBOARDING_PATH, status_code=302)
    if SETTINGS_HTML_PATH.exists():
        html = _render_template_with_locations(
            request,
            SETTINGS_HTML_PATH,
            page_mode="settings",
            page_title="Settings - Job Hunter",
            page_heading="Settings",
            page_copy="Configure your candidate search and profile settings here.",
        )
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/settings.html</p>")


@router.get(ONBOARDING_PATH)
@router.get(ONBOARDING_DEBUG_ALIAS_PATH)
def page_onboarding(request: Request):  # type: ignore[no-untyped-def]
    if srv._onboarding_complete() and not srv.DEBUG_MODE:
        return RedirectResponse("/", status_code=302)
    if ONBOARDING_HTML_PATH.exists():
        html = _render_template_with_locations(
            request,
            ONBOARDING_HTML_PATH,
            onboarding_defaults=srv.DEFAULT_ONBOARDING_SETTINGS,
            onboarding_copy=srv.ONBOARDING_PAGE_COPY,
            resume_step=srv._onboarding_resume_step(),
        )
        return html_response(html)
    return html_response("<h1>Template missing</h1><p>Missing templates/onboarding.html</p>")


@router.get("/demo")
def page_demo():  # type: ignore[no-untyped-def]
    if srv.SHOWCASE_PATH.exists():
        return html_response(srv.SHOWCASE_PATH.read_text(encoding="utf-8", errors="ignore"))
    return html_response("<h1>Demo page not found</h1>")
