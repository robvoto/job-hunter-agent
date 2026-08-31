"""Workspace service helpers.

Purpose: assemble the counts, stats, and fragments shown on the workspace page.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


from job_hunter_agent import workspace_data
from job_hunter_agent import filters as _filters
from job_hunter_agent.config import DEBUG_MODE, JOB_HUNTER_BASE_URL
from job_hunter_agent.fit_scoring import fit_score_displayed
from job_hunter_agent.global_settings import (
    get_archive_stale_after_days,
    get_hidden_review_days,
)
from job_hunter_agent.history import (
    TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING,
    build_history_cluster_index,
    viewed_by_user,
)
from job_hunter_agent.io_utils import load_audit_rows, load_ui_labels
from job_hunter_agent.llm_gate import get_cost_summary
from job_hunter_agent.job_identity import deduplicate_across_sources, normalize_job_key
from job_hunter_agent.llm_review_state import has_complete_llm_keep_data
from job_hunter_agent.match_labels import score_to_match_label
from job_hunter_agent.paths import REPO_ROOT
from job_hunter_agent.posting_utils import days_since, parse_timestamp
from job_hunter_agent.profile_store import (
    ENGAGEMENT_TYPE_OPTIONS,
    KEY_ENGAGEMENT_TYPE,
    KEY_PREFER_SECTOR,
    KEY_WORK_MODE_PREFERENCE,
    SECTOR_PREFERENCE_OPTIONS,
    WORK_MODE_PREFERENCE_NONE_LABEL,
    WORK_MODE_PREFERENCE_OPTIONS,
    GovPref,
    get_match_levels,
    get_search_settings,
    load_profile,
    normalize_engagement_type_preferences,
    normalize_sector_preference_values,
    normalize_work_mode_preferences,
)
from job_hunter_agent.score_labels import viewed_badge_html
from job_hunter_agent.system_warnings import make_system_warning_fingerprint, record_system_warning
from job_hunter_agent.user_settings import get_workspace_minimum_score
from job_hunter_agent.utils import safe_html
from job_hunter_agent.workspace_renderer import (
    ARCHIVE_LABEL,
    humanize_reject_reason,
    load_workspace_page_labels,
    render_page_size_select_html,
    render_posted_filter_options,
    render_results_fragment,
    render_score_filter_options,
    render_section,
    render_workspace_tabs_html,
    render_work_type_filter_options,
    render_job_board_filter_choices,
)

WORKSPACE_DEBUG_MODE = DEBUG_MODE
passes_title_filters = _filters.passes_title_filters


def _label_from_options(options: tuple[dict[str, Any], ...], value: object, default: str) -> str:

    normalized = str(value or "").strip().lower()

    for item in options:
        if str(item.get("value") or "").strip().lower() == normalized:
            return str(item.get("label") or default).strip() or default

    return default


def _format_common_search_preferences(profile: dict[str, Any]) -> tuple[str, str, str]:

    match_preferences = dict(profile.get("match_preferences") or {})

    selected_work_types = normalize_engagement_type_preferences(
        match_preferences.get(KEY_ENGAGEMENT_TYPE)
    )

    work_type_lookup = {
        str(item["value"]).strip().lower(): str(item["label"]).strip()
        for item in ENGAGEMENT_TYPE_OPTIONS
    }

    work_type_label = " | ".join(
        work_type_lookup.get(value, value.title())
        for value in selected_work_types
        if value in work_type_lookup
    )

    selected_work_modes = normalize_work_mode_preferences(
        match_preferences.get(KEY_WORK_MODE_PREFERENCE)
    )

    work_mode_lookup = {
        str(item["value"]).strip().lower(): str(item["label"]).strip()
        for item in WORK_MODE_PREFERENCE_OPTIONS
    }

    work_mode_label = (
        " | ".join(
            work_mode_lookup.get(value, value.title())
            for value in selected_work_modes
            if value in work_mode_lookup
        )
        or WORK_MODE_PREFERENCE_NONE_LABEL
    )

    sector_lookup = {
        str(item["value"]).strip().lower(): str(item["label"]).strip()
        for item in SECTOR_PREFERENCE_OPTIONS
    }

    selected_sector_prefs = normalize_sector_preference_values(
        match_preferences.get(KEY_PREFER_SECTOR)
    )

    sector_label = " | ".join(
        sector_lookup.get(value, value.title())
        for value in selected_sector_prefs
        if value in sector_lookup
    ) or _label_from_options(SECTOR_PREFERENCE_OPTIONS, GovPref.ANY, "No preference")

    return work_type_label, work_mode_label, sector_label


def _format_salary_min_label(profile: dict[str, Any]) -> str:

    salary_prefs = dict(profile.get("salary_preferences") or {})

    yearly = int(salary_prefs.get("minimum_salary_yearly", 0) or 0)

    daily = int(salary_prefs.get("minimum_daily_rate", 0) or 0)

    parts = []

    if yearly > 0:
        parts.append(f"${yearly:,}/yr")

    if daily > 0:
        parts.append(f"${daily:,}/day")

    return " | ".join(parts) if parts else "Not set"


def is_workspace_eligible(
    record: dict,
    profile: Optional[dict] = None,
    workspace_min_score: Optional[int] = None,
) -> bool:
    if not has_complete_llm_keep_data(record):
        logger.error(
            "[WORKSPACE_ELIGIBLE][LLM_INCOMPLETE] job=%s title=%r — excluded from workspace: complete LLM keep data is required",
            record.get("job_key", "<unknown>"),
            str(record.get("title") or "").strip(),
        )
        return False

    active_workspace_min_score = (
        int(workspace_min_score)
        if workspace_min_score is not None
        else get_workspace_minimum_score()
    )

    try:
        return fit_score_displayed(record, profile) >= active_workspace_min_score

    except RuntimeError as exc:
        logger.error(
            "[WORKSPACE_ELIGIBLE][SCORING_ERROR] job=%s title=%r — excluded from workspace: %s",
            record.get("job_key", "<unknown>"),
            str(record.get("title") or "").strip(),
            exc,
        )

        return False


def _enrich_records_with_candidate_application_history(records: list[dict]) -> list[dict]:

    enriched_records = records

    enriched_count = 0

    try:
        from job_hunter_agent.candidate_application_history import (
            enrich_records_with_application_history,
            load_candidate_job_rejection_history,
        )

        candidate_history = load_candidate_job_rejection_history()

        if candidate_history:
            enriched_records = enrich_records_with_application_history(records, candidate_history)

            enriched_count = sum(
                1
                for before, after in zip(records, enriched_records)
                if "candidate_application_history" not in before
                and "candidate_application_history" in after
            )

    except Exception as exc:
        logger.warning("[candidate_application_history] unavailable: %s", exc)
        record_system_warning(
            severity="warning",
            category="candidate_application_history_enrichment",
            source="_enrich_records_with_candidate_application_history",
            message=f"Candidate application history enrichment unavailable: {exc}",
            fingerprint=make_system_warning_fingerprint(
                "candidate_application_history_enrichment", str(exc)
            ),
            context={"error": str(exc)},
        )

        enriched_records = records

    logger.info("[candidate_application_history] records enriched: %s", enriched_count)

    return enriched_records


def build_history_workspace_record(
    job_key: str, entry: dict, run_started_at: datetime
) -> Optional[dict]:

    return workspace_data.build_history_workspace_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
        archive_stale_after_days=get_archive_stale_after_days(),
    )


def build_archive_records(
    history: dict[str, dict],
    current_run_keys: set[str],
    applied_job_keys: set[str],
    hidden_job_keys: set[str],
    run_started_at: datetime,
) -> list[dict]:

    return workspace_data.build_archive_records(
        history,
        current_run_keys,
        applied_job_keys,
        hidden_job_keys,
        run_started_at,
        normalize_job_key_fn=normalize_job_key,
        parse_timestamp_fn=parse_timestamp,
        build_history_workspace_record_fn=build_history_workspace_record,
    )


def build_hidden_workspace_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:

    return workspace_data.build_hidden_workspace_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
    )


def build_hidden_records(
    hidden_job_keys: set[str],
    history: dict[str, dict],
    run_started_at: datetime,
) -> list[dict]:

    return workspace_data.build_hidden_records(
        hidden_job_keys,
        history,
        run_started_at,
        parse_timestamp_fn=parse_timestamp,
        days_since_fn=days_since,
        hidden_review_days=get_hidden_review_days(),
        build_hidden_workspace_record_fn=build_hidden_workspace_record,
    )


def build_applied_workspace_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:

    return workspace_data.build_applied_workspace_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
    )


def build_applied_records(
    applied_job_keys: set[str],
    history: dict[str, dict],
    run_started_at: datetime,
) -> list[dict]:

    return workspace_data.build_applied_records(
        applied_job_keys,
        history,
        run_started_at,
        parse_timestamp_fn=parse_timestamp,
        build_applied_workspace_record_fn=build_applied_workspace_record,
    )


def build_workspace_record_sets(
    kept_records: list[dict],
    job_history: dict[str, dict],
    applied_job_keys: set[str],
    hidden_job_keys: set[str],
    reference_time: datetime,
    scoring_profile: Optional[dict] = None,
    workspace_min_score: Optional[int] = None,
) -> dict[str, list[dict]]:

    profile = scoring_profile or load_profile()

    is_workspace_eligible_fn = is_workspace_eligible

    if workspace_min_score is not None:
        active_workspace_min_score = int(workspace_min_score)

        def is_workspace_eligible_fn(
            record: dict,
            current_profile: Optional[dict] = None,
        ) -> bool:
            return is_workspace_eligible(
                record,
                current_profile,
                active_workspace_min_score,
            )

    return workspace_data.build_workspace_record_sets(
        kept_records,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
        profile=profile,
        is_workspace_eligible_fn=is_workspace_eligible_fn,
        fit_score_fn=fit_score_displayed,
        viewed_by_user_fn=viewed_by_user,
        normalize_job_key_fn=normalize_job_key,
        parse_timestamp_fn=parse_timestamp,
        build_archive_records_fn=build_archive_records,
        build_applied_records_fn=build_applied_records,
        build_hidden_records_fn=build_hidden_records,
    )


def load_last_kept_records() -> list[dict]:

    return workspace_data.load_last_kept_records(
        load_audit_rows(),
        deduplicate_across_sources_fn=deduplicate_across_sources,
    )


def load_saved_workspace_pool() -> list[dict]:
    import json as _json

    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()

    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM workspace_pool WHERE user_id = ?",
            (user_id,),
        ).fetchone()

    if row is None:
        return []

    data = _json.loads(row["data"])

    return data if isinstance(data, list) else []


def build_run_stats(
    audit_rows: list[dict],
    kept_records: list[dict],
    run_started_at: datetime,
    run_finished_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    seek_max_pages: int,
) -> dict:

    return workspace_data.build_run_stats(
        audit_rows,
        kept_records,
        run_started_at,
        run_finished_at,
        date_range_days,
        sort_newest_first,
        seek_max_pages,
    )


def format_llm_usage_metric(value: int | float, *, currency: bool = False) -> str:
    """Format LLM usage for workspace cards without changing the source value."""
    if currency:
        return f"${float(value):.2f}"

    token_count = int(value)
    if token_count < 1_000:
        return f"{token_count:,}"

    for divisor, suffix in (
        (1_000_000_000, "B"),
        (1_000_000, "M"),
        (1_000, "K"),
    ):
        if token_count < divisor:
            continue
        scaled = token_count / divisor
        decimal_places = 2 if scaled < 10 else 1 if scaled < 100 else 0
        formatted = f"{scaled:.{decimal_places}f}"
        if float(formatted) >= 1_000 and suffix != "B":
            continue
        return f"{formatted.rstrip('0').rstrip('.')}{suffix}"

    return f"{token_count:,}"


def _render_summary_cards_html(card_specs: list[tuple[Any, str]]) -> str:

    return "".join(
        f'<div class="summary-card"><strong>{safe_html(str(value))}</strong><span>{safe_html(label)}</span></div>'
        for value, label in card_specs
    )


def render_html(
    output_path: str | Path,
    kept_records: list[dict],
    run_started_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    run_stats: dict,
    job_history: dict[str, dict],
    applied_job_keys: set[str],
    hidden_job_keys: set[str],
    workspace_reference_at: Optional[datetime] = None,
    debug_mode: bool = WORKSPACE_DEBUG_MODE,
    workspace_records: Optional[dict[str, list[dict]]] = None,
) -> None:

    reference_time = workspace_reference_at or run_started_at

    scoring_profile = load_profile()

    workspace_min_score = get_workspace_minimum_score()

    active_debug_mode = bool(debug_mode)

    kept_records = _enrich_records_with_candidate_application_history(kept_records)

    if workspace_records is None:
        workspace_records = build_workspace_record_sets(
            kept_records,
            job_history,
            applied_job_keys,
            hidden_job_keys,
            reference_time,
            scoring_profile,
            workspace_min_score,
        )

    history_clusters = build_history_cluster_index(job_history)

    shortlist_records = workspace_records["shortlist_records"]

    applied_records = workspace_records["applied_records"]

    hidden_records = workspace_records["hidden_records"]

    potential_records = shortlist_records

    score_filter_options_html = render_score_filter_options(
        scoring_profile,
        workspace_min_score,
        debug_mode=active_debug_mode,
    )

    posted_filter_options_html = render_posted_filter_options(potential_records, reference_time)

    work_type_filter_options_html = render_work_type_filter_options()
    job_board_filter_choices_html = render_job_board_filter_choices()

    shortlist_count = len(shortlist_records)

    workspace_run_id = str(
        run_stats.get("run_started_at")
        or run_stats.get("run_finished_at")
        or run_stats.get("last_run_attempt_at")
        or run_started_at.isoformat(timespec="seconds")
    ).strip() or run_started_at.isoformat(timespec="seconds")

    target_summaries = [
        f"{location}: pages {', '.join(str(page) for page in pages) if pages else 'none'}"
        for location, pages in (run_stats.get("search_targets") or {}).items()
    ]

    testing_mode_notes = []

    if active_debug_mode:
        testing_mode_notes.append(
            "Workspace debug mode is on, showing the full current job set and keeping filtered rows visible for inspection."
        )

    if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        testing_mode_notes.append(
            "Viewed history has been reset, so all roles are shown as unseen."
        )

    testing_mode_note = " " + " ".join(testing_mode_notes) if testing_mode_notes else ""

    search_settings = get_search_settings(scoring_profile)

    search_keywords_label = str(search_settings.get("keywords") or "").strip() or "Not set"

    search_locations = [
        str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()
    ]

    search_locations_label = " | ".join(search_locations) or "Not set"

    work_type_label, work_mode_label, sector_label = _format_common_search_preferences(
        scoring_profile
    )

    salary_min_label = _format_salary_min_label(scoring_profile)

    date_range_label = (
        "Any time"
        if date_range_days <= 0
        else "Last 24 hours"
        if date_range_days == 1
        else f"Last {date_range_days} days"
    )

    view_history_text = (
        "treats all roles as New To You"
        if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING
        else "preserves your viewed history"
    )

    snapshot_helper = (
        "Workspace debug mode keeps filtered rows visible for inspection."
        if active_debug_mode
        else "Shortlist currently keeps roles at "
        f"{score_to_match_label(workspace_min_score, get_match_levels(scoring_profile))} "
        f"or better and {view_history_text}."
    )

    ws_page_labels = load_workspace_page_labels()
    # Read the one shared action label this renderer needs through the low-level
    # UI-label loader. Importing server_helpers here creates a service-layer
    # cycle through source_connector/workspace rebuild paths.
    shared_ui_labels = load_ui_labels().get("shared_ui_labels", {})
    if not isinstance(shared_ui_labels, dict):
        raise ValueError("ui_labels.json is missing shared_ui_labels")
    remove_item_label = str(shared_ui_labels.get("remove_item_label") or "").strip()
    if not remove_item_label:
        raise ValueError("ui_labels.json is missing shared_ui_labels.remove_item_label")

    # Read the review-action button labels through the low-level UI-label loader
    # so results-page.js can rebuild a job card's action buttons after an
    # applied/hidden toggle without depending on another card already present
    # in the destination tab to clone markup from.
    workspace_card_labels = load_ui_labels().get("workspace_card_labels", {})
    if not isinstance(workspace_card_labels, dict):
        raise ValueError("ui_labels.json is missing workspace_card_labels")

    def _card_label(key: str) -> str:
        value = str(workspace_card_labels.get(key) or "").strip()
        if not value:
            raise ValueError(f"ui_labels.json is missing workspace_card_labels.{key}")
        return value

    last_run_cards_html = _render_summary_cards_html(
        [
            (
                run_stats.get("cards_seen", 0),
                ws_page_labels["LABEL_WS_LAST_RUN_CARDS_SEEN_LABEL"],
            ),
            (
                run_stats.get("detail_fetches", 0),
                ws_page_labels["LABEL_WS_LAST_RUN_DETAILS_CHECKED_LABEL"],
            ),
            (
                run_stats.get("kept_count", 0),
                ws_page_labels["LABEL_WS_LAST_RUN_ACCEPTED_LABEL"],
            ),
            (
                run_stats.get("rejected_count", 0),
                ws_page_labels["LABEL_WS_LAST_RUN_REJECTED_LABEL"],
            ),
            (
                format_llm_usage_metric(
                    float(run_stats.get("llm_total_cost_usd", 0.0) or 0.0), currency=True
                ),
                ws_page_labels["LABEL_WS_LAST_RUN_LLM_COST_LABEL"],
            ),
            (
                format_llm_usage_metric(int(run_stats.get("llm_total_input_tokens", 0) or 0)),
                ws_page_labels["LABEL_WS_LAST_RUN_INPUT_TOKENS_LABEL"],
            ),
            (
                format_llm_usage_metric(int(run_stats.get("llm_total_output_tokens", 0) or 0)),
                ws_page_labels["LABEL_WS_LAST_RUN_OUTPUT_TOKENS_LABEL"],
            ),
        ]
    )

    lifetime_llm_usage = get_cost_summary()
    lifetime_cards_html = _render_summary_cards_html(
        [
            (
                format_llm_usage_metric(
                    float(lifetime_llm_usage.get("grand_total_usd", 0.0) or 0.0), currency=True
                ),
                ws_page_labels["LABEL_WS_LIFETIME_LLM_COST_LABEL"],
            ),
            (
                format_llm_usage_metric(int(lifetime_llm_usage.get("grand_input_tokens", 0) or 0)),
                ws_page_labels["LABEL_WS_LIFETIME_INPUT_TOKENS_LABEL"],
            ),
            (
                format_llm_usage_metric(int(lifetime_llm_usage.get("grand_output_tokens", 0) or 0)),
                ws_page_labels["LABEL_WS_LIFETIME_OUTPUT_TOKENS_LABEL"],
            ),
        ]
    )

    workspace_config_labels = {
        "rejectionLoadingSuggestions": ws_page_labels.get("rejection_loading_suggestions"),
        "removeItemLabel": remove_item_label,
        "profileGapAddedNewTemplate": ws_page_labels[
            "LABEL_WS_PROFILE_GAP_ADDED_NEW_TEMPLATE"
        ],
        "profileGapAddedExistingTemplate": ws_page_labels[
            "LABEL_WS_PROFILE_GAP_ADDED_EXISTING_TEMPLATE"
        ],
        "profileGapAlreadyPresentTemplate": ws_page_labels[
            "LABEL_WS_PROFILE_GAP_ALREADY_PRESENT_TEMPLATE"
        ],
        "profileGapNotHaveSavedTemplate": ws_page_labels[
            "LABEL_WS_PROFILE_GAP_NOT_HAVE_SAVED_TEMPLATE"
        ],
        "profileGapErrorLabel": ws_page_labels["LABEL_WS_PROFILE_GAP_ERROR_LABEL"],
        "actionUndoAppliedLabel": _card_label("action_undo_applied_label"),
        "actionUnhideLabel": _card_label("action_unhide_label"),
        "appliedBadgeLabel": _card_label("applied_badge"),
        "actionNotForMeLabel": _card_label("action_not_for_me_label"),
        "actionNotForMeTooltip": _card_label("action_not_for_me_tooltip"),
        "actionHideLabel": _card_label("action_hide_label"),
        "actionHideTooltip": _card_label("action_hide_tooltip"),
    }

    top_reject_reasons_html = "".join(
        f'<span class="chip" title="{safe_html(str(item.get("reason", "UNKNOWN")))}"><strong>{safe_html(humanize_reject_reason(str(item.get("reason", "UNKNOWN"))))}:</strong> {safe_html(str(item.get("count", 0)))}</span>'
        for item in run_stats.get("top_reject_reasons", [])
    )
    run_efficiency_panel_html = ""
    if active_debug_mode:
        run_efficiency_panel_html = (
            '<details class="side-panel">'
            "<summary>"
            f"<span>{safe_html(ws_page_labels['LABEL_WS_RUN_EFFICIENCY_SUMMARY'])}</span>"
            f'<span class="side-toggle-hint">{safe_html(ws_page_labels["LABEL_WS_SHOW_HIDE_HINT"])}</span>'
            "</summary>"
            '<div class="side-panel-body">'
            f'<p class="side-panel-copy">{safe_html(ws_page_labels["LABEL_WS_RUN_EFFICIENCY_INTRO"])}'
            f'{safe_html(" | ".join(target_summaries) or "None")}'
            f'{safe_html(ws_page_labels["LABEL_WS_RUN_EFFICIENCY_SEPARATOR"])}'
            f"{safe_html(snapshot_helper)}"
            f"{safe_html(testing_mode_note)}</p>"
            f'<div class="job-meta">{top_reject_reasons_html}</div>'
            "</div>"
            "</details>"
        )

    scope_saved_option_html = (
        f'<option value="saved">{safe_html(ARCHIVE_LABEL)}</option>' if active_debug_mode else ""
    )
    current_tabs_html = render_workspace_tabs_html(
        shortlist_count,
        len(applied_records),
        len(hidden_records),
        active_target="potential",
    )
    applied_tabs_html = render_workspace_tabs_html(
        shortlist_count,
        len(applied_records),
        len(hidden_records),
        active_target="applied",
    )
    hidden_tabs_html = render_workspace_tabs_html(
        shortlist_count,
        len(applied_records),
        len(hidden_records),
        active_target="hidden",
    )

    html = render_results_fragment(
        {
            "SHORTLIST_COUNT": str(shortlist_count),
            "APPLIED_COUNT": str(len(applied_records)),
            "HIDDEN_COUNT": str(len(hidden_records)),
            "POSTED_FILTER_OPTIONS_HTML": posted_filter_options_html,
            "SCORE_FILTER_OPTIONS_HTML": score_filter_options_html,
            "WORK_TYPE_FILTER_OPTIONS_HTML": work_type_filter_options_html,
            "JOB_BOARD_FILTER_CHOICES_HTML": job_board_filter_choices_html,
            "CURRENT_SECTION_HTML": render_section(
                "Job Results",
                shortlist_records,
                ws_page_labels["LABEL_WS_POTENTIAL_JOBS_EMPTY_STATE"],
                scoring_profile,
                applied_pool=applied_records,
                history_clusters=history_clusters,
                debug_mode=active_debug_mode,
                header_tools_html=render_page_size_select_html(),
                header_nav_html=current_tabs_html,
            ),
            "RECENT_SECTION_HTML": "",
            "ARCHIVE_LABEL": safe_html(ARCHIVE_LABEL),
            "APPLIED_SECTION_HTML": render_section(
                "Applied Jobs",
                applied_records,
                "No applied jobs saved yet.",
                scoring_profile,
                history_clusters=history_clusters,
                debug_mode=active_debug_mode,
                header_nav_html=applied_tabs_html,
            ),
            "HIDDEN_SECTION_HTML": render_section(
                "Hidden Jobs",
                hidden_records,
                "No hidden jobs right now.",
                scoring_profile,
                history_clusters=history_clusters,
                debug_mode=active_debug_mode,
                header_nav_html=hidden_tabs_html,
            ),
            "SEARCH_KEYWORDS_LABEL": safe_html(search_keywords_label),
            "SEARCH_LOCATIONS_LABEL": safe_html(search_locations_label),
            "WORK_TYPE_LABEL": safe_html(work_type_label),
            "WORK_MODE_LABEL": safe_html(work_mode_label),
            "SECTOR_PREFERENCE_LABEL": safe_html(sector_label),
            "SALARY_MIN_LABEL": safe_html(salary_min_label),
            "DATE_RANGE_LABEL": safe_html(date_range_label),
            "SCOPE_SAVED_OPTION_HTML": scope_saved_option_html,
            "LAST_RUN_CARDS_HTML": last_run_cards_html,
            "LIFETIME_LLM_CARDS_HTML": lifetime_cards_html,
            "TARGET_SUMMARIES": safe_html(" | ".join(target_summaries) or "None"),
            "SNAPSHOT_HELPER": safe_html(snapshot_helper),
            "TESTING_MODE_NOTE": safe_html(testing_mode_note),
            "TOP_REJECT_REASONS_HTML": top_reject_reasons_html,
            "RUN_EFFICIENCY_PANEL_HTML": run_efficiency_panel_html,
            "WORKSPACE_RUN_ID_JSON": json.dumps(workspace_run_id),
            "DEFAULT_SCORE_FILTER_MIN_JSON": json.dumps(
                "all" if active_debug_mode else str(workspace_min_score)
            ),
            "VIEWED_BADGE_HTML_JSON": json.dumps(viewed_badge_html()),
            "WORKSPACE_LABELS_JSON": json.dumps(workspace_config_labels),
            # This file is also saved to disk and can be opened directly (file://),
            # outside the authenticated /workspace page -- see the static-export
            # guard in results-page.js. This URL is where that guard sends the user.
            "LIVE_WORKSPACE_URL_JSON": json.dumps(f"{JOB_HUNTER_BASE_URL}/workspace"),
        }
    )

    output_file = Path(output_path)

    if not output_file.is_absolute():
        output_file = REPO_ROOT / output_file

    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_file.write_text(html, encoding="utf-8")
