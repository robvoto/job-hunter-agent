"""
Workspace HTML rendering functions.

This module follows an "App Shell + Fragment" architecture. It processes
'results.html' as a template fragment to produce the data-heavy content (job
cards, filters, stats), which is then injected into the 'workspace.html' shell
by the frontend. No scraping or pipeline logic belongs here.
"""

import json
import logging
import re
from datetime import datetime
from functools import lru_cache
from html import escape
from string import Template
from typing import Any, Dict, List, Optional

from job_hunter_agent.capability_matching import (
    build_risk_and_missing_profile_support,
    reviewed_signal_match_summary,
)
from job_hunter_agent.company_normalization import normalize_company_name
from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.description_trust import (
    full_description_confidence,
    get_trusted_full_description,
)
from job_hunter_agent.filters import _detect_title_domain_qualifier, suggest_title_block_phrases
from job_hunter_agent.fit_scoring import (
    build_fit_highlights,
    fit_score_and_breakdown_displayed,
    fit_score_displayed,
)
from job_hunter_agent.global_settings import get_default_country_suffix
from job_hunter_agent.history import (
    assess_history_warning_signals,
    viewed_by_user,
)
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.job_identity import find_confirmed_duplicate
from job_hunter_agent.match_labels import score_to_match_label
from job_hunter_agent.paths import RESULTS_TEMPLATE_PATH
from job_hunter_agent.posting_utils import (
    current_posted_age_days,
    format_timestamp_label,
    posted_display_label,
)
from job_hunter_agent.preferences import display_work_type_label
from job_hunter_agent.profile_gaps import (
    STATUS_CONFIRMED_DO_NOT_HAVE,
    STATUS_CONFIRMED_HAVE,
    STATUS_UNKNOWN,
    classify_requirement_status,
    compute_profile_gaps,
)
from job_hunter_agent.preferences import get_match_preferences
from job_hunter_agent.profile_store import (
    ENGAGEMENT_TYPE_OPTIONS,
    Engagement,
    VALID_ENGAGEMENT_TYPES,
    get_match_levels,
    load_profile,
    normalize_engagement_type_preferences,
)
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EASY_APPLY,
    APPLY_METHOD_QUICK_APPLY,
    RECORD_APPLY_METHOD_KEY,
    RECORD_DUPLICATE_LINKS_KEY,
    RECORD_JOB_REQUIREMENTS_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_DEBUG_REASON_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_ELAPSED_MS_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_POTENTIAL_DUPLICATE_LINKS_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)
from job_hunter_agent.salary_utils import salary_sort_value
from job_hunter_agent.score_labels import (
    render_badge,
    salary_fit_label,
    score_to_tone_class,
    viewed_badge_html,
)
from job_hunter_agent.signal_detection import (
    competitive_signal_assessments,
    hard_block_reasons,
)
from job_hunter_agent.signal_schema import TITLE_REASON_POTENTIAL_MATCH
from job_hunter_agent.source_registry import get_source_display_label
from job_hunter_agent.text_processing import (
    build_role_summary,
    compact_whitespace,
    dedupe_preserve_order,
    list_to_phrase,
    synthesize_role_snapshot,
)
from job_hunter_agent.user_settings import get_workspace_minimum_score
from job_hunter_agent.utils import safe_html
from job_hunter_agent.work_mode_extraction import (
    WORK_MODE_UNKNOWN,
    display_work_mode_label,
    extract_from_text,
)

logger = logging.getLogger(__name__)

WORKSPACE_DEBUG_MODE = DEBUG_MODE

DESCRIPTION_CAPTURE_ISSUE = "Full job description not captured clearly"
TITLE_BLOCK_GUIDANCE_COPY = (
    "Job sites often return broad results even when the search is correct. "
    "If a title clearly does not match what you want, you can block similar titles directly from the title. "
    "This helps remove repeated noise from future results."
)
TITLE_BLOCK_PROMPT_COPY = "Block future titles before description review."
TITLE_BLOCK_HELP_SUMMARY = "Learn more"
TITLE_BLOCK_MANUAL_HELP = "Adds to the checked words above. Use commas to add more than one."
TITLE_BLOCK_STRONG_FILTER_COPY = (
    "This is a strong filter. Matching titles will be hidden before description review."
)
_WORKSPACE_PAGE_LABEL_KEYS = (
    "hero_title",
    "potential_jobs_tab",
    "applied_jobs_tab",
    "hidden_jobs_tab",
    "match_controls_heading",
    "reset_all_filters_button",
    "sort_label",
    "sort_option_best_match",
    "sort_option_newest",
    "sort_option_highest_salary",
    "jobs_per_page_label",
    "filters_label",
    "show_label",
    "show_option_all_potential",
    "show_option_matches_last_run",
    "posted_label",
    "type_label",
    "work_mode_label",
    "work_mode_option_any",
    "work_mode_option_remote",
    "work_mode_option_hybrid",
    "work_mode_option_on_site",
    "sector_label",
    "sector_option_any",
    "sector_option_public",
    "sector_option_private",
    "match_level_label",
    "results_helper_copy",
    "results_helper_dismiss_button",
    "applied_jobs_heading",
    "applied_jobs_copy",
    "hidden_jobs_heading",
    "hidden_jobs_copy",
    "search_settings_heading",
    "search_settings_helper",
    "keywords_label",
    "locations_label",
    "work_type_sidebar_label",
    "work_mode_sidebar_label",
    "sector_sidebar_label",
    "salary_min_label",
    "date_range_label",
    "last_run_heading",
    "crawler_stats_heading",
    "crawler_stats_helper",
    "applications_heading",
    "run_efficiency_summary",
    "show_hide_hint",
    "run_efficiency_intro",
    "run_efficiency_separator",
    "how_match_levels_work_summary",
    "how_match_levels_work_copy",
    "rejection_panel_title",
    "rejection_panel_copy",
    "rejection_how_this_works_summary",
    "rejection_how_this_works_body",
    "rejection_loading_suggestions",
    "rejection_add_own_term_label",
    "rejection_add_own_term_placeholder",
    "rejection_add_button",
    "rejection_save_button",
    "rejection_skip_button",
    "rejection_cancel_button",
    "rejection_admin_tip_prefix",
    "rejection_admin_tip_link_text",
)
ARCHIVE_LABEL = "Saved Earlier Searches"
ARCHIVE_BADGE_TOOLTIP = "This role was saved from an earlier search and kept on your workspace."
ARCHIVE_CONTEXT_PREFIX = "Saved Earlier Searches"


@lru_cache(maxsize=1)
def _workspace_ui_labels() -> dict:
    return load_ui_labels()


def load_workspace_page_labels() -> dict[str, str]:
    labels = _workspace_ui_labels().get("workspace_page_labels", {})
    if not isinstance(labels, dict):
        raise ValueError("ui_labels.json is missing workspace_page_labels")
    missing = [key for key in _WORKSPACE_PAGE_LABEL_KEYS if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing workspace_page_labels values: {', '.join(missing)}"
        )
    return {
        f"LABEL_WS_{key.upper()}": escape(str(labels[key]).strip())
        for key in _WORKSPACE_PAGE_LABEL_KEYS
    }


def _workspace_label(group: str, key: str, default: str) -> str:
    payload = _workspace_ui_labels().get(group, {})
    if isinstance(payload, dict):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return default


def _workspace_job_card_id(job_key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", compact_whitespace(job_key).lower()).strip("-")
    return f"job-card-{slug}" if slug else "job-card"


def _duplicate_match_label(matched_on: str) -> str:
    key = f"match_on_{matched_on}"
    return _workspace_label("duplicate_labels", key, matched_on.replace("_", " "))


_CAPABILITY_ENTRY_TAGS = ("[canonical]", "[alias:", "[contextual_llm]")

_NV1_PATTERNS = re.compile(r"\bnv\s*1\b|\bnegative\s+vetting\s*1\b", re.IGNORECASE)
_CLEARANCE_PATTERNS = re.compile(
    r"\b(baseline|nv\s*2|top\s+secret|protected)\s*(clearance)?\b|\bclearance\s+required\b",
    re.IGNORECASE,
)


def _humanize_check_item(text: str) -> str:
    """Convert raw hard-block / risk text into plain-English check items."""
    t = safe_html(text)
    lower = text.lower()
    if _NV1_PATTERNS.search(lower):
        return (
            "This job appears to require NV1 clearance. "
            "Your profile does not show NV1, so this may block the application."
        )
    if _CLEARANCE_PATTERNS.search(lower):
        return (
            "This job appears to require a security clearance. "
            "Check whether your clearance level meets the requirement before applying."
        )
    return t


def _workspace_job_reference_html(job_key_raw: str, *parts: str) -> str:
    label_parts = [safe_html(part) for part in parts if compact_whitespace(part)]
    label_html = " \u2014 ".join(label_parts)
    if label_html and job_key_raw:
        return f'<a href="#{safe_html(_workspace_job_card_id(job_key_raw))}">{label_html}</a>'
    return label_html


def _render_attention_needed_before_applying_html(
    history_warning_signals: list[str],
    description_issue: bool,
    is_possible_repost: bool,
    similar_applied_record: Optional[dict],
    candidate_history: Optional[dict],
    missing_profile_support: list[str],
    salary_fit_state: str,
) -> str:
    """Render the single strict attention strip for the highest-priority issue."""

    message_html = ""
    if history_warning_signals:
        message_html = (
            f'Potential red flag: {safe_html(history_warning_signals[0].removeprefix("Potential red flag: ").strip())}.'
        )
    elif description_issue:
        message_html = "Description issue: full job description was not captured clearly."
    elif is_possible_repost:
        similar_applied_job_key_raw = str((similar_applied_record or {}).get("job_key") or "").strip()
        repost_reference_html = _workspace_job_reference_html(
            similar_applied_job_key_raw,
            str((similar_applied_record or {}).get("title") or "").strip(),
            str((similar_applied_record or {}).get("company") or "").strip(),
            get_source_display_label(
                str((similar_applied_record or {}).get("source") or "").strip().lower()
            ),
        )
        if repost_reference_html:
            message_html = "Possible repost of applied job: " + repost_reference_html
    elif isinstance(candidate_history, dict) and candidate_history:
        cand_company = str(candidate_history.get("llm_company") or "").strip()
        cand_role = str(candidate_history.get("llm_role") or "").strip()
        cand_status = str(candidate_history.get("llm_application_status") or "").strip()
        cand_confidence = str(candidate_history.get("llm_confidence") or "").strip().lower()
        if cand_company or cand_role:
            history_label = "Rejected before" if cand_status == "rejection" and cand_confidence != "low" else "Possible previous application"
            message_html = f"{history_label}: {_workspace_job_reference_html('', cand_company, cand_role)}"
    elif missing_profile_support:
        message_html = f"Critical missing requirement: {safe_html(str(missing_profile_support[0]))}"
    elif salary_fit_state == "below":
        message_html = "Salary below target."
    if not message_html:
        return ""
    return (
        '<div class="job-note">'
        "<strong>Attention needed before applying:</strong> "
        f"{message_html}"
        "</div>"
    )


def _is_capability_entry(label: str) -> bool:
    return any(tag in label for tag in _CAPABILITY_ENTRY_TAGS)


def _all_work_types_selected(active_profile: Optional[dict]) -> bool:
    if not isinstance(active_profile, dict):
        return False

    prefs = get_match_preferences(active_profile)
    selected = frozenset(normalize_engagement_type_preferences(prefs.get("engagement_type")))
    return selected == VALID_ENGAGEMENT_TYPES


def _work_type_fit_reason(record: dict, active_profile: Optional[dict]) -> str:
    if _all_work_types_selected(active_profile):
        return ""

    work_type_label = display_work_type_label(record)
    if not work_type_label:
        return ""

    prefs = get_match_preferences(active_profile or {})
    selected = set(normalize_engagement_type_preferences(prefs.get("engagement_type")))
    if not selected:
        return ""

    if work_type_label in {"Contract", "FTC"} and Engagement.CONTRACT in selected:
        return "This matches your contract preference."
    if work_type_label == "Permanent" and Engagement.PERMANENT in selected:
        return "This matches your permanent preference."
    if work_type_label == "FTC" and Engagement.FULL_TIME_CONTRACT in selected:
        return "This matches your FTC preference."
    return ""


def _visible_reason_text(reason: str, active_profile: Optional[dict]) -> str:
    cleaned = compact_whitespace(reason)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if cleaned.startswith("[") and "requirement" in lowered:
        return ""
    if lowered.startswith("competitive signal") or lowered.startswith("signal elsewhere"):
        return ""
    if "role-family" in lowered:
        if "alternative" in lowered:
            return "The job title matches one of your alternative roles"
        return "The job title matches one of your target roles"
    if lowered.startswith("description fit is"):
        return "The job ad strongly matches your BA / technical BA experience"
    if lowered.startswith("work type"):
        return ""
    return cleaned


def _score_gap_text(key: str, default: str, **kwargs: object) -> str:
    try:
        return default.format(**kwargs)
    except Exception:
        return default


def _humanize_score_breakdown_label(label: str, active_profile: Optional[dict]) -> str:
    cleaned = compact_whitespace(label)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if "role-family" in lowered:
        if "alternative" in lowered or "also-consider" in lowered:
            return "The job title matches one of your alternative roles"
        return "The job title matches one of your target roles"
    if lowered.startswith("description fit is"):
        return "The job ad strongly matches your BA / technical BA experience"
    if lowered.startswith("work type"):
        if _all_work_types_selected(active_profile):
            return ""
        if "contract" in lowered:
            return "This matches your contract preference"
        if "permanent" in lowered:
            return "This matches your permanent preference"
        if "ftc" in lowered:
            return "This matches your FTC preference"
        return "Work type matches your preference"
    if lowered.startswith("[") and "requirement supported:" in lowered:
        match = re.search(
            r"requirement supported:\s*(.*?)(?:\s*\|\s*capability:.*)?$",
            cleaned,
            re.IGNORECASE,
        )
        if match:
            requirement = compact_whitespace(match.group(1))
            if requirement:
                return f"Requirement matched: {requirement}"
    if cleaned == "Passed content filters":
        return "Passed content filters"
    if cleaned == "Already viewed by you":
        return "Already viewed by you"
    return cleaned


def visible_fit_reasons(
    fit_highlights: List[str],
    score_breakdown: List[dict],
    max_items: int = 4,
    include_values: bool = False,
    active_profile: Optional[dict] = None,
    work_type_reason: str = "",
    work_type_value: Optional[int] = None,
) -> List[str]:
    reason_items: list[tuple[str, Optional[int]]] = []
    seen_reasons: set[str] = set()

    for item in fit_highlights:
        reason = compact_whitespace(item)
        if not reason:
            continue
        normalized = reason.lower()
        if normalized in seen_reasons:
            continue
        reason_items.append((reason, None))
        seen_reasons.add(normalized)

    excluded = {
        "Base fit",
        "Passed content filters",
    }
    # Work type is only a fit reason when the user has a specific work type preference.
    # When all types are accepted, it's a neutral fact shown as a badge, not a fit signal.
    suppress_work_type = _all_work_types_selected(active_profile)

    for item in score_breakdown:
        label = compact_whitespace(item.get("label") or "")
        value = int(item.get("value", 0) or 0)
        if not label or value <= 0 or label in excluded:
            continue
        if _is_capability_entry(label):
            continue
        if label.startswith("[") and "requirement" in label.lower():
            continue
        if suppress_work_type and label.startswith("Work type"):
            continue

        reason = _visible_reason_text(label, active_profile)
        if not reason:
            continue
        normalized = reason.lower()
        if normalized in seen_reasons:
            continue
        reason_items.append((reason, value))
        seen_reasons.add(normalized)
        if len(reason_items) >= max_items:
            break

    reason_items = reason_items[:max_items]

    if work_type_reason:
        normalized = compact_whitespace(work_type_reason).lower()
        if normalized and normalized not in seen_reasons:
            reason_items.append((compact_whitespace(work_type_reason), work_type_value))
            seen_reasons.add(normalized)

    if include_values:
        formatted_reasons = []
        for reason, val in reason_items:
            if val is not None:
                formatted_reasons.append(f"{reason}: {val:+d}")
            else:
                formatted_reasons.append(reason)
        return formatted_reasons

    return [reason for reason, _ in reason_items]


def _fit_summary_candidates_from_coverage(raw_coverage: Any) -> list[str]:
    if not isinstance(raw_coverage, list):
        return []

    importance_rank = {
        "mandatory": 0,
        "strongly_preferred": 1,
        "preferred": 2,
        "nice_to_have": 3,
    }
    status_rank = {
        "supported": 0,
        "partially_supported": 1,
    }
    candidates: list[tuple[int, int, int, str]] = []
    seen: set[str] = set()

    for index, item in enumerate(raw_coverage):
        if not isinstance(item, dict):
            continue
        status = compact_whitespace(str(item.get("status") or "")).lower()
        if status not in {"supported", "partially_supported"}:
            continue
        requirement = compact_whitespace(str(item.get("requirement") or ""))
        if not requirement:
            continue
        normalized = requirement.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        importance = compact_whitespace(str(item.get("importance") or "preferred")).lower()
        candidates.append(
            (
                importance_rank.get(importance, 99),
                status_rank.get(status, 99),
                index,
                requirement,
            )
        )

    candidates.sort()
    return [item[3] for item in candidates[:5]]


def _build_fit_summary_text(raw_coverage: Any) -> str:
    summary_items = _fit_summary_candidates_from_coverage(raw_coverage)
    if not summary_items:
        return ""

    return (
        "This role looks like a good fit because the ad asks for "
        f"{list_to_phrase(summary_items)}, and the candidate profile shows support for those areas."
    )


def negative_score_reasons(
    score_breakdown: List[dict],
    max_items: int = 4,
    include_values: bool = True,
) -> List[str]:
    rules = load_ui_labels()
    friendly_labels = rules.get("negative_score_labels", {})
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
    capability_entries = [
        item
        for item in score_breakdown
        if _is_capability_entry(compact_whitespace(item.get("label") or ""))
    ]
    evidence_points = sum(int(item.get("value", 0) or 0) for item in capability_entries)
    gaps: List[str] = []

    if not any(
        label.startswith("Posted within") or label == "Still relatively recent" for label in labels
    ):
        gaps.append(
            _score_gap_text(
                "no_recent_posted_signal",
                "Posting date wasn't clear, so the age could not be counted.",
            )
        )

    if not any(label in {"Salary/rate signal", "Salary/rate below target"} for label in labels):
        salary = compact_whitespace(record.get("salary") or "")
        if not salary or salary == "N/A":
            gaps.append(
                _score_gap_text(
                    "no_comparable_salary_rate",
                    "No salary info was available, so pay fit could not be compared.",
                )
            )

    if evidence_points < 12:
        capability_count = len(capability_entries)
        if capability_count == 0:
            gaps.append("No capability matches were counted for this card.")
        elif capability_count == 1:
            gaps.append("1 capability match was counted for this card.")
        else:
            gaps.append(f"{capability_count} capability matches were counted for this card.")

    if full_description_confidence(record) == "LOW":
        gaps.append(
            _score_gap_text(
                "limited_description_confidence",
                "The full description wasn't captured clearly, so some scoring may be missing.",
            )
        )

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
    scoring_profile: Optional[dict] = None,
    workspace_min_score: Optional[int] = None,
    debug_mode: bool = WORKSPACE_DEBUG_MODE,
) -> List[int]:
    active_profile = scoring_profile or load_profile()
    match_levels = get_match_levels(active_profile)
    active_workspace_min_score = (
        int(workspace_min_score)
        if workspace_min_score is not None
        else get_workspace_minimum_score()
    )
    if debug_mode:
        return [int(level.get("minimum_score", 0) or 0) for level in match_levels]
    return [
        int(level.get("minimum_score", 0) or 0)
        for level in match_levels
        if int(level.get("minimum_score", 0) or 0) >= active_workspace_min_score
    ]


def render_score_filter_options(
    scoring_profile: Optional[dict] = None,
    workspace_min_score: Optional[int] = None,
    debug_mode: bool = WORKSPACE_DEBUG_MODE,
) -> str:
    active_profile = scoring_profile or load_profile()
    active_workspace_min_score = (
        int(workspace_min_score)
        if workspace_min_score is not None
        else get_workspace_minimum_score()
    )
    if debug_mode:
        active_workspace_min_score = 0
    options = [
        '<option value="all"{selected}>All match levels</option>'.format(
            selected=" selected" if debug_mode else ""
        )
    ]
    for threshold in score_filter_thresholds(
        active_profile, active_workspace_min_score, debug_mode=debug_mode
    ):
        selected_attr = (
            " selected" if (not debug_mode and active_workspace_min_score == threshold) else ""
        )
        options.append(
            f'<option value="{threshold}"{selected_attr}>'
            f"{safe_html(score_filter_option_label(threshold, active_profile))}</option>"
        )
    return "".join(options)


def posted_filter_option_label(threshold: int) -> str:
    rules = load_ui_labels()
    labels = rules.get("posted_threshold_labels", {})
    return labels.get(str(threshold), f"Last {threshold} days")


def render_posted_filter_options(records: List[dict], now: Optional[datetime] = None) -> str:
    options = [f'<option value="all" selected>Any posted date ({len(records)})</option>']
    for threshold in [1, 3, 7, 14, 30]:
        count = sum(
            1
            for record in records
            if (age_days := current_posted_age_days(record, now)) is not None
            and age_days <= threshold
        )
        options.append(
            f'<option value="{threshold}">'
            f"{safe_html(posted_filter_option_label(threshold))} ({count})</option>"
        )
    return "".join(options)


def render_work_type_filter_options() -> str:
    options = ['<option value="all">Any type</option>']
    for item in ENGAGEMENT_TYPE_OPTIONS:
        value = str(item.get("value") or "").strip().lower()
        label = str(item.get("label") or "").strip()
        if not value or not label:
            continue
        options.append(f'<option value="{safe_html(value)}">{safe_html(label)}</option>')
    return "".join(options)


def render_page_size_options() -> str:
    jobs_per_page_label = (
        str(
            _workspace_ui_labels().get("workspace_page_labels", {}).get("jobs_per_page_label")
            or "Jobs per page"
        )
        .strip()
        .lower()
    )
    options = []
    for size in (12, 24, 48, 96):
        selected = " selected" if size == 12 else ""
        options.append(
            f'<option value="{size}"{selected}>{size} {safe_html(jobs_per_page_label)}</option>'
        )
    return "".join(options)


def render_page_size_select_html() -> str:
    labels = load_workspace_page_labels()
    return (
        f'<select id="page_size_select" class="jh-select" aria-label="{labels["LABEL_WS_JOBS_PER_PAGE_LABEL"]}">'
        f"{render_page_size_options()}"
        "</select>"
    )


def _record_is_hard_blocked(record: dict) -> bool:
    reject_reason = str(record.get("reject_reason") or record.get("content_reason") or "").strip()
    if reject_reason.startswith("DESC_HARD_BLOCK_RULE"):
        return True
    hard_blocks = record.get("hard_block_reasons")
    return isinstance(hard_blocks, list) and any(str(item).strip() for item in hard_blocks)


def _record_debug_status(record: dict) -> str:
    if str(record.get("decision") or "").strip().upper() != "REJECT":
        return ""
    return "hard-blocked" if _record_is_hard_blocked(record) else "debug-only"


def humanize_reject_reason(reason: Optional[str]) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return "Other filtered-out roles"

    rules = load_ui_labels()
    direct_map = rules.get("reject_reason_human_map", {})
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
    if prefix == "PREF_SECTOR_OUTSIDE_SELECTED":
        return "Rejected because job sector is outside selected sectors."
    if prefix == TITLE_REASON_POTENTIAL_MATCH:
        return (
            load_ui_labels()
            .get("title_match_labels", {})
            .get("secondary_match", "Also-consider role-family match")
        )
    if prefix == "CARD_SPECIALIST" and cleaned_detail:
        return f"Rejected early from card metadata: {cleaned_detail}"
    fallback = raw.replace("_", " ").lower()
    return fallback[:1].upper() + fallback[1:]


def render_job_card(
    record: dict,
    scoring_profile: Optional[dict] = None,
    applied_pool: Optional[List[dict]] = None,
    history_clusters: Optional[Dict[str, dict]] = None,
    debug_mode: Optional[bool] = None,
) -> str:
    active_debug_mode = WORKSPACE_DEBUG_MODE if debug_mode is None else bool(debug_mode)
    default_country_suffix = get_default_country_suffix()
    active_profile = scoring_profile or load_profile()
    display_record = dict(record)
    loc = str(display_record.get("location") or "").strip()
    if default_country_suffix and loc.endswith(f", {default_country_suffix}"):
        display_record["location"] = loc[: -(len(default_country_suffix) + 2)].strip()

    title = safe_html(record.get("title", "Untitled"))
    company_display = normalize_company_name(
        str(record.get("company") or "")
    ) or compact_whitespace(str(record.get("company") or "N/A"))
    url = safe_html(record.get("url", "#"))
    job_key = safe_html(str(record.get("job_key") or ""))
    title_reason = record.get("title_reason")
    applied_record = bool(record.get("applied"))
    archived = bool(record.get("archived"))
    hidden_record = bool(record.get("hidden"))
    is_stale = bool(record.get("is_stale"))
    seen_by_you = viewed_by_user(record)
    stored_snapshot = compact_whitespace(
        record.get("role_snapshot") or record.get("teaser") or "N/A"
    )
    if stored_snapshot in {"", "N/A"}:
        stored_snapshot = synthesize_role_snapshot(record)
    fit_confidence_level = full_description_confidence(record)
    trusted_desc = get_trusted_full_description(record)

    if fit_confidence_level == "HIGH" and trusted_desc:
        display_record["fit_source_text"] = trusted_desc
        display_record["fit_confidence"] = "HIGH"
        # Refresh work mode from description only if stored extraction found nothing useful.
        # Metadata-sourced values (seek_detail_payload, linkedin_structured, etc.) are
        # more reliable than text inference — don't override them at display time.
        stored_source = record.get("work_mode_source", "")
        if not stored_source or stored_source == "fallback_text":
            text_result = extract_from_text(trusted_desc)
            if text_result["work_mode"] != WORK_MODE_UNKNOWN:
                display_record["work_mode"] = text_result["work_mode"]
        role_summary = build_role_summary(record, trusted_desc, active_profile)
        display_record["competitive_signals"] = competitive_signal_assessments(
            record, active_profile
        )
        fit_highlights = build_fit_highlights(record, trusted_desc, active_profile)
        soft_risk_reasons, missing_profile_support = build_risk_and_missing_profile_support(
            trusted_desc,
            title_reason,
            active_profile,
            competitive_signals=display_record.get("competitive_signals")
            if isinstance(display_record.get("competitive_signals"), list)
            else None,
        )
        blocking_reasons = hard_block_reasons(display_record, active_profile)
        if blocking_reasons:
            missing_profile_support = dedupe_preserve_order(
                [*blocking_reasons, *missing_profile_support]
            )
    else:
        role_summary = stored_snapshot
        display_record["fit_confidence"] = "LOW"
        display_record["competitive_signals"] = []
        fit_highlights = []
        soft_risk_reasons = []
        missing_profile_support = [DESCRIPTION_CAPTURE_ISSUE]
        blocking_reasons = []

    similar_applied_record = None
    is_possible_repost = False
    if not applied_record and applied_pool:
        similar_applied_record = find_confirmed_duplicate(record, applied_pool)
        is_possible_repost = similar_applied_record is not None
    domain_qualifier = _detect_title_domain_qualifier(str(record.get("title") or ""))
    if domain_qualifier:
        soft_risk_reasons = dedupe_preserve_order([
            *soft_risk_reasons,
            f"The title specifies a '{domain_qualifier}' domain — check the description confirms this matches your background.",
        ])
    _record_source = str(record.get("source") or "").lower().strip()
    if _record_source == "linkedin" and record.get("posted_age_days") is None:
        soft_risk_reasons = dedupe_preserve_order([
            *soft_risk_reasons,
            "Freshness unknown — LinkedIn did not provide a post date for this listing. Confirm it is still open before applying.",
        ])
    display_record["hard_block_reasons"] = blocking_reasons
    display_record["role_snapshot"] = role_summary
    display_record["fit_highlights"] = fit_highlights
    display_record["soft_risk_reasons"] = soft_risk_reasons
    display_record["missing_profile_support"] = missing_profile_support
    try:
        fit_points, score_breakdown = fit_score_and_breakdown_displayed(display_record, scoring_profile)
    except RuntimeError as _score_exc:
        _review_note = (
            "LLM started review but grade is missing (partial pipeline run)"
            if display_record.get("llm_decision")
            else "LLM never reviewed this job (pipeline not run or job was pre-filtered)"
        )
        _debug_note = (
            " — visible because --debug bypasses eligibility filtering" if active_debug_mode else ""
        )
        logger.warning(
            "[RENDERER] job=%s title=%r showing score 0: %s%s",
            display_record.get("job_key", "<unknown>"),
            str(display_record.get("title") or "").strip(),
            _review_note,
            _debug_note,
        )
        fit_points = 0
        score_breakdown = []
    match_levels = get_match_levels(scoring_profile or load_profile())
    fit_label = score_to_match_label(fit_points, match_levels)
    fit_tone_class = score_to_tone_class(fit_points, scoring_profile)
    work_type_reason = _work_type_fit_reason(record, active_profile)
    work_type_value = next(
        (
            int(item.get("value", 0) or 0)
            for item in score_breakdown
            if compact_whitespace(item.get("label") or "").lower().startswith("work type")
            and int(item.get("value", 0) or 0) > 0
        ),
        None,
    )
    visible_reasons = visible_fit_reasons(
        fit_highlights,
        score_breakdown,
        include_values=active_debug_mode,
        active_profile=scoring_profile,
        work_type_reason=work_type_reason,
        work_type_value=work_type_value,
    )
    description_issue = fit_confidence_level == "LOW"
    work_mode = str(display_record.get("work_mode") or "N/A")
    posted_age_days = current_posted_age_days(record)
    salary_value = salary_sort_value(str(display_record.get("salary") or ""))
    salary_fit_state = salary_fit_label(display_record, scoring_profile)
    record_kind = (
        "applied"
        if applied_record
        else ("hidden" if hidden_record else ("saved" if archived else "current"))
    )
    company_attr = safe_html(company_display)
    teaser_attr = safe_html(compact_whitespace(str(record.get("teaser") or "")))
    card_sector = "unknown"
    channel_signal = display_record.get("posting_channel_evidence")
    if not isinstance(channel_signal, dict):
        channel_signal = {}
    job_requirements = [
        compact_whitespace(item)
        for item in (display_record.get(RECORD_JOB_REQUIREMENTS_KEY) or [])
        if compact_whitespace(item)
    ]
    candidate_capabilities = active_profile.get("candidate_capabilities") or []
    must_not_require_skills = active_profile.get("must_not_require_skills") or []
    requirement_statuses = [
        {
            "requirement": item,
            "status": classify_requirement_status(
                item, candidate_capabilities, must_not_require_skills
            ),
        }
        for item in job_requirements
    ]
    profile_gaps = compute_profile_gaps(
        job_requirements,
        candidate_capabilities,
        must_not_require_skills,
    )
    duplicate_links = record.get(RECORD_DUPLICATE_LINKS_KEY)
    if not isinstance(duplicate_links, list):
        duplicate_links = []
    potential_duplicate_links = record.get(RECORD_POTENTIAL_DUPLICATE_LINKS_KEY)
    if not isinstance(potential_duplicate_links, list):
        potential_duplicate_links = []
    _block_phrases_list = suggest_title_block_phrases(str(record.get("title") or ""))
    block_phrase = safe_html(_block_phrases_list[0]) if _block_phrases_list else ""
    block_phrases_json = safe_html(json.dumps(_block_phrases_list))
    similar_applied_title = safe_html(str((similar_applied_record or {}).get("title") or ""))
    similar_applied_company = safe_html(str((similar_applied_record or {}).get("company") or "").strip())
    similar_applied_source = str((similar_applied_record or {}).get("source") or "").lower().strip()
    similar_applied_source_label = safe_html(
        get_source_display_label(similar_applied_source) if similar_applied_source else ""
    )
    similar_applied_job_key = safe_html(str((similar_applied_record or {}).get("job_key") or ""))
    button_data_attrs = (
        f'data-job-key="{job_key}" '
        f'data-job-url="{url}" '
        f'data-job-title="{title}" '
        f'data-job-company="{company_attr}" '
        f'data-job-teaser="{teaser_attr}" '
        f'data-role-sector="{safe_html(card_sector)}" '
        f'data-similar-applied-warning="{"1" if is_possible_repost else "0"}" '
        f'data-similar-applied-job-key="{similar_applied_job_key}" '
        f'data-similar-applied-title="{similar_applied_title}" '
        f'data-similar-applied-company="{similar_applied_company}" '
        f'data-similar-applied-source="{similar_applied_source_label}"'
    )
    source = str(record.get("source") or "unknown").lower().strip()
    source_label = get_source_display_label(source)

    badges = []
    if applied_record:
        badges.append(render_badge("Applied", "badge-viewed", "You already applied for this role."))
    elif hidden_record:
        badges.append(render_badge("Hidden", "badge-hidden", "You hid this role for now."))
    elif is_possible_repost:
        badges.append(
            render_badge(
                "Possible Repost",
                "badge-warning",
                "This role looks very similar to one you have already applied to.",
            )
        )
    elif archived:
        badges.append(render_badge(ARCHIVE_LABEL, "badge-archive", ARCHIVE_BADGE_TOOLTIP))
    if not applied_record and not seen_by_you:
        badges.append(
            render_badge(
                "New To You", "badge-new", "You have not opened this role from the workspace yet."
            )
        )
    if is_stale:
        badges.append(
            render_badge(
                "15+ Days Old", "badge-stale", "This role is older, but still saved for reference."
            )
        )
    elif seen_by_you:
        badges.append(viewed_badge_html())
    if description_issue:
        badges.append(
            render_badge(
                "Description Issue",
                "badge-warning",
                "The full job description was not captured clearly, so this match needs manual checking.",
            )
        )
    badges.append(
        render_badge(source_label, f"badge-source-{source}", f"Sourced from {source_label}.")
    )
    apply_method = str(record.get(RECORD_APPLY_METHOD_KEY) or "").strip()
    if apply_method == APPLY_METHOD_EASY_APPLY:
        badges.append(
            render_badge(
                _workspace_label(
                    "workspace_card_labels", "apply_method_easy_apply_badge", "Easy Apply"
                ),
                "badge-apply-method",
                _workspace_label(
                    "workspace_card_labels",
                    "apply_method_easy_apply_tooltip",
                    "Apply directly on the job board with one click.",
                ),
            )
        )
    elif apply_method == APPLY_METHOD_QUICK_APPLY:
        badges.append(
            render_badge(
                _workspace_label(
                    "workspace_card_labels", "apply_method_quick_apply_badge", "Quick Apply"
                ),
                "badge-apply-method",
                _workspace_label(
                    "workspace_card_labels",
                    "apply_method_quick_apply_tooltip",
                    "Apply directly on the job board without leaving the site.",
                ),
            )
        )
    channel_kind = channel_signal.get("kind", "unknown")
    if channel_kind == "agency_or_recruiter":
        badges.append(
            render_badge(
                "Recruiter",
                "badge-source-neutral",
                "Posted via a recruitment agency or third-party recruiter.",
            )
        )
    elif channel_kind == "direct_employer":
        badges.append(
            render_badge("Company", "badge-source-neutral", "Posted directly by the employer.")
        )
    elif channel_signal.get("needs_review"):
        badges.append(
            render_badge(
                _workspace_label(
                    "workspace_card_labels",
                    "posting_channel_likely_recruiter_badge",
                    "Likely recruiter",
                ),
                "badge-warning",
                _workspace_label(
                    "workspace_card_labels",
                    "posting_channel_likely_recruiter_tooltip",
                    "Recruiter language detected in the description. This may be posted on behalf of an employer.",
                ),
            )
        )
    else:
        badges.append(
            render_badge(
                _workspace_label(
                    "workspace_card_labels", "posting_channel_unknown_badge", "Source unclear"
                ),
                "badge-archive",
                _workspace_label(
                    "workspace_card_labels",
                    "posting_channel_unknown_tooltip",
                    "Couldn't determine whether this was posted by the employer directly or via a recruiter.",
                ),
            )
        )
    history_warning_signals = assess_history_warning_signals(record, history_clusters)
    if history_warning_signals:
        badges.append(
            render_badge("Potential Red Flag", "badge-warning", history_warning_signals[0])
        )
    if duplicate_links:
        duplicate_tooltip = _workspace_label(
            "duplicate_labels",
            "confirmed_tooltip",
            "This job already has a matching card in your workspace.",
        )
        badges.append(
            render_badge(
                _workspace_label("duplicate_labels", "confirmed_badge", "Duplicate in workspace"),
                "badge-source-neutral",
                duplicate_tooltip,
            )
        )
    if potential_duplicate_links:
        _pd_first = potential_duplicate_links[0]
        _pd_title = str(_pd_first.get("related_title") or "").strip()
        _pd_company = (
            normalize_company_name(str(_pd_first.get("related_company") or ""))
            or str(_pd_first.get("related_company") or "").strip()
        )
        _pd_count = len(potential_duplicate_links)
        if _pd_title:
            _pd_ref = f"{_pd_title} @ {_pd_company}" if _pd_company else _pd_title
            potential_tooltip = f"Related to {_pd_ref}."
            if _pd_count > 1:
                potential_tooltip += f" +{_pd_count - 1} more."
        else:
            potential_tooltip = _workspace_label(
                "duplicate_labels",
                "potential_tooltip",
                "This job looks related to another card in your workspace.",
            )
        badges.append(
            render_badge(
                _workspace_label("duplicate_labels", "potential_badge", "Related cards"),
                "badge-warning",
                potential_tooltip,
            )
        )
    potential_duplicate_callout = ""
    if potential_duplicate_links:
        related = potential_duplicate_links[0]
        related_title = str(related.get("related_title") or "").strip()
        related_company = (
            normalize_company_name(str(related.get("related_company") or ""))
            or str(related.get("related_company") or "").strip()
        )
        related_job_key = str(related.get("related_job_key") or "").strip()
        related_url = str(related.get("related_url") or "").strip()
        related_label_parts = [
            part
            for part in [related_title, f"@ {related_company}" if related_company else ""]
            if part
        ]
        related_label = " ".join(related_label_parts).strip()
        if related_label and related_job_key:
            related_label_html = f'<a href="#{safe_html(_workspace_job_card_id(related_job_key))}">{safe_html(related_label)}</a>'
        elif related_label and related_url:
            related_label_html = f'<a href="{safe_html(related_url)}" target="_blank" rel="noopener noreferrer">{safe_html(related_label)}</a>'
        else:
            related_label_html = safe_html(related_label)
        if related_label_html:
            potential_duplicate_callout = (
                '<div class="job-duplicate-callout">'
                f"<strong>{safe_html(_workspace_label('duplicate_labels', 'potential_badge', 'Related cards'))}</strong> "
                f"{safe_html(_workspace_label('duplicate_labels', 'callout_prefix', 'Open matching card'))} {related_label_html}. "
                f'<span class="duplicate-help-text">{safe_html(_workspace_label("duplicate_labels", "help_text", "This is the matching card in your workspace. Use it to compare details."))}</span>'
                "</div>"
            )
    job_quality_signals = [
        s for s in (record.get("job_quality_signals") or []) if isinstance(s, dict)
    ]
    for _sig in job_quality_signals:
        badges.append(
            render_badge(
                _sig.get("label", "Quality Concern"), "badge-warning", _sig.get("evidence", "")
            )
        )
    debug_status = _record_debug_status(record)
    if active_debug_mode and debug_status:
        if debug_status == "hard-blocked":
            badges.append(
                render_badge(
                    _workspace_label("workspace_card_labels", "hard_blocked_badge", "Hard blocked"),
                    "badge-hidden",
                    _workspace_label(
                        "workspace_card_labels",
                        "hard_blocked_tooltip",
                        "This role hit a hard blocker and would normally be excluded.",
                    ),
                )
            )
        else:
            badges.append(
                render_badge(
                    _workspace_label("workspace_card_labels", "debug_only_badge", "Debug only"),
                    "badge-source-neutral",
                    _workspace_label(
                        "workspace_card_labels",
                        "debug_only_tooltip",
                        "This role was filtered out in the normal workspace view, but stays visible in debug mode.",
                    ),
                )
            )
    _cand_hist = record.get("candidate_application_history")
    _cand_hist_badge_label = ""
    _cand_hist_needs_review = False
    _cand_hist_review_reason = ""
    _cand_hist_details: dict = {}
    if isinstance(_cand_hist, dict):
        _ch_status = str(_cand_hist.get("llm_application_status") or "").strip()
        _ch_confidence = str(_cand_hist.get("llm_confidence") or "").strip().lower()
        _cand_hist_needs_review = bool(_cand_hist.get("llm_needs_review"))
        _cand_hist_review_reason = str(_cand_hist.get("llm_review_reason") or "").strip()
        _cand_hist_badge_label = (
            "Rejected before"
            if _ch_status == "rejection" and _ch_confidence != "low"
            else "Possible previous application"
        )
        _cand_hist_details = {
            "company": str(_cand_hist.get("llm_company") or "").strip(),
            "role": str(_cand_hist.get("llm_role") or "").strip(),
            "run_date": str(_cand_hist.get("run_date") or "").strip(),
            "confidence": _ch_confidence,
            "evidence": str(_cand_hist.get("llm_evidence") or "").strip(),
        }
    if _cand_hist_badge_label:
        badges.append(
            render_badge(
                _cand_hist_badge_label,
                "badge-warning",
                "A match was found in your candidate application history.",
            )
        )
        if _cand_hist_needs_review:
            badges.append(
                render_badge(
                    "Needs review",
                    "badge-warning",
                    _cand_hist_review_reason or "This match needs manual review.",
                )
            )
    score_percent = max(min(int(fit_points), 100), 0)
    score_html = (
        f'<div class="match-tile {fit_tone_class}" style="--match-score: {score_percent}%;">'
        + (f'<span class="match-tile-number">{fit_points}</span>' if active_debug_mode else "")
        + f'<span class="match-tile-label">{safe_html(fit_label)}</span>'
        + '<span class="match-tile-bar" aria-hidden="true"><span class="match-tile-bar-fill"></span></span>'
        + "</div>"
    )

    _posted_raw = posted_display_label(record)
    posted_display = "" if not _posted_raw or _posted_raw == "N/A" else _posted_raw
    meta_items = []
    if posted_display:
        meta_items.append(
            f'<span class="job-meta-item"><strong>Posted</strong> {safe_html(str(posted_display))}</span>'
        )
    for label, value, always_show in [
        ("Location", display_record.get("location"), False),
        ("Work mode", display_work_mode_label(display_record), False),
        (
            _workspace_label("workspace_meta_labels", "work_type", "Work type"),
            display_work_type_label(display_record),
            False,
        ),
        ("Salary", display_record.get("salary"), False),
    ]:
        if always_show or (value and value != "N/A" and value != "Unknown"):
            meta_items.append(
                f'<span class="job-meta-item"><strong>{safe_html(label)}</strong> {safe_html(str(value))}</span>'
            )
    context_bits = []
    if salary_fit_state == "below":
        soft_risk_reasons = dedupe_preserve_order(
            [
                *soft_risk_reasons,
                "Salary is below target range",
            ]
        )
    if seen_by_you and record.get("last_viewed_at"):
        context_bits.append(f"Opened by you {format_timestamp_label(record.get('last_viewed_at'))}")
    if applied_record and record.get("last_applied_at"):
        context_bits.append(f"Applied {format_timestamp_label(record.get('last_applied_at'))}")
    if hidden_record and record.get("last_hidden_at"):
        context_bits.append(f"Hidden {format_timestamp_label(record.get('last_hidden_at'))}")
    elif archived and record.get("last_kept_at"):
        context_bits.append(
            f"{ARCHIVE_CONTEXT_PREFIX} {format_timestamp_label(record.get('last_kept_at'))}"
        )
    context_html = (
        f'<div class="job-context">{safe_html(" | ".join(context_bits))}</div>'
        if context_bits
        else ""
    )

    summary_html = (
        f'<p class="job-summary">{safe_html(role_summary)}</p>'
        if role_summary and role_summary != "N/A"
        else ""
    )
    note_html = _render_attention_needed_before_applying_html(
        history_warning_signals,
        description_issue,
        is_possible_repost,
        similar_applied_record,
        _cand_hist,
        missing_profile_support,
        salary_fit_state,
    )
    reviewed_signal_matches = reviewed_signal_match_summary(display_record, scoring_profile)
    insight_sections = []
    fit_summary_text = _build_fit_summary_text(display_record.get(RECORD_REQUIREMENT_COVERAGE_KEY))
    if fit_summary_text or visible_reasons:
        visible_reasons_html = (
            f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in visible_reasons)}</ul>"
            if visible_reasons
            else ""
        )
        insight_sections.append(
            '<div class="job-insight-group">'
            "<strong>Why this is a good fit</strong>"
            f'{f"<p class=\"job-fit-summary\">{safe_html(fit_summary_text)}</p>" if fit_summary_text else ""}'
            f"{visible_reasons_html}"
            "</div>"
        )
    if reviewed_signal_matches["matched"]:
        insight_sections.append(
            '<div class="job-insight-group">'
            "<strong>Your approved experience appears in this ad</strong>"
            f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in reviewed_signal_matches['matched'])}</ul>"
            "</div>"
        )
    if active_debug_mode and reviewed_signal_matches["unresolved"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            "<strong>Unclassified details</strong>"
            f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in reviewed_signal_matches['unresolved'])}</ul>"
            "</div>"
        )
    if reviewed_signal_matches["evidence_only"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            "<strong>Found, not scored</strong>"
            f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in reviewed_signal_matches['evidence_only'])}</ul>"
            "</div>"
        )
    if reviewed_signal_matches["ignored"]:
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            "<strong>Filtered out</strong>"
            f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in reviewed_signal_matches['ignored'])}</ul>"
            "</div>"
        )
    if active_debug_mode and debug_status:
        debug_status_items = []
        title_reason_text = str(record.get("title_reason") or "").strip()
        content_reason_text = str(record.get("content_reason") or "").strip()
        reject_reason_text = str(record.get("reject_reason") or "").strip()
        if title_reason_text and title_reason_text.upper() != "OK":
            debug_status_items.append(f"Title filter: {humanize_reject_reason(title_reason_text)}")
        if (
            content_reason_text
            and content_reason_text.upper() != "OK"
            and content_reason_text != title_reason_text
        ):
            debug_status_items.append(
                f"Content filter: {humanize_reject_reason(content_reason_text)}"
            )
        if reject_reason_text and reject_reason_text not in {
            title_reason_text,
            content_reason_text,
        }:
            debug_status_items.append(
                f"Reject reason: {humanize_reject_reason(reject_reason_text)}"
            )
        hard_block_items = [
            str(item).strip()
            for item in (record.get("hard_block_reasons") or [])
            if str(item).strip()
        ]
        if hard_block_items:
            debug_status_items.append(f"Hard blocker details: {'; '.join(hard_block_items)}")
        if debug_status_items:
            insight_sections.append(
                '<div class="job-insight-group is-secondary">'
                f"<strong>{safe_html(_workspace_label('workspace_card_labels', 'debug_status_summary', 'Filter status'))}</strong>"
                f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in debug_status_items)}</ul>"
                "</div>"
            )
    job_requirements_html = ""
    raw_coverage = display_record.get(RECORD_REQUIREMENT_COVERAGE_KEY)
    merged_requirement_rows: dict[str, dict[str, Any]] = {}
    merged_requirement_order: list[str] = []
    # When requirement_coverage is available, show only those rows (they are more
    # detailed and LLM-verified). Skip the short job_requirements bullets to avoid
    # showing the same requirements twice with different text.
    has_coverage = isinstance(raw_coverage, list) and len(raw_coverage) > 0
    coverage_status_labels = {
        "supported": "In profile",
        "partially_supported": "Partial match",
        "not_shown": "",
        "mismatch": "Not in profile",
    }
    profile_status_labels = {
        STATUS_CONFIRMED_HAVE: "In profile",
        STATUS_CONFIRMED_DO_NOT_HAVE: "Not in profile",
        STATUS_UNKNOWN: "",
    }
    importance_label_keys = {
        "mandatory": "importance_mandatory",
        "strongly_preferred": "importance_strongly_preferred",
        "preferred": "importance_preferred",
        "nice_to_have": "importance_nice_to_have",
    }

    def _requirement_key(value: str) -> str:
        return compact_whitespace(value).lower()

    if has_coverage:
        # Coverage path: one row per coverage entry, no job_requirements duplication
        for item in raw_coverage:
            if not isinstance(item, dict):
                continue
            req_text = compact_whitespace(str(item.get("requirement") or ""))
            if not req_text:
                continue
            key = _requirement_key(req_text)
            if key not in merged_requirement_rows:
                merged_requirement_rows[key] = {"requirement": req_text}
                merged_requirement_order.append(key)
            row = merged_requirement_rows[key]
            row["coverage_status"] = str(item.get("status") or "not_shown").strip().lower()
            row["importance"] = str(item.get("importance") or "preferred").strip().lower()
            row["capability_name"] = compact_whitespace(str(item.get("capability_name") or ""))
            row["matched_job_text"] = compact_whitespace(str(item.get("matched_job_text") or ""))
    else:
        # Fallback: no coverage — show job_requirements with profile-match status
        for item in requirement_statuses:
            req_text = compact_whitespace(str(item.get("requirement") or ""))
            if not req_text:
                continue
            key = _requirement_key(req_text)
            if key not in merged_requirement_rows:
                merged_requirement_rows[key] = {"requirement": req_text}
                merged_requirement_order.append(key)
            merged_requirement_rows[key]["profile_status"] = item.get("status")

    if requirement_statuses or isinstance(raw_coverage, list):
        requirement_items_html = ""
        for key in merged_requirement_order:
            row = merged_requirement_rows.get(key)
            if not isinstance(row, dict):
                continue
            req_text = compact_whitespace(str(row.get("requirement") or ""))
            if not req_text:
                continue
            profile_status = str(row.get("profile_status") or "").strip()
            coverage_status = str(row.get("coverage_status") or "").strip().lower()
            importance = str(row.get("importance") or "").strip().lower()
            cap_name = compact_whitespace(str(row.get("capability_name") or ""))
            matched_text = compact_whitespace(str(row.get("matched_job_text") or ""))

            if coverage_status == "supported":
                css_modifier = "supported"
            elif coverage_status == "partially_supported":
                css_modifier = "partially-supported"
            elif coverage_status == "mismatch":
                css_modifier = "mismatch"
            elif coverage_status == "not_shown" and importance == "mandatory":
                css_modifier = "mandatory-not-shown"
            elif coverage_status == "not_shown":
                css_modifier = "not-shown"
            elif profile_status == STATUS_CONFIRMED_HAVE:
                css_modifier = "confirmed-have"
            elif profile_status == STATUS_CONFIRMED_DO_NOT_HAVE:
                css_modifier = "confirmed-do-not-have"
            else:
                css_modifier = "unknown"

            if coverage_status:
                status_label = coverage_status_labels.get(coverage_status, "")
            else:
                status_label = profile_status_labels.get(profile_status, "")

            importance_label = ""
            if importance:
                importance_label = _workspace_label(
                    "workspace_card_labels",
                    importance_label_keys.get(importance, "importance_preferred"),
                    importance.replace("_", " ").title(),
                )

            detail_parts = []
            if cap_name:
                detail_parts.append(cap_name)
            if matched_text and compact_whitespace(matched_text).lower() != req_text.lower():
                detail_parts.append(f'"{matched_text}"')
            detail_html = (
                f'<span class="req-coverage-detail">{safe_html(" · ".join(detail_parts))}</span>'
                if detail_parts
                else ""
            )
            importance_html = (
                f'<span class="job-req-importance">{safe_html(importance_label)}</span>'
                if importance_label
                else ""
            )
            status_html = (
                f'<span class="job-requirement-status">{safe_html(status_label)}</span>'
                if status_label
                else ""
            )

            add_to_profile_html = ""
            if css_modifier in ("mismatch", "not-shown", "mandatory-not-shown", "unknown"):
                add_to_profile_html = (
                    f'<a class="req-add-to-profile" href="/settings#section-matrix" '
                    f'data-prefill="{safe_html(req_text)}" '
                    f'title="Add this to your capability profile" target="_blank" rel="noopener">'
                    f'+ Add to profile</a>'
                )
            requirement_items_html += (
                f'<li class="job-requirement-item job-requirement-item--{safe_html(css_modifier)}">'
                f'<span class="job-requirement-text">{safe_html(req_text)}{detail_html}</span>'
                f"{importance_html}"
                f"{status_html}"
                f"{add_to_profile_html}"
                f"</li>"
            )

        if requirement_items_html:
            job_requirements_html = (
                '<details class="job-insights job-requirements-panel">'
                f"<summary>{safe_html(_workspace_label('workspace_card_labels', 'job_requirements_summary', 'Requirements'))}</summary>"
                f'<div class="job-insight-group is-secondary"><ul class="job-requirement-list">{requirement_items_html}</ul></div>'
                "</details>"
            )
        else:
            job_requirements_html = (
                '<details class="job-insights job-requirements-panel">'
                f"<summary>{safe_html(_workspace_label('workspace_card_labels', 'job_requirements_summary', 'Requirements'))}</summary>"
                '<div class="job-insight-group is-secondary">'
                f'<p class="job-requirements-empty">{safe_html(_workspace_label("workspace_card_labels", "job_requirements_empty_state", "No requirements were extracted for this job."))}</p>'
                '</div>'
                "</details>"
            )

    profile_gaps_html = ""
    if profile_gaps:
        gap_items_html = "".join(
            f'<div class="job-gap-item">'
            f'<span class="job-gap-requirement">{safe_html(gap["requirement"])}</span>'
            f'<div class="job-gap-actions">'
            f'<button class="gap-btn gap-btn--have" data-requirement="{safe_html(gap["requirement"])}" data-action="confirm_have">Yes, I have this</button>'
            f'<button class="gap-btn gap-btn--not-have" data-requirement="{safe_html(gap["requirement"])}" data-action="confirm_do_not_have">No, I don\'t have this</button>'
            f'<button class="gap-btn gap-btn--later" data-requirement="{safe_html(gap["requirement"])}" data-action="decide_later">Decide later</button>'
            f"</div>"
            f"</div>"
            for gap in profile_gaps
        )
        profile_gaps_html = (
            f'<div class="job-gaps-block" data-job-key="{job_key}">'
            f'<div class="job-gap-heading">Needs confirmation ({len(profile_gaps)})</div>'
            f'<div class="job-gap-items">{gap_items_html}</div>'
            f"</div>"
        )
    if duplicate_links:
        linked_items = []
        for item in duplicate_links:
            matched_on = _duplicate_match_label(str(item.get("matched_on") or ""))
            related_job_key = str(item.get("job_key") or "").strip()
            related_url = str(item.get("url") or "").strip()
            related_title = str(item.get("title") or "").strip()
            title_html = safe_html(related_title)
            if related_title and related_job_key:
                title_html = f'<a href="#{safe_html(_workspace_job_card_id(related_job_key))}">{safe_html(related_title)}</a>'
            elif related_title and related_url:
                title_html = f'<a href="{safe_html(related_url)}" target="_blank" rel="noopener noreferrer">{safe_html(related_title)}</a>'
            parts = [
                safe_html(str(item.get("source") or "").strip().title()),
                safe_html(
                    normalize_company_name(str(item.get("company") or ""))
                    or str(item.get("company") or "").strip()
                ),
                title_html,
                safe_html(f"matched on {matched_on}") if matched_on else "",
            ]
            linked_items.append(" | ".join(bit for bit in parts if bit))
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            f"<strong>{safe_html(_workspace_label('duplicate_labels', 'confirmed_section_heading', 'Matching cards'))}</strong>"
            f"<ul>{''.join(f'<li>{item}</li>' for item in linked_items)}</ul>"
            "</div>"
        )
    if potential_duplicate_links:
        linked_items = []
        for item in potential_duplicate_links:
            matched_on = list_to_phrase(
                [
                    _duplicate_match_label(str(value))
                    for value in (item.get("matched_on") or [])
                    if str(value).strip()
                ]
            )
            related_title = str(item.get("related_title") or "").strip()
            related_company = (
                normalize_company_name(str(item.get("related_company") or ""))
                or str(item.get("related_company") or "").strip()
            )
            related_source = str(item.get("related_source") or "").strip().title()
            related_url = str(item.get("related_url") or "").strip()
            related_job_key = str(item.get("related_job_key") or "").strip()
            title_html = safe_html(related_title)
            if related_title and related_job_key:
                title_html = f'<a href="#{safe_html(_workspace_job_card_id(related_job_key))}">{safe_html(related_title)}</a>'
            elif related_title and related_url:
                title_html = f'<a href="{safe_html(related_url)}" target="_blank" rel="noopener noreferrer">{safe_html(related_title)}</a>'
            parts = [
                safe_html(related_source),
                safe_html(related_company),
                safe_html(f"matched on {matched_on}") if matched_on else "",
            ]
            item_text = " | ".join(bit for bit in parts if bit)
            if title_html:
                item_text = f"{item_text} | {title_html}" if item_text else title_html
            linked_items.append(item_text)
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            f"<strong>{safe_html(_workspace_label('duplicate_labels', 'potential_section_heading', 'Related cards'))}</strong>"
            f"<ul>{''.join(f'<li>{item}</li>' for item in linked_items)}</ul>"
            "</div>"
        )
    visible_penalties = negative_score_reasons(score_breakdown, include_values=active_debug_mode)
    if description_issue:
        visible_penalties = [
            item
            for item in visible_penalties
            if not item.startswith("Description capture incomplete")
        ]
    negative_items = dedupe_preserve_order(
        [
            *([] if description_issue else missing_profile_support),
            *soft_risk_reasons,
        ]
    )[:6]
    if description_issue:
        description_issue_items = [DESCRIPTION_CAPTURE_ISSUE]
        if active_debug_mode:
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
            "<strong>Incomplete description</strong>"
            f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in description_issue_items)}</ul>"
            "</div>"
        )
    if history_warning_signals:
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            "<strong>Potential red flags</strong>"
            f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in history_warning_signals)}</ul>"
            "</div>"
        )
    if job_quality_signals:
        _quality_items = "".join(
            f"<li>{safe_html(s.get('evidence', ''))}</li>" for s in job_quality_signals
        )
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            "<strong>Job quality concerns</strong>"
            f"<ul>{_quality_items}</ul>"
            "</div>"
        )
    if negative_items:
        humanized_negative_items = []
        seen_humanized: set[str] = set()
        for item in negative_items:
            cleaned_item = compact_whitespace(item)
            if not cleaned_item:
                continue
            humanized = _humanize_check_item(cleaned_item)
            normalized = compact_whitespace(humanized).lower()
            if not normalized or normalized in seen_humanized:
                continue
            seen_humanized.add(normalized)
            humanized_negative_items.append(humanized)
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            "<strong>Things to check before applying</strong>"
            f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in humanized_negative_items)}</ul>"
            "</div>"
        )
    if active_debug_mode:
        debug_negative_reasons = negative_score_reasons(score_breakdown)
        if debug_negative_reasons:
            insight_sections.append(
                '<div class="job-insight-group job-insight-warning">'
                "<strong>Debug: negative score penalties</strong>"
                f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in debug_negative_reasons)}</ul>"
                "</div>"
            )
        gap_reasons = score_gap_reasons(display_record, score_breakdown)
        if gap_reasons:
            insight_sections.append(
                '<div class="job-insight-group is-secondary">'
                f"<strong>{safe_html(_workspace_label('workspace_card_labels', 'debug_score_notes_summary', 'Why this score is lower'))}</strong>"
                f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in gap_reasons)}</ul>"
                "</div>"
            )
    if active_debug_mode and score_breakdown:
        score_breakdown_html = "".join(
            f"<li>{safe_html(_humanize_score_breakdown_label(re.sub(r'\\s*\\[alias:[^\\]]*\\]', '', str(item['label'])).strip(), active_profile))}: {'{:+d}'.format(int(item['value']))}</li>"
            for item in score_breakdown
            if int(item["value"]) != 0
        )
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            f"<strong>{safe_html(_workspace_label('workspace_card_labels', 'debug_score_breakdown_summary', 'How this score was calculated'))}</strong>"
            f"<ul>{score_breakdown_html}</ul>"
            "</div>"
        )
    insight_html = (
        '<details class="job-insights">'
        "<summary>Fit breakdown</summary>"
        f"{''.join(insight_sections)}"
        "</details>"
        if insight_sections
        else ""
    )

    llm_review_html = ""
    if active_debug_mode and any(
        record.get(key)
        for key in (
            RECORD_LLM_DECISION_KEY,
            RECORD_LLM_FIT_GRADE_KEY,
            RECORD_LLM_ELAPSED_MS_KEY,
            RECORD_LLM_COST_USD_KEY,
        )
    ):
        llm_decision = str(record.get(RECORD_LLM_DECISION_KEY) or "").strip().upper()
        final_decision = (
            "KEPT"
            if llm_decision == "KEEP"
            else ("REJECTED" if llm_decision == "REJECT" else llm_decision or "UNKNOWN")
        )
        llm_grade = str(record.get(RECORD_LLM_FIT_GRADE_KEY) or "").strip().upper() or "UNKNOWN"
        debug_reason = str(record.get(RECORD_LLM_DEBUG_REASON_KEY) or "").strip()
        elapsed_ms = record.get(RECORD_LLM_ELAPSED_MS_KEY)
        cost_usd = record.get(RECORD_LLM_COST_USD_KEY)
        summary_items = [
            f"<li>Final decision: {safe_html(final_decision)}</li>",
            f"<li>Final score: {safe_html(str(fit_points))}</li>",
            f"<li>LLM fit grade: {safe_html(llm_grade)}</li>",
        ]
        if isinstance(elapsed_ms, (int, float)):
            summary_items.append(f"<li>Time taken: {safe_html(str(int(elapsed_ms)))} ms</li>")
        if isinstance(cost_usd, (int, float)):
            summary_items.append(f"<li>Estimated LLM cost: US${float(cost_usd):.4f}</li>")
        llm_review_parts = [
            f'<div class="job-insight-group is-secondary"><ul>{"".join(summary_items)}</ul></div>'
        ]
        if debug_reason:
            llm_review_parts.append(
                f'<div class="job-insight-group is-secondary"><strong>Debug reason</strong>'
                f"<p>{safe_html(debug_reason)}</p></div>"
            )
        llm_review_html = (
            '<details class="job-insights job-llm-review">'
            "<summary>Debug: LLM fit review</summary>"
            f"{''.join(llm_review_parts)}"
            "</details>"
        )

    candidate_history_html = ""
    if _cand_hist_details:
        _ch_company = _cand_hist_details["company"]
        _ch_role = _cand_hist_details["role"]
        _ch_run_date = _cand_hist_details["run_date"]
        _ch_confidence = _cand_hist_details["confidence"]
        _ch_evidence_raw = _cand_hist_details["evidence"]
        # Skip the details block when there's nothing actionable to show — low
        # confidence with no evidence or role means the LLM failed at import and
        # the only data is the raw company name from the sheet, which the badge
        # already signals.
        if not (_ch_confidence == "low" and not _ch_evidence_raw and not _ch_role):
            _ch_evidence = (
                _ch_evidence_raw[:100] + "..." if len(_ch_evidence_raw) > 100 else _ch_evidence_raw
            )
            _ch_formatted_date = _ch_run_date
            for _fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                try:
                    _dt = datetime.strptime(_ch_run_date, _fmt)
                    _ch_formatted_date = f"{_dt.day} {_dt.strftime('%B %Y')}"
                    break
                except ValueError:
                    pass
            _ch_items = []
            _ch_header_parts = [p for p in [_ch_company, _ch_formatted_date] if p]
            if _ch_header_parts:
                _ch_items.append(" — ".join(_ch_header_parts))
            if _ch_role:
                _ch_items.append(f"Role: {_ch_role}")
            if _ch_evidence_raw:
                _ch_items.append(f"Evidence: {_ch_evidence_raw}")
            if _ch_confidence:
                _ch_items.append(f"Confidence: {_ch_confidence}")
            if _cand_hist_review_reason:
                _ch_items.append(f"Review reason: {_cand_hist_review_reason}")
            candidate_history_html = (
                '<details class="job-candidate-history">'
                "<summary>Candidate application history</summary>"
                f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in _ch_items)}</ul>"
                "</details>"
            )

    action_rec_html = ""
    if not applied_record and not hidden_record and not blocking_reasons:
        if fit_points >= 70:
            action_rec_html = '<div class="job-action-rec job-action-rec--apply">Recommended: Apply</div>'
        elif fit_points >= 55:
            action_rec_html = '<div class="job-action-rec job-action-rec--review">Recommended: Review before applying</div>'
        else:
            action_rec_html = '<div class="job-action-rec job-action-rec--stretch">Lower priority — apply only if other options are limited</div>'

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

    card_classes = f"job-card {fit_tone_class}" + (
        " is-description-issue" if description_issue else ""
    )
    card_dom_id = _workspace_job_card_id(job_key)

    return (
        f'<article id="{safe_html(card_dom_id)}" class="{safe_html(card_classes)}" data-fit-score="{fit_points}" data-posted-age="{posted_age_days if posted_age_days is not None else 9999}" data-salary-sort="{salary_value}" data-salary-fit="{safe_html(salary_fit_state)}" data-work-mode="{safe_html(work_mode.lower())}" data-work-type="{safe_html(display_work_type_label(record).lower())}" data-viewed="{1 if seen_by_you else 0}" data-record-kind="{record_kind}" data-fit-label="{safe_html(fit_label.lower())}" data-title-search="{safe_html((record.get("title") or "").lower())}" data-company-search="{safe_html(company_display.lower())}" data-source="{safe_html(source)}" data-apply-method="{safe_html(apply_method or "unknown")}">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        '<div class="job-header-row">'
        '<div class="job-header-copy">'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">{title}</a>'
        + (
            f'<button class="title-block-btn" type="button" data-review-action="block_similar" data-block-phrase="{block_phrase}" data-block-phrases="{block_phrases_json}" {button_data_attrs} title="{safe_html(_workspace_label("workspace_card_labels", "title_block_button_tooltip", "Hide future roles whose titles contain the selected words, before description review."))}">{safe_html(_workspace_label("workspace_card_labels", "title_block_button_label", "Hide similar titles"))}</button>'
            '<div class="block-confirm" data-block-confirm hidden>'
            f'<div class="feature-guide-note">{safe_html(_workspace_label("workspace_card_labels", "title_block_guidance_copy", TITLE_BLOCK_GUIDANCE_COPY))}</div>'
            f'<p class="block-confirm-copy">{safe_html(_workspace_label("workspace_card_labels", "title_block_prompt_copy", TITLE_BLOCK_PROMPT_COPY))}</p>'
            '<details class="block-confirm-help">'
            f'<summary>{safe_html(_workspace_label("workspace_card_labels", "title_block_help_summary", TITLE_BLOCK_HELP_SUMMARY))}</summary>'
            f'<p>{safe_html(_workspace_label("workspace_card_labels", "title_block_guidance_copy", TITLE_BLOCK_GUIDANCE_COPY))}</p>'
            "</details>"
            '<p class="block-confirm-copy">Block future titles with:</p>'
            '<div class="block-phrase-checks" data-block-phrase-checks></div>'
            '<button class="mini-button block-manual-toggle" type="button" data-block-manual-toggle>Add other title words</button>'
            '<div class="block-manual-row">'
            '<span class="block-manual-label">Add title words</span>'
            '<input class="block-manual-input" type="text" data-block-manual-input placeholder="e.g. project manager, payroll">'
            f'<span class="block-manual-help">{safe_html(_workspace_label("workspace_card_labels", "title_block_manual_help", TITLE_BLOCK_MANUAL_HELP))}</span>'
            "</div>"
            '<p class="block-impact" data-block-impact></p>'
            f'<p class="block-confirm-sub">{safe_html(_workspace_label("workspace_card_labels", "title_block_strong_filter_copy", TITLE_BLOCK_STRONG_FILTER_COPY))}</p>'
            '<div class="block-confirm-actions">'
            '<button class="mini-button mini-button-primary" type="button" data-confirm-block disabled>Block Selected Titles</button>'
            '<button class="mini-button" type="button" data-cancel-block>Cancel</button>'
            "</div>"
            "</div>"
            '<span class="block-status" aria-live="polite"></span>'
            if (not applied_record and not hidden_record and _block_phrases_list)
            else ""
        )
        + f'<div class="job-company">{safe_html(company_display)}</div>'
        "</div>"
        f"{score_html}"
        "</div>"
        f"{summary_html}"
        f"{potential_duplicate_callout}"
        f'<div class="job-meta">{"".join(meta_items)}</div>'
        f"{note_html}"
        f"{insight_html}"
        f"{llm_review_html}"
        f"{job_requirements_html}"
        f"{profile_gaps_html}"
        f"{candidate_history_html}"
        f"{context_html}"
        f"{action_rec_html}"
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
    debug_mode: Optional[bool] = None,
    header_tools_html: str = "",
) -> str:
    if not records:
        header_tools = (
            f'<div class="section-head-tools">{header_tools_html}</div>'
            if header_tools_html
            else ""
        )
        return (
            f'<section class="section">'
            f'<div class="section-head section-head--with-tools">'
            f'<div class="section-head-title-row"><h2>{safe_html(title)}</h2>{header_tools}</div>'
            f"</div>"
            f'<p class="empty-state">{safe_html(empty_message)}</p>'
            f"</section>"
        )
    dom_id = section_dom_id(title)
    cards = "".join(
        render_job_card(
            record,
            scoring_profile,
            applied_pool=applied_pool,
            history_clusters=history_clusters,
            debug_mode=debug_mode,
        )
        for record in records
    )
    header_tools = (
        f'<div class="section-head-tools">{header_tools_html}</div>' if header_tools_html else ""
    )
    return (
        f'<section class="section job-section" data-section-id="{safe_html(dom_id)}">'
        '<div class="section-head section-head--with-tools">'
        f'<div class="section-head-title-row"><h2>{safe_html(title)}</h2>{header_tools}</div>'
        '<div class="section-tools">'
        '<span class="pagination-label"></span>'
        '<button class="pagination-button" type="button" data-page-direction="prev">Prev</button>'
        '<button class="pagination-button" type="button" data-page-direction="next">Next</button>'
        "</div>"
        "</div>"
        f'<div class="job-grid">{cards}</div>'
        "</section>"
    )


def render_results_fragment(context: dict) -> str:
    if not RESULTS_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Missing template: {RESULTS_TEMPLATE_PATH}")
    template = Template(RESULTS_TEMPLATE_PATH.read_text(encoding="utf-8"))

    # Perform initial substitution with workspace labels
    workspace_labels = load_workspace_page_labels()
    all_substitutions = {**workspace_labels, **context}

    # Using substitute() instead of safe_substitute() ensures we crash loudly
    # if the Python context is missing a key required by the HTML template.
    try:
        rendered_html = template.substitute(all_substitutions)
    except KeyError as exc:
        raise ValueError(f"Missing required context key for results template: {exc}") from exc

    unresolved_labels = re.findall(r"\$LABEL_WS_[A-Z_]+", rendered_html)
    if unresolved_labels:
        raise ValueError(
            f"Unresolved workspace labels in template: {', '.join(set(unresolved_labels))}"
        )

    return rendered_html


def render_match_level_guide_html(profile: Optional[dict] = None) -> str:
    active_profile = profile or load_profile()
    match_levels = get_match_levels(active_profile)
    guide_bits = [
        f'<span class="chip"><strong>{safe_html(str(level["label"]))}:</strong> {safe_html(str(level["description"]))}</span>'
        for level in match_levels
    ]
    guide_bits.extend(
        [
            '<span class="chip"><strong>Title match:</strong> direct titles are favored over secondary titles</span>',
            '<span class="chip"><strong>Description review:</strong> stronger description fit lifts the match level</span>',
            '<span class="chip"><strong>Competitive signals:</strong> specialist bias can lift or lower the match level</span>',
            '<span class="chip"><strong>Freshness:</strong> newer roles are favored</span>',
            '<span class="chip"><strong>Decision weights:</strong> fit, pay, location, work mode, work type, sector, and freshness can be dialed up or down</span>',
            '<span class="chip"><strong>Watchouts:</strong> essential gaps hit harder than desirable-only gaps</span>',
            '<span class="chip"><strong>Risks:</strong> essential gaps hit harder than desirable-only gaps</span>',
        ]
    )
    return "".join(guide_bits)
