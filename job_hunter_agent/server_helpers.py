"""Server-side helper functions for the Job Hunter Agent web application.

This module provides utilities for handling server-specific logic,
including user authentication, settings management, data normalization,
and interaction with core agent functionalities like job scraping and
workspace rebuilding. It centralizes common server-side operations
to ensure consistency and maintainability.
"""

import hashlib
import json
import logging
import re
import shutil
import threading
from datetime import datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any

from job_hunter_agent import profile_store as _profile_store
from job_hunter_agent import workspace_refresh_service as _workspace_refresh_service
from job_hunter_agent.config import (
    ALLOWED_DOC_REL_PATHS,
    DEBUG_MODE,
)
from job_hunter_agent.global_settings import (
    CAPABILITY_STRENGTH_PRESETS,
    KEY_CAPABILITY_ALIAS_LIMIT,
    KEY_DATE_RANGE_DAYS,
    KEY_LIMITS,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_LLM_SETTINGS,
    KEY_LOCATIONS_MAX_SELECTED,
    KEY_MODEL_OPTIONS,
    KEY_SEARCH_SETTINGS,
    KEY_SEEK_MAX_PAGES,
    KEY_SIGNAL_CLUSTER_DENSE_SNIPPET_ALIAS_HITS,
    KEY_SIGNAL_CLUSTER_MIN_ALIAS_HITS,
    KEY_SIGNAL_CLUSTER_MIN_SNIPPET_HITS,
    get_salary_limits,
    load_global_settings,
)
from job_hunter_agent.io_utils import (
    clear_agent_state,
    clear_audit_rows,
    clear_job_history,
    clear_review_data,
    clear_run_stats,
    clear_runtime_caches,
    clear_user_settings,
    clear_workspace_pool,
    load_run_stats,
    load_ui_labels,
    write_run_stats,
)
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.paths import (
    REPO_ROOT as ROOT_DIR,
)
from job_hunter_agent.paths import (
    USERS_DIR,
    get_workspace_results_path,
)
from job_hunter_agent.posting_utils import parse_timestamp
from job_hunter_agent.profile_store import (
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PROFILE,
    ENGAGEMENT_TYPE_DEFAULT_VALUES,
    ENGAGEMENT_TYPE_OPTIONS,
    KEY_CV_MAX_PAGES,
    KEY_ENGAGEMENT_TYPE,
    KEY_KEYWORDS,
    KEY_LOCATIONS,
    KEY_LOOKBACK_YEARS,
    KEY_MAX_SECONDARY,
    KEY_MAX_TARGET,
    KEY_MIN_DAILY_RATE,
    KEY_MIN_MONTHS,
    KEY_MIN_SALARY_YEARLY,
    KEY_ONBOARDING_COMPLETE,
    KEY_ONBOARDING_SETTINGS,
    KEY_STAR_EVIDENCE,
    MATCHING_RULE_PROFILE_KEYS,
    MIN_CONTRACT_MONTH_NONE_LABEL,
    MIN_CONTRACT_MONTH_OPTIONS,
    SECTOR_PREFERENCE_CHOICE_OPTIONS,
    SECTOR_PREFERENCE_OPTIONS,
    VALID_ENGAGEMENT_TYPES,
    WORK_MODE_PREFERENCE_DEFAULT_VALUES,
    WORK_MODE_PREFERENCE_NONE_LABEL,
    WORK_MODE_PREFERENCE_OPTIONS,
    GovPref,
    load_profile,
    normalize_engagement_type_preferences,
    normalize_onboarding_settings,
    normalize_search_settings,
    normalize_work_mode_preferences,
    save_profile,
    validate_search_keywords,
)
from job_hunter_agent.release_metadata import (
    load_app_release_metadata as load_app_release_metadata,
)
from job_hunter_agent.run_control import (
    RunInterruptedError,
    begin_run_progress_scope,
    clear_run_shutdown_request,
    clear_run_stop_request,
    end_run_progress_scope,
    get_run_progress,
    get_run_progress_detail,
    request_run_shutdown,
    run_shutdown_requested,
    run_stop_requested,
)
from job_hunter_agent.source_connector import scrape_jobs_direct
from job_hunter_agent.source_documents import (
    DEFAULT_SOURCE_MATERIALS,
    save_source_materials,
)
from job_hunter_agent.user_context import get_user_id, set_user_id
from job_hunter_agent.user_settings import (
    DEFAULT_USER_SETTINGS,
    KEY_LLM,
    KEY_SCHEDULE,
    KEY_TELEGRAM,
    KEY_WORKSPACE,
    list_user_setting_user_ids,
    load_agent_state,
    load_user_settings,
)
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results

logger = logging.getLogger(__name__)

RUN_STATUS_IDLE = "idle"
RUN_STATUS_RUNNING = "running"
RUN_STATUS_STOPPING = "stopping"
RUN_STATUS_STOPPED = "stopped"
RUN_STATUS_INTERRUPTED = "interrupted"
RUN_INTERRUPTED_MESSAGE = (
    "[RUN_INTERRUPTED] Server shutdown requested while job search is still running. "
    "The current run did not complete and its results were not finalized."
)
_RUN_TERMINAL_STATUSES = frozenset(
    {RUN_STATUS_IDLE, RUN_STATUS_STOPPED, RUN_STATUS_INTERRUPTED}
)

_run_in_progress = False
_run_started_at: datetime | None = None
_run_last_elapsed_seconds: int | None = None
_run_terminal_status = RUN_STATUS_IDLE
_run_active_id: str | None = None
_run_active_user_id: str | None = None
_shutdown_interruption_recorded = False
_run_state_lock = threading.Lock()
_rejection_suggestions_cache: dict[str, dict[str, Any]] = {}
profile_review_status = _profile_store.profile_review_status
patch_profile = _profile_store.patch_profile
require_profile_ready_for_review = _profile_store.require_profile_ready_for_review
rebuild_workspace_after_rule_change = (
    _workspace_refresh_service.rebuild_workspace_after_rule_change
)
_ONBOARDING_TITLE_TIER_LABEL_KEYS = (
    "target_roles_label",
    "target_roles_help",
    "target_roles_input_placeholder",
    "target_roles_empty_text",
    "move_to_target_roles_label",
    "keep_target_roles_continue_error",
    "keep_target_roles_finish_error",
    "also_consider_roles_label",
    "also_consider_roles_help",
    "also_consider_roles_input_placeholder",
    "also_consider_roles_empty_text",
    "move_to_also_consider_label",
    "search_keyword_label",
    "search_keyword_help",
    "search_keyword_example",
    "explore_adjacent_roles_label",
    "explore_adjacent_roles_help",
)
_ONBOARDING_IMPORT_SUMMARY_LABEL_KEYS = (
    "lead_in",
    "target_roles_singular",
    "target_roles_plural",
    "secondary_roles_singular",
    "secondary_roles_plural",
    "capabilities_singular",
    "capabilities_plural",
    "llm_cost_label",
    "source_suffix",
)
_CAPABILITY_UI_LABEL_KEYS = (
    "settings_title",
    "matching_nav_label",
    "onboarding_title",
    "help_text",
    "add_button_aria_label",
    "related_skills_label",
    "related_skills_summary",
    "settings_edit_multiple_label",
    "settings_done_editing_label",
    "settings_select_label",
    "settings_selected_label",
    "settings_select_shown_label",
    "settings_clear_selection_label",
    "settings_remove_selected_label",
    "settings_selected_copy",
    "filter_placeholder",
    "remove_related_skill_aria_label",
    "settings_empty_text",
    "settings_no_match_text",
    "onboarding_empty_text",
    "onboarding_no_match_text",
    "review_strength_prompt_label",
)
_SHARED_UI_LABEL_KEYS = (
    "select_theme_aria_label",
    "account_menu_aria_label",
    "account_menu_title",
    "account_menu_logout_label",
    "app_stage_label",
    "app_stage_title",
    "account_menu_settings_shortcut_label",
    "account_menu_settings_shortcut_aria_label",
    "account_menu_workspace_shortcut_label",
    "account_menu_workspace_shortcut_aria_label",
    "account_menu_test_label",
    "account_menu_test_actions_label",
    "account_menu_clean_search_label",
    "account_menu_reset_user_label",
    "account_menu_reset_user_warning_label",
    "add_button_label",
    "add_button_aria_label",
    "add_button_title",
    "location_help",
    "schedule_section_title",
    "schedule_section_copy",
    "search_wait_copy",
    "search_wait_why_label",
    "search_wait_why_copy",
    "search_running_title",
    "search_running_copy",
    "search_starting_title",
    "search_starting_copy",
    "search_refreshing_title",
    "search_refreshing_copy",
    "search_running_subcopy",
    "search_starting_subcopy",
    "search_stop_label",
    "search_elapsed_suffix",
    "search_progress_aria_suffix",
    "search_stopping_title",
    "search_stopping_copy",
    "search_stopping_subcopy",
    "settings_section_search_label",
    "settings_section_search_placeholder",
    "settings_privacy_title",
    "settings_privacy_copy",
    "settings_privacy_link_label",
    "settings_search_save_button_label",
    "settings_saved_success",
    "global_settings_saved_success",
    "settings_saved_no_effective_changes",
    "settings_saved_changes_heading",
    "settings_value_blank",
    "settings_value_not_set",
    "settings_value_none",
    "settings_value_on",
    "settings_value_off",
    "select_shown_label",
    "clear_selection_label",
    "remove_selected_label",
)
_SEARCH_SOURCE_LABEL_KEYS = (
    "section_title",
    "section_copy",
    "shared_inputs_copy",
    "seek_toggle_label",
    "seek_toggle_help",
    "linkedin_toggle_label",
    "linkedin_toggle_help",
    "apsjobs_toggle_label",
    "apsjobs_toggle_help",
    "seek_display_label",
    "seek_badge_label",
    "linkedin_display_label",
    "linkedin_badge_label",
    "apsjobs_display_label",
    "apsjobs_badge_label",
    "generic_display_label",
)

_SETTINGS_ALERTS_LABEL_KEYS = (
    "section_title",
    "section_copy",
    "telegram_heading",
    "telegram_copy",
    "telegram_enabled_label",
    "telegram_enabled_help",
    "telegram_bot_token_label",
    "telegram_bot_token_help",
    "telegram_bot_username_label",
    "telegram_bot_username_help",
    "telegram_disable_link_preview_label",
    "telegram_disable_link_preview_help",
    "telegram_connect_heading",
    "telegram_connect_help",
    "telegram_connect_help_missing",
    "telegram_connect_help_ready",
    "telegram_connect_link_label",
    "telegram_connect_open_label",
    "telegram_connect_refresh_label",
    "telegram_connection_status_label",
    "telegram_connection_status_empty",
    "telegram_test_label",
    "telegram_subscribers_empty",
    "telegram_subscribers_label",
    "telegram_user_label",
    "llm_heading",
    "llm_copy",
    "llm_model_label",
    "llm_model_placeholder",
)

_SETTINGS_CLEARANCES_LABEL_KEYS = (
    "settings_title",
    "help_text",
    "add_button_aria_label",
    "settings_empty_text",
    "name_placeholder",
    "have_label",
    "held_state_label",
    "not_held_state_label",
    "unset_state_label",
    "implied_state_label",
    "clear_button_label",
    "clear_button_aria_label",
    "remove_button_aria_label",
    "eligibility_add_error_message",
    "eligibility_add_loading_message",
    "eligibility_settings_title",
    "eligibility_help_text",
    "eligibility_name_label",
    "eligibility_name_placeholder",
    "eligibility_add_button_label",
    "eligibility_add_button_aria_label",
    "eligibility_empty_text",
    "eligibility_prefill_added_message",
    "eligibility_prefill_exists_message",
    "eligibility_remove_button_label",
    "qualification_add_error_message",
    "qualification_settings_title",
    "qualification_help_text",
    "qualification_name_label",
    "qualification_name_placeholder",
    "qualification_add_button_label",
    "qualification_empty_text",
    "qualification_prefill_added_message",
    "qualification_prefill_exists_message",
    "qualification_remove_button_label",
)

_ROLE_HISTORY_LABEL_KEYS = (
    "settings_title",
    "help_text",
    "refresh_button_label",
    "refresh_button_busy_label",
    "empty_text",
)

_ONBOARDING_PAGE_LABEL_KEYS = (
    "page_title",
    "hero_title",
    "progress_step_1_label",
    "progress_step_2_label",
    "progress_step_3_label",
    "progress_step_4_label",
    "workflow_title",
    "workflow_step_1",
    "workflow_step_2",
    "workflow_step_3",
    "cv_drop_zone_empty_title",
    "cv_drop_zone_empty_hint",
    "cv_drop_zone_loaded_hint",
    "cv_upload_help",
    "privacy_title",
    "privacy_intro",
    "privacy_upload_only",
    "privacy_sensitive_intro",
    "privacy_sensitive_item_passport",
    "privacy_sensitive_item_licence",
    "privacy_sensitive_item_address",
    "privacy_sensitive_item_birth_date",
    "privacy_sensitive_item_identity",
    "privacy_footer",
    "guidance_title",
    "guidance_include_title",
    "guidance_include_recent_roles",
    "guidance_include_titles",
    "guidance_include_employers",
    "guidance_include_bullets",
    "guidance_include_skills",
    "guidance_avoid_title",
    "guidance_avoid_marketing_cvs",
    "guidance_avoid_image_layouts",
    "guidance_avoid_missing_dates",
    "guidance_avoid_mixed_directions",
    "guidance_note",
    "experience_priority_label",
    "experience_priority_help",
    "experience_priority_option_recent",
    "experience_priority_option_balanced",
    "experience_priority_option_full",
    "build_draft_profile_label",
    "continue_label",
    "need_help_label",
    "location_label",
    "sector_preference_label",
    "sector_preference_help",
    "work_type_label",
    "work_type_help",
    "work_type_summary_all_label",
    "work_type_summary_contract_length_label",
    "sector_preference_summary_all_label",
    "work_mode_label",
    "work_mode_help",
    "work_mode_summary_all_label",
    "summary_any_length_label",
    "minimum_compensation_label",
    "minimum_compensation_help",
    "back_label",
    "save_and_continue_label",
    "draft_profile_ready_label",
    "extraction_review_caution",
    "review_setup_title",
    "review_setup_copy",
    "draft_profile_label",
    "edit_label",
    "search_basics_label",
    "locations_label",
    "finish_setup_label",
    "review_capability_count_initial_label",
)

_ONBOARDING_FLOW_LABEL_KEYS = (
    "clean_search_confirm_title",
    "clean_search_confirm_body_1",
    "clean_search_confirm_body_2",
    "clean_search_error",
    "refresh_profile_confirm_title",
    "refresh_profile_confirm_body_1",
    "refresh_profile_confirm_body_2",
    "create_profile_error",
    "create_profile_ready_message",
    "create_profile_status_started",
    "create_profile_status_reading_pages",
    "create_profile_status_extracting",
    "create_profile_status_reviewing",
    "create_profile_status_building",
    "review_capability_helper_copy",
    "continue_search_basics_error",
    "finish_setup_error",
    "reset_user_confirm_title",
    "reset_user_confirm_body_1",
    "reset_user_confirm_body_2",
    "reset_user_error",
    "profile_status_error",
    "load_profile_error",
    "create_profile_button_building",
    "create_profile_button_refreshing",
    "finish_review_button_saving",
    "finish_review_button_finishing",
    "finish_review_status_saving",
    "finish_review_status_applying",
    "finish_review_status_finalising",
    "not_provided_label",
    "capabilities_none_label",
    "capability_rows_label_one",
    "capability_rows_label_many",
    "capability_actions_for_label",
    "capability_remove_label",
    "capability_remove_title",
    "capability_untitled_label",
    "capability_show_more_label",
    "capability_show_fewer_label",
    "capability_shown_of_label",
    "capability_count_with_selection_label",
    "capability_count_label",
    "capability_select_shown_label",
    "capability_clear_selection_label",
    "capability_remove_selected_label",
    "capability_selected_copy",
    "reading_updated_cv_label",
    "reading_cv_label",
)

_SYSTEM_HEALTH_LABEL_KEYS = (
    "system_health_heading",
    "system_health_copy",
    "system_health_refresh_label",
    "system_health_diagnostics_show_label",
    "system_health_diagnostics_hide_label",
    "system_health_checking_status",
    "system_health_empty",
    "system_health_diagnostics_heading",
    "system_health_diagnostics_copy",
    "system_health_diagnostics_empty",
    "system_health_acknowledge_label",
    "system_health_acknowledging_label",
    "system_health_acknowledged_status",
    "system_health_scraper_validation_action_label",
    "system_health_scraper_validation_running_label",
    "system_health_scraper_validation_running_status",
    "system_health_scraper_validation_completed_status",
    "system_health_scraper_validation_error",
    "system_health_developer_investigation_help",
    "system_health_scraper_investigation_help",
    "system_health_technical_context_label",
    "system_health_sample_label",
    "system_health_records_label",
    "system_health_occurrences_label",
    "system_health_last_seen_label",
    "system_health_job_label",
    "system_health_run_label",
    "system_health_active_count_template",
    "system_health_diagnostic_count_template",
    "system_health_load_error",
    "system_health_action_error",
)

_GLOBAL_SETTINGS_LABEL_KEYS = (
    "card_highlight_heading",
    "card_highlight_copy",
    "strong_capability_matches_label",
    "strong_capability_matches_help",
    "working_capability_matches_label",
    "working_capability_matches_help",
    "basic_capability_matches_label",
    "basic_capability_matches_help",
    "reviewed_capability_matches_label",
    "reviewed_capability_matches_help",
    "max_highlights_label",
    "max_highlights_help",
    "search_defaults_heading",
    "search_defaults_copy",
    "default_search_window_label",
    "default_search_window_help",
    "default_seek_pages_label",
    "default_seek_pages_help",
    "default_linkedin_age_window_label",
    "default_linkedin_age_window_help",
    "default_linkedin_results_per_search_label",
    "default_linkedin_results_per_search_help",
    "sort_newest_first_label",
    "sort_newest_first_help",
    "linkedin_easy_apply_label",
    "linkedin_easy_apply_help",
    "runtime_defaults_heading",
    "runtime_defaults_copy",
    "default_country_suffix_label",
    "default_country_suffix_help",
    "playwright_viewport_width_label",
    "playwright_viewport_width_help",
    "playwright_viewport_height_label",
    "playwright_viewport_height_help",
    "playwright_selector_timeout_label",
    "playwright_selector_timeout_help",
    "session_max_age_days_label",
    "session_max_age_days_help",
    "search_limits_heading",
    "search_limits_copy",
    "search_window_min_label",
    "search_window_max_label",
    "search_window_help",
    "seek_pages_min_label",
    "seek_pages_max_label",
    "seek_pages_help",
    "linkedin_age_window_min_label",
    "linkedin_age_window_max_label",
    "linkedin_age_window_help",
    "linkedin_results_min_label",
    "linkedin_results_max_label",
    "linkedin_results_help",
    "salary_limits_heading",
    "salary_limits_copy",
    "max_permanent_salary_label",
    "max_permanent_salary_help",
    "max_contract_daily_rate_label",
    "max_contract_daily_rate_help",
    "evidence_tier_weights_heading",
    "evidence_tier_weights_copy",
    "primary_profile_context_weight_label",
    "secondary_profile_context_weight_label",
    "supplementary_profile_context_weight_label",
    "preference_weights_heading",
    "preference_weights_copy",
    "fit_weight_label",
    "salary_weight_label",
    "location_weight_label",
    "freshness_weight_label",
    "history_retention_heading",
    "history_retention_copy",
    "archive_stale_after_days_label",
    "archive_stale_after_days_help",
    "hidden_review_days_label",
    "hidden_review_days_help",
    "repeated_listing_min_times_seen_label",
    "repeated_listing_min_times_seen_help",
    "repeated_listing_min_span_days_label",
    "repeated_listing_min_span_days_help",
    "multi_listing_red_flag_min_listings_label",
    "multi_listing_red_flag_min_listings_help",
    "multi_listing_red_flag_min_span_days_label",
    "multi_listing_red_flag_min_span_days_help",
    "description_trust_heading",
    "description_trust_copy",
    "minimum_trusted_description_length_label",
    "minimum_trusted_description_length_help",
    "cv_files_heading",
    "cv_files_copy",
    "allowed_cv_file_suffixes_label",
    "allowed_cv_file_suffixes_help",
    "onboarding_defaults_heading",
    "onboarding_defaults_copy",
    "onboarding_learning_help",
    "extraction_lookback_years_label",
    "extraction_lookback_years_help",
    "title_extraction_min_months_label",
    "title_extraction_min_months_help",
    "max_target_patterns_label",
    "max_target_patterns_help",
    "max_secondary_patterns_label",
    "max_secondary_patterns_help",
    "cv_page_limit_label",
    "cv_page_limit_help",
    "capability_alias_limit_label",
    "capability_alias_limit_help",
    "signal_cluster_min_alias_hits_label",
    "signal_cluster_min_alias_hits_help",
    "signal_cluster_min_snippet_hits_label",
    "signal_cluster_min_snippet_hits_help",
    "signal_cluster_dense_snippet_alias_hits_label",
    "signal_cluster_dense_snippet_alias_hits_help",
    "capability_preset_label",
    "llm_models_heading",
    "llm_models_copy",
    "allowed_models_label",
    "allowed_models_help",
    "maximum_llm_chars_label",
    "maximum_llm_chars_help",
    "model_pricing_label",
    "model_pricing_help",
    "prompt_settings_label",
    "prompt_settings_help",
    "capability_presets_heading",
    "capability_presets_copy",
    "capability_presets_empty_help",
    *_SYSTEM_HEALTH_LABEL_KEYS,
)

_SIGNAL_REGISTRY_LABEL_KEYS = (
    "category_capability_label",
    "category_capability_description",
    "category_capability_examples",
    "category_capability_warning",
    "category_cv_farming_label",
    "category_cv_farming_description",
    "category_cv_farming_examples",
    "category_cv_farming_warning",
    "category_hard_blocker_label",
    "category_hard_blocker_description",
    "category_hard_blocker_examples",
    "category_hard_blocker_warning",
    "category_job_type_label",
    "category_job_type_description",
    "category_job_type_examples",
    "category_job_type_warning",
    "category_profile_section_label",
    "category_profile_section_description",
    "category_profile_section_examples",
    "category_profile_section_warning",
    "category_requirement_review_label",
    "category_requirement_review_description",
    "category_requirement_review_examples",
    "category_requirement_review_warning",
    "requirement_type_field_label",
    "requirement_type_capability_label",
    "requirement_type_eligibility_label",
    "requirement_type_qualification_label",
)

_SIGNAL_REGISTRY_EXAMPLE_KEYS = tuple(
    key for key in _SIGNAL_REGISTRY_LABEL_KEYS if key.endswith("_examples")
)
_SIGNAL_REGISTRY_WARNING_KEYS = tuple(
    key for key in _SIGNAL_REGISTRY_LABEL_KEYS if key.endswith("_warning")
)


def _load_required_ui_labels(group_name: str, keys: tuple[str, ...]) -> dict[str, str]:
    labels = load_ui_labels().get(group_name, {})
    if not isinstance(labels, dict):
        raise ValueError(f"ui_labels.json is missing {group_name}")
    missing = [key for key in keys if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(f"ui_labels.json is missing {group_name} values: {', '.join(missing)}")
    return {key: str(labels[key]).strip() for key in keys}


def load_signal_registry_labels() -> dict[str, Any]:
    """Return the validated managed display contract for the Signals inbox."""
    labels = load_ui_labels().get("signal_registry_labels", {})
    if not isinstance(labels, dict):
        raise ValueError("ui_labels.json is missing signal_registry_labels")

    missing = [
        key
        for key in _SIGNAL_REGISTRY_LABEL_KEYS
        if key not in labels
        or (
            key not in _SIGNAL_REGISTRY_WARNING_KEYS
            and not str(labels.get(key, "")).strip()
        )
    ]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing signal_registry_labels values: {', '.join(missing)}"
        )

    for key in _SIGNAL_REGISTRY_EXAMPLE_KEYS:
        examples = labels[key]
        if not isinstance(examples, list) or not examples or any(
            not isinstance(example, str) or not example.strip() for example in examples
        ):
            raise ValueError(
                f"ui_labels.json signal_registry_labels.{key} must be a non-empty list of strings"
            )

    for key in _SIGNAL_REGISTRY_WARNING_KEYS:
        warning = labels[key]
        if warning is not None and (not isinstance(warning, str) or not warning.strip()):
            raise ValueError(
                f"ui_labels.json signal_registry_labels.{key} must be null or a non-empty string"
            )

    return {key: labels[key] for key in _SIGNAL_REGISTRY_LABEL_KEYS}


def load_onboarding_title_tier_labels() -> dict[str, str]:
    labels = load_ui_labels().get("title_tier_labels", {})
    if not isinstance(labels, dict):
        raise ValueError("ui_labels.json is missing title_tier_labels")
    missing = [
        key for key in _ONBOARDING_TITLE_TIER_LABEL_KEYS if not str(labels.get(key, "")).strip()
    ]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing title_tier_labels values: {', '.join(missing)}"
        )
    return {key: str(labels[key]).strip() for key in _ONBOARDING_TITLE_TIER_LABEL_KEYS}


def load_onboarding_import_summary_labels() -> dict:
    labels = load_ui_labels().get("onboarding_import_summary_labels", {})
    if not isinstance(labels, dict):
        raise ValueError("ui_labels.json is missing onboarding_import_summary_labels")
    missing = [
        key for key in _ONBOARDING_IMPORT_SUMMARY_LABEL_KEYS if not str(labels.get(key, "")).strip()
    ]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing onboarding_import_summary_labels values: {', '.join(missing)}"
        )
    result: dict = {key: str(labels[key]).strip() for key in _ONBOARDING_IMPORT_SUMMARY_LABEL_KEYS}
    raw = labels.get("capability_preview_rows")
    if not isinstance(raw, int) or raw < 1:
        raise ValueError(
            "ui_labels.json onboarding_import_summary_labels.capability_preview_rows must be a positive integer"
        )
    result["capability_preview_rows"] = raw
    return result


def load_capability_ui_labels() -> dict[str, str]:
    payload = load_ui_labels()
    raw_labels = payload.get("capability_ui_labels", {})
    if not isinstance(raw_labels, dict):
        raise ValueError("ui_labels.json is missing capability_ui_labels")
    shared_labels = payload.get("shared_ui_labels", {})
    if not isinstance(shared_labels, dict):
        raise ValueError("ui_labels.json is missing shared_ui_labels")
    # shared_ui_labels is the canonical source for these bulk-selection action
    # labels so the settings and onboarding capability editors show the same text.
    labels = {
        **raw_labels,
        "settings_select_shown_label": shared_labels.get("select_shown_label", ""),
        "settings_clear_selection_label": shared_labels.get("clear_selection_label", ""),
        "settings_remove_selected_label": shared_labels.get("remove_selected_label", ""),
    }
    missing = [key for key in _CAPABILITY_UI_LABEL_KEYS if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing capability_ui_labels values: {', '.join(missing)}"
        )
    return {key: str(labels[key]).strip() for key in _CAPABILITY_UI_LABEL_KEYS}


def load_shared_ui_labels() -> dict[str, str]:
    labels = load_ui_labels().get("shared_ui_labels", {})
    if not isinstance(labels, dict):
        raise ValueError("ui_labels.json is missing shared_ui_labels")
    missing = [key for key in _SHARED_UI_LABEL_KEYS if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(f"ui_labels.json is missing shared_ui_labels values: {', '.join(missing)}")
    return {key: str(labels[key]).strip() for key in _SHARED_UI_LABEL_KEYS}



def load_search_source_labels() -> dict[str, str]:
    labels = load_ui_labels().get("search_source_labels", {})
    if not isinstance(labels, dict):
        raise ValueError("ui_labels.json is missing search_source_labels")
    missing = [key for key in _SEARCH_SOURCE_LABEL_KEYS if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing search_source_labels values: {', '.join(missing)}"
        )
    return {key: str(labels[key]).strip() for key in _SEARCH_SOURCE_LABEL_KEYS}


def clear_current_user_search_state(*, preserve_profile: bool = True) -> dict[str, Any]:
    """Clear only the current user's search/result state."""
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    clear_job_history()
    clear_workspace_pool()
    clear_review_data()
    clear_run_stats()
    clear_audit_rows()
    clear_agent_state()
    cache_result = clear_runtime_caches()

    if preserve_profile:
        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})
        review_controls["applied_job_keys"] = []
        review_controls["hidden_job_keys"] = []
        save_profile(profile)

    user_id = get_active_user_id()
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM candidate_application_history WHERE user_id = ?",
            (user_id,),
        )

    output_path = get_workspace_results_path()
    try:
        output_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("Failed to remove workspace results %s: %s", output_path, exc)

    return {
        "ok": True,
        "message": "Search results, applied jobs, hidden jobs, and transient caches were cleared. Profile and settings were preserved.",
        "cleared_runtime_files": list(cache_result.get("cleared_files") or []),
        "redirect_to": "/workspace",
    }


def load_settings_alerts_labels() -> dict[str, str]:
    raw_labels = load_ui_labels().get("settings_alerts_labels", {})
    if not isinstance(raw_labels, dict):
        raise ValueError("ui_labels.json is missing settings_alerts_labels")
    labels = {
        **raw_labels,
        "telegram_subscribers_empty": raw_labels.get("telegram_connection_status_empty", ""),
    }
    missing = [key for key in _SETTINGS_ALERTS_LABEL_KEYS if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing settings_alerts_labels values: {', '.join(missing)}"
        )
    return {key: str(labels[key]).strip() for key in _SETTINGS_ALERTS_LABEL_KEYS}


def load_settings_clearances_labels() -> dict[str, str]:
    return _load_required_ui_labels("settings_clearances_labels", _SETTINGS_CLEARANCES_LABEL_KEYS)


def load_clearance_ui_options() -> list[dict[str, Any]]:
    return _profile_store.load_clearance_ui_options()


def load_role_history_labels() -> dict[str, str]:
    return _load_required_ui_labels("role_history_labels", _ROLE_HISTORY_LABEL_KEYS)


def load_onboarding_page_labels() -> dict[str, str]:
    payload = load_ui_labels()
    raw_labels = payload.get("onboarding_page_labels", {})
    if not isinstance(raw_labels, dict):
        raise ValueError("ui_labels.json is missing onboarding_page_labels")
    workspace_page_labels = payload.get("workspace_page_labels", {})
    if not isinstance(workspace_page_labels, dict):
        raise ValueError("ui_labels.json is missing workspace_page_labels")
    # workspace_page_labels is the canonical source for these field labels so the
    # onboarding profile builder and the workspace search sidebar show the same text.
    labels = {
        **raw_labels,
        "locations_label": workspace_page_labels.get("locations_label", ""),
        "work_type_label": workspace_page_labels.get("work_type_sidebar_label", ""),
        "work_mode_label": workspace_page_labels.get("work_mode_sidebar_label", ""),
    }
    missing = [key for key in _ONBOARDING_PAGE_LABEL_KEYS if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing onboarding_page_labels values: {', '.join(missing)}"
        )
    return {key: str(labels[key]).strip() for key in _ONBOARDING_PAGE_LABEL_KEYS}


def load_onboarding_flow_labels() -> dict[str, str]:
    payload = load_ui_labels()
    raw_labels = payload.get("onboarding_flow_labels", {})
    if not isinstance(raw_labels, dict):
        raise ValueError("ui_labels.json is missing onboarding_flow_labels")
    shared_labels = payload.get("shared_ui_labels", {})
    if not isinstance(shared_labels, dict):
        raise ValueError("ui_labels.json is missing shared_ui_labels")
    # shared_ui_labels is the canonical source for these bulk-selection action
    # labels so the settings and onboarding capability editors show the same text.
    labels = {
        **raw_labels,
        "capability_select_shown_label": shared_labels.get("select_shown_label", ""),
        "capability_clear_selection_label": shared_labels.get("clear_selection_label", ""),
        "capability_remove_selected_label": shared_labels.get("remove_selected_label", ""),
    }
    missing = [key for key in _ONBOARDING_FLOW_LABEL_KEYS if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing onboarding_flow_labels values: {', '.join(missing)}"
        )
    return {key: str(labels[key]).strip() for key in _ONBOARDING_FLOW_LABEL_KEYS}


def load_global_settings_labels() -> dict[str, str]:
    return _load_required_ui_labels("global_settings_labels", _GLOBAL_SETTINGS_LABEL_KEYS)


def load_system_health_labels() -> dict[str, str]:
    """Return the managed copy used by the admin System health panel."""

    return _load_required_ui_labels("global_settings_labels", _SYSTEM_HEALTH_LABEL_KEYS)


def get_docs() -> list[dict[str, str]]:
    """Return allowed markdown docs under the repo root (for /docs API)."""
    docs: list[dict[str, str]] = []
    root = ROOT_DIR.resolve()
    for rel_path in ALLOWED_DOC_REL_PATHS:
        file_path = (root / rel_path).resolve()
        if root not in file_path.parents and file_path != root:
            continue
        if file_path.is_file():
            docs.append({"name": rel_path, "content": file_path.read_text(encoding="utf-8")})
    return docs


def _set_run_in_progress(value: bool) -> None:
    """Compatibility mutator for callers that only own the running flag."""
    global _run_in_progress, _run_started_at
    with _run_state_lock:
        _run_in_progress = bool(value)
        if not _run_in_progress:
            _run_started_at = None


def _finish_run(terminal_status: str) -> None:
    """Atomically close the active run and retain its final elapsed total."""
    global _run_in_progress, _run_started_at, _run_last_elapsed_seconds, _run_terminal_status
    if terminal_status not in _RUN_TERMINAL_STATUSES:
        raise ValueError(f"Invalid terminal run status: {terminal_status!r}")
    finished_at = datetime.now().astimezone()
    with _run_state_lock:
        if (
            _run_terminal_status == RUN_STATUS_INTERRUPTED
            and terminal_status != RUN_STATUS_INTERRUPTED
        ):
            terminal_status = RUN_STATUS_INTERRUPTED
        if _run_started_at is not None:
            _run_last_elapsed_seconds = max(
                0,
                int((finished_at - _run_started_at).total_seconds()),
            )
        _run_in_progress = False
        _run_started_at = None
        _run_terminal_status = terminal_status
    _write_run_stats_field("run_status", terminal_status)


def _is_run_in_progress() -> bool:
    with _run_state_lock:
        return _run_in_progress


def _current_run_status() -> str:
    """Return running, stopping, stopped, or idle from the owned lifecycle state."""
    with _run_state_lock:
        running = _run_in_progress
        terminal_status = _run_terminal_status
    if running:
        return RUN_STATUS_STOPPING if run_stop_requested() else RUN_STATUS_RUNNING
    return terminal_status


def _try_mark_run_started() -> bool:
    global _run_in_progress, _run_started_at, _run_terminal_status
    global _run_active_id, _run_active_user_id, _shutdown_interruption_recorded
    started_at = datetime.now().astimezone()
    with _run_state_lock:
        if _run_in_progress:
            return False
        _run_in_progress = True
        _run_started_at = started_at
        _run_terminal_status = RUN_STATUS_IDLE
        _run_active_id = started_at.isoformat(timespec="seconds")
        _run_active_user_id = get_user_id()
        _shutdown_interruption_recorded = False
    clear_run_shutdown_request()
    _write_run_stats_field("run_status", RUN_STATUS_RUNNING)
    _write_run_stats_field("run_interrupted_at", None)
    _write_run_stats_field("run_interruption_signal", None)
    _write_run_stats_field("run_interruption_source", None)
    _write_run_stats_field("run_interruption_progress", None)
    _write_run_stats_field("run_interruption_reason", None)
    return True


def _signal_name(signal_number: int | None) -> str:
    if signal_number is None:
        return "unknown"
    try:
        import signal

        return signal.Signals(signal_number).name
    except (ValueError, TypeError):
        return f"unknown({signal_number})"


def _handle_server_shutdown(signal_number: int | None = None) -> bool:
    """Record an active scrape interruption and request cooperative shutdown."""
    global _run_in_progress, _run_started_at, _run_last_elapsed_seconds, _run_terminal_status
    global _shutdown_interruption_recorded

    shutdown_at = datetime.now().astimezone()
    signal_label = _signal_name(signal_number)
    with _run_state_lock:
        if not _run_in_progress or _shutdown_interruption_recorded:
            return False
        _shutdown_interruption_recorded = True
        run_id = _run_active_id or "unknown"
        active_user_id = _run_active_user_id
        started_at = _run_started_at
        if started_at is not None:
            _run_last_elapsed_seconds = max(
                0,
                int((shutdown_at - started_at).total_seconds()),
            )
        _run_in_progress = False
        _run_started_at = None
        _run_terminal_status = RUN_STATUS_INTERRUPTED

    request_run_shutdown()

    progress = get_run_progress() or "(not available)"
    progress_detail = get_run_progress_detail() or {}
    source = str(progress_detail.get("source") or "(not available)")
    warning = RUN_INTERRUPTED_MESSAGE
    logger.warning(
        "%s run_id=%s source=%s progress=%s shutdown_at=%s signal=%s",
        warning,
        run_id,
        source,
        progress,
        shutdown_at.isoformat(timespec="seconds"),
        signal_label,
    )

    if active_user_id:
        set_user_id(active_user_id)
    _write_run_stats_field("run_status", RUN_STATUS_INTERRUPTED)
    _write_run_stats_field("last_run_error", warning)
    _write_run_stats_field("run_interrupted_at", shutdown_at.isoformat(timespec="seconds"))
    _write_run_stats_field("run_interruption_signal", signal_label)
    _write_run_stats_field("run_interruption_source", source)
    _write_run_stats_field("run_interruption_progress", progress)
    _write_run_stats_field(
        "run_interruption_reason",
        "Server shutdown requested before the scrape completed.",
    )
    return True


def _current_run_elapsed_seconds() -> int | None:
    """Return live elapsed seconds, or the final total after the run ends."""
    with _run_state_lock:
        if _run_in_progress and _run_started_at is not None:
            started_at = _run_started_at
        else:
            return _run_last_elapsed_seconds
    return max(0, int((datetime.now().astimezone() - started_at).total_seconds()))


def _format_current_run_elapsed() -> str:
    elapsed_seconds = _current_run_elapsed_seconds()
    if elapsed_seconds is None:
        return ""
    minutes, seconds = divmod(elapsed_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _normalize_suggestion_phrase(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _parse_non_negative_salary_value(value: Any, *, label: str) -> int:
    try:
        parsed = int(str(value).replace(",", "").strip() or 0)
    except Exception as exc:
        raise ValueError(f"{label} must be a whole number.") from exc
    if parsed < 0:
        raise ValueError(f"{label} cannot be negative.")
    return parsed


def _enforce_salary_caps(value: int, *, label: str, limit_key: str) -> int:
    salary_limits = get_salary_limits()
    limit = salary_limits.get(limit_key, {}) if isinstance(salary_limits, dict) else {}
    try:
        maximum = int(limit.get("max", value))
    except Exception:
        maximum = value
    if value > maximum:
        raise ValueError(f"{label} cannot exceed {maximum:,}.")
    return value


def _render_template(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _account_scope_token(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]


def build_bootstrap_script(
    *,
    csrf_token: str | None = None,
    location_options: list[dict[str, Any]] | None = None,
    default_location: str | None = None,
    onboarding_defaults: dict[str, Any] | None = None,
    onboarding_copy: dict[str, Any] | None = None,
    global_settings: dict[str, Any] | None = None,
    resume_step: int | None = None,
    account_scope: str | None = None,
) -> str:
    parts = [
        f"<script>window.__JOB_HUNTER_DEBUG_MODE__ = {'true' if DEBUG_MODE else 'false'};</script>"
    ]
    if account_scope is not None:
        parts.append(
            f"<script>window.__JOB_HUNTER_USER_SCOPE__ = {json.dumps(_account_scope_token(account_scope), ensure_ascii=True)};</script>"
        )
    if onboarding_defaults is not None:
        parts.append(
            f"<script>window.__JOB_HUNTER_ONBOARDING_DEFAULTS__ = {json.dumps(onboarding_defaults, ensure_ascii=True)};</script>"
        )
    if onboarding_copy is not None:
        parts.append(
            f"<script>window.__JOB_HUNTER_ONBOARDING_COPY__ = {json.dumps(onboarding_copy, ensure_ascii=True)};</script>"
        )
    parts.append(
        f"<script>window.__JOB_HUNTER_ONBOARDING_FLOW_LABELS__ = {json.dumps(load_onboarding_flow_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_ONBOARDING_PAGE_LABELS__ = {json.dumps(load_onboarding_page_labels(), ensure_ascii=True)};</script>"
    )
    if resume_step is not None:
        parts.append(
            f"<script>window.__JOB_HUNTER_ONBOARDING_RESUME_STEP__ = {json.dumps(resume_step, ensure_ascii=True)};</script>"
        )
    if csrf_token is not None:
        parts.append(
            f"<script>window.__JOB_HUNTER_CSRF_TOKEN__ = {json.dumps(csrf_token, ensure_ascii=True)};</script>"
        )
    if location_options is not None:
        parts.append(
            f"<script>window.__JOB_HUNTER_LOCATION_OPTIONS__ = {json.dumps(location_options, ensure_ascii=True)};</script>"
        )
    if default_location is not None:
        parts.append(
            f"<script>window.__JOB_HUNTER_DEFAULT_LOCATION__ = {json.dumps(default_location, ensure_ascii=True)};</script>"
        )
    if global_settings is not None:
        parts.append(
            f"<script>window.__JOB_HUNTER_GLOBAL_SETTINGS__ = {json.dumps(global_settings, ensure_ascii=True)};</script>"
        )
    parts.append(
        f"<script>window.__JOB_HUNTER_TITLE_TIER_LABELS__ = {json.dumps(load_onboarding_title_tier_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_CAPABILITY_UI_LABELS__ = {json.dumps(load_capability_ui_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_SHARED_UI_LABELS__ = {json.dumps(load_shared_ui_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_SEARCH_SOURCE_LABELS__ = {json.dumps(load_search_source_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_SETTINGS_ALERTS_LABELS__ = {json.dumps(load_settings_alerts_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_SYSTEM_HEALTH_LABELS__ = {json.dumps(load_system_health_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_SETTINGS_CLEARANCES_LABELS__ = {json.dumps(load_settings_clearances_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_CLEARANCE_OPTIONS__ = {json.dumps(load_clearance_ui_options(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_ROLE_HISTORY_LABELS__ = {json.dumps(load_role_history_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_ONBOARDING_IMPORT_SUMMARY_LABELS__ = {json.dumps(load_onboarding_import_summary_labels(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_SALARY_LIMITS__ = {json.dumps(get_salary_limits(), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_MIN_CONTRACT_MONTH_OPTIONS__ = {json.dumps(MIN_CONTRACT_MONTH_OPTIONS, ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__ = {json.dumps(ENGAGEMENT_TYPE_OPTIONS, ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT_VALUES__ = {json.dumps(ENGAGEMENT_TYPE_DEFAULT_VALUES, ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_WORK_MODE_PREFERENCE_OPTIONS__ = {json.dumps(WORK_MODE_PREFERENCE_OPTIONS, ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_WORK_MODE_PREFERENCE_DEFAULT__ = {json.dumps(list(WORK_MODE_PREFERENCE_DEFAULT_VALUES), ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_WORK_MODE_PREFERENCE_NONE_LABEL__ = {json.dumps(WORK_MODE_PREFERENCE_NONE_LABEL, ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__ = {json.dumps(SECTOR_PREFERENCE_OPTIONS, ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_SECTOR_PREFERENCE_DEFAULT__ = {json.dumps(GovPref.ANY, ensure_ascii=True)};</script>"
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_MIN_CONTRACT_MONTH_NONE_LABEL__ = {json.dumps(MIN_CONTRACT_MONTH_NONE_LABEL, ensure_ascii=True)};</script>"
    )
    _gs = load_global_settings()
    _model_options = (
        _gs.get(KEY_LLM_SETTINGS, {}).get(KEY_MODEL_OPTIONS, []) if isinstance(_gs, dict) else []
    )
    parts.append(
        f"<script>window.__JOB_HUNTER_LLM_MODEL_OPTIONS__ = {json.dumps(_model_options, ensure_ascii=True)};</script>"
    )
    return "\n  ".join(parts)


def _parse_locations_override(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[\r\n,]+", text) if part.strip()]


LOCATION_NAME_RE = re.compile(r"^[A-Za-z\s,'()-]+$")


def _normalize_choice_values(values: object) -> list[str]:
    if isinstance(values, str):
        source_values = [
            part.strip().lower() for part in re.split(r"[,\n|/]+", values) if part.strip()
        ]
    elif isinstance(values, (list, tuple, set)):
        source_values = [str(value).strip().lower() for value in values if str(value).strip()]
    else:
        source_values = []
    selected: list[str] = []
    seen: set[str] = set()
    for value in source_values:
        if value and value not in seen:
            seen.add(value)
            selected.append(value)
    return selected


def render_choice_strip(
    *,
    name: str,
    options: list[dict[str, str]],
    selected_values: object,
    input_type: str,
    group_id: str,
    label_id: str,
    card_class: str,
) -> str:
    input_type = str(input_type or "radio").strip().lower()
    selected = _normalize_choice_values(selected_values)
    selected_set = set(selected)
    selected_value = (
        selected[0] if selected else str(options[0]["value"] if options else "").strip().lower()
    )
    if input_type == "radio" and not selected_value:
        selected_value = str(options[0]["value"] if options else "").strip().lower()
    rendered_options = []
    for item in options:
        value = str(item["value"]).strip().lower()
        checked = (
            " checked"
            if (input_type == "radio" and value == selected_value)
            or (input_type != "radio" and value in selected_set)
            else ""
        )
        rendered_options.append(
            f'<label class="choice-card jh-choice {escape(card_class)}"><input type="{escape(input_type)}" name="{escape(name)}" value="{escape(value)}"{checked}><span>{escape(item["label"])}</span></label>'
        )
    role = "radiogroup" if input_type == "radio" else "group"
    return f'<div id="{escape(group_id)}" class="choice-strip jh-choice-group" role="{role}" aria-labelledby="{escape(label_id)}">{"".join(rendered_options)}</div>'


def render_engagement_type_choices(*, name: str, selected_values: object) -> str:
    return render_choice_strip(
        name=name,
        options=list(ENGAGEMENT_TYPE_OPTIONS),
        selected_values=normalize_engagement_type_preferences(selected_values),
        input_type="checkbox",
        group_id="engagement_type_choices",
        label_id="engagement_type_label",
        card_class="choice-card--work-mode",
    )


def render_min_contract_month_options(*, selected_value: object | None) -> str:
    selected = str(selected_value or "").strip()
    return "".join(
        f'<option value="{escape(item["value"])}"{(" selected" if item["value"] == selected else "")}>{escape(item["label"])}</option>'
        for item in MIN_CONTRACT_MONTH_OPTIONS
    )


def render_sector_preference_select_options(*, selected_value: str) -> str:
    selected = str(selected_value or GovPref.ANY).strip().lower()
    options = []
    for item in SECTOR_PREFERENCE_OPTIONS:
        selected_attr = " selected" if item["value"] == selected else ""
        options.append(
            f'<option value="{escape(item["value"])}"{selected_attr}>{escape(item["label"])}</option>'
        )
    return "".join(options)


def render_sector_preference_choices(*, selected_values: object) -> str:
    valid_values = {item["value"] for item in SECTOR_PREFERENCE_CHOICE_OPTIONS}
    selected = [
        value for value in _normalize_choice_values(selected_values) if value in valid_values
    ]
    if not selected:
        selected = [item["value"] for item in SECTOR_PREFERENCE_CHOICE_OPTIONS]
    return render_choice_strip(
        name="prefer_sector",
        options=list(SECTOR_PREFERENCE_CHOICE_OPTIONS),
        selected_values=selected,
        input_type="checkbox",
        group_id="prefer_sector_choices",
        label_id="prefer_sector_label",
        card_class="choice-card--work-mode",
    )


def render_work_mode_preference_choices(*, selected_values: object) -> str:
    selected = normalize_work_mode_preferences(selected_values)
    return render_choice_strip(
        name="work_mode_preference",
        options=list(WORK_MODE_PREFERENCE_OPTIONS),
        selected_values=selected if selected else list(WORK_MODE_PREFERENCE_DEFAULT_VALUES),
        input_type="checkbox",
        group_id="work_mode_preference",
        label_id="work_mode_preference_label",
        card_class="choice-card--work-mode",
    )


def render_seek_max_pages_choices(
    *, selected_value: object | None = None, label_id: str = "seek_max_pages_label"
) -> str:
    global_settings = load_global_settings()
    search_settings = (
        global_settings.get(KEY_SEARCH_SETTINGS, {}) if isinstance(global_settings, dict) else {}
    )
    search_limits = (
        global_settings.get(KEY_LIMITS, {}).get("search", {})
        if isinstance(global_settings, dict)
        else {}
    )
    bounds = search_limits.get(KEY_SEEK_MAX_PAGES, {})
    min_value = int(bounds.get("min", 1))
    max_value = int(bounds.get("max", 10))
    if min_value > max_value:
        raise ValueError("global_settings.limits.search.seek_max_pages.min must be <= max")
    options = [
        {"value": str(value), "label": str(value)} for value in range(min_value, max_value + 1)
    ]
    selected = str(
        selected_value
        if selected_value is not None
        else search_settings.get(KEY_SEEK_MAX_PAGES, max_value)
    ).strip()
    if selected not in {option["value"] for option in options}:
        raise ValueError(
            f"global_settings.search_settings.{KEY_SEEK_MAX_PAGES} must be between {min_value} and {max_value}"
        )
    return render_choice_strip(
        name=KEY_SEEK_MAX_PAGES,
        options=options,
        selected_values=selected,
        input_type="radio",
        group_id="seek_max_pages_choices",
        label_id=label_id,
        card_class="choice-card--work-mode choice-card--seek-pages",
    )


def _normalize_onboarding_search_preferences(payload: dict | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    keywords = str(source.get(KEY_KEYWORDS) or "").strip()
    locations = _parse_locations_override(source.get(KEY_LOCATIONS))
    normalized = {
        KEY_KEYWORDS: keywords,
        KEY_LOCATIONS: locations,
        KEY_ENGAGEMENT_TYPE: normalize_engagement_type_preferences(
            source.get(KEY_ENGAGEMENT_TYPE), default_to_all=False
        ),
    }
    if KEY_MIN_SALARY_YEARLY in source:
        normalized[KEY_MIN_SALARY_YEARLY] = source.get(KEY_MIN_SALARY_YEARLY)
    if KEY_MIN_DAILY_RATE in source:
        normalized[KEY_MIN_DAILY_RATE] = source.get(KEY_MIN_DAILY_RATE)
    return normalized


def _validate_required_onboarding_inputs(
    search_preferences: dict[str, Any],
    onboarding_settings_payload: dict | None,
) -> None:
    keywords = str(search_preferences.get(KEY_KEYWORDS) or "").strip()
    locations = _parse_locations_override(search_preferences.get(KEY_LOCATIONS))
    engagement_type = normalize_engagement_type_preferences(
        search_preferences.get(KEY_ENGAGEMENT_TYPE), default_to_all=False
    )

    validate_search_keywords(keywords, require_phrase=True)
    search_limits = load_global_settings()[KEY_LIMITS]["search"]
    max_locations = int(search_limits[KEY_LOCATIONS_MAX_SELECTED]["max"])
    if not locations:
        raise ValueError("Please choose at least one search location.")
    if len(locations) > max_locations:
        raise ValueError(f"Please choose no more than {max_locations} search locations.")
    for location in locations:
        if len(location) < 2 or len(location) > 80:
            raise ValueError("Location should be between 2 and 80 characters.")
        if not LOCATION_NAME_RE.match(location):
            raise ValueError("Location should look like a normal city, state, or region name.")
        resolve_location(location)
    if not engagement_type or any(value not in VALID_ENGAGEMENT_TYPES for value in engagement_type):
        raise ValueError("Please choose which work types you want to include.")

    raw_yearly = search_preferences.get(KEY_MIN_SALARY_YEARLY)
    if raw_yearly not in (None, ""):
        yearly = _parse_non_negative_salary_value(raw_yearly, label="Minimum permanent salary")
        _enforce_salary_caps(
            yearly, label="Minimum permanent salary", limit_key=KEY_MIN_SALARY_YEARLY
        )

    raw_daily = search_preferences.get(KEY_MIN_DAILY_RATE)
    if raw_daily not in (None, ""):
        daily = _parse_non_negative_salary_value(raw_daily, label="Minimum contract daily rate")
        _enforce_salary_caps(
            daily, label="Minimum contract daily rate", limit_key=KEY_MIN_DAILY_RATE
        )

    raw_settings = (
        onboarding_settings_payload if isinstance(onboarding_settings_payload, dict) else {}
    )
    if isinstance(raw_settings.get(KEY_ONBOARDING_SETTINGS), dict):
        raw_settings = raw_settings.get(KEY_ONBOARDING_SETTINGS) or {}

    raw_lookback = raw_settings.get(KEY_LOOKBACK_YEARS)
    raw_min_months = raw_settings.get(KEY_MIN_MONTHS)
    if raw_lookback in (None, ""):
        raise ValueError("Please choose how far back we should look.")
    if raw_min_months in (None, ""):
        raise ValueError("Please choose when a role is too short to count as a main signal.")

    try:
        lookback = int(raw_lookback)
    except Exception as exc:
        raise ValueError("Lookback must be a whole number of years.") from exc
    try:
        min_months = int(raw_min_months)
    except Exception as exc:
        raise ValueError("Short-role threshold must be a whole number of months.") from exc

    if lookback < 1 or lookback > 20:
        raise ValueError("Please enter a lookback between 1 and 20 years.")
    if min_months < 1 or min_months > 24:
        raise ValueError("Please enter a short-role threshold between 1 and 24 months.")


def _read_last_run_timestamp() -> str | None:
    try:
        payload = load_run_stats()
        if isinstance(payload, dict) and payload:
            timestamp = str(
                payload.get("last_run_attempt_at")
                or payload.get("run_finished_at")
                or payload.get("run_started_at")
                or ""
            ).strip()
            if timestamp:
                return timestamp
        state = load_agent_state()
        return str(state.get("last_agent_run_at") or "").strip() or None
    except Exception as exc:
        logger.warning("Failed to read last run timestamp: %s", exc)
        return None


def _read_scheduler_status() -> dict[str, Any]:
    from job_hunter_agent.agent_runner import (
        STATE_LAST_SCHEDULED_ATTEMPT_AT,
        STATE_LAST_SCHEDULED_MESSAGE,
        STATE_LAST_SCHEDULED_STATUS,
        STATE_SCHEDULER_LAST_SEEN_AT,
    )

    settings = load_user_settings(None, create_if_missing=True)
    schedule = settings.get(KEY_SCHEDULE, {}) if isinstance(settings, dict) else {}
    schedule_enabled = bool(
        schedule.get("enabled", DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["enabled"])
    )
    daily_time_local = str(
        schedule.get("daily_time_local")
        or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["daily_time_local"]
    ).strip()
    loop_sleep_seconds = int(
        schedule.get("loop_sleep_seconds")
        or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"]
    )
    state = load_agent_state()
    now = datetime.now().astimezone()
    heartbeat_at = str(state.get(STATE_SCHEDULER_LAST_SEEN_AT) or "").strip()
    heartbeat_dt = parse_timestamp(heartbeat_at)
    heartbeat_window = timedelta(seconds=max(loop_sleep_seconds * 2, loop_sleep_seconds + 60))
    scheduler_active = bool(
        heartbeat_dt and (now - heartbeat_dt) <= heartbeat_window
    )

    try:
        hour_text, minute_text = daily_time_local.split(":", 1)
        scheduled_hour = int(hour_text)
        scheduled_minute = int(minute_text)
    except Exception:
        daily_time_local = str(DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["daily_time_local"]).strip()
        hour_text, minute_text = daily_time_local.split(":", 1)
        scheduled_hour = int(hour_text)
        scheduled_minute = int(minute_text)

    next_run_at = now.replace(
        hour=scheduled_hour,
        minute=scheduled_minute,
        second=0,
        microsecond=0,
    )
    if next_run_at <= now:
        next_run_at += timedelta(days=1)

    return {
        "active": scheduler_active,
        "enabled": schedule_enabled,
        "daily_time_local": daily_time_local,
        "next_run_at": next_run_at.isoformat(timespec="seconds"),
        "last_seen_at": heartbeat_at or None,
        "last_attempt_at": str(state.get(STATE_LAST_SCHEDULED_ATTEMPT_AT) or "").strip() or None,
        "last_status": str(state.get(STATE_LAST_SCHEDULED_STATUS) or "").strip() or None,
        "last_message": str(state.get(STATE_LAST_SCHEDULED_MESSAGE) or "").strip() or None,
    }


def _normalize_search_settings_payload(payload: dict | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    if isinstance(source.get("search_settings"), dict):
        source = source.get("search_settings") or {}

    overrides: dict[str, Any] = {}
    if KEY_KEYWORDS in source:
        value = str(source.get(KEY_KEYWORDS) or "").strip()
        if value:
            overrides[KEY_KEYWORDS] = value
    if KEY_LOCATIONS in source:
        parsed = _parse_locations_override(source.get(KEY_LOCATIONS))
        if parsed:
            overrides[KEY_LOCATIONS] = parsed
    if KEY_DATE_RANGE_DAYS in source:
        overrides[KEY_DATE_RANGE_DAYS] = source.get(KEY_DATE_RANGE_DAYS)
    if KEY_SEEK_MAX_PAGES in source:
        overrides[KEY_SEEK_MAX_PAGES] = source.get(KEY_SEEK_MAX_PAGES)
    if KEY_LINKEDIN_HOURS_OLD in source:
        overrides[KEY_LINKEDIN_HOURS_OLD] = source.get(KEY_LINKEDIN_HOURS_OLD)
    if KEY_LINKEDIN_RESULTS_PER_SEARCH in source:
        overrides[KEY_LINKEDIN_RESULTS_PER_SEARCH] = source.get(KEY_LINKEDIN_RESULTS_PER_SEARCH)

    if not overrides:
        return {}

    current_search_settings = normalize_search_settings(load_profile().get("search_settings", {}))
    current_search_settings.update(overrides)
    return normalize_search_settings(current_search_settings)


def _normalize_onboarding_settings_payload(payload: dict | None) -> dict[str, int]:
    allowed_keys = (
        KEY_CAPABILITY_ALIAS_LIMIT,
        KEY_LOOKBACK_YEARS,
        KEY_MIN_MONTHS,
        KEY_MAX_TARGET,
        KEY_MAX_SECONDARY,
        KEY_CV_MAX_PAGES,
        KEY_SIGNAL_CLUSTER_MIN_ALIAS_HITS,
        KEY_SIGNAL_CLUSTER_MIN_SNIPPET_HITS,
        KEY_SIGNAL_CLUSTER_DENSE_SNIPPET_ALIAS_HITS,
    )
    source = payload if isinstance(payload, dict) else {}
    if isinstance(source.get(KEY_ONBOARDING_SETTINGS), dict):
        source = source.get(KEY_ONBOARDING_SETTINGS) or {}

    if not source:
        current = load_profile().get(KEY_ONBOARDING_SETTINGS)
        if isinstance(current, dict) and current:
            source = current
        else:
            source = dict(DEFAULT_ONBOARDING_SETTINGS)

    normalized = normalize_onboarding_settings(source)
    return {key: int(normalized[key]) for key in allowed_keys if key in normalized}


def describe_capability_strength_preset(preset_name: str) -> dict[str, Any]:
    preset_key = str(preset_name or "").strip().lower()
    if preset_key not in CAPABILITY_STRENGTH_PRESETS:
        preset_key = str(DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]).strip().lower()
    return {
        "capability_strength_preset": preset_key,
        "values": dict(CAPABILITY_STRENGTH_PRESETS[preset_key]),
    }


def _onboarding_complete(profile: dict[str, Any] | None = None) -> bool:
    current = profile if isinstance(profile, dict) else load_profile()
    return bool(current.get(KEY_ONBOARDING_COMPLETE))


def _onboarding_resume_step(profile: dict[str, Any] | None = None) -> int:
    """Returns the wizard step to resume at (1 = upload, 2 = review draft)."""
    current = profile if isinstance(profile, dict) else load_profile()
    capability_rules = [r for r in current.get("candidate_capabilities", []) if r]
    if capability_rules:
        return 2
    return 1


def _write_run_stats_field(key: str, value: object) -> None:
    try:
        payload = load_run_stats() or {}
        if not isinstance(payload, dict):
            payload = {}
        payload[key] = value
        write_run_stats(payload)
    except Exception as write_exc:
        logger.warning("Could not write run_stats.%s: %s", key, write_exc)


def _run_scrape_job(*, force_refresh: bool = False) -> None:
    """Own one background scrape lifecycle from start through terminal state."""
    progress_scope = begin_run_progress_scope()
    try:
        scrape_jobs_direct(force_refresh=force_refresh)
        if run_shutdown_requested():
            raise RunInterruptedError("Server shutdown interrupted the scrape run.")
        _write_run_stats_field("last_run_error", None)
    except RunInterruptedError:
        _write_run_stats_field("run_status", RUN_STATUS_INTERRUPTED)
        _write_run_stats_field("last_run_error", RUN_INTERRUPTED_MESSAGE)
        logger.warning(
            "[RUN_INTERRUPTED] Scrape worker exited without finalizing results after server shutdown."
        )
    except Exception as exc:
        if run_shutdown_requested():
            _write_run_stats_field("run_status", RUN_STATUS_INTERRUPTED)
            _write_run_stats_field("last_run_error", RUN_INTERRUPTED_MESSAGE)
            logger.warning(
                "[RUN_INTERRUPTED] Scrape worker exited without finalizing results after server shutdown."
            )
        elif run_stop_requested():
            logger.info("Scrape run stopped by request; preserving partial results.")
            _write_run_stats_field("last_run_error", None)
        else:
            msg = f"{type(exc).__name__}: {exc}"
            logger.error("Scrape run failed: %s", msg)
            _write_run_stats_field("last_run_error", msg)
    finally:
        interrupted = run_shutdown_requested() or _current_run_status() == RUN_STATUS_INTERRUPTED
        stopped = run_stop_requested()
        _finish_run(
            RUN_STATUS_INTERRUPTED
            if interrupted
            else RUN_STATUS_STOPPED
            if stopped
            else RUN_STATUS_IDLE
        )
        end_run_progress_scope(progress_scope)
        clear_run_shutdown_request()
        clear_run_stop_request()


def _rebuild_workspace_on_startup() -> None:
    from job_hunter_agent.user_context import set_user_id

    user_ids = list_user_setting_user_ids()
    if not user_ids:
        return
    for user_id in user_ids:
        set_user_id(user_id)
        try:
            if not get_workspace_results_path().exists() and not load_run_stats():
                continue
            rebuild_workspace_results(reason="server startup rebuild")
        except Exception as exc:
            logger.warning(
                "Could not rebuild workspace on startup for %s: %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
        finally:
            set_user_id(None)


def _log_previous_interrupted_runs() -> None:
    """Make persisted interrupted searches visible when the server starts."""
    for user_id in list_user_setting_user_ids():
        set_user_id(user_id)
        try:
            run_stats = load_run_stats()
            if str(run_stats.get("run_status") or "").strip() != RUN_STATUS_INTERRUPTED:
                continue
            logger.warning(
                "[RUN_INTERRUPTED][PREVIOUS] Previous search was interrupted before completion. "
                "run_id=%s interrupted_at=%s signal=%s",
                str(run_stats.get("last_run_attempt_at") or "unknown"),
                str(run_stats.get("run_interrupted_at") or "unknown"),
                str(run_stats.get("run_interruption_signal") or "unknown"),
            )
        except Exception as exc:
            logger.warning(
                "Could not inspect previous run state for %s: %s: %s",
                user_id,
                type(exc).__name__,
                exc,
            )
        finally:
            set_user_id(None)


class SettingsHandler:
    @staticmethod
    def _changed_matching_rule_keys(before: dict, after: dict) -> list[str]:
        before = before or {}
        after = after or {}
        return [key for key in MATCHING_RULE_PROFILE_KEYS if before.get(key) != after.get(key)]

    @classmethod
    def _matching_rules_changed(cls, before: dict, after: dict) -> bool:
        """True only when a matching rule value actually differs, not merely appears in the patch."""
        return bool(cls._changed_matching_rule_keys(before, after))

    @staticmethod
    def _normalize_profile_patch_for_save(current: dict, patch: dict) -> dict:
        normalized = dict(patch or {})
        if KEY_STAR_EVIDENCE in normalized:
            normalized[KEY_STAR_EVIDENCE] = str(normalized.get(KEY_STAR_EVIDENCE) or "").strip()
        return normalized

    @classmethod
    def _reset_current_user_state(cls) -> dict[str, Any]:
        if _is_run_in_progress():
            raise ValueError(
                "A scrape is currently running. Wait for it to finish before resetting."
            )
        # Wipe every per-user data directory under data/users/
        if USERS_DIR.exists():
            try:
                user_entries = list(USERS_DIR.iterdir())
            except OSError as _enum_err:
                logger.warning("Could not enumerate %s: %s", USERS_DIR, _enum_err)
                user_entries = []
            for user_dir in user_entries:
                try:
                    if user_dir.is_dir():
                        shutil.rmtree(user_dir, ignore_errors=True)
                    else:
                        user_dir.unlink(missing_ok=True)
                except Exception as exc:
                    logger.warning("Failed to remove user directory %s: %s", user_dir, exc)
                    continue

        save_profile(DEFAULT_PROFILE)
        save_source_materials(DEFAULT_SOURCE_MATERIALS)

        clear_current_user_search_state(preserve_profile=False)
        clear_user_settings()

        return {
            "ok": True,
            "message": "All user state reset. Shared signals were preserved.",
            "redirect_to": "/start?fresh=1",
        }

    @staticmethod
    def _reset_global_learning() -> dict[str, Any]:
        from job_hunter_agent.signal_registry import clear_signal_learning_state

        clear_signal_learning_state()
        return {
            "ok": True,
            "message": "Global signals reset. Shared learned signals were cleared.",
        }

    @staticmethod
    def _sanitize_user_settings_payload(payload: dict) -> dict:
        workspace = payload.get(KEY_WORKSPACE, {}) if isinstance(payload, dict) else {}
        telegram = payload.get(KEY_TELEGRAM, {}) if isinstance(payload, dict) else {}
        llm = payload.get(KEY_LLM, {}) if isinstance(payload, dict) else {}
        schedule_payload = payload.get(KEY_SCHEDULE) if isinstance(payload, dict) else None
        sanitized = {
            KEY_WORKSPACE: {
                "minimum_score": max(
                    0,
                    min(
                        int(
                            workspace.get(
                                "minimum_score",
                                DEFAULT_USER_SETTINGS[KEY_WORKSPACE]["minimum_score"],
                            )
                            or DEFAULT_USER_SETTINGS[KEY_WORKSPACE]["minimum_score"]
                        ),
                        100,
                    ),
                ),
            },
            KEY_TELEGRAM: {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token": str(telegram.get("bot_token") or "").strip(),
                "bot_username": str(telegram.get("bot_username") or "").strip().lstrip("@"),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
            },
        }
        model = str(llm.get("model") or "").strip()
        if "model" in llm or model:
            allowed_models = [
                str(value).strip()
                for value in (
                    load_global_settings().get(KEY_LLM_SETTINGS, {}).get(KEY_MODEL_OPTIONS, [])
                )
                if str(value).strip()
            ]
            if not allowed_models:
                raise ValueError("No LLM models are configured in Admin.")
            if not model:
                raise ValueError("Please choose an LLM model.")
            if model not in allowed_models:
                raise ValueError("Please choose a model configured in Global Settings.")
            sanitized[KEY_LLM] = {
                "model": model,
            }
        if isinstance(schedule_payload, dict):
            daily_time_local = str(
                schedule_payload.get("daily_time_local")
                or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["daily_time_local"]
            ).strip()
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_time_local):
                raise ValueError("Schedule time must be in HH:MM 24-hour format.")
            try:
                loop_sleep_seconds = int(
                    schedule_payload.get(
                        "loop_sleep_seconds",
                        DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"],
                    )
                    or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"]
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Schedule polling interval must be a whole number of seconds."
                ) from exc
            sanitized[KEY_SCHEDULE] = {
                "enabled": bool(
                    schedule_payload.get(
                        "enabled",
                        DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["enabled"],
                    )
                ),
                "daily_time_local": daily_time_local,
                "loop_sleep_seconds": max(60, loop_sleep_seconds),
            }
        return sanitized

    @staticmethod
    def _public_user_settings_payload(settings: dict) -> dict:
        workspace = settings.get(KEY_WORKSPACE, {}) if isinstance(settings, dict) else {}
        telegram = settings.get(KEY_TELEGRAM, {}) if isinstance(settings, dict) else {}
        llm_settings = settings.get(KEY_LLM, {}) if isinstance(settings, dict) else {}
        schedule = settings.get(KEY_SCHEDULE, {}) if isinstance(settings, dict) else {}
        subscribers = telegram.get("subscribers", []) if isinstance(telegram, dict) else []
        return {
            KEY_WORKSPACE: {
                "minimum_score": max(
                    0,
                    min(
                        int(
                            workspace.get(
                                "minimum_score",
                                DEFAULT_USER_SETTINGS[KEY_WORKSPACE]["minimum_score"],
                            )
                            or DEFAULT_USER_SETTINGS[KEY_WORKSPACE]["minimum_score"]
                        ),
                        100,
                    ),
                ),
            },
            KEY_SCHEDULE: {
                "enabled": bool(
                    schedule.get("enabled", DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["enabled"])
                ),
                "daily_time_local": str(
                    schedule.get("daily_time_local")
                    or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["daily_time_local"]
                ).strip(),
                "loop_sleep_seconds": max(
                    60,
                    int(
                        schedule.get(
                            "loop_sleep_seconds",
                            DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"],
                        )
                        or DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"]
                    ),
                ),
            },
            KEY_TELEGRAM: {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token_present": bool(str(telegram.get("bot_token") or "").strip()),
                "bot_username": str(telegram.get("bot_username") or "").strip(),
                "chat_id_present": bool(str(telegram.get("chat_id") or "").strip()),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
                "subscriber_count": len(subscribers),
                "subscribers": subscribers,
            },
            KEY_LLM: {  # Use llm_settings here to avoid shadowing the imported KEY_LLM
                "model": str(llm_settings.get("model") or "").strip(),
            },
        }

    @staticmethod
    def _issue_rejection_suggestion_approval_tokens(
        job_id: str, suggestions: list[str]
    ) -> dict[str, str]:
        normalized_job_id = normalize_job_key(job_id) or str(job_id or "").strip()
        tokens: dict[str, str] = {}
        for suggestion in suggestions:
            phrase = _normalize_suggestion_phrase(suggestion)
            if not phrase:
                continue
            token = hashlib.sha1(f"{normalized_job_id}|{phrase}".encode("utf-8")).hexdigest()[:16]
            tokens[phrase] = token
        return tokens

    @staticmethod
    def _validate_llm_suggestion_approvals(
        job_id: str,
        blockers: list[str],
        approved_suggestion_tokens: dict[str, str] | None = None,
    ) -> None:
        normalized_job_id = normalize_job_key(job_id) or str(job_id or "").strip()
        cached = _rejection_suggestions_cache.get(normalized_job_id)
        if not isinstance(cached, dict):
            return

        suggested_terms = {
            _normalize_suggestion_phrase(item)
            for item in (cached.get("suggestions") or [])
            if _normalize_suggestion_phrase(item)
        }
        if not suggested_terms:
            return

        provided = (
            approved_suggestion_tokens if isinstance(approved_suggestion_tokens, dict) else {}
        )
        expected_tokens = SettingsHandler._issue_rejection_suggestion_approval_tokens(
            normalized_job_id,
            list(suggested_terms),
        )
        for blocker in blockers:
            phrase = _normalize_suggestion_phrase(blocker)
            if not phrase or phrase not in suggested_terms:
                continue
            expected = expected_tokens.get(phrase, "")
            if not expected or str(provided.get(phrase) or "").strip() != expected:
                raise ValueError(f"Missing explicit approval for suggested blocker: {phrase}")


def _validate_onboarding_settings_inputs(onboarding_settings_payload: dict | None) -> None:
    raw_settings = (
        onboarding_settings_payload if isinstance(onboarding_settings_payload, dict) else {}
    )
    if isinstance(raw_settings.get(KEY_ONBOARDING_SETTINGS), dict):
        raw_settings = raw_settings.get(KEY_ONBOARDING_SETTINGS) or {}

    raw_lookback = raw_settings.get(KEY_LOOKBACK_YEARS)
    raw_min_months = raw_settings.get(KEY_MIN_MONTHS)
    if raw_lookback in (None, ""):
        raise ValueError("Please choose how far back we should look.")
    if raw_min_months in (None, ""):
        raise ValueError("Please choose when a role is too short to count as a main signal.")

    try:
        lookback = int(raw_lookback)
    except Exception as exc:
        raise ValueError("Lookback must be a whole number of years.") from exc
    try:
        min_months = int(raw_min_months)
    except Exception as exc:
        raise ValueError("Short-role threshold must be a whole number of months.") from exc

    if lookback < 1 or lookback > 20:
        raise ValueError("Please enter a lookback between 1 and 20 years.")
    if min_months < 1 or min_months > 24:
        raise ValueError("Please enter a short-role threshold between 1 and 24 months.")
