"""
Workspace HTML rendering functions.

This module follows an "App Shell + Fragment" architecture. 
It processes 'results.html' as a template fragment to produce the data-heavy 
content (job cards, filters, stats), which is then injected into the 
'workspace.html' shell by the frontend. No scraping or pipeline logic belongs here.
"""

import json
import re
from functools import lru_cache
from datetime import datetime
from string import Template
from typing import Dict, List, Optional

from job_hunter_agent.user_settings import get_workspace_minimum_score
from job_hunter_agent.capability_matching import (
    build_risk_and_missing_evidence,
    capability_fit_highlights,
    reviewed_signal_match_summary,
)
from job_hunter_agent.description_trust import (
    full_description_confidence,
    get_trusted_full_description,
)
from job_hunter_agent.company_rules import normalize_company_name
from job_hunter_agent.filters import suggest_title_block_phrases
from job_hunter_agent.fit_scoring import (
    build_fit_highlights,
    fit_score,
    fit_score_breakdown,
)
from job_hunter_agent.history import (
    assess_history_warning_signals,
    viewed_by_user,
)
from job_hunter_agent.job_identity import find_confirmed_duplicate
from job_hunter_agent.match_labels import score_to_match_label
from job_hunter_agent.paths import RESULTS_TEMPLATE_PATH
from job_hunter_agent.posting_utils import (
    current_posted_age_days,
    format_timestamp_label,
    posted_display_label,
)
from job_hunter_agent.preferences import assess_contract_preference
from job_hunter_agent.preferences import display_work_type_label
from job_hunter_agent.profile_store import ENGAGEMENT_TYPE_OPTIONS, get_match_levels, load_profile
from job_hunter_agent.role_analysis import infer_role_sector
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.global_settings import get_default_country_suffix
from job_hunter_agent.salary_utils import salary_sort_value
from job_hunter_agent.score_labels import (
    render_badge,
    salary_fit_label,
    score_to_tone_class,
    viewed_badge_html,
)
from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.signal_detection import (
    competitive_signal_assessments,
    hard_block_reasons,
)
from job_hunter_agent.signal_schema import TITLE_REASON_POTENTIAL_MATCH
from job_hunter_agent.record_schema import RECORD_DUPLICATE_LINKS_KEY, RECORD_POTENTIAL_DUPLICATE_LINKS_KEY
from job_hunter_agent.source_registry import get_source_display_label
from job_hunter_agent.work_mode_extraction import display_work_mode_label
from job_hunter_agent.text_processing import (
    build_role_summary,
    compact_whitespace,
    dedupe_preserve_order,
    list_to_phrase,
    synthesize_role_snapshot,
)
from job_hunter_agent.utils import safe_html
from job_hunter_agent.work_mode_extraction import extract_from_text, WORK_MODE_UNKNOWN

WORKSPACE_DEBUG_MODE = DEBUG_MODE

DESCRIPTION_CAPTURE_ISSUE = "Full job description not captured clearly"
ARCHIVE_LABEL = "Saved Earlier Searches"
ARCHIVE_BADGE_TOOLTIP = "This role was saved from an earlier search and kept on your workspace."
ARCHIVE_CONTEXT_PREFIX = "Saved Earlier Searches"


@lru_cache(maxsize=1)
def _workspace_ui_labels() -> dict:
    return load_ui_labels()


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


def _is_capability_entry(label: str) -> bool:
    return any(tag in label for tag in _CAPABILITY_ENTRY_TAGS)


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
        "Passed content filters",
    }

    for item in score_breakdown:
        label = compact_whitespace(item.get("label") or "")
        value = int(item.get("value", 0) or 0)
        # Per-capability entries (tagged [canonical], [alias:...], [contextual_llm]) are scoring
        # internals already surfaced via fit_highlights — skip them here.
        if not label or value <= 0 or label in excluded or _is_capability_entry(label):
            if not ((label.startswith("Work mode") or label.startswith("Work type") or label.startswith("Sector")) and label not in reasons):
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
    capability_entries = [item for item in score_breakdown if _is_capability_entry(compact_whitespace(item.get("label") or ""))]
    evidence_points = sum(int(item.get("value", 0) or 0) for item in capability_entries)
    gap_labels = _workspace_ui_labels().get("score_gap_labels", {})
    capability_gap_label = "Capability evidence is limited: {count} matches contributed to scoring"
    if isinstance(gap_labels, dict):
        capability_gap_label = str(gap_labels.get("capability_evidence_limited") or capability_gap_label)
    gaps: List[str] = []

    if not any(label.startswith("Posted within") or label == "Still relatively recent" for label in labels):
        gaps.append(_workspace_label("score_gap_labels", "no_recent_posted_signal", "No reliable recent-posted signal"))

    if not any(label in {"Salary/rate signal", "Salary/rate below target"} for label in labels):
        salary = compact_whitespace(record.get("salary") or "")
        if not salary or salary == "N/A":
            gaps.append(_workspace_label("score_gap_labels", "no_comparable_salary_rate", "No comparable salary/rate found"))

    if evidence_points < 12:
        capability_count = len(capability_entries)
        gaps.append(capability_gap_label.format(count=capability_count))

    if full_description_confidence(record) == "LOW":
        gaps.append(_workspace_label(
            "score_gap_labels",
            "limited_description_confidence",
            "Scoring confidence is limited because the full description was not captured",
        ))

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
) -> List[int]:
    active_profile = scoring_profile or load_profile()
    match_levels = get_match_levels(active_profile)
    active_workspace_min_score = (
        int(workspace_min_score)
        if workspace_min_score is not None
        else get_workspace_minimum_score()
    )
    return [
        int(level.get("minimum_score", 0) or 0)
        for level in match_levels
        if int(level.get("minimum_score", 0) or 0) >= active_workspace_min_score
    ]


def render_score_filter_options(
    scoring_profile: Optional[dict] = None,
    workspace_min_score: Optional[int] = None,
) -> str:
    active_profile = scoring_profile or load_profile()
    active_workspace_min_score = (
        int(workspace_min_score)
        if workspace_min_score is not None
        else get_workspace_minimum_score()
    )
    options = ['<option value="all">All match levels</option>']
    for threshold in score_filter_thresholds(active_profile, active_workspace_min_score):
        selected_attr = " selected" if active_workspace_min_score == threshold else ""
        options.append(
            f'<option value="{threshold}"{selected_attr}>'
            f'{safe_html(score_filter_option_label(threshold, active_profile))}</option>'
        )
    return "".join(options)


def posted_filter_option_label(threshold: int) -> str:
    rules = load_ui_labels()
    labels = rules.get("posted_threshold_labels", {})
    return labels.get(str(threshold), f"Last {threshold} days")


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


def render_work_type_filter_options() -> str:
    options = ['<option value="all">Any type</option>']
    for item in ENGAGEMENT_TYPE_OPTIONS:
        value = str(item.get("value") or "").strip().lower()
        label = str(item.get("label") or "").strip()
        if not value or not label:
            continue
        options.append(f'<option value="{safe_html(value)}">{safe_html(label)}</option>')
    return "".join(options)


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
        return load_ui_labels().get("title_match_labels", {}).get("secondary_match", "Also-consider role-family match")
    if prefix == "CARD_SPECIALIST" and cleaned_detail:
        return f"Rejected early from card metadata: {cleaned_detail}"
    fallback = raw.replace("_", " ").lower()
    return fallback[:1].upper() + fallback[1:]


def render_job_card(
    record: dict,
    scoring_profile: Optional[dict] = None,
    applied_pool: Optional[List[dict]] = None,
    history_clusters: Optional[Dict[str, dict]] = None,
) -> str:
    default_country_suffix = get_default_country_suffix()
    active_profile = scoring_profile or load_profile()
    display_record = dict(record)
    loc = str(display_record.get("location") or "").strip()
    if default_country_suffix and loc.endswith(f", {default_country_suffix}"):
        display_record["location"] = loc[:-(len(default_country_suffix) + 2)].strip()

    title = safe_html(record.get("title", "Untitled"))
    company_display = normalize_company_name(str(record.get("company") or "")) or compact_whitespace(str(record.get("company") or "N/A"))
    company = safe_html(company_display or "N/A")
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
        # Refresh work mode from description only if stored extraction found nothing useful.
        # Metadata-sourced values (seek_detail_payload, linkedin_structured, etc.) are
        # more reliable than text inference — don't override them at display time.
        stored_source = record.get("work_mode_source", "")
        if not stored_source or stored_source == "fallback_text":
            text_result = extract_from_text(trusted_desc)
            if text_result["work_mode"] != WORK_MODE_UNKNOWN:
                display_record["work_mode"] = text_result["work_mode"]
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
        similar_applied_record = find_confirmed_duplicate(record, applied_pool)
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
    visible_reasons = visible_fit_reasons(fit_highlights, score_breakdown, include_values=WORKSPACE_DEBUG_MODE)
    description_issue = fit_confidence_level == "LOW"
    work_mode = str(display_record.get("work_mode") or "N/A")
    posted_age_days = current_posted_age_days(record)
    salary_value = salary_sort_value(str(display_record.get("salary") or ""))
    salary_fit_state = salary_fit_label(display_record, scoring_profile)
    record_kind = "applied" if applied_record else ("hidden" if hidden_record else ("saved" if archived else "current"))
    company_attr = safe_html(company_display)
    teaser_attr = safe_html(compact_whitespace(str(record.get("teaser") or "")))
    sector_signal = infer_role_sector(display_record, trusted_desc if trusted_desc else stored_snapshot)
    channel_signal = display_record.get("posting_channel_evidence")
    if not isinstance(channel_signal, dict):
        channel_signal = {}
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
    similar_applied_company = safe_html(normalize_company_name(str((similar_applied_record or {}).get("company") or "")) or str((similar_applied_record or {}).get("company") or ""))
    similar_applied_source = str((similar_applied_record or {}).get("source") or "").lower().strip()
    similar_applied_source_label = safe_html(get_source_display_label(similar_applied_source) if similar_applied_source else "")
    similar_applied_job_key = safe_html(str((similar_applied_record or {}).get("job_key") or ""))
    button_data_attrs = (
        f'data-job-key="{job_key}" '
        f'data-job-url="{url}" '
        f'data-job-title="{title}" '
        f'data-job-company="{company_attr}" '
        f'data-job-teaser="{teaser_attr}" '
        f'data-role-sector="{safe_html(sector_signal.get("kind") or "unknown")}" '
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
        badges.append(render_badge("Possible Repost", "badge-warning", "This role looks very similar to one you have already applied to."))
    elif archived:
        badges.append(render_badge(ARCHIVE_LABEL, "badge-archive", ARCHIVE_BADGE_TOOLTIP))
    if not applied_record and not seen_by_you:
        badges.append(render_badge("New To You", "badge-new", "You have not opened this role from the workspace yet."))
    if is_stale:
        badges.append(render_badge("15+ Days Old", "badge-stale", "This role is older, but still saved for reference."))
    elif seen_by_you:
        badges.append(viewed_badge_html())
    if description_issue:
        badges.append(render_badge("Description Issue", "badge-warning", "The full job description was not captured clearly, so this match needs manual checking."))
    badges.append(render_badge(source_label, f"badge-source-{source}", f"Sourced from {source_label}."))
    if sector_signal.get("kind") == "government":
        badges.append(render_badge("Public sector", "badge-sector-government", "Public-sector context detected from the captured job text."))
    channel_kind = channel_signal.get("kind", "unknown")
    channel_source = channel_signal.get("source", "")
    if channel_kind == "agency_or_recruiter" and channel_source == "metadata_first":
        badges.append(render_badge("Recruiter", "badge-source-neutral", "Posted via a recruitment agency or third-party recruiter."))
    elif channel_kind == "direct_employer" and channel_source == "metadata_first":
        badges.append(render_badge("Company", "badge-source-neutral", "Posted directly by the employer."))
    history_warning_signals = assess_history_warning_signals(record, history_clusters)
    if history_warning_signals:
        badges.append(render_badge("Potential Red Flag", "badge-warning", history_warning_signals[0]))
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
        _pd_company = normalize_company_name(str(_pd_first.get("related_company") or "")) or str(_pd_first.get("related_company") or "").strip()
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
        related_company = normalize_company_name(str(related.get("related_company") or "")) or str(related.get("related_company") or "").strip()
        related_job_key = str(related.get("related_job_key") or "").strip()
        related_url = str(related.get("related_url") or "").strip()
        related_label_parts = [part for part in [related_title, f"@ {related_company}" if related_company else ""] if part]
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
                f'<strong>{safe_html(_workspace_label("duplicate_labels", "potential_badge", "Related cards"))}</strong> '
                f'{safe_html(_workspace_label("duplicate_labels", "callout_prefix", "Open matching card"))} {related_label_html}. '
                f'<span class="duplicate-help-text">{safe_html(_workspace_label("duplicate_labels", "help_text", "This is the matching card in your workspace. Use it to compare details."))}</span>'
                '</div>'
            )
    job_quality_signals = [s for s in (record.get("job_quality_signals") or []) if isinstance(s, dict)]
    for _sig in job_quality_signals:
        badges.append(render_badge(_sig.get("label", "Quality Concern"), "badge-warning", _sig.get("evidence", "")))
    score_percent = max(min(int(fit_points), 100), 0)
    score_html = (
        f'<div class="match-tile {fit_tone_class}" style="--match-score: {score_percent}%;">'
        + (
            f'<span class="match-tile-number">{fit_points}</span>'
            if WORKSPACE_DEBUG_MODE
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
        ("Work mode", display_work_mode_label(display_record)),
        (_workspace_label("workspace_meta_labels", "work_type", "Work type"), display_work_type_label(display_record)),
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
    if WORKSPACE_DEBUG_MODE and reviewed_signal_matches["unresolved"]:
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
                safe_html(normalize_company_name(str(item.get("company") or "")) or str(item.get("company") or "").strip()),
                title_html,
                safe_html(f"matched on {matched_on}") if matched_on else "",
            ]
            linked_items.append(" | ".join(bit for bit in parts if bit))
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            f'<strong>{safe_html(_workspace_label("duplicate_labels", "confirmed_section_heading", "Matching cards"))}</strong>'
            f'<ul>{"".join(f"<li>{item}</li>" for item in linked_items)}</ul>'
            '</div>'
        )
    if potential_duplicate_links:
        linked_items = []
        for item in potential_duplicate_links:
            matched_on = list_to_phrase([
                _duplicate_match_label(str(value))
                for value in (item.get("matched_on") or [])
                if str(value).strip()
            ])
            related_title = str(item.get("related_title") or "").strip()
            related_company = normalize_company_name(str(item.get("related_company") or "")) or str(item.get("related_company") or "").strip()
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
            f'<strong>{safe_html(_workspace_label("duplicate_labels", "potential_section_heading", "Related cards"))}</strong>'
            f'<ul>{"".join(f"<li>{item}</li>" for item in linked_items)}</ul>'
            '</div>'
        )
    visible_penalties = negative_score_reasons(score_breakdown, include_values=WORKSPACE_DEBUG_MODE)
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
        if WORKSPACE_DEBUG_MODE:
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
    if job_quality_signals:
        _quality_items = "".join(
            f"<li>{safe_html(s.get('evidence', ''))}</li>" for s in job_quality_signals
        )
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            '<strong>Job quality concerns</strong>'
            f'<ul>{_quality_items}</ul>'
            '</div>'
        )
    if negative_items:
        insight_sections.append(
            '<div class="job-insight-group job-insight-warning">'
            '<strong>What lowers it</strong>'
            f'<ul>{"".join(f"<li>{safe_html(item)}</li>" for item in negative_items)}</ul>'
            '</div>'
        )
    elif WORKSPACE_DEBUG_MODE:
        insight_sections.append(
            '<div class="job-insight-group job-insight-muted">'
            '<strong>Watchouts</strong>'
            '<p class="insight-unavailable-note">No explicit risks detected from the captured description.</p>'
            '</div>'
        )
    if WORKSPACE_DEBUG_MODE:
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
    if WORKSPACE_DEBUG_MODE and score_breakdown:
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
    if WORKSPACE_DEBUG_MODE and channel_signal:
        ch_kind = channel_signal.get("kind", "unknown")
        ch_source = channel_signal.get("source", "unknown")
        ch_trusted = [str(x) for x in channel_signal.get("trusted_metadata", []) if str(x).strip()]
        ch_weak = [str(x) for x in channel_signal.get("weak_text_matches", []) if str(x).strip()]
        ch_needs_review = channel_signal.get("needs_review", False)
        ch_lines = [f"kind={safe_html(ch_kind)}", f"source={safe_html(ch_source)}", f"needs_review={ch_needs_review}"]
        if ch_trusted:
            ch_lines.append(f"trusted: {safe_html(', '.join(ch_trusted))}")
        if ch_weak:
            ch_lines.append(f"weak text: {safe_html(', '.join(ch_weak))}")
        insight_sections.append(
            '<div class="job-insight-group is-secondary">'
            '<strong>Posting channel</strong>'
            f'<ul>{"".join(f"<li>{line}</li>" for line in ch_lines)}</ul>'
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
    card_dom_id = _workspace_job_card_id(job_key)

    return (
        f'<article id="{safe_html(card_dom_id)}" class="{safe_html(card_classes)}" data-fit-score="{fit_points}" data-posted-age="{posted_age_days if posted_age_days is not None else 9999}" data-salary-sort="{salary_value}" data-salary-fit="{safe_html(salary_fit_state)}" data-work-mode="{safe_html(work_mode.lower())}" data-work-type="{safe_html(display_work_type_label(record).lower())}" data-viewed="{1 if seen_by_you else 0}" data-record-kind="{record_kind}" data-fit-label="{safe_html(fit_label.lower())}" data-title-search="{safe_html((record.get("title") or "").lower())}" data-company-search="{safe_html(company_display.lower())}" data-source="{safe_html(source)}">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        '<div class="job-header-row">'
        '<div class="job-header-copy">'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">{title}</a>'
        + (
            f'<button class="title-block-btn" type="button" data-review-action="block_similar" data-block-phrase="{block_phrase}" data-block-phrases="{block_phrases_json}" {button_data_attrs} title="Hide future roles whose titles contain the selected words, before description review.">Hide similar titles</button>'
            '<div class="block-confirm" data-block-confirm hidden>'
            '<div class="feature-guide-note">'
            'Job sites often return broad results even when the search is correct. '
            'If a title clearly doesn’t match what you want, you can block similar titles directly from the title. '
            'This helps remove repeated noise from future results.'
            '</div>'
            '<p class="block-confirm-copy">Block future titles before description review.</p>'
            '<details class="block-confirm-help">'
            '<summary>Learn more</summary>'
            '<p>'
            'Job sites often return broad results even when the search is correct. '
            'If a title clearly does not match what you want, you can block similar titles directly from the title. '
            'This helps remove repeated noise from future results.'
            '</p>'
            '</details>'
            '<p class="block-confirm-copy">Block future titles with:</p>'
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
        + f'<div class="job-company">{safe_html(company_display)}</div>'
        '</div>'
        f"{score_html}"
        '</div>'
        f"{summary_html}"
        f"{potential_duplicate_callout}"
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


def render_results_fragment(context: dict) -> str:
    if not RESULTS_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Missing template: {RESULTS_TEMPLATE_PATH}")
    template = Template(RESULTS_TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.safe_substitute(context)


def render_match_level_guide_html(profile: Optional[dict] = None) -> str:
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
        '<span class="chip"><strong>Decision weights:</strong> fit, pay, location, work mode, work type, sector, and freshness can be dialed up or down</span>',
        '<span class="chip"><strong>Watchouts:</strong> essential gaps hit harder than desirable-only gaps</span>',
        '<span class="chip"><strong>Risks:</strong> essential gaps hit harder than desirable-only gaps</span>',
    ])
    return "".join(guide_bits)
