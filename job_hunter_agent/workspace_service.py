"""Helpers for workspace service."""



from __future__ import annotations



import json

import logging

from datetime import datetime

from pathlib import Path

from typing import Any, Optional



logger = logging.getLogger(__name__)



from job_hunter_agent import workspace_data

from job_hunter_agent.user_settings import get_workspace_minimum_score

from job_hunter_agent.global_settings import get_archive_stale_after_days, get_hidden_review_days

from job_hunter_agent.workspace_renderer import (

    ARCHIVE_LABEL,

    _workspace_ui_labels,

    humanize_reject_reason,

    render_match_level_guide_html,

    render_page_size_select_html,

    render_posted_filter_options, 

    render_results_fragment,

    render_score_filter_options,

    render_section,

    render_work_type_filter_options,

)

from job_hunter_agent.filters import passes_title_filters

from job_hunter_agent.fit_scoring import fit_score, fit_score_displayed

from job_hunter_agent.history import (

    TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING,

    build_history_cluster_index,

    viewed_by_user,

)

from job_hunter_agent.io_utils import load_audit_rows

from job_hunter_agent.job_identity import deduplicate_across_sources, normalize_job_key

from job_hunter_agent.match_labels import score_to_match_label

from job_hunter_agent.paths import REPO_ROOT

from job_hunter_agent.posting_utils import days_since, parse_timestamp

from job_hunter_agent.profile_store import (

    ENGAGEMENT_TYPE_OPTIONS,

    GovPref,

    KEY_PREFER_SECTOR,

    SECTOR_PREFERENCE_OPTIONS,

    KEY_ENGAGEMENT_TYPE,

    KEY_WORK_MODE_PREFERENCE,

    normalize_engagement_type_preferences,

    normalize_sector_preference_values,

    WORK_MODE_PREFERENCE_NONE_LABEL,

    WORK_MODE_PREFERENCE_OPTIONS,

    get_match_levels,

    get_search_settings,

    load_profile,

    normalize_work_mode_preferences,

)

from job_hunter_agent.score_labels import viewed_badge_html

from job_hunter_agent.config import DEBUG_MODE

from job_hunter_agent.utils import safe_html





WORKSPACE_DEBUG_MODE = DEBUG_MODE





def _label_from_options(options: tuple[dict[str, Any], ...], value: object, default: str) -> str:

    normalized = str(value or "").strip().lower()

    for item in options:

        if str(item.get("value") or "").strip().lower() == normalized:

            return str(item.get("label") or default).strip() or default

    return default





def _format_common_search_preferences(profile: dict[str, Any]) -> tuple[str, str, str]:

    match_preferences = dict(profile.get("match_preferences") or {})

    selected_work_types = normalize_engagement_type_preferences(match_preferences.get(KEY_ENGAGEMENT_TYPE))

    work_type_lookup = {str(item["value"]).strip().lower(): str(item["label"]).strip() for item in ENGAGEMENT_TYPE_OPTIONS}

    work_type_label = " | ".join(

        work_type_lookup.get(value, value.title())

        for value in selected_work_types

        if value in work_type_lookup

    )

    selected_work_modes = normalize_work_mode_preferences(match_preferences.get(KEY_WORK_MODE_PREFERENCE))

    work_mode_lookup = {str(item["value"]).strip().lower(): str(item["label"]).strip() for item in WORK_MODE_PREFERENCE_OPTIONS}

    work_mode_label = " | ".join(

        work_mode_lookup.get(value, value.title())

        for value in selected_work_modes

        if value in work_mode_lookup

    ) or WORK_MODE_PREFERENCE_NONE_LABEL

    sector_lookup = {str(item["value"]).strip().lower(): str(item["label"]).strip() for item in SECTOR_PREFERENCE_OPTIONS}

    selected_sector_prefs = normalize_sector_preference_values(match_preferences.get(KEY_PREFER_SECTOR))

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

    ok_title, _ = passes_title_filters(str(record.get("title") or ""))

    if not ok_title:

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

            load_candidate_job_rejection_history,

            enrich_records_with_application_history,

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

        print(f"[candidate_application_history] unavailable: {exc}")

        enriched_records = records

    print(f"[candidate_application_history] records enriched: {enriched_count}")

    return enriched_records





def build_history_workspace_record(job_key: str, entry: dict, run_started_at: datetime) -> Optional[dict]:

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

    debug_mode: bool = WORKSPACE_DEBUG_MODE,

    audit_rows: Optional[list[dict]] = None,

) -> dict[str, list[dict]]:

    profile = scoring_profile or load_profile()

    is_workspace_eligible_fn = is_workspace_eligible

    if debug_mode:

        is_workspace_eligible_fn = lambda record, current_profile=None, workspace_min_score=None: True

    elif workspace_min_score is not None:

        active_workspace_min_score = int(workspace_min_score)

        is_workspace_eligible_fn = (

            lambda record, current_profile=None: is_workspace_eligible(

                record,

                current_profile,

                active_workspace_min_score,

            )

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

        debug_mode=debug_mode,

        audit_rows=audit_rows,

    )





def load_last_kept_records() -> list[dict]:

    return workspace_data.load_last_kept_records(

        load_audit_rows(),

        deduplicate_across_sources_fn=deduplicate_across_sources,

    )





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

    audit_rows: Optional[list[dict]] = None,

    debug_mode: bool = WORKSPACE_DEBUG_MODE,

) -> None:

    reference_time = workspace_reference_at or run_started_at

    scoring_profile = load_profile()

    workspace_min_score = get_workspace_minimum_score()

    active_debug_mode = bool(debug_mode)

    active_audit_rows = audit_rows

    if active_debug_mode and active_audit_rows is None:

        active_audit_rows = load_audit_rows()



    kept_records = _enrich_records_with_candidate_application_history(kept_records)



    workspace_records = build_workspace_record_sets(

        kept_records,

        job_history,

        applied_job_keys,

        hidden_job_keys,

        reference_time,

        scoring_profile,

        workspace_min_score,

        debug_mode=active_debug_mode,

        audit_rows=active_audit_rows,

    )

    history_clusters = build_history_cluster_index(job_history)

    shortlist_records = workspace_records["shortlist_records"]

    recent_archive_records = workspace_records["recent_archive_records"]

    stale_archive_records = workspace_records["stale_archive_records"]

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

        testing_mode_notes.append("Viewed history has been reset, so all roles are shown as unseen.")



    testing_mode_note = " " + " ".join(testing_mode_notes) if testing_mode_notes else ""

    search_settings = get_search_settings(scoring_profile)

    search_keywords_label = str(search_settings.get("keywords") or "").strip() or "Not set"

    search_locations = [str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()]

    search_locations_label = " | ".join(search_locations) or "Not set"

    work_type_label, work_mode_label, sector_label = _format_common_search_preferences(scoring_profile)

    salary_min_label = _format_salary_min_label(scoring_profile)

    date_range_label = (

        "Any time" if date_range_days <= 0

        else "Last 24 hours" if date_range_days == 1

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

    this_run_cards_html = _render_summary_cards_html([

        (len(shortlist_records), "Matches"),

        (sum(1 for record in shortlist_records if not viewed_by_user(record)), "New to you"),

        (sum(1 for record in shortlist_records if viewed_by_user(record)), "Opened by you"),

        (len(recent_archive_records), ARCHIVE_LABEL),

    ])

    crawler_cards_html = _render_summary_cards_html([

        (run_stats.get("cards_seen", 0), "Cards seen"),

        (run_stats.get("detail_fetches", 0), "Ads reviewed"),

        (f"{round(float(run_stats.get('keep_rate', 0.0)) * 100, 1)}%", "Keep rate"),

    ])

    application_cards_html = _render_summary_cards_html([

        (len(applied_records), "Applied"),

        (len(hidden_records), "Hidden"),

    ])



    ws_page_labels = _workspace_ui_labels().get("workspace_page_labels", {})

    workspace_config_labels = {

        "rejectionLoadingSuggestions": ws_page_labels.get("rejection_loading_suggestions")

    }



    top_reject_reasons_html = "".join(

        f'<span class="chip" title="{safe_html(str(item.get("reason", "UNKNOWN")))}"><strong>{safe_html(humanize_reject_reason(str(item.get("reason", "UNKNOWN"))))}:</strong> {safe_html(str(item.get("count", 0)))}</span>'

        for item in run_stats.get("top_reject_reasons", [])

    ) 

    scope_saved_option_html = '<option value="saved">Saved Earlier Searches</option>' if active_debug_mode else ""

    html = render_results_fragment(

        {

            "SHORTLIST_COUNT": str(shortlist_count),

            "APPLIED_COUNT": str(len(applied_records)),

            "HIDDEN_COUNT": str(len(hidden_records)),

            "POSTED_FILTER_OPTIONS_HTML": posted_filter_options_html,

            "SCORE_FILTER_OPTIONS_HTML": score_filter_options_html,

            "WORK_TYPE_FILTER_OPTIONS_HTML": work_type_filter_options_html,

            "CURRENT_SECTION_HTML": render_section(

                "Job Results",

                shortlist_records,

                "No shortlist matches are available right now.",

                scoring_profile,

                applied_pool=applied_records,

                history_clusters=history_clusters,

                debug_mode=active_debug_mode,

                header_tools_html=render_page_size_select_html(),

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

            ),

            "HIDDEN_SECTION_HTML": render_section(

                "Hidden Jobs",

                hidden_records,

                "No hidden jobs right now.",

                scoring_profile,

                history_clusters=history_clusters,

                debug_mode=active_debug_mode,

            ),

            "SEARCH_KEYWORDS_LABEL": safe_html(search_keywords_label),

            "SEARCH_LOCATIONS_LABEL": safe_html(search_locations_label),

            "WORK_TYPE_LABEL": safe_html(work_type_label),

            "WORK_MODE_LABEL": safe_html(work_mode_label),

            "SECTOR_PREFERENCE_LABEL": safe_html(sector_label),

            "SALARY_MIN_LABEL": safe_html(salary_min_label),

            "DATE_RANGE_LABEL": safe_html(date_range_label),

            "SCOPE_SAVED_OPTION_HTML": scope_saved_option_html,

            "THIS_RUN_CARDS_HTML": this_run_cards_html,

            "CRAWLER_CARDS_HTML": crawler_cards_html,

            "APPLICATION_CARDS_HTML": application_cards_html,

            "TARGET_SUMMARIES": safe_html(" | ".join(target_summaries) or "None"),

            "SNAPSHOT_HELPER": safe_html(snapshot_helper),

            "TESTING_MODE_NOTE": safe_html(testing_mode_note),

            "TOP_REJECT_REASONS_HTML": top_reject_reasons_html,

            "MATCH_LEVEL_GUIDE_HTML": render_match_level_guide_html(scoring_profile),

            "WORKSPACE_RUN_ID_JSON": json.dumps(workspace_run_id),

            "DEFAULT_SCORE_FILTER_MIN_JSON": json.dumps("all" if active_debug_mode else str(workspace_min_score)),

            "VIEWED_BADGE_HTML_JSON": json.dumps(viewed_badge_html()),

            "WORKSPACE_LABELS_JSON": json.dumps(workspace_config_labels),

        }

    )

    output_file = Path(output_path)

    if not output_file.is_absolute():

        output_file = REPO_ROOT / output_file

    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_file.write_text(html, encoding="utf-8")

