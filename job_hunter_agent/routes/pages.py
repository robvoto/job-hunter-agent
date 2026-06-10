"""Route handlers for pages."""

import json
from html import escape as _html_escape
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.auth import (
    auth_required_response,
    is_admin,
    issue_csrf_token,
    read_session_user,
)
from job_hunter_agent.config import (
    GLOBAL_SETTINGS_PATH,
    LOGOUT_PATH,
    ONBOARDING_DEBUG_ALIAS_PATH,
    ONBOARDING_PATH,
)
from job_hunter_agent.global_settings import KEY_SEEK_MAX_PAGES
from job_hunter_agent.locations import default_location_value, load_location_options
from job_hunter_agent.paths import (
    GLOBAL_SETTINGS_HTML_PATH,
    ONBOARDING_HTML_PATH,
    SETTINGS_GLOBAL_PARTIALS_DIR,
    SETTINGS_HTML_PATH,
    SETTINGS_STANDARD_PARTIALS_DIR,
    WORKSPACE_HTML_PATH,
)
from job_hunter_agent.profile_store import (
    ENGAGEMENT_TYPE_DEFAULT_VALUES,
    MIN_CONTRACT_MONTH_HELP_TEXT,
    MIN_CONTRACT_MONTH_LABEL,
    MIN_CONTRACT_MONTH_NONE_LABEL,
    SALARY_MIN_ANNUAL_LABEL,
    SALARY_MIN_COMPENSATION_HELP_TEXT,
    SALARY_MIN_DAILY_LABEL,
    SECTOR_PREFERENCE_HELP_TEXT,
    SETTINGS_SALARY_ANNUAL_HELP_TEXT,
    SETTINGS_SALARY_DAILY_HELP_TEXT,
    WORK_MODE_PREFERENCE_DEFAULT_VALUES,
    WORK_MODE_PREFERENCE_HELP_TEXT,
    WORK_TYPE_PREFERENCE_HELP_TEXT,
    GovPref,
)
from job_hunter_agent.routes.responses import html_response
from job_hunter_agent.user_context import get_user_id_for_runtime

router = APIRouter()

JOB_HUNTER_LOGO_SRC = "/static/assets/job_hunter_img.png"


def _build_top_utility_bar_html(
    request: Request,
    *,
    csrf_token: str | None = None,
    shortcut_href: str | None = None,
    shortcut_label: str | None = None,
    shortcut_aria_label: str | None = None,
) -> str:

    shared_labels = srv.load_shared_ui_labels()

    session_user = read_session_user(request)

    if session_user:
        user_email = session_user.get("email", "")

        user_name = session_user.get("name", "")

        user_initial = (user_name[:1] or user_email[:1]).upper()

    else:
        user_email = ""

        user_name = ""

        user_initial = "?"

    brand_html = (
        '<div class="job-hunter-page-utility__brand" aria-label="Job Hunter">'
        f'<img src="{JOB_HUNTER_LOGO_SRC}" alt="" class="job-hunter-page-utility__brand-icon">'
        '<span class="job-hunter-page-utility__brand-name">Job Hunter</span>'
        "</div>"
    )

    name_row = (
        f'<p class="job-hunter-account-bar__name">{_html_escape(user_name)}</p>'
        if user_name
        else ""
    )

    email_row = (
        f'<p class="job-hunter-account-bar__email">{_html_escape(user_email)}</p>'
        if user_email
        else ""
    )

    shortcut_html = ""

    if shortcut_href and shortcut_label:
        shortcut_aria = shortcut_aria_label or shortcut_label

        shortcut_html = (
            f'<a href="{_html_escape(shortcut_href)}" class="btn btn-secondary account-bar-shortcut"'
            f' aria-label="{_html_escape(shortcut_aria)}" title="{_html_escape(shortcut_aria)}">'
            f"{_html_escape(shortcut_label)}"
            f"</a>"
        )

    test_html = ""

    if srv.DEBUG_MODE:
        test_html = (
            '<div class="account-bar-test" id="job_hunter_account_test_panel">'
            f'<button class="account-bar-test-trigger" id="job_hunter_account_test_trigger" type="button"'
            f' aria-haspopup="true" aria-expanded="false">{_html_escape(shared_labels["account_menu_test_label"])}</button>'
            f'<div class="account-bar-test-menu" id="job_hunter_account_test_menu" role="menu"'
            f' aria-label="{_html_escape(shared_labels["account_menu_test_actions_label"])}">'
            f'<div class="account-bar-test-menu-title">{_html_escape(shared_labels["account_menu_test_actions_label"])}</div>'
            '<div class="account-bar-test-menu-separator" aria-hidden="true"></div>'
            f'<button class="account-bar-test-action" id="job_hunter_reset_user_btn" type="button" role="menuitem">'
            f"{_html_escape(shared_labels['account_menu_reset_user_label'])}"
            "</button>"
            "</div></div>"
        )

    logout_form = (
        f'<form class="job-hunter-account-bar__logout-form" action="{LOGOUT_PATH}" method="post">'
        f'<input type="hidden" name="csrf_token" value="{_html_escape(csrf_token or "")}">'
        f'<button class="job-hunter-account-bar__logout" type="submit" role="menuitem">'
        f"{_html_escape(shared_labels['account_menu_logout_label'])}"
        "</button>"
        "</form>"
    )

    return (
        '<div class="job-hunter-page-utility" id="job_hunter_top_utility_bar">'
        f"{brand_html}"
        '<div class="job-hunter-account-bar">'
        '<div class="job-hunter-account-bar__cluster">'
        f'<select id="theme_picker" aria-label="{_html_escape(shared_labels["select_theme_aria_label"])}">'
        '<option value="soft-professional">Soft Professional</option>'
        '<option value="bold-aggressive">Bold Aggressive</option>'
        '<option value="dark-professional">Dark Professional</option>'
        "</select>"
        f"{shortcut_html}"
        f"{test_html}"
        "</div>"
        '<div class="job-hunter-account-bar__user" id="job_hunter_account_user_menu">'
        f'<button class="job-hunter-account-bar__avatar" id="job_hunter_account_avatar_btn" type="button"'
        f' aria-haspopup="true" aria-expanded="false" aria-label="{_html_escape(shared_labels["account_menu_aria_label"])}"'
        f' title="{_html_escape(shared_labels["account_menu_title"])}">{_html_escape(user_initial)}</button>'
        '<div class="job-hunter-account-bar__dropdown" id="job_hunter_account_dropdown" role="menu" hidden>'
        f"{name_row}{email_row}"
        '<div class="job-hunter-account-bar__dropdown-sep" aria-hidden="true"></div>'
        f"{logout_form}"
        "</div></div></div>"
        "</div>"
    )


SETTINGS_PARTIALS = {
    "__JOB_HUNTER_SETTINGS_SECTION_SEARCH__": SETTINGS_STANDARD_PARTIALS_DIR
    / "settings-search.html",
    "__JOB_HUNTER_SETTINGS_SECTION_PROFILE__": SETTINGS_STANDARD_PARTIALS_DIR
    / "settings-profile.html",
    "__JOB_HUNTER_SETTINGS_SECTION_MATRIX__": SETTINGS_STANDARD_PARTIALS_DIR
    / "settings-matrix.html",
    "__JOB_HUNTER_SETTINGS_SECTION_RULES__": SETTINGS_STANDARD_PARTIALS_DIR / "settings-rules.html",
    "__JOB_HUNTER_SETTINGS_SECTION_ALERTS__": SETTINGS_STANDARD_PARTIALS_DIR
    / "settings-alerts.html",
    "__JOB_HUNTER_SETTINGS_SECTION_OPTIMISE__": SETTINGS_STANDARD_PARTIALS_DIR
    / "settings-optimise.html",
    "__JOB_HUNTER_SETTINGS_SECTION_ADMIN__": SETTINGS_GLOBAL_PARTIALS_DIR / "settings-admin.html",
    "__JOB_HUNTER_SETTINGS_SECTION_LEARNING__": SETTINGS_GLOBAL_PARTIALS_DIR
    / "settings-learning.html",
}


def _replace_label_tokens(html: str, prefix: str, labels: dict[str, str]) -> str:

    for key, value in labels.items():
        html = html.replace(f"__JOB_HUNTER_{prefix}_{key.upper()}__", value)

    return html


def _render_template_with_locations(
    request: Request,
    template_path: Path,
    *,
    page_mode: str = "default",
    page_title: str = "Job Hunter",
    page_heading: str = "",
    page_copy: str = "",
    onboarding_defaults: dict | None = None,
    global_settings: dict | None = None,
    resume_step: int | None = None,
    account_shortcut_href: str | None = None,
    account_shortcut_label: str | None = None,
    account_shortcut_aria_label: str | None = None,
) -> str:

    csrf_token = issue_csrf_token(request)

    shared_labels = srv.load_shared_ui_labels()

    bootstrap_script = srv.build_bootstrap_script(
        csrf_token=csrf_token,
        location_options=load_location_options(),
        default_location=default_location_value(),
        onboarding_defaults=onboarding_defaults,
        global_settings=global_settings,
        resume_step=resume_step,
        user_id=get_user_id_for_runtime(),
    )

    html = srv._render_template(template_path)

    html = html.replace(
        "__JOB_HUNTER_TOP_UTILITY_BAR__",
        _build_top_utility_bar_html(
            request,
            shortcut_href=account_shortcut_href,
            shortcut_label=account_shortcut_label,
            shortcut_aria_label=account_shortcut_aria_label,
            csrf_token=csrf_token,
        ),
    )

    html = html.replace(
        "__JOB_HUNTER_WORKSPACE_LINK_LABEL__",
        shared_labels["account_menu_workspace_shortcut_label"],
    )

    if template_path == SETTINGS_HTML_PATH:
        title_tier_labels = srv.load_onboarding_title_tier_labels()

        capability_labels = srv.load_capability_ui_labels()

        search_source_labels = srv.load_search_source_labels()

        settings_alerts_labels = srv.load_settings_alerts_labels()

        for token, partial_path in SETTINGS_PARTIALS.items():
            if token in {
                "__JOB_HUNTER_SETTINGS_SECTION_ADMIN__",
                "__JOB_HUNTER_SETTINGS_SECTION_LEARNING__",
            }:
                html = html.replace(token, "")

            else:
                html = html.replace(token, srv._render_template(partial_path))

        html = html.replace(
            "__JOB_HUNTER_ADMIN_BADGE__",
            '<span class="sidebar-admin-badge">Admin</span>' if is_admin(request) else "",
        )

        html = html.replace(
            "__JOB_HUNTER_ADMIN_NAV_GROUP__",
            (
                '<div class="sidebar-group-label sidebar-group-label-global">Admin</div>'
                f'<a href="{GLOBAL_SETTINGS_PATH}" class="nav-item nav-item-admin" data-admin-only="true">Global settings</a>'
                if is_admin(request)
                else ""
            ),
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_LABEL__",
            title_tier_labels["search_keyword_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_HELP__",
            title_tier_labels["search_keyword_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_EXAMPLE__",
            title_tier_labels["search_keyword_example"],
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_LABEL__", title_tier_labels["target_roles_label"]
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_HELP__", title_tier_labels["target_roles_help"]
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_PLACEHOLDER__",
            title_tier_labels["target_roles_input_placeholder"],
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_LABEL__",
            title_tier_labels["also_consider_roles_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_HELP__",
            title_tier_labels["also_consider_roles_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_PLACEHOLDER__",
            title_tier_labels["also_consider_roles_input_placeholder"],
        )

        html = html.replace(
            "__JOB_HUNTER_MIN_CONTRACT_MONTH_OPTIONS__",
            srv.render_min_contract_month_options(selected_value=None),
        )

        html = html.replace("__JOB_HUNTER_MIN_CONTRACT_MONTH_LABEL__", MIN_CONTRACT_MONTH_LABEL)

        html = html.replace("__JOB_HUNTER_MIN_CONTRACT_MONTH_HELP__", MIN_CONTRACT_MONTH_HELP_TEXT)

        html = html.replace(
            "__JOB_HUNTER_CAPABILITY_ADD_BUTTON_ARIA_LABEL__",
            capability_labels["add_button_aria_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SEARCH_SOURCE_SECTION_TITLE__", search_source_labels["section_title"]
        )

        html = html.replace(
            "__JOB_HUNTER_SEARCH_SOURCE_SECTION_COPY__", search_source_labels["section_copy"]
        )

        html = html.replace(
            "__JOB_HUNTER_SEARCH_SOURCE_SHARED_INPUTS_COPY__",
            search_source_labels["shared_inputs_copy"],
        )

        html = html.replace(
            "__JOB_HUNTER_SEARCH_SOURCE_SEEK_TOGGLE_LABEL__",
            search_source_labels["seek_toggle_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SEARCH_SOURCE_SEEK_TOGGLE_HELP__",
            search_source_labels["seek_toggle_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_SEARCH_SOURCE_LINKEDIN_TOGGLE_LABEL__",
            search_source_labels["linkedin_toggle_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SEARCH_SOURCE_LINKEDIN_TOGGLE_HELP__",
            search_source_labels["linkedin_toggle_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_SECTION_TITLE__", settings_alerts_labels["section_title"]
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_SECTION_COPY__", settings_alerts_labels["section_copy"]
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_LABELS_JSON__",
            json.dumps(settings_alerts_labels, ensure_ascii=True),
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_HEADING__",
            settings_alerts_labels["telegram_heading"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_COPY__", settings_alerts_labels["telegram_copy"]
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_ENABLED_LABEL__",
            settings_alerts_labels["telegram_enabled_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_ENABLED_HELP__",
            settings_alerts_labels["telegram_enabled_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_BOT_TOKEN_LABEL__",
            settings_alerts_labels["telegram_bot_token_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_BOT_TOKEN_HELP__",
            settings_alerts_labels["telegram_bot_token_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_BOT_USERNAME_LABEL__",
            settings_alerts_labels["telegram_bot_username_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_BOT_USERNAME_HELP__",
            settings_alerts_labels["telegram_bot_username_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_DISABLE_LINK_PREVIEW_LABEL__",
            settings_alerts_labels["telegram_disable_link_preview_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_DISABLE_LINK_PREVIEW_HELP__",
            settings_alerts_labels["telegram_disable_link_preview_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_CONNECT_HEADING__",
            settings_alerts_labels["telegram_connect_heading"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_CONNECT_HELP__",
            settings_alerts_labels["telegram_connect_help"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_CONNECT_OPEN_LABEL__",
            settings_alerts_labels["telegram_connect_open_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_CONNECT_REFRESH_LABEL__",
            settings_alerts_labels["telegram_connect_refresh_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_CONNECTION_STATUS_LABEL__",
            settings_alerts_labels["telegram_connection_status_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_CONNECTION_STATUS_EMPTY__",
            settings_alerts_labels["telegram_connection_status_empty"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_TEST_LABEL__",
            settings_alerts_labels["telegram_test_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_SUBSCRIBERS_EMPTY__",
            settings_alerts_labels["telegram_subscribers_empty"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_SUBSCRIBERS_LABEL__",
            settings_alerts_labels["telegram_subscribers_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_TELEGRAM_USER_LABEL__",
            settings_alerts_labels["telegram_user_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_LLM_HEADING__", settings_alerts_labels["llm_heading"]
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_LLM_COPY__", settings_alerts_labels["llm_copy"]
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_LLM_MODEL_LABEL__",
            settings_alerts_labels["llm_model_label"],
        )

        html = html.replace(
            "__JOB_HUNTER_SETTINGS_ALERTS_LLM_MODEL_PLACEHOLDER__",
            settings_alerts_labels["llm_model_placeholder"],
        )

    if template_path == GLOBAL_SETTINGS_HTML_PATH:
        global_settings_labels = srv.load_global_settings_labels()

        for token, partial_path in SETTINGS_PARTIALS.items():
            if token in {
                "__JOB_HUNTER_SETTINGS_SECTION_ADMIN__",
                "__JOB_HUNTER_SETTINGS_SECTION_LEARNING__",
            }:
                html = html.replace(token, srv._render_template(partial_path))

            else:
                html = html.replace(token, "")

        html = _replace_label_tokens(html, "GLOBAL_SETTINGS", global_settings_labels)

    if template_path == ONBOARDING_HTML_PATH:
        title_tier_labels = srv.load_onboarding_title_tier_labels()

        onboarding_page_labels = srv.load_onboarding_page_labels()

        onboarding_replacements = {
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_LABEL__": title_tier_labels["target_roles_label"],
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_HELP__": title_tier_labels["target_roles_help"],
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_PLACEHOLDER__": title_tier_labels[
                "target_roles_input_placeholder"
            ],
            "__JOB_HUNTER_TITLE_TIER_TARGET_ROLES_EMPTY_TEXT__": title_tier_labels[
                "target_roles_empty_text"
            ],
            "__JOB_HUNTER_TITLE_TIER_MOVE_TO_TARGET_ROLES_LABEL__": title_tier_labels[
                "move_to_target_roles_label"
            ],
            "__JOB_HUNTER_TITLE_TIER_KEEP_TARGET_ROLES_CONTINUE_ERROR__": title_tier_labels[
                "keep_target_roles_continue_error"
            ],
            "__JOB_HUNTER_TITLE_TIER_KEEP_TARGET_ROLES_FINISH_ERROR__": title_tier_labels[
                "keep_target_roles_finish_error"
            ],
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_LABEL__": title_tier_labels[
                "also_consider_roles_label"
            ],
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_HELP__": title_tier_labels[
                "also_consider_roles_help"
            ],
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_PLACEHOLDER__": title_tier_labels[
                "also_consider_roles_input_placeholder"
            ],
            "__JOB_HUNTER_TITLE_TIER_ALSO_CONSIDER_ROLES_EMPTY_TEXT__": title_tier_labels[
                "also_consider_roles_empty_text"
            ],
            "__JOB_HUNTER_TITLE_TIER_MOVE_TO_ALSO_CONSIDER_LABEL__": title_tier_labels[
                "move_to_also_consider_label"
            ],
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_LABEL__": title_tier_labels[
                "search_keyword_label"
            ],
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_HELP__": title_tier_labels[
                "search_keyword_help"
            ],
            "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_EXAMPLE__": title_tier_labels[
                "search_keyword_example"
            ],
            "__JOB_HUNTER_MIN_CONTRACT_MONTH_OPTIONS__": srv.render_min_contract_month_options(
                selected_value=None
            ),
            "__JOB_HUNTER_MIN_CONTRACT_MONTH_LABEL__": MIN_CONTRACT_MONTH_LABEL,
            "__JOB_HUNTER_MIN_CONTRACT_MONTH_HELP__": MIN_CONTRACT_MONTH_HELP_TEXT,
        }

        for token, value in onboarding_replacements.items():
            html = html.replace(token, value)

        html = _replace_label_tokens(html, "ONBOARDING_PAGE", onboarding_page_labels)

        html = html.replace("✎ Edit", onboarding_page_labels["edit_label"])

    return (
        html.replace("__JOB_HUNTER_DEBUG_MODE_BOOL__", "true" if srv.DEBUG_MODE else "false")
        .replace("__JOB_HUNTER_ADD_BUTTON_LABEL__", shared_labels["add_button_label"])
        .replace("__JOB_HUNTER_ADD_BUTTON_ARIA_LABEL__", shared_labels["add_button_aria_label"])
        .replace("__JOB_HUNTER_ADD_BUTTON_TITLE__", shared_labels["add_button_title"])
        .replace(
            "__JOB_HUNTER_ENGAGEMENT_TYPE_CHOICES__",
            srv.render_engagement_type_choices(
                name="engagement_type", selected_values=ENGAGEMENT_TYPE_DEFAULT_VALUES
            ),
        )
        .replace("__JOB_HUNTER_ENGAGEMENT_TYPE_HELP__", WORK_TYPE_PREFERENCE_HELP_TEXT)
        .replace(
            "__JOB_HUNTER_WORK_MODE_PREFERENCE_CHOICES__",
            srv.render_work_mode_preference_choices(
                selected_values=WORK_MODE_PREFERENCE_DEFAULT_VALUES
            ),
        )
        .replace("__JOB_HUNTER_WORK_MODE_PREFERENCE_HELP__", WORK_MODE_PREFERENCE_HELP_TEXT)
        .replace(
            "__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__",
            srv.render_sector_preference_select_options(selected_value=GovPref.ANY),
        )
        .replace(
            "__JOB_HUNTER_SECTOR_PREFERENCE_CHOICES__",
            srv.render_sector_preference_choices(selected_values=GovPref.ANY),
        )
        .replace("__JOB_HUNTER_SECTOR_PREFERENCE_HELP__", SECTOR_PREFERENCE_HELP_TEXT)
        .replace("__JOB_HUNTER_MIN_CONTRACT_MONTH_NONE_LABEL__", MIN_CONTRACT_MONTH_NONE_LABEL)
        .replace(
            "__JOB_HUNTER_SEEK_MAX_PAGES_CHOICES__",
            srv.render_seek_max_pages_choices(label_id="seek_max_pages_label"),
        )
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
        .replace("__JOB_HUNTER_PAGE_MODE__", page_mode)
        .replace("__JOB_HUNTER_PAGE_TITLE__", page_title)
        .replace("__JOB_HUNTER_PAGE_HEADING__", page_heading)
        .replace("__JOB_HUNTER_PAGE_COPY__", page_copy)
        .replace("__JOB_HUNTER_BOOTSTRAP_SCRIPTS__", bootstrap_script)
    )


@router.get("/")
@router.get("/workspace")
def page_workspace(request: Request):  # type: ignore[no-untyped-def]

    shared_labels = srv.load_shared_ui_labels()

    if not srv._onboarding_complete():
        return RedirectResponse(ONBOARDING_PATH, status_code=302)

    if WORKSPACE_HTML_PATH.exists():
        html = _render_template_with_locations(
            request,
            WORKSPACE_HTML_PATH,
            account_shortcut_href="/settings",
            account_shortcut_label=shared_labels["account_menu_settings_shortcut_label"],
            account_shortcut_aria_label=shared_labels["account_menu_settings_shortcut_aria_label"],
        )

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
            resume_step=srv._onboarding_resume_step(),
        )

        return html_response(html)

    return html_response("<h1>Template missing</h1><p>Missing templates/onboarding.html</p>")
