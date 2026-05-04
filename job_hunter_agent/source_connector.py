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
from job_hunter_agent.llm_gate import build_llm_cache_key, llm_is_enabled, llm_should_consider, normalize_llm_review
from job_hunter_agent.match_labels import score_to_match_level, score_to_match_label
from job_hunter_agent.profile_store import (
    get_match_levels,
    get_evidence_tier_weights,
    get_evidence_tiers,
    get_preference_weights,
    get_scoring_rules,
    get_search_settings,
    load_profile,
)
from job_hunter_agent.review_insights import build_review_data
from job_hunter_agent.signal_registry import load_approved_signal_catalog, load_registry, register_signals, signal_in_approved_knowledge
from job_hunter_agent.profile_learning import _role_title_review_token
from job_hunter_agent.title_normalization_rules import learn_title_normalization_candidates
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
    TRUSTED_DESCRIPTION_SOURCES,
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
    detect_competitive_signals,
    evaluate_competitive_signal_alignment,
    competitive_signal_assessments,
    competitive_fit_highlights,
    extract_skill_observations,
    build_job_learning_signals,
    hard_block_entries,
    hard_block_reasons,
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
DESCRIPTION_CAPTURE_ISSUE = "Full job description not captured clearly"
ARCHIVE_LABEL = "Saved From Earlier Searches"
ARCHIVE_BADGE_TOOLTIP = "This role was saved from an earlier search and kept on your dashboard."
ARCHIVE_CONTEXT_PREFIX = "Saved From Earlier Searches"


def deterministic_review_outcome(record: dict, fit_highlights: List[str], missing_evidence: List[str], soft_risk_reasons: List[str]) -> Optional[dict]:
    title_reason = str(record.get("title_reason") or "")
    strong_signal_count = len(capability_fit_highlights(fit_highlights))
    high_risks = len(missing_evidence)
    medium_risks = len(soft_risk_reasons)

    if high_risks >= 2 and strong_signal_count <= 1:
        return {"decision": "REJECT", "grade": "MISMATCH"}
    if title_reason == "TITLE_POTENTIAL_MATCH" and high_risks >= 1 and strong_signal_count <= 1:
        return {"decision": "REJECT", "grade": "POOR"}
    if title_reason == "OK" and strong_signal_count >= 4 and high_risks == 0:
        return {"decision": "KEEP", "grade": "STRONG"}
    if title_reason == "OK" and strong_signal_count >= 3 and high_risks == 0 and medium_risks <= 1:
        return {"decision": "KEEP", "grade": "SOLID"}
    return None


def visible_fit_reasons(
    fit_highlights: List[str],
    score_breakdown: List[dict],
    max_items: int = 4,
    include_values: bool = False,
) -> List[str]:
    reasons = dedupe_preserve_order([
        compact_whitespace(item)
        for item in fit_highlights
        if compact_whitespace(item)
    ])
    excluded = {
        "Fit evidence bullets",
        "Passed content filters",
    }

    for item in score_breakdown:
        label = compact_whitespace(item.get("label") or "")
        value = int(item.get("value", 0) or 0)
        if not label or value <= 0 or label in excluded:
            continue
        if label not in reasons:
            reasons.append(label)
        if len(reasons) >= max_items:
            break

    reasons = reasons[:max_items]

    if include_values:
        formatted_reasons = []
        for reason in reasons:
            val = next((int(i.get("value", 0) or 0) for i in score_breakdown if compact_whitespace(i.get("label") or "") == reason), None)
            if val is not None:
                formatted_reasons.append(f"{reason}: {val:+d}")
            else:
                formatted_reasons.append(reason)
        return formatted_reasons

    return reasons


def negative_score_reasons(
    score_breakdown: List[dict],
    max_items: int = 4,
    include_values: bool = True,
) -> List[str]:
    friendly_labels = {
        "Salary/rate below target": "Salary is below target range",
        "Description capture incomplete": DESCRIPTION_CAPTURE_ISSUE,
        "Already viewed by you": "Already opened by you",
        "Contract is shorter than preferred": "Contract length is shorter than preferred",
    }
    reasons = [
        (
            f"{compact_whitespace(item.get('label') or '')}: {int(item.get('value', 0) or 0):+d}"
            if include_values
            else friendly_labels.get(
                compact_whitespace(item.get("label") or ""),
                compact_whitespace(item.get("label") or ""),
            )
        )
        for item in score_breakdown
        if compact_whitespace(item.get("label") or "") and int(item.get("value", 0) or 0) < 0
    ]
    return dedupe_preserve_order(reasons)[:max_items]


def score_gap_reasons(record: dict, score_breakdown: List[dict], max_items: int = 4) -> List[str]:
    labels = [compact_whitespace(item.get("label") or "") for item in score_breakdown]
    evidence_points = next(
        (int(item.get("value", 0) or 0) for item in score_breakdown if item.get("label") == "Fit evidence bullets"),
        0,
    )
    gaps: List[str] = []

    if not any(label.startswith("Posted within") or label == "Still relatively recent" for label in labels):
        gaps.append("No reliable recent-posted signal")

    if not any(label in {"Salary/rate signal", "Salary/rate below target"} for label in labels):
        salary = compact_whitespace(record.get("salary") or "")
        if not salary or salary == "N/A":
            gaps.append("No comparable salary/rate found")

    if evidence_points < 12:
        capability_matches = capability_match_summary(record)
        capability_count = (
            len(capability_matches.get("strong", []))
            + len(capability_matches.get("working", []))
            + len(capability_matches.get("basic", []))
        )
        gaps.append(f"Only {capability_count} capability evidence match{'es' if capability_count != 1 else ''} counted")

    if full_description_confidence(record) == "LOW":
        gaps.append("Scoring confidence is limited because the full description was not captured")

    return dedupe_preserve_order(gaps)[:max_items]


def score_filter_option_label(threshold: int, scoring_profile: Optional[dict] = None) -> str:
    active_profile = scoring_profile or load_profile()
    match_levels = get_match_levels(active_profile)
    label = score_to_match_label(threshold, match_levels)
    highest_threshold = max(int(level.get("minimum_score", 0) or 0) for level in match_levels)
    if threshold >= highest_threshold:
        return f"{label} only"
    return f"{label} or better"


def score_filter_thresholds(
    records: List[dict],
    scoring_profile: Optional[dict] = None,
    include_borderline: Optional[bool] = None,
) -> List[int]:
    active_profile = scoring_profile or load_profile()
    show_borderline = DASHBOARD_DEBUG_MODE if include_borderline is None else bool(include_borderline)
    scores = [fit_score(record, active_profile) for record in records]
    match_levels = get_match_levels(active_profile)
    thresholds = [int(level.get("minimum_score", 0) or 0) for level in match_levels if int(level.get("minimum_score", 0) or 0) > 0]
    lowest_band_threshold = int(match_levels[-1].get("minimum_score", 0) or 0) if match_levels else 0
    if (show_borderline or any(score < (thresholds[-1] if thresholds else 0) for score in scores)) and lowest_band_threshold not in thresholds:
        thresholds.append(lowest_band_threshold)
    return thresholds


def render_score_filter_options(
    records: List[dict],
    scoring_profile: Optional[dict] = None,
    dashboard_min_score: Optional[int] = None,
    include_borderline: Optional[bool] = None,
) -> str:
    active_profile = scoring_profile or load_profile()
    active_dashboard_min_score = (
        int(dashboard_min_score)
        if dashboard_min_score is not None
        else get_dashboard_minimum_score()
    )
    options = ['<option value="all">All match levels</option>']
    for threshold in score_filter_thresholds(records, active_profile, include_borderline=include_borderline):
        selected_attr = " selected" if active_dashboard_min_score == threshold else ""
        options.append(
            f'<option value="{threshold}"{selected_attr}>'
            f'{safe_html(score_filter_option_label(threshold, active_profile))}</option>'
        )
    return "".join(options)


def posted_filter_option_label(threshold: int) -> str:
    labels = {
        1: "Posted today",
        3: "Last 3 days",
        7: "Last 7 days",
        14: "Last 14 days",
        # 30: "Last 30 days",
    }
    return labels.get(threshold, f"Last {threshold} days")


def render_posted_filter_options(records: List[dict], now: Optional[datetime] = None) -> str:
    options = [f'<option value="all">Any posted date ({len(records)})</option>']
    for threshold in [1, 3, 7, 14, 30]:
        count = sum(
            1
            for record in records
            if (age_days := current_posted_age_days(record, now)) is not None
            and age_days <= threshold
        )
        options.append(
            f'<option {"selected" if threshold == 1 else ""} value="{threshold}">'
            f'{safe_html(posted_filter_option_label(threshold))} ({count})</option>'
        )
    return "".join(options)


def humanize_reject_reason(reason: Optional[str]) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return "Other filtered-out roles"

    direct_map = {
        "TITLE_NOT_TARGET": "Title outside target role family",
        "NO_DETAILS": "Could not read full job details",
        "DETAILS_CHALLENGE_PAGE": "Blocked by SEEK challenge page",
        "DETAILS_BLOCKED_PAGE": "Blocked from reading job details",
        "DETAILS_NAVIGATION_ERROR": "Could not open the job ad page",
        "DET_REJECT": "Deterministic fit gate rejected",
        "LLM_REJECT": "AI fit review rejected",
        "DUPLICATE_URL": "Duplicate listing removed",
        "ALREADY_APPLIED": "Already marked as applied",
        "MANUALLY_HIDDEN": "Already hidden by you",
        "UNKNOWN": "Other filtered-out roles",
    }
    if raw in direct_map:
        return direct_map[raw]

    prefix, _, detail = raw.partition(":")
    cleaned_detail = detail.replace("_", " ").strip()
    if prefix == "TITLE_BAD_KEYWORD" and cleaned_detail:
        return f"Excluded title keyword: {cleaned_detail}"
    if prefix == "TITLE_BAD_ROLE" and cleaned_detail:
        return f"Excluded role family: {cleaned_detail}"
    if prefix == "POSTED_TOO_OLD" and cleaned_detail:
        return f"Older than the search window ({cleaned_detail} days)"
    if prefix == "DESC_LOCATION" and cleaned_detail:
        return f"Location mismatch: {cleaned_detail}"
    if prefix == "DESC_CAPABILITY_LOW" and cleaned_detail:
        return f"Low-fit specialist area: {cleaned_detail}"
    if prefix == "DESC_HARD_BLOCK" and cleaned_detail:
        return f"Hard blocker mismatch: {cleaned_detail}"
    if prefix == "DESC_HARD_BLOCK_RULE" and cleaned_detail:
        return f"Hard blocker requirement: {cleaned_detail}"
    if prefix == "CARD_EXCEPTION" and cleaned_detail:
        return f"Collection error: {cleaned_detail}"
    if prefix == "DESC_BAD_PHRASE" and cleaned_detail:
        return f"Excluded description phrase: {cleaned_detail}"
    if prefix == "DESC_BAD_REGEX" and cleaned_detail:
        return f"Excluded description pattern: {cleaned_detail}"
    if prefix == "LEARNED_REJECT" and cleaned_detail:
        return f"Learned blocker: {cleaned_detail.split(':')[-1].strip()}"
    if prefix == "TITLE_POTENTIAL_MATCH":
        return "Secondary role-family match"
    if prefix == "CARD_SPECIALIST" and cleaned_detail:
        return f"Rejected early from card metadata: {cleaned_detail}"

    fallback = raw.replace("_", " ").lower()
    return fallback[:1].upper() + fallback[1:]


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
                "suggested_category": "hard_blocker_pattern",
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


def render_job_card(
    record: dict,
    scoring_profile: Optional[dict] = None,
    applied_pool: Optional[List[dict]] = None,
    history_clusters: Optional[Dict[str, dict]] = None,
) -> str:
    active_profile = scoring_profile or load_profile()
    display_record = dict(record)
    
    loc = str(display_record.get("location") or "").strip()
    if loc.endswith(", Australia"):
        display_record["location"] = loc[:-11].strip()
        
    title = safe_html(record.get("title", "Untitled"))
    company = safe_html(record.get("company", "N/A"))
    url = safe_html(record.get("url", "#"))
    job_key = safe_html(str(record.get("job_key") or ""))
    title_reason = record.get("title_reason")
    applied_record = bool(record.get("applied"))
    archived = bool(record.get("archived"))
    hidden_record = bool(record.get("hidden"))
    is_stale = bool(record.get("is_stale"))
    seen_by_you = viewed_by_user(record)
    stored_snapshot = compact_whitespace(record.get("role_snapshot") or record.get("teaser") or "N/A")
    if stored_snapshot in {"", "N/A"}:
        stored_snapshot = synthesize_role_snapshot(record)
    fit_confidence_level = full_description_confidence(record)
    trusted_desc = get_trusted_full_description(record)

    if fit_confidence_level == "HIGH" and trusted_desc:
        display_record["fit_source_text"] = trusted_desc
        display_record["fit_confidence"] = "HIGH"
        detail_work_mode = extract_work_mode(trusted_desc)
        if detail_work_mode != "N/A":
            display_record["work_mode"] = detail_work_mode
        role_summary = build_role_summary(record, trusted_desc, active_profile)
        display_record["competitive_signals"] = competitive_signal_assessments(record, active_profile)
        fit_highlights = build_fit_highlights(record, trusted_desc, active_profile)
        soft_risk_reasons, missing_evidence = build_risk_and_missing_evidence(
            trusted_desc,
            title_reason,
            active_profile,
            competitive_signals=display_record.get("competitive_signals") if isinstance(display_record.get("competitive_signals"), list) else None,
        )
        blocking_reasons = hard_block_reasons(display_record, active_profile)
        if blocking_reasons:
            missing_evidence = dedupe_preserve_order([*blocking_reasons, *missing_evidence])
    else:
        role_summary = stored_snapshot
        display_record["fit_confidence"] = "LOW"
        display_record["competitive_signals"] = []
        fit_highlights = []
        soft_risk_reasons = []
        missing_evidence = [DESCRIPTION_CAPTURE_ISSUE]
        blocking_reasons = []

    similar_applied_record = None
    is_possible_repost = False
    if not applied_record and applied_pool:
        similar_applied_record = find_similar_job(record, applied_pool)
        is_possible_repost = similar_applied_record is not None

    display_record["hard_block_reasons"] = blocking_reasons
    display_record["role_snapshot"] = role_summary
    display_record["fit_highlights"] = fit_highlights
    display_record["soft_risk_reasons"] = soft_risk_reasons
    display_record["missing_evidence"] = missing_evidence
    fit_points = fit_score(display_record, scoring_profile)
    match_levels = get_match_levels(scoring_profile or load_profile())
    fit_label = score_to_match_label(fit_points, match_levels)
    fit_tone_class = score_to_tone_class(fit_points, scoring_profile)
    score_breakdown = fit_score_breakdown(display_record, scoring_profile)
    visible_reasons = visible_fit_reasons(fit_highlights, score_breakdown, include_values=DASHBOARD_DEBUG_MODE)
    description_issue = fit_confidence_level == "LOW"
    work_mode = str(display_record.get("work_mode") or "N/A")
    posted_age_days = current_posted_age_days(record)
    salary_value = salary_sort_value(str(display_record.get("salary") or ""))
    salary_fit_state = salary_fit_label(display_record, scoring_profile)
    record_kind = "applied" if applied_record else ("hidden" if hidden_record else ("saved" if archived else "current"))
    company_attr = safe_html(compact_whitespace(str(record.get("company") or "")))
    teaser_attr = safe_html(compact_whitespace(str(record.get("teaser") or "")))
    sector_signal = infer_role_sector(display_record, trusted_desc if trusted_desc else stored_snapshot)
    channel_signal = infer_posting_channel(display_record, trusted_desc if trusted_desc else stored_snapshot)
    _block_phrases_list = suggest_title_block_phrases(str(record.get("title") or ""))
    block_phrase = safe_html(_block_phrases_list[0]) if _block_phrases_list else ""
    block_phrases_json = safe_html(json.dumps(_block_phrases_list))
    similar_applied_title = safe_html(str((similar_applied_record or {}).get("title") or ""))
    similar_applied_company = safe_html(str((similar_applied_record or {}).get("company") or ""))
    similar_applied_source = str((similar_applied_record or {}).get("source") or "").lower().strip()
    similar_applied_source_label = safe_html(
        {"linkedin": "LinkedIn", "seek": "SEEK"}.get(similar_applied_source, similar_applied_source.upper())
        if similar_applied_source
        else ""
    )
    similar_applied_job_key = safe_html(str((similar_applied_record or {}).get("job_key") or ""))
    button_data_attrs = (
        f'data-job-key="{job_key}" '
        f'data-job-url="{url}" '
        f'data-job-title="{title}" '
        f'data-job-company="{company_attr}" '
        f'data-job-teaser="{teaser_attr}" '
        f'data-role-sector="{safe_html(sector_signal.get("kind") or "unknown")}" '
        f'data-posting-channel="{safe_html(channel_signal.get("kind") or "unknown")}" '
        f'data-similar-applied-warning="{"1" if is_possible_repost else "0"}" '
        f'data-similar-applied-job-key="{similar_applied_job_key}" '
        f'data-similar-applied-title="{similar_applied_title}" '
        f'data-similar-applied-company="{similar_applied_company}" '
        f'data-similar-applied-source="{similar_applied_source_label}"'
    )

    source = str(record.get("source") or "unknown").lower().strip()
    source_label = {"linkedin": "LinkedIn", "seek": "SEEK"}.get(source, source.upper())

    badges = []
    if applied_record:
        badges.append(render_badge("Applied", "badge-viewed", "You already applied for this role."))
    elif hidden_record:
        badges.append(render_badge("Hidden", "badge-hidden", "You hid this role for now."))
    elif is_possible_repost:
        badges.append(render_badge("Possible Repost", "badge-warning", "This role looks very similar to one you have already applied to."))
    elif archived:
        badges.append(render_badge(ARCHIVE_LABEL, "badge-archive", ARCHIVE_BADGE_TOOLTIP))
    if not applied_record and not seen_by_you:
        badges.append(render_badge("New To You", "badge-new", "You have not opened this role from the dashboard yet."))
    if is_stale:
        badges.append(render_badge("15+ Days Old", "badge-stale", "This role is older, but still saved for reference."))
    elif seen_by_you:
        badges.append(viewed_badge_html())
    if description_issue:
        badges.append(render_badge("Description Issue", "badge-warning", "The full job description was not captured clearly, so this match needs manual checking."))
    badges.append(render_badge(source_label, f"badge-source-{source}", f"Sourced from {source_label}."))
    if sector_signal.get("kind") == "government":
        badges.append(render_badge("Government", "badge-sector-government", "Government/public-sector context detected from the captured job text."))
    if channel_signal.get("kind") == "recruiter":
        confidence_text = channel_signal.get("confidence") or "inferred"
        badges.append(render_badge("Recruiter", "badge-channel-recruiter", f"Recruiter/intermediary posting inferred with {confidence_text} confidence from the captured job text."))
    elif channel_signal.get("kind") == "direct_employer":
        confidence_text = channel_signal.get("confidence") or "inferred"
        badges.append(render_badge("Direct Employer", "badge-new", f"Direct employer posting inferred with {confidence_text} confidence from the captured job text."))
    history_warning_signals = assess_history_warning_signals(record, history_clusters)
    if history_warning_signals:
        badges.append(render_badge("Potential Red Flag", "badge-warning", history_warning_signals[0]))

    score_percent = max(min(int(fit_points), 100), 0)
    score_html = (
        f'<div class="match-tile {fit_tone_class}" style="--match-score: {score_percent}%;">'
        + (
            f'<span class="match-tile-number">{fit_points}</span>'
            if DASHBOARD_DEBUG_MODE
            else ""
        )
        + f'<span class="match-tile-label">{safe_html(fit_label)}</span>'
        + '<span class="match-tile-bar" aria-hidden="true"><span class="match-tile-bar-fill"></span></span>'
        + "</div>"
    )

    posted_display = posted_display_label(record)

    meta_items = []
    for label, value in [
        ("Posted", posted_display),
        ("Location", display_record.get("location")),
        ("Work mode", display_record.get("work_mode")),
        ("Type", display_record.get("work_type")),
        ("Salary", display_record.get("salary")),
    ]:
        if value and value != "N/A" and value != "Unknown":
            meta_items.append(
                f'<span class="job-meta-item"><strong>{safe_html(label)}</strong> {safe_html(str(value))}</span>'
            )
    context_bits = []
    if salary_fit_state == "below":
        soft_risk_reasons = dedupe_preserve_order([
            *soft_risk_reasons,
            "Salary is below target range",
        ])
    contract_item = assess_contract_preference(display_record, scoring_profile)
    if contract_item and int(contract_item.get("value", 0)) < 0:
        soft_risk_reasons = dedupe_preserve_order([
            *soft_risk_reasons,
            "Contract length is shorter than preferred",
        ])
    if seen_by_you and record.get("last_viewed_at"):
        context_bits.append(f"Opened by you {format_timestamp_label(record.get('last_viewed_at'))}")
    if applied_record and record.get("last_applied_at"):
        context_bits.append(f"Applied {format_timestamp_label(record.get('last_applied_at'))}")
    if hidden_record and record.get("last_hidden_at"):
        context_bits.append(f"Hidden {format_timestamp_label(record.get('last_hidden_at'))}")
    elif archived and record.get("last_kept_at"):
        context_bits.append(f"{ARCHIVE_CONTEXT_PREFIX} {format_timestamp_label(record.get('last_kept_at'))}")
    context_html = f'<div class="job-context">{safe_html(" | ".join(context_bits))}</div>' if context_bits else ""

    summary_html = (
        f'<p class="job-summary">{safe_html(role_summary)}</p>'
        if role_summary and role_summary != "N/A"
        else ""
    )
    note_bits: List[str] = []
    if history_warning_signals:
        note_bits.append(f"Potential red flag: {history_warning_signals[0].removeprefix('Potential red flag: ').strip()}.")
    elif description_issue:
        note_bits.append("Description issue: full job description was not captured clearly.")
    elif is_possible_repost:
        note_bits.append("Alert: This looks like a role you already marked as applied at this company.")
    elif missing_evidence:
        note_bits.append(f"Missing evidence: {missing_evidence[0]}.")
    elif soft_risk_reasons:
        note_bits.append(f"Risk: {soft_risk_reasons[0]}.")
    note_html = (
        f'<div class="job-note">{safe_html(" ".join(note_bits))}</div>'
        if note_bits
        else ""
    )
    reviewed_signal_matches = reviewed_signal_match_summary(display_record, scoring_profile)
    insight_sections = []
    if visible_reasons:
        insight_sections.append(
            '<div class="job-insight-group">'
            '<strong>Why it fits</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in visible_reasons)}</ul>'
            '</div>'
        )
    if reviewed_signal_matches["matched"]:
        insight_sections.append(
            '<div class="job-insight-group">'
            '<strong>Matched signals</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in reviewed_signal_matches["matched"])}</ul>'
            '</div>'
        )
    if reviewed_signal_matches["unresolved"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Unresolved signals</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in reviewed_signal_matches["unresolved"])}</ul>'
            '</div>'
        )
    if reviewed_signal_matches["evidence_only"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Evidence only</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in reviewed_signal_matches["evidence_only"])}</ul>'
            '</div>'
        )
    if reviewed_signal_matches["ignored"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Ignored</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in reviewed_signal_matches["ignored"])}</ul>'
            '</div>'
        )
    visible_penalties = negative_score_reasons(score_breakdown, include_values=DASHBOARD_DEBUG_MODE)
    if description_issue:
        visible_penalties = [
            item for item in visible_penalties
            if not item.startswith("Description capture incomplete")
        ]
    negative_items = dedupe_preserve_order([
        *([] if description_issue else missing_evidence),
        *soft_risk_reasons,
        *visible_penalties,
    ])[:6]
    if description_issue:
        description_issue_items = [DESCRIPTION_CAPTURE_ISSUE]
        if DASHBOARD_DEBUG_MODE:
            capture_facts = []
            status = compact_whitespace(record.get("details_status") or "")
            source_name = compact_whitespace(record.get("description_source") or "")
            details_length = record.get("details_length")
            if status:
                capture_facts.append(f"details status: {status}")
            if source_name:
                capture_facts.append(f"description source: {source_name}")
            if details_length not in {None, ""}:
                capture_facts.append(f"details length: {details_length}")
            if capture_facts:
                description_issue_items.append("; ".join(capture_facts))
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            '<strong>Description issue</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in description_issue_items)}</ul>'
            '</div>'
        )
    if history_warning_signals:
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            '<strong>Potential red flags</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in history_warning_signals)}</ul>'
            '</div>'
        )
    if negative_items:
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            '<strong>What lowers it</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in negative_items)}</ul>'
            '</div>'
        )
    elif DASHBOARD_DEBUG_MODE:
        insight_sections.append(
            '<div class="job-insight-group job-insight-muted">'
            '<strong>Watchouts</strong>'
            '<p class="insight-unavailable-note">No explicit risks detected from the captured description.</p>'
            '</div>'
        )
    if DASHBOARD_DEBUG_MODE:
        negative_reasons = negative_score_reasons(score_breakdown)
        if negative_reasons:
            insight_sections.append(
                '<div class="job-insight-group job-insight-warning">'
                '<strong>Score penalties</strong>'
                f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in negative_reasons)}</ul>'
                '</div>'
            )
        gap_reasons = score_gap_reasons(display_record, score_breakdown)
        if gap_reasons:
            insight_sections.append(
                '<div class="job-insight-group is-secondary">'
                '<strong>Score gaps</strong>'
                f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in gap_reasons)}</ul>'
                '</div>'
            )
    if DASHBOARD_DEBUG_MODE and score_breakdown:
        score_breakdown_html = "".join(
            f"<li>{safe_html(str(item['label']))}: {int(item['value']):+d}</li>"
            for item in score_breakdown
        )
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Score details</strong>'
            f'<ul>{score_breakdown_html}</ul>'
            '</div>'
        )
    insight_html = (
        '<details class="job-insights">'
        '<summary>Fit breakdown</summary>'
        f'{"".join(insight_sections)}'
        '</details>'
        if insight_sections
        else ""
    )

    if applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-undo" type="button" data-review-action="unapply" {button_data_attrs}>Undo Applied</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif hidden_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-undo" type="button" data-review-action="unhide" {button_data_attrs}>Unhide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif not applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-applied" type="button" data-review-action="applied" {button_data_attrs}>Applied</button>'
            f'<button class="review-button review-not-for-me" type="button" data-review-action="not_for_me" {button_data_attrs} title="Marks this role as not a fit and stores it as learning feedback">Not For Me</button>'
            f'<button class="review-button review-hide" type="button" data-review-action="hidden" {button_data_attrs} title="Hide this one job only. You can unhide it later from Hidden jobs.">Hide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    else:
        actions_html = ""

    card_classes = f'job-card {fit_tone_class}' + (" is-description-issue" if description_issue else "")

    return (
        f'<article class="{safe_html(card_classes)}" data-fit-score="{fit_points}" data-posted-age="{posted_age_days if posted_age_days is not None else 9999}" data-salary-sort="{salary_value}" data-salary-fit="{safe_html(salary_fit_state)}" data-work-mode="{safe_html(work_mode.lower())}" data-viewed="{1 if seen_by_you else 0}" data-record-kind="{record_kind}" data-fit-label="{safe_html(fit_label.lower())}" data-title-search="{safe_html((record.get("title") or "").lower())}" data-company-search="{safe_html((record.get("company") or "").lower())}" data-source="{safe_html(source)}">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        '<div class="job-header-row">'
        '<div class="job-header-copy">'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">{title}</a>'
        + (
            f'<button class="title-block-btn" type="button" data-review-action="block_similar" data-block-phrase="{block_phrase}" data-block-phrases="{block_phrases_json}" {button_data_attrs} title="Hide future roles whose titles contain the selected words, before description review.">Hide title words</button>'
            '<div class="block-confirm" data-block-confirm hidden>'
            '<div class="feature-guide-note">'
            'Job sites often return broad results even when the search is correct. '
            'If a title clearly doesnâ€™t match what you want, you can block similar titles directly from the title. '
            'This helps remove repeated noise from future results.'
            '</div>'
            '<p class="block-confirm-copy">Hide future titles with:</p>'
            '<div class="block-phrase-checks" data-block-phrase-checks></div>'
            '<button class="mini-button block-manual-toggle" type="button" data-block-manual-toggle>Add other title words</button>'
            '<div class="block-manual-row">'
            '<span class="block-manual-label">Add title words</span>'
            '<input class="block-manual-input" type="text" data-block-manual-input placeholder="e.g. project manager, payroll">'
            '<span class="block-manual-help">Adds to the checked words above. Use commas to add more than one.</span>'
            '</div>'
            '<p class="block-impact" data-block-impact></p>'
            '<p class="block-confirm-sub">This is a strong filter. Matching titles will be hidden before description review.</p>'
            '<div class="block-confirm-actions">'
            '<button class="mini-button mini-button-primary" type="button" data-confirm-block disabled>Block Selected Titles</button>'
            '<button class="mini-button" type="button" data-cancel-block>Cancel</button>'
            '</div>'
            '</div>'
            '<span class="block-status" aria-live="polite"></span>'
            if (not applied_record and not hidden_record and _block_phrases_list) else "" 
        )
        + f'<div class="job-company">{company}</div>'
        '</div>'
        f"{score_html}"
        '</div>'
        f"{summary_html}"
        f'<div class="job-meta">{"".join(meta_items)}</div>'
        f"{note_html}"
        f"{insight_html}"
        f"{context_html}"
        f"{actions_html}"
        "</article>"
    )


def section_dom_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "matches"


def render_section(
    title: str,
    records: List[dict],
    empty_message: str,
    scoring_profile: Optional[dict] = None,
    applied_pool: Optional[List[dict]] = None,
    history_clusters: Optional[Dict[str, dict]] = None,
) -> str:
    if not records:
        return (
            f'<section class="section"><h2>{safe_html(title)}</h2>'
            f'<p class="empty-state">{safe_html(empty_message)}</p></section>'
        )
    dom_id = section_dom_id(title)
    cards = "".join(
        render_job_card(record, scoring_profile, applied_pool=applied_pool, history_clusters=history_clusters)
        for record in records
    )
    return (
        f'<section class="section job-section" data-section-id="{safe_html(dom_id)}">'
        '<div class="section-head">'
        f'<h2>{safe_html(title)}</h2>'
        '<div class="section-tools">'
        '<span class="pagination-label"></span>'
        '<button class="pagination-button" type="button" data-page-direction="prev">Prev</button>'
        '<button class="pagination-button" type="button" data-page-direction="next">Next</button>'
        "</div>"
        "</div>"
        f'<div class="job-grid">{cards}</div>'
        "</section>"
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


def _render_results_fragment(context: dict[str, str]) -> str:
    if not RESULTS_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Missing template: {RESULTS_TEMPLATE_PATH}")
    template = Template(RESULTS_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.safe_substitute(context)


def _render_match_level_guide_html(profile: Optional[dict] = None) -> str:
    active_profile = profile or load_profile()
    match_levels = get_match_levels(active_profile)
    guide_bits = [
        f'<span class="chip"><strong>{safe_html(str(level["label"]))}:</strong> {safe_html(str(level["description"]))}</span>'
        for level in match_levels
    ]
    guide_bits.extend([
        '<span class="chip"><strong>Title match:</strong> direct titles are favored over secondary titles</span>',
        '<span class="chip"><strong>Description review:</strong> stronger description fit lifts the match level</span>',
        '<span class="chip"><strong>Competitive signals:</strong> specialist bias can lift or lower the match level</span>',
        '<span class="chip"><strong>Freshness:</strong> newer roles are favored</span>',
        '<span class="chip"><strong>Decision weights:</strong> fit, pay, location, work mode, contract, government, and freshness can be dialed up or down</span>',
        '<span class="chip"><strong>Watchouts:</strong> essential gaps hit harder than desirable-only gaps</span>',
        '<span class="chip"><strong>Risks:</strong> essential gaps hit harder than desirable-only gaps</span>',
    ])
    return "".join(guide_bits)


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
        "search_location": search_target["location"],
        "search_keywords": search_target["keywords"],
        "search_classifications": ",".join(search_target.get("classification_ids", [])),
        "source": "seek",
        "job_key": stable_job_key(full_url) if full_url else None,
        "title": title,
        "company": company,
        "posted": posted,
        "posted_age_days": posted_age_days,
        "url": full_url,
        "location": card_meta["location"],
        "work_mode": card_meta["work_mode"],
        "work_type": card_meta["work_type"],
        "teaser": card_meta["teaser"],
        "card_salary": card_meta["card_salary"],
        "decision": "REJECT",
        "reject_reason": None,
        "title_reason": None,
        "title_match_metadata": {},
        "content_reason": None,
        "llm_decision": None,
        "llm_fit_grade": None,
        "role_snapshot": "N/A",
        "fit_highlights": [],
        "soft_risk_reasons": [],
        "missing_evidence": [],
        "competitive_signals": [],
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
    details_payload = fetch_job_details_payload(detail_page, record["url"])
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

    record["fit_source_text"] = details_text
    record["full_description"] = details_text
    record["description_source"] = details_payload.get("source") or "jobAdDetails"
    source = str(record.get("description_source") or "").strip().lower()
    is_trusted = source in TRUSTED_DESCRIPTION_SOURCES and len(details_text) >= MIN_TRUSTED_DESCRIPTION_LENGTH
    record["fit_confidence"] = "HIGH" if is_trusted else "LOW"

    ok_desc, desc_reason = passes_content_filters(details_text, record["location"], title_reason)
    if not ok_desc:
        if desc_reason.startswith("DESC_HARD_BLOCK_RULE"):
            knowledge_matches = find_hard_block_matches(details_text, profile.get("must_not_require_skills", []))
            record["hard_block_reasons"] = dedupe_preserve_order(
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

    record["competitive_signals"] = [
        evaluate_competitive_signal_alignment(signal, profile)
        for signal in detect_competitive_signals(details_text, profile)
    ]
    record["reviewed_signal_matches"] = reviewed_signal_matches_for_text(details_text)
    
    hard_block_matches = hard_block_entries(record, profile)
    record["hard_block_reasons"] = [entry["text"] for entry in hard_block_matches]
    if record["hard_block_reasons"]:
        term = compact_whitespace(record["hard_block_reasons"][0]).lower()
        reason_code = f"DESC_HARD_BLOCK_RULE:{re.sub(r'[^a-z0-9]+', '_', term).strip('_') or 'hard_block'}"
        register_hard_blocker_learning_from_rejection(record, reason_code, details_text, hard_block_matches, profile=profile)
        return False, reason_code

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
    
    if deterministic_review is not None:
        review = deterministic_review
        source = "rule"
    else:
        llm_input_text = record["full_description"][:MAX_LLM_CHARS]
        llm_fp = build_llm_cache_key(llm_input_text)
        if NO_LLM_MODE or not llm_is_enabled():
            review = normalize_llm_review(None)
            source = "disabled"
        elif llm_fp in llm_cache:
            review = normalize_llm_review(llm_cache[llm_fp])
            source = "cache"
        else:
            review = normalize_llm_review(llm_should_consider(llm_input_text))
            llm_cache[llm_fp] = review
            source = "llm"

    return {
        "llm_decision": review["decision"],
        "llm_fit_grade": review["grade"],
        "review_source": source,
        "decision": "KEEP" if review["decision"] != "REJECT" else "REJECT"
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
                            title, company = record["title"], record["company"]
                            posted_age_days = record["posted_age_days"]
                            learn_title_normalization_candidates(
                                [title],
                                source="job title",
                                source_text=record.get("teaser") or "",
                            )

                            if posted_age_days is None or posted_age_days <= configured_date_range:
                                page_has_fresh_card = True

                            title_analysis = analyze_title_filters(title, profile)
                            ok_title = bool(title_analysis.get("ok"))
                            title_reason = str(title_analysis.get("reason") or "")
                            record["title_reason"] = title_reason
                            record["title_match_metadata"] = title_analysis
                            if not ok_title:
                                print(f"REJECTED (title) [{title_reason}] {title}")
                                record["reject_reason"] = title_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if not record["url"]:
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

                            if record["url"] in seen_urls:
                                print(f"SKIP (duplicate) {title} @ {company}")
                                record.update({"decision": "SKIP", "reject_reason": "DUPLICATE_URL"})
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            seen_urls.add(record["url"])

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
                            
                            record_skill_observations = extract_skill_observations(record, record["full_description"], profile)
                            skill_observations.extend(record_skill_observations)
                            pending_signals = build_job_learning_signals(record, record_skill_observations, profile)
                            if pending_signals:
                                register_signals(pending_signals)
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
