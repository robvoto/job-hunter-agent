"""
Main job-source connector and dashboard builder.

Main goals:
- fetch current job listings from all enabled source implementations
- apply deterministic filtering and optional LLM fit review
- persist audit data, run stats, review insights, and dashboard HTML

Notes:
- this file orchestrates individual source connectors (e.g. SEEK, LinkedIn)
- the normalized record shape is intended to be reusable for additional sources
"""

import json
import math
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from job_hunter_agent.capability_matrix import expand_capability_terms
from job_hunter_agent.capability_matrix import canonical_capability_term
from job_hunter_agent.agent_settings import get_dashboard_minimum_score
from job_hunter_agent.config import OUTPUT_HTML
from job_hunter_agent import dashboard_data
from job_hunter_agent.filters import (
    analyze_title_filters,
    passes_content_filters,
    passes_quick_card_filters,
    passes_saved_rejection_rules,
    passes_title_filters,
    suggest_title_block_phrase,
    suggest_title_block_phrases,
)
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches, generalize_hard_block_pattern
from job_hunter_agent.job_identity import (
    deduplicate_across_sources,
    find_similar_job,
)
from job_hunter_agent.llm_gate import (
    build_llm_cache_key,
    llm_is_enabled,
    llm_should_consider_learning_candidates,
    llm_should_consider_with_learning,
    normalize_llm_review_payload,
)
from job_hunter_agent.match_labels import score_to_match_level, score_to_match_label
from job_hunter_agent.profile_store import (
    get_match_levels,
    get_candidate_profile_tier_weights,
    get_candidate_profile_tiers,
    get_preference_weights,
    get_scoring_rules,
    get_search_settings,
    load_profile,
)
from job_hunter_agent.review_insights import build_review_data
from job_hunter_agent.signal_registry import (
    filter_registerable_signals,
    load_approved_signal_catalog,
    load_registry,
    register_signals,
    signal_in_approved_knowledge,
)
from job_hunter_agent.scrapers.seek import (
    SELECTOR_CARDS,
    SELECTOR_COMPANY,
    SELECTOR_POSTED,
    SELECTOR_TITLE,
    build_seek_search_targets,
    extract_card_metadata,
    extract_posted_text_from_card,
    fetch_job_details_payload,
    stable_job_key,
    build_full_seek_url,
)
from job_hunter_agent.paths import (
    AUDIT_RECORDS_PATH as DEBUG_JSON_PATH,
    DATA_DIR,
    GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    GOVERNMENT_CONTEXT_RULES_PATH,
    JOB_HISTORY_PATH,
    LLM_CACHE_PATH,
    OUTPUT_DIR,
    REPO_ROOT as ROOT_DIR,
    RESULTS_TEMPLATE_PATH,
    REVIEW_DATA_PATH,
    RUN_STATS_PATH,
    TEMPLATES_DIR,
)
from job_hunter_agent.utils import (
    extract_salary,
    extract_work_mode,
    parse_seek_posted_age_days,
    safe_html,
    set_page_param,
)
from job_hunter_agent.salary_utils import (
    salary_sort_value,
    _salary_max_value,
    _salary_includes_super_or_package,
)
from job_hunter_agent.io_utils import (
    normalize_posted_text,
    configure_console_output,
    load_json_dict,
    load_json_list,
    save_json,
    load_llm_cache,
    save_llm_cache,
    load_job_history,
    save_job_history,
    write_debug_json,
    write_run_stats,
    write_run_attempt,
    write_review_data,
)
from job_hunter_agent.text_processing import (
    dedupe_preserve_order,
    compact_whitespace,
    split_text_snippets,
    list_to_phrase,
    summarize_snippet,
    synthesize_role_snapshot,
    description_summary_snippet,
    build_role_summary,
)
from job_hunter_agent.role_analysis import (
    friendly_capability_label,
    role_text_bundle,
    text_contains_term,
    has_government_context,
    infer_role_sector,
    infer_posting_channel,
)
from job_hunter_agent.scoring_utils import (
    weighted_points,
    build_scoring_source_text,
    extract_contract_months,
    find_profile_experience_year_in_text,
    find_profile_experience_year,
    profile_recency_multiplier,
)
from job_hunter_agent.description_trust import (
    MIN_TRUSTED_DESCRIPTION_LENGTH,
    get_trusted_sources,
    get_trusted_full_description,
    full_description_confidence,
    is_description_trusted,
)
from job_hunter_agent.capability_matching import (
    reviewed_signal_matches_for_text,
    reviewed_signal_match_summary,
    find_profile_capability_matches,
    description_watchout_reasons,
    is_capability_fit_highlight,
    capability_fit_highlights,
    build_risk_and_missing_evidence,
    _normalized_aliases,
    evidence_tier_alignment_score,
)
from job_hunter_agent.signal_detection import (
    build_job_learning_signals,
    detect_competitive_signals,
    evaluate_competitive_signal_alignment,
    competitive_signal_assessments,
    competitive_fit_highlights,
    extract_skill_observations,
    hard_block_entries,
    hard_block_reasons,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_HARD_BLOCKER_PATTERN,
    CATEGORY_ROLE_TITLE_TOKEN,
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE,
    COMPETITIVE_SIGNALS_KEY,
    HARD_BLOCK_REASONS_KEY,
    LEARNING_CATEGORY_KEY,
    LEARNING_SIGNAL_KEY,
    RECORD_COMPANY_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_SEARCH_LOCATION_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
    TITLE_REASON_KEY,
    TITLE_REASON_POTENTIAL_MATCH,
)
from job_hunter_agent.preferences import (
    get_match_preferences,
    assess_location_preference,
    assess_contract_preference,
    assess_government_preference,
    salary_fit_adjustment,
)
from job_hunter_agent.score_labels import (
    salary_fit_label,
    score_to_tone_class,
    compact_score_label,
    format_score_breakdown_for_console,
    render_badge,
    viewed_badge_html,
)
from job_hunter_agent.posting_utils import (
    parse_timestamp,
    days_since,
    normalize_job_key,
    get_manual_skip_sets,
    format_timestamp_label,
    posted_datetime_from_age,
    format_posted_date_label,
    relative_posted_age_label,
    posted_reference_time,
    is_relative_posted_text,
    posted_display_label,
    current_posted_age_days,
)


from job_hunter_agent.fit_scoring import (
    build_fit_highlights,
    capability_evidence_score,
    capability_match_summary,
    capability_scored_matches,
    competitive_signal_breakdown,
    convergence_bonus_entry,
    fit_score,
    fit_score_breakdown,
    llm_description_fit_entry,
)
from job_hunter_agent.history import (
    ARCHIVE_STALE_AFTER_DAYS,
    HIDDEN_REVIEW_DAYS,
    KEEP_SNAPSHOT_FIELDS,
    TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING,
    apply_kept_job_reuse,
    assess_history_warning_signals,
    build_history_cluster_index,
    build_history_sighting,
    build_keep_snapshot,
    can_reuse_kept_job,
    finalize_record,
    history_cluster_key,
    history_cluster_key_from_parts,
    update_job_history,
    viewed_by_user,
)

MAX_LLM_CHARS = 3000
CLI_FLAGS = set(sys.argv[1:])
NO_LLM_MODE = "--no-llm" in CLI_FLAGS
CHEAP_LLM_MODE = "--cheap-llm" in CLI_FLAGS
DASHBOARD_DEBUG_MODE = "--debug-mode" in CLI_FLAGS

from job_hunter_agent.dashboard_renderer import (  # noqa: E402 — after CLI_FLAGS
    ARCHIVE_BADGE_TOOLTIP,
    ARCHIVE_CONTEXT_PREFIX,
    ARCHIVE_LABEL,
    DESCRIPTION_CAPTURE_ISSUE,
    humanize_reject_reason,
    negative_score_reasons,
    posted_filter_option_label,
    render_job_card,
    render_posted_filter_options,
    render_score_filter_options,
    render_section,
    score_filter_option_label,
    score_filter_thresholds,
    score_gap_reasons,
    section_dom_id,
    visible_fit_reasons,
    _render_match_level_guide_html,
    _render_results_fragment,
)


def deterministic_review_outcome(record: dict, fit_highlights: List[str], missing_evidence: List[str], soft_risk_reasons: List[str]) -> Optional[dict]:
    title_reason = str(record.get(TITLE_REASON_KEY) or "")
    strong_signal_count = len(capability_fit_highlights(fit_highlights))
    high_risks = len(missing_evidence)
    medium_risks = len(soft_risk_reasons)

    if high_risks >= 2 and strong_signal_count <= 1:
        return {"decision": "REJECT", "grade": "MISMATCH"}
    if title_reason == TITLE_REASON_POTENTIAL_MATCH and high_risks >= 1 and strong_signal_count <= 1:
        return {"decision": "REJECT", "grade": "POOR"}
    if title_reason == "OK" and strong_signal_count >= 4 and high_risks == 0:
        return {"decision": "KEEP", "grade": "STRONG"}
    if title_reason == "OK" and strong_signal_count >= 3 and high_risks == 0 and medium_risks <= 1:
        return {"decision": "KEEP", "grade": "SOLID"}
    return None


def register_hard_blocker_learning_from_rejection(
    record: dict,
    reject_reason: str,
    details_text: str = "",
    hard_block_matches: Optional[List[dict]] = None,
    profile: Optional[dict] = None,
) -> None:
    reason = compact_whitespace(reject_reason)
    if not reason:
        return

    prefix, _, detail = reason.partition(":")
    signals: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_signal(signal: str, original_text: str) -> None:
        cleaned_signal = compact_whitespace(signal)
        if not cleaned_signal:
            return
        signal_key = cleaned_signal.lower()
        if signal_key in seen:
            return
        seen.add(signal_key)
        signals.append(
            {
                "signal": cleaned_signal,
                "suggested_category": CATEGORY_HARD_BLOCKER_PATTERN,
                "original_texts": [compact_whitespace(original_text)] if compact_whitespace(original_text) else [],
            }
        )

    if prefix in {"DESC_HARD_BLOCK_RULE", "DESC_HARD_BLOCK"}:
        profile_terms = (profile or {}).get("must_not_require_skills", [])
        matches = hard_block_matches or find_hard_block_matches(details_text, profile_terms)
        for match in matches:
            term = str(match.get("matched_term") or "").replace("_", " ")
            pattern = generalize_hard_block_pattern(details_text, term) or str(match.get("value") or "").strip()
            add_signal(pattern, str(match.get("context") or details_text or reason))
    elif prefix == "LEARNED_REJECT" and detail:
        token = detail.split(":")[-1].strip()
        if token:
            pattern = generalize_hard_block_pattern(details_text, token.replace("_", " "))
            if pattern:
                add_signal(pattern, token.replace("_", " "))

    if signals:
        register_signals(signals)


def _has_high_value_ambiguous_learning_candidate(signals: list[dict[str, Any]]) -> bool:
    interesting_categories = {CATEGORY_ROLE_TITLE_TOKEN, CATEGORY_TITLE_NORMALIZATION_CANDIDATE}
    for signal in signals or []:
        if not isinstance(signal, dict):
            continue
        category = compact_whitespace(signal.get("suggested_category") or signal.get(LEARNING_CATEGORY_KEY) or "").lower()
        if category in interesting_categories:
            return True
    return False


def _merge_pending_learning_signals(*signal_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in signal_groups:
        for signal in group or []:
            if not isinstance(signal, dict):
                continue
            key = compact_whitespace(signal.get(LEARNING_SIGNAL_KEY) or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            combined.append(signal)
    return combined


def _register_pending_learning_signals(signals: list[dict[str, Any]]) -> None:
    filtered = filter_registerable_signals(signals)
    if filtered:
        register_signals(filtered)


def _resolve_llm_review_payload(
    record: dict,
    llm_cache: dict,
    *,
    learning_only: bool = False,
) -> dict[str, Any]:
    llm_input_text = record.get(RECORD_FULL_DESCRIPTION_KEY) or record.get(RECORD_FIT_SOURCE_TEXT_KEY) or ""
    llm_fp = build_llm_cache_key(llm_input_text[:MAX_LLM_CHARS])
    cached = normalize_llm_review_payload(llm_cache.get(llm_fp)) if llm_fp in llm_cache else None

    if cached:
        if learning_only and cached.get("learning_candidates"):
            return {**cached, "payload_source": "cache"}
        if not learning_only and cached.get("fit_review"):
            return {**cached, "payload_source": "cache"}

    if not llm_is_enabled():
        raise RuntimeError("LLM review requested but OPENAI_API_KEY is missing")

    if learning_only:
        payload = {"fit_review": None, "learning_candidates": llm_should_consider_learning_candidates(llm_input_text[:MAX_LLM_CHARS])}
    else:
        payload = llm_should_consider_with_learning(llm_input_text[:MAX_LLM_CHARS])

    if cached:
        merged = dict(cached)
        if payload.get("fit_review"):
            merged["fit_review"] = payload["fit_review"]
        merged["learning_candidates"] = _merge_pending_learning_signals(
            cached.get("learning_candidates") or [],
            payload.get("learning_candidates") or [],
        )
        if payload.get("learning_only"):
            merged["learning_only"] = True
        llm_cache[llm_fp] = merged
        return {**merged, "payload_source": "llm"}

    llm_cache[llm_fp] = payload
    return {**payload, "payload_source": "llm"}


def is_dashboard_eligible(
    record: dict,
    profile: Optional[dict] = None,
    dashboard_min_score: Optional[int] = None,
) -> bool:
    ok_title, _ = passes_title_filters(str(record.get("title") or ""))
    if not ok_title:
        return False
    active_dashboard_min_score = (
        int(dashboard_min_score)
        if dashboard_min_score is not None
        else get_dashboard_minimum_score()
    )
    return fit_score(record, profile) >= active_dashboard_min_score


def build_history_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> Optional[dict]:
    return dashboard_data.build_history_dashboard_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
        archive_stale_after_days=ARCHIVE_STALE_AFTER_DAYS,
    )


def build_archive_records(
    history: Dict[str, dict],
    current_run_keys: Set[str],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    run_started_at: datetime,
) -> List[dict]:
    return dashboard_data.build_archive_records(
        history,
        current_run_keys,
        applied_job_keys,
        hidden_job_keys,
        run_started_at,
        normalize_job_key_fn=normalize_job_key,
        parse_timestamp_fn=parse_timestamp,
        build_history_dashboard_record_fn=build_history_dashboard_record,
    )


def build_hidden_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:
    return dashboard_data.build_hidden_dashboard_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
    )


def build_hidden_records(
    hidden_job_keys: Set[str],
    history: Dict[str, dict],
    run_started_at: datetime,
) -> List[dict]:
    return dashboard_data.build_hidden_records(
        hidden_job_keys,
        history,
        run_started_at,
        parse_timestamp_fn=parse_timestamp,
        days_since_fn=days_since,
        hidden_review_days=HIDDEN_REVIEW_DAYS,
        build_hidden_dashboard_record_fn=build_hidden_dashboard_record,
    )


def build_applied_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:
    return dashboard_data.build_applied_dashboard_record(
        job_key,
        entry,
        run_started_at,
        days_since_fn=days_since,
    )


def build_applied_records(
    applied_job_keys: Set[str],
    history: Dict[str, dict],
    run_started_at: datetime,
) -> List[dict]:
    return dashboard_data.build_applied_records(
        applied_job_keys,
        history,
        run_started_at,
        parse_timestamp_fn=parse_timestamp,
        build_applied_dashboard_record_fn=build_applied_dashboard_record,
    )


def build_dashboard_record_sets(
    kept_records: List[dict],
    job_history: Dict[str, dict],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    reference_time: datetime,
    scoring_profile: Optional[dict] = None,
    dashboard_min_score: Optional[int] = None,
) -> Dict[str, List[dict]]:
    profile = scoring_profile or load_profile()
    is_dashboard_eligible_fn = is_dashboard_eligible
    if dashboard_min_score is not None:
        active_dashboard_min_score = int(dashboard_min_score)
        is_dashboard_eligible_fn = (
            lambda record, current_profile=None: is_dashboard_eligible(
                record,
                current_profile,
                active_dashboard_min_score,
            )
        )
    return dashboard_data.build_dashboard_record_sets(
        kept_records,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
        profile=profile,
        is_dashboard_eligible_fn=is_dashboard_eligible_fn,
        fit_score_fn=fit_score,
        viewed_by_user_fn=viewed_by_user,
        normalize_job_key_fn=normalize_job_key,
        parse_timestamp_fn=parse_timestamp,
        build_archive_records_fn=build_archive_records,
        build_applied_records_fn=build_applied_records,
        build_hidden_records_fn=build_hidden_records,
    )


def load_last_kept_records() -> List[dict]:
    return dashboard_data.load_last_kept_records(
        load_json_list(DEBUG_JSON_PATH),
        deduplicate_across_sources_fn=deduplicate_across_sources,
    )


def build_run_stats(
    audit_rows: List[dict],
    kept_records: List[dict],
    run_started_at: datetime,
    run_finished_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    seek_max_pages: int,
) -> dict:
    return dashboard_data.build_run_stats(
        audit_rows,
        kept_records,
        run_started_at,
        run_finished_at,
        date_range_days,
        sort_newest_first,
        seek_max_pages,
    )


def render_html(
    output_path: str,
    kept_records: List[dict],
    run_started_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    run_stats: dict,
    job_history: Dict[str, dict],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    dashboard_reference_at: Optional[datetime] = None,
) -> None:
    reference_time = dashboard_reference_at or run_started_at
    scoring_profile = load_profile()
    dashboard_min_score = get_dashboard_minimum_score()
    dashboard_records = build_dashboard_record_sets(
        kept_records,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
        scoring_profile,
        dashboard_min_score,
    )
    history_clusters = build_history_cluster_index(job_history)
    shortlist_records = dashboard_records["shortlist_records"]
    current_records = dashboard_records["current_records"]
    recent_archive_records = dashboard_records["recent_archive_records"]
    stale_archive_records = dashboard_records["stale_archive_records"]
    applied_records = dashboard_records["applied_records"]
    hidden_records = dashboard_records["hidden_records"]
    potential_records = shortlist_records
    score_filter_options_html = render_score_filter_options(
        potential_records,
        scoring_profile,
        dashboard_min_score,
    )
    posted_filter_options_html = render_posted_filter_options(potential_records, reference_time)
    shortlist_count = len(shortlist_records)
    dashboard_run_id = str(
        run_stats.get("run_started_at")
        or run_stats.get("run_finished_at")
        or run_stats.get("last_run_attempt_at")
        or run_started_at.isoformat(timespec="seconds")
    ).strip() or run_started_at.isoformat(timespec="seconds")
    target_summaries = []
    for location, pages in (run_stats.get("search_targets") or {}).items():
        page_label = ", ".join(str(page) for page in pages) if pages else "none"
        target_summaries.append(f"{location}: pages {page_label}")
    testing_mode_notes = []
    if DASHBOARD_DEBUG_MODE:
        testing_mode_notes.append(
            "Dashboard debug mode is on, showing scores and keeping roles at "
            f"{score_to_match_label(dashboard_min_score, get_match_levels(scoring_profile))} or better "
            "without a fresh scrape."
        )
    if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        testing_mode_notes.append("Viewed history has been reset, so all roles are shown as unseen.")
        
    testing_mode_note = " " + " ".join(testing_mode_notes) if testing_mode_notes else ""
    search_window_label = f"Last {date_range_days} day" + ("" if date_range_days == 1 else "s")
    sort_order_label = "Newest first" if sort_newest_first else "Source relevance"
    current_search_settings = get_search_settings(scoring_profile)
    search_settings_payload = {
        "keywords": str(current_search_settings.get("keywords") or "").strip(),
        "locations": [str(value).strip() for value in current_search_settings.get("locations", []) if str(value).strip()],
        "date_range_days": int(current_search_settings.get("date_range_days", date_range_days) or date_range_days),
        "seek_max_pages": int(
            current_search_settings.get("seek_max_pages", run_stats.get("seek_max_pages", 10))
            or run_stats.get("seek_max_pages", 10)
        ),
        "linkedin_hours_old": int(current_search_settings.get("linkedin_hours_old", 24) or 24),
        "linkedin_results_per_search": int(current_search_settings.get("linkedin_results_per_search", 25) or 25),
    }
    search_keywords_label = search_settings_payload["keywords"] or "Not set"
    search_locations_label = " | ".join(search_settings_payload["locations"]) or "Not set"
    search_locations_text = "\n".join(search_settings_payload["locations"])
    search_settings_json = json.dumps(search_settings_payload, ensure_ascii=False).replace("</", "<\\/")
    
    li_hours = scoring_profile.get("search_settings", {}).get("linkedin_hours_old", 24)
    li_results = scoring_profile.get("search_settings", {}).get("linkedin_results_per_search", 25)
    
    view_history_text = "treats all roles as New To You" if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else "preserves your viewed history"
    snapshot_helper = (
        "Shortlist currently keeps roles at "
        f"{score_to_match_label(dashboard_min_score, get_match_levels(scoring_profile))} "
        f"or better and {view_history_text}."
    )
    this_run_cards_html = "".join(
        f'<div class="summary-card"><strong>{safe_html(str(value))}</strong><span>{safe_html(label)}</span></div>'
        for value, label in [
            (len(shortlist_records), "Matches"),
            (sum(1 for record in shortlist_records if not viewed_by_user(record)), "New to you"),
            (sum(1 for record in shortlist_records if viewed_by_user(record)), "Opened by you"),
            (len(recent_archive_records), ARCHIVE_LABEL),
        ]
    )
    crawler_cards_html = "".join(
        f'<div class="summary-card"><strong>{safe_html(str(value))}</strong><span>{safe_html(label)}</span></div>'
        for value, label in [
            (run_stats.get("cards_seen", 0), "Cards seen"),
            (run_stats.get("detail_fetches", 0), "Ads reviewed"),
            (run_stats.get("page_count", 0), "Pages crawled"),
            (f"{round(float(run_stats.get('keep_rate', 0.0)) * 100, 1)}%", "Keep rate"),
        ]
    )
    application_cards_html = "".join(
        f'<div class="summary-card"><strong>{safe_html(str(value))}</strong><span>{safe_html(label)}</span></div>'
        for value, label in [
            (len(applied_records), "Applied"),
            (len(hidden_records), "Hidden"),
        ]
    )

    top_reject_reasons_html = "".join(
        f'<span class="chip" title="{safe_html(str(item.get("reason", "UNKNOWN")))}"><strong>{safe_html(humanize_reject_reason(str(item.get("reason", "UNKNOWN"))))}:</strong> {safe_html(str(item.get("count", 0)))}</span>'
        for item in run_stats.get("top_reject_reasons", [])
    )
    html = _render_results_fragment(
        {
            "SHORTLIST_COUNT": str(shortlist_count),
            "APPLIED_COUNT": str(len(applied_records)),
            "HIDDEN_COUNT": str(len(hidden_records)),
            "POSTED_FILTER_OPTIONS_HTML": posted_filter_options_html,
            "SCORE_FILTER_OPTIONS_HTML": score_filter_options_html,
            "CURRENT_SECTION_HTML": render_section(
                "Best Matches",
                shortlist_records,
                "No shortlist matches are available right now.",
                scoring_profile,
                applied_pool=applied_records,
                history_clusters=history_clusters,
            ),
            "RECENT_SECTION_HTML": "",
            "ARCHIVE_LABEL": safe_html(ARCHIVE_LABEL),
            "APPLIED_SECTION_HTML": render_section(
                "Applied Jobs",
                applied_records,
                "No applied jobs saved yet.",
                scoring_profile,
                history_clusters=history_clusters,
            ),
            "HIDDEN_SECTION_HTML": render_section(
                "Hidden Jobs",
                hidden_records,
                "No hidden jobs right now.",
                scoring_profile,
                history_clusters=history_clusters,
            ),
            "SEARCH_KEYWORDS_LABEL": safe_html(search_keywords_label),
            "SEARCH_LOCATIONS_LABEL": safe_html(search_locations_label),
            "SEARCH_DATE_RANGE_DAYS": safe_html(str(search_settings_payload["date_range_days"])),
            "SEARCH_DATE_RANGE_SUFFIX": "s" if int(search_settings_payload["date_range_days"]) != 1 else "",
            "SEARCH_SEEK_MAX_PAGES": safe_html(str(search_settings_payload["seek_max_pages"])),
            "LINKEDIN_HOURS": safe_html(str(li_hours)),
            "LINKEDIN_RESULTS": safe_html(str(li_results)),
            "SEARCH_KEYWORDS_INPUT": safe_html(search_settings_payload["keywords"]),
            "SEARCH_LOCATIONS_TEXT": safe_html(search_locations_text),
            "THIS_RUN_CARDS_HTML": this_run_cards_html,
            "CRAWLER_CARDS_HTML": crawler_cards_html,
            "APPLICATION_CARDS_HTML": application_cards_html,
            "TARGET_SUMMARIES": safe_html(" | ".join(target_summaries) or "None"),
            "SNAPSHOT_HELPER": safe_html(snapshot_helper),
            "TESTING_MODE_NOTE": safe_html(testing_mode_note),
            "TOP_REJECT_REASONS_HTML": top_reject_reasons_html,
            "MATCH_LEVEL_GUIDE_HTML": _render_match_level_guide_html(scoring_profile),
            "DASHBOARD_RUN_ID_JSON": json.dumps(dashboard_run_id),
            "SEARCH_SETTINGS_JSON": search_settings_json,
            "DEFAULT_SCORE_FILTER_MIN_JSON": json.dumps(str(dashboard_min_score)),
            "VIEWED_BADGE_HTML_JSON": json.dumps(viewed_badge_html()),
        }
    )
    output_file = Path(output_path)
    if not output_file.is_absolute():
        output_file = ROOT_DIR / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")


def _extract_seek_card_data(card, search_target: dict, run_iso: str) -> dict:
    """Extracts basic information from a SEEK job card and returns a normalized record."""
    title_el = card.query_selector(SELECTOR_TITLE)
    company_el = card.query_selector(SELECTOR_COMPANY)
    posted_el = card.query_selector(SELECTOR_POSTED)
    card_meta = extract_card_metadata(card)
    card_text = (card.inner_text() or "").strip()

    title = title_el.inner_text().strip() if title_el else ""
    company = company_el.inner_text().strip() if company_el else "N/A"
    posted = posted_el.inner_text().strip() if posted_el else ""
    if not posted:
        posted = extract_posted_text_from_card(card_text)
    posted = normalize_posted_text(posted)
    posted_age_days = parse_seek_posted_age_days(posted)
    
    relative_url = title_el.get_attribute("href") if title_el else None
    full_url = build_full_seek_url(relative_url)

    return {
        "run_started_at": run_iso,
        RECORD_SEARCH_LOCATION_KEY: search_target["location"],
        "search_keywords": search_target["keywords"],
        "search_classifications": ",".join(search_target.get("classification_ids", [])),
        "source": "seek",
        "job_key": stable_job_key(full_url) if full_url else None,
        RECORD_TITLE_KEY: title,
        RECORD_COMPANY_KEY: company,
        "posted": posted,
        "posted_age_days": posted_age_days,
        RECORD_URL_KEY: full_url,
        "location": card_meta["location"],
        "work_mode": card_meta["work_mode"],
        "work_type": card_meta["work_type"],
        "teaser": card_meta["teaser"],
        "card_salary": card_meta["card_salary"],
        "decision": "REJECT",
        "reject_reason": None,
        TITLE_REASON_KEY: None,
        "title_match_metadata": {},
        "content_reason": None,
        "llm_decision": None,
        "llm_fit_grade": None,
        "role_snapshot": "N/A",
        "fit_highlights": [],
        "soft_risk_reasons": [],
        "missing_evidence": [],
        COMPETITIVE_SIGNALS_KEY: [],
        "reviewed_signal_matches": {"matched": [], "evidence_only": [], "ignored": [], "unresolved": []},
        "details_length": 0,
    }


def _process_seek_job_details(
    record: dict, 
    detail_page, 
    profile: dict, 
    title_reason: str
) -> tuple[bool, str]:
    """Fetches full job details and performs initial content filtering and metadata enrichment."""
    details_payload = fetch_job_details_payload(detail_page, record[RECORD_URL_KEY])
    details_text = str(details_payload.get("text") or "")
    details_status = str(details_payload.get("status") or ("ok" if details_text else "empty"))
    
    record["details_status"] = details_status
    record["details_length"] = len(details_text)
    
    if details_status != "ok" or not details_text:
        reject_reason = {
            "challenge_page": "DETAILS_CHALLENGE_PAGE",
            "blocked_page": "DETAILS_BLOCKED_PAGE",
            "navigation_error": "DETAILS_NAVIGATION_ERROR",
            "empty": "NO_DETAILS",
        }.get(details_status, "NO_DETAILS")
        return False, reject_reason

    record[RECORD_FIT_SOURCE_TEXT_KEY] = details_text
    record[RECORD_FULL_DESCRIPTION_KEY] = details_text
    record["description_source"] = details_payload.get("source") or "jobAdDetails"
    source = str(record.get("description_source") or "").strip().lower()
    is_trusted = source in get_trusted_sources() and len(details_text) >= MIN_TRUSTED_DESCRIPTION_LENGTH
    record["fit_confidence"] = "HIGH" if is_trusted else "LOW"

    ok_desc, desc_reason = passes_content_filters(details_text, record["location"], title_reason)
    if not ok_desc:
        if desc_reason.startswith("DESC_HARD_BLOCK_RULE"):
            knowledge_matches = find_hard_block_matches(details_text, profile.get("must_not_require_skills", []))
            record[HARD_BLOCK_REASONS_KEY] = dedupe_preserve_order(
                [
                    compact_whitespace(match.get("value") or match.get("matched_term") or "")
                    for match in knowledge_matches
                ]
            )[:3]
        register_hard_blocker_learning_from_rejection(record, desc_reason, details_text, profile=profile)
        return False, desc_reason

    ok_learned, learned_reason = passes_saved_rejection_rules(details_text)
    if not ok_learned:
        register_hard_blocker_learning_from_rejection(record, learned_reason, details_text, profile=profile)
        return False, learned_reason

    record[COMPETITIVE_SIGNALS_KEY] = [
        evaluate_competitive_signal_alignment(signal, profile)
        for signal in detect_competitive_signals(details_text, profile)
    ]
    record["reviewed_signal_matches"] = reviewed_signal_matches_for_text(details_text)
    
    hard_block_matches = hard_block_entries(record, profile)
    record[HARD_BLOCK_REASONS_KEY] = [entry["text"] for entry in hard_block_matches]
    if record[HARD_BLOCK_REASONS_KEY]:
        term = compact_whitespace(record[HARD_BLOCK_REASONS_KEY][0]).lower()
        reason_code = f"DESC_HARD_BLOCK_RULE:{re.sub(r'[^a-z0-9]+', '_', term).strip('_') or 'hard_block'}"
        register_hard_blocker_learning_from_rejection(record, reason_code, details_text, hard_block_matches, profile=profile)
        return False, reason_code

    record_skill_observations = extract_skill_observations(record, profile)
    record["skill_observations"] = record_skill_observations
    record["ad_learning_signals"] = build_job_learning_signals(record, details_text, profile)

    record["salary"] = extract_salary(details_text) or record.get("card_salary", "N/A")
    detail_work_mode = extract_work_mode(details_text)
    if detail_work_mode != "N/A":
        record["work_mode"] = detail_work_mode

    record["role_snapshot"] = build_role_summary(record, details_text, profile)
    record["fit_highlights"] = build_fit_highlights(record, details_text, profile)
    record["soft_risk_reasons"], record["missing_evidence"] = build_risk_and_missing_evidence(
        details_text, title_reason, profile, competitive_signals=record["competitive_signals"]
    )
    
    return True, "OK"


def _evaluate_job_fit(record: dict, profile: dict, llm_cache: dict) -> dict:
    """Determines the final fit decision based on rules or LLM review."""
    deterministic_review = deterministic_review_outcome(
        record, record["fit_highlights"], record["missing_evidence"], record["soft_risk_reasons"]
    )
    record["llm_learning_candidates"] = []

    if deterministic_review is not None:
        review = deterministic_review
        source = "rule"
        if llm_is_enabled() and _has_high_value_ambiguous_learning_candidate(record.get("ad_learning_signals") or []):
            payload = _resolve_llm_review_payload(
                record,
                llm_cache,
                learning_only=True,
            )
            record["llm_learning_candidates"] = payload.get("learning_candidates") or []
            if record["llm_learning_candidates"]:
                source = "rule+learning"
    else:
        payload = _resolve_llm_review_payload(
            record,
            llm_cache,
        )
        review = payload["fit_review"]
        record["llm_learning_candidates"] = payload.get("learning_candidates") or []
        source = str(payload.get("payload_source") or "llm")

    return {
        "llm_decision": review["decision"],
        "llm_fit_grade": review["grade"],
        "review_source": source,
        "decision": "KEEP" if review["decision"] != "REJECT" else "REJECT",
    }


def _seek_scrape_to_records(
    profile: dict,
    search_targets: List[dict],
    job_history: Dict[str, dict],
    llm_cache: Dict[str, Any],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    run_iso: str,
    configured_date_range: int,
    enforce_posted_age_limit: bool,
    configured_seek_max_pages: int,
    headless: bool,
) -> tuple:
    """Run the SEEK Playwright scraping loop.

    Returns (kept_records, audit_rows, skill_observations).
    Shared state objects (job_history, llm_cache) are mutated in-place.
    """
    audit_rows: List[dict] = []
    kept_records: List[dict] = []
    skill_observations: List[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        list_page = browser.new_page(viewport={"width": 1400, "height": 900})
        detail_page = browser.new_page(viewport={"width": 1400, "height": 900})

        try:
            seen_urls: Set[str] = set()
            for search_target in search_targets:
                base_search_url = search_target["url"]
                search_location = search_target["location"]
                search_keywords = search_target["keywords"]
                classification_ids = ",".join(search_target.get("classification_ids", []))
                current_page_num = 1

                print(f"Location: {search_location}")
                print(f"Keywords: {search_keywords}")
                print(f"classification_ids: {classification_ids}")
                
                while current_page_num <= configured_seek_max_pages:
                    page_url = set_page_param(base_search_url, current_page_num) if current_page_num > 1 else base_search_url

                    print(f"\n=== {search_location} | Page {current_page_num} ===")
                    print("URL:", page_url)

                    try:
                        list_page.goto(page_url, wait_until="domcontentloaded")
                        list_page.wait_for_selector(SELECTOR_CARDS, timeout=8000)
                    except Exception as exc:
                        print(
                            f"No visible job cards for {search_location} on page {current_page_num}. "
                            f"Stopping this target. [{type(exc).__name__}]"
                        )
                        break

                    job_cards = list_page.query_selector_all(SELECTOR_CARDS)
                    print(f"Found {len(job_cards)} job cards")

                    if len(job_cards) == 0:
                        print("No cards found. Stopping this target.")
                        break

                    page_has_fresh_card = False
                    
                    for card in job_cards:
                        try:
                            record = _extract_seek_card_data(card, search_target, run_iso)
                            record["page"] = current_page_num
                            title, company = record[RECORD_TITLE_KEY], record[RECORD_COMPANY_KEY]
                            posted_age_days = record["posted_age_days"]
                            if posted_age_days is None or posted_age_days <= configured_date_range:
                                page_has_fresh_card = True

                            title_analysis = analyze_title_filters(title, profile)
                            ok_title = bool(title_analysis.get("ok"))
                            title_reason = str(title_analysis.get("reason") or "")
                            record[TITLE_REASON_KEY] = title_reason
                            record["title_match_metadata"] = title_analysis
                            if not ok_title:
                                print(f"REJECTED (title) [{title_reason}] {title}")
                                record["reject_reason"] = title_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if not record[RECORD_URL_KEY]:
                                print(f"REJECTED (card) [NO_URL] {title} @ {company}")
                                record["reject_reason"] = "NO_URL"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            job_key = record["job_key"]
                            if job_key in applied_job_keys:
                                print(f"SKIP (applied) {title} @ {company}")
                                record.update({"decision": "SKIP", "reject_reason": "ALREADY_APPLIED"})
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if job_key in hidden_job_keys:
                                print(f"SKIP (hidden) {title} @ {company}")
                                record.update({"decision": "SKIP", "reject_reason": "MANUALLY_HIDDEN"})
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if enforce_posted_age_limit and posted_age_days is not None and posted_age_days > configured_date_range:
                                print(f"REJECTED (posted) [POSTED_TOO_OLD:{configured_date_range}] {title} @ {company}")
                                record["reject_reason"] = f"POSTED_TOO_OLD:{configured_date_range}"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record[RECORD_URL_KEY] in seen_urls:
                                print(f"SKIP (duplicate) {title} @ {company}")
                                record.update({"decision": "SKIP", "reject_reason": "DUPLICATE_URL"})
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            seen_urls.add(record[RECORD_URL_KEY])

                            ok_card, card_reason = passes_quick_card_filters(title=title, teaser=record["teaser"], company=company, location=record["location"], work_mode=record["work_mode"], work_type=record["work_type"], salary=record.get("card_salary", "N/A"))
                            if not ok_card:
                                print(f"REJECTED (card gate) [{card_reason}] {title} @ {company}")
                                record["reject_reason"] = card_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            history_entry = job_history.get(job_key or "", {})
                            if can_reuse_kept_job(history_entry, record, profile):
                                record = apply_kept_job_reuse(record, history_entry)
                                finalize_record(job_history, audit_rows, record, run_iso)
                                kept_records.append(record)
                                print(f"KEPT (history reuse): {title} @ {company}")
                                continue

                            ok_details, reject_reason = _process_seek_job_details(record, detail_page, profile, title_reason)
                            if not ok_details:
                                print(f"REJECTED (details/content) [{reject_reason}] {title} @ {company}")
                                record["reject_reason"] = reject_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            fit_eval = _evaluate_job_fit(record, profile, llm_cache)
                            record.update(fit_eval)
                            
                            if record["decision"] == "REJECT":
                                print(f"REJECTED ({record['review_source']}) {title} @ {company}")
                                record["reject_reason"] = "LLM_REJECT" if record["review_source"] == "llm" else "DET_REJECT"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            
                            skill_observations.extend(record.get("skill_observations") or [])
                            pending_signals = _merge_pending_learning_signals(
                                record.get("ad_learning_signals") or [],
                                record.get("llm_learning_candidates") or [],
                            )
                            _register_pending_learning_signals(pending_signals)
                            record.pop("skill_observations", None)
                            record.pop("ad_learning_signals", None)
                            record.pop("llm_learning_candidates", None)
                            finalize_record(job_history, audit_rows, record, run_iso)
                            kept_records.append(record)
                            print(f"KEPT: {title} @ {company} | {'SEEN_BEFORE' if record.get('seen_before') else 'NEW'}")

                        except Exception as exc:
                            record["reject_reason"] = f"CARD_EXCEPTION:{type(exc).__name__}"
                            print(f"REJECTED (card) [CARD_EXCEPTION:{type(exc).__name__}] {title} @ {company}")
                            finalize_record(job_history, audit_rows, record, run_iso)

                    if enforce_posted_age_limit and not page_has_fresh_card:
                        print(
                            f"All cards for {search_location} on page {current_page_num} "
                            f"were older than {configured_date_range} day(s). Stopping this target."
                        )
                        break

                    current_page_num += 1

        finally:
            browser.close()

    return kept_records, audit_rows, skill_observations


def scrape_jobs_direct(headless: bool = False) -> str:
    configure_console_output()
    from job_hunter_agent.llm_gate import _get_llm_model
    dashboard_min_score = get_dashboard_minimum_score()
    print("=" * 60)
    print("  JOB HUNTER AGENT - SCRAPE RUN")
    print("=" * 60)
    print("  Trigger            : manual scrape command")
    print("  Action             : scrape fresh jobs, review them, rebuild dashboard")
    print("  Fresh scrape       : YES")
    print(f"  Dashboard debug    : {'ON (--debug-mode)' if DASHBOARD_DEBUG_MODE else 'OFF'}")
    print(f"  Cheap LLM          : {'ON (--cheap-llm)' if CHEAP_LLM_MODE else 'OFF'}")
    print(f"  LLM Disabled       : {'YES (--no-llm flag)' if NO_LLM_MODE else 'NO'}")
    print(f"  LLM Model          : {_get_llm_model()}")
    print(f"  Score Floor        : {dashboard_min_score}")
    print(f"  Reset New To You   : {'YES (--reset-new-to-you)' if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else 'NO'}")
    print("=" * 60)

    profile = load_profile()
    previous_audit_rows = load_json_list(DEBUG_JSON_PATH)
    previous_run_stats = load_json_dict(RUN_STATS_PATH)
    search_settings = get_search_settings(profile)
    configured_seek_max_pages = int(search_settings.get("seek_max_pages", 10) or 10)
    configured_date_range = int(search_settings.get("date_range_days", 3) or 3)
    enforce_posted_age_limit = bool(search_settings.get("enforce_posted_age_limit", True))
    sort_newest_first = bool(search_settings.get("sort_newest_first", True))
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)

    run_started_at = datetime.now().astimezone()
    run_iso = run_started_at.isoformat(timespec="seconds")
    write_run_attempt(run_started_at)
    llm_cache: Dict[str, Any] = load_llm_cache()
    job_history = load_job_history()

    enabled_sources = [s.lower().strip() for s in (profile.get("enabled_sources") or ["seek"])]

    kept_records: List[dict] = []
    audit_rows: List[dict] = []
    skill_observations: List[dict] = []

    # --- SEEK ---
    if "seek" in enabled_sources:
        search_targets = build_seek_search_targets(profile, configured_date_range, sort_newest_first)
        s_kept, s_audit, s_skills = _seek_scrape_to_records(
            profile=profile,
            search_targets=search_targets,
            job_history=job_history,
            llm_cache=llm_cache,
            applied_job_keys=applied_job_keys,
            hidden_job_keys=hidden_job_keys,
            run_iso=run_iso,
            configured_date_range=configured_date_range,
            enforce_posted_age_limit=enforce_posted_age_limit,
            configured_seek_max_pages=configured_seek_max_pages,
            headless=headless,
        )
        kept_records.extend(s_kept)
        audit_rows.extend(s_audit)
        skill_observations.extend(s_skills)

    # --- LinkedIn ---
    if "linkedin" in enabled_sources:
        from job_hunter_agent.scrapers.linkedin import LinkedInScraper  # noqa: PLC0415
        try:
            li = LinkedInScraper(
                profile=profile,
                llm_cache=llm_cache,
                job_history=job_history,
                applied_job_keys=applied_job_keys,
                hidden_job_keys=hidden_job_keys,
                run_iso=run_iso,
            )
            li_kept, li_audit, li_skills = li.scrape()
            kept_records.extend(li_kept)
            audit_rows.extend(li_audit)
            skill_observations.extend(li_skills)
        except Exception as exc:
            print(f"[LinkedIn] Scraping failed: {type(exc).__name__}: {exc}")

    # --- Finalize ---
    # Final semantic deduplication pass to collapse reposts and cross-source duplicates
    kept_records = deduplicate_across_sources(kept_records)

    if not audit_rows and previous_audit_rows:
        render_html(
            OUTPUT_HTML,
            load_last_kept_records(),
            parse_timestamp(previous_run_stats.get("run_started_at")) or run_started_at,
            configured_date_range,
            sort_newest_first,
            previous_run_stats or {},
            job_history,
            applied_job_keys,
            hidden_job_keys,
            datetime.now().astimezone(),
        )
        save_llm_cache(llm_cache)
        save_job_history(job_history)
        print("\nNo fresh cards were captured in this run, so the previous dashboard state was preserved.")
        print(f"Dashboard preserved at {OUTPUT_HTML}")
        return OUTPUT_HTML

    run_finished_at = datetime.now().astimezone()
    run_stats = build_run_stats(
        audit_rows,
        kept_records,
        run_started_at,
        run_finished_at,
        configured_date_range,
        sort_newest_first,
        configured_seek_max_pages,
    )
    run_stats["last_run_attempt_at"] = run_iso

    render_html(
        OUTPUT_HTML,
        kept_records,
        run_started_at,
        configured_date_range,
        sort_newest_first,
        run_stats,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        run_started_at,
    )
    save_llm_cache(llm_cache)
    save_job_history(job_history)
    write_debug_json(audit_rows)
    write_run_stats(run_stats)
    write_review_data(build_review_data(audit_rows, skill_observations, profile))
    print(f"\nSaved {len(kept_records)} jobs to {OUTPUT_HTML}")
    print(f"Saved {len(audit_rows)} audit rows to {DEBUG_JSON_PATH}")
    print(f"Saved run stats to {RUN_STATS_PATH}")
    print(f"Saved review data to {REVIEW_DATA_PATH}")
    print(f"Saved history for {len(job_history)} jobs to {JOB_HISTORY_PATH}")
    return OUTPUT_HTML


def rebuild_html_dashboard(reason: str = "Manual --rebuild-dashboard command") -> str:
    configure_console_output()
    print("=" * 60)
    print("  JOB HUNTER AGENT - DASHBOARD REBUILD")
    print("=" * 60)
    print(f"  Trigger            : {reason}")
    print("  Action             : re-render saved dashboard only")
    print("  Fresh scrape       : NO")
    print("  AI review          : NO")
    print(f"  Debug dashboard   : {'ON (--debug-mode)' if DASHBOARD_DEBUG_MODE else 'OFF'}")
    print(f"  Reset New To You   : {'YES (--reset-new-to-you)' if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else 'NO'}")
    print("=" * 60)
    profile = load_profile()
    search_settings = get_search_settings(profile)
    configured_date_range = int(search_settings.get("date_range_days", 3) or 3)
    sort_newest_first = bool(search_settings.get("sort_newest_first", True))
    run_stats = load_json_dict(RUN_STATS_PATH)
    run_started_at = parse_timestamp(run_stats.get("run_started_at")) or datetime.now().astimezone()
    reference_time = datetime.now().astimezone()
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    job_history = load_job_history()
    kept_records = load_last_kept_records()
    print(f"  Saved kept records : {len(kept_records)}")
    print(f"  Job history records: {len(job_history)}")
    print(f"  Applied keys       : {len(applied_job_keys)}")
    print(f"  Hidden keys        : {len(hidden_job_keys)}")
    print("=" * 60)

    render_html(
        OUTPUT_HTML,
        kept_records, 
        run_started_at,
        configured_date_range,
        sort_newest_first,
        run_stats,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    )
    print(f"Dashboard rebuilt at {OUTPUT_HTML}")
    return OUTPUT_HTML


if __name__ == "__main__":
    if "--rebuild-dashboard" in sys.argv:
        rebuild_html_dashboard()
    else:
        scrape_jobs_direct()
