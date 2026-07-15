"""Workspace HTML rendering helpers.

Purpose: render the results fragment, job cards, filters, and supporting labels
that are injected into the workspace shell.
"""

import json
import logging
import re
from datetime import datetime
from functools import lru_cache
from html import escape, unescape
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
    get_min_trusted_description_length,
    get_trusted_full_description,
    get_trusted_sources,
)
from job_hunter_agent.filters import normalize_title_block_phrase
from job_hunter_agent.fit_scoring import (
    build_fit_highlights,
    eligibility_gate_diagnostics,
    fit_score_and_breakdown_displayed,
    fit_score_displayed,
    occupation_alignment_diagnostics,
    requirement_fit_diagnostics,
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
from job_hunter_agent.preferences import (
    display_contract_duration_label,
    display_work_type_label,
)
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
    get_scoring_rules,
    load_profile,
    normalize_engagement_type_preferences,
)
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EASY_APPLY,
    APPLY_METHOD_QUICK_APPLY,
    RECORD_APPLY_METHOD_KEY,
    RECORD_DECISION_KEY,
    RECORD_DUPLICATE_LINKS_KEY,
    RECORD_JOB_REQUIREMENTS_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_ELAPSED_MS_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    RECORD_POTENTIAL_DUPLICATE_LINKS_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_REVIEW_SOURCE_KEY,
    RECORD_TITLE_REASON_KEY,
)
from job_hunter_agent.salary_utils import format_salary_display, salary_sort_value
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
from job_hunter_agent.role_analysis import friendly_capability_label
from job_hunter_agent.text_processing import (
    build_role_summary,
    clean_display_text,
    clean_display_text_preserving_blocks,
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
    "If a title clearly does not match what you want, enter the exact phrase you want blocked from future titles. "
    "This helps remove repeated noise from future results without guessing which title fragments are safe to exclude."
)


def _chunk_full_description_text(description: str) -> list[str]:
    """Split a long description into readable display chunks without dropping content."""

    cleaned = clean_display_text(unescape(description))
    if not cleaned:
        return []

    normalized = re.sub(r"\s+(?=(?:\d+\.\s+|[-•–—]\s+))", "\n", cleaned)
    chunks: list[str] = []

    for block in (part.strip() for part in normalized.split("\n") if part.strip()):
        sentences = [
            compact_whitespace(part)
            for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", block)
            if compact_whitespace(part)
        ]
        if len(sentences) <= 1:
            chunks.append(block)
            continue

        current = ""
        for sentence in sentences:
            if not current:
                current = sentence
                continue
            if len(current) + len(sentence) + 1 <= 260:
                current = f"{current} {sentence}"
            else:
                chunks.append(current)
                current = sentence
        if current:
            chunks.append(current)

    return chunks or [cleaned]


_DESCRIPTION_BULLET_RE = re.compile(r"^(?:[-*•]\s+|\d+[\.\)]\s+)(.+)$")
_DESCRIPTION_HEADING_JOINERS = frozenset(
    {"a", "an", "and", "at", "de", "for", "in", "of", "on", "or", "the", "to", "with"}
)


def _get_trusted_display_description(record: dict) -> str:
    """Return trusted description text while preserving source line structure for display."""

    full_description = clean_display_text_preserving_blocks(record.get("full_description") or "")
    if full_description:
        return full_description

    source = str(record.get("description_source") or "").strip().lower()
    fallback_text = clean_display_text_preserving_blocks(record.get("fit_source_text") or "")
    if len(compact_whitespace(fallback_text)) < get_min_trusted_description_length():
        return ""
    if source in get_trusted_sources():
        return fallback_text
    return ""


def _looks_like_description_heading(line: str) -> bool:
    cleaned = compact_whitespace(line)
    if not cleaned:
        return False
    if _DESCRIPTION_BULLET_RE.match(cleaned):
        return False
    if ":" in cleaned and not cleaned.endswith(":"):
        return False

    candidate = cleaned.rstrip(":").strip()
    if not candidate:
        return False
    if len(candidate) > 90:
        return False
    if cleaned.endswith((".", ";", ",")):
        return False

    words = [part for part in re.split(r"\s+", candidate) if part]
    if not words or len(words) > 9:
        return False

    if candidate.isupper() and any(ch.isalpha() for ch in candidate):
        return True
    if cleaned.endswith("?"):
        candidate = candidate.rstrip("?").strip()
        words = [part for part in re.split(r"\s+", candidate) if part]
        if not words:
            return False

    for index, word in enumerate(words):
        token = word.strip(".,:;!?()[]{}\"'")
        if not token:
            continue
        if any(ch.isdigit() for ch in token) and len(words) == 1:
            continue
        if token.isupper():
            continue
        if token[:1].isupper():
            continue
        lower = token.lower()
        if lower in _DESCRIPTION_HEADING_JOINERS:
            if index == 0:
                return False
            continue
        return False
    return True


def _render_structured_description_html(description: str) -> str:
    lines = clean_display_text_preserving_blocks(unescape(description)).split("\n")
    blocks: list[tuple[str, Any]] = []
    paragraph_lines: list[str] = []
    list_items: list[str] = []
    found_structure = False

    def flush_paragraph() -> None:
        if not paragraph_lines:
            return
        paragraph = compact_whitespace(" ".join(paragraph_lines))
        if paragraph:
            blocks.append(("paragraph", paragraph))
        paragraph_lines.clear()

    def flush_list() -> None:
        if not list_items:
            return
        blocks.append(("list", list_items.copy()))
        list_items.clear()

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            flush_list()
            continue

        if " - " in line:
            prefix, remainder = [part.strip() for part in line.split(" - ", 1)]
            if _looks_like_description_heading(prefix) and compact_whitespace(remainder):
                flush_paragraph()
                flush_list()
                blocks.append(("heading", prefix.rstrip(":").strip()))
                paragraph_lines.append(remainder)
                found_structure = True
                continue

        bullet_match = _DESCRIPTION_BULLET_RE.match(line)
        if bullet_match:
            flush_paragraph()
            bullet_text = compact_whitespace(bullet_match.group(1))
            if bullet_text:
                list_items.append(bullet_text)
                found_structure = True
            continue

        if _looks_like_description_heading(line):
            flush_paragraph()
            flush_list()
            blocks.append(("heading", line.rstrip(":").strip()))
            found_structure = True
            continue

        flush_list()
        paragraph_lines.append(line)

    flush_paragraph()
    flush_list()

    if not blocks:
        return ""

    if not found_structure and len(blocks) == 1 and blocks[0][0] == "paragraph":
        chunks = _chunk_full_description_text(str(blocks[0][1]))
        blocks = [("paragraph", chunk) for chunk in chunks]

    rendered_blocks: list[str] = []
    for kind, payload in blocks:
        if kind == "heading":
            rendered_blocks.append(
                f'<h4 class="job-full-description-heading">{safe_html(str(payload))}</h4>'
            )
        elif kind == "list":
            items = "".join(
                f'<li class="job-full-description-list-item">{safe_html(item)}</li>'
                for item in payload
                if compact_whitespace(item)
            )
            if items:
                rendered_blocks.append(f'<ul class="job-full-description-list">{items}</ul>')
        else:
            rendered_blocks.append(f'<p class="job-full-description">{safe_html(str(payload))}</p>')

    return (
        '<div class="job-full-description-body">'
        '<div class="job-full-description-reading">'
        + "".join(rendered_blocks)
        + "</div>"
        + "</div>"
    )


def _render_full_description_html(description: str) -> str:
    return _render_structured_description_html(description)
TITLE_BLOCK_PROMPT_COPY = "Enter the exact title phrase to block before description review."
TITLE_BLOCK_HELP_SUMMARY = "Learn more"
TITLE_BLOCK_MANUAL_HELP = "Use exact phrases from the title. Use commas to add more than one."
TITLE_BLOCK_STRONG_FILTER_COPY = (
    "This is a strong filter. Matching titles will be hidden before description review."
)
_MANDATORY_REQUIREMENT_ACRONYMS = frozenset(
    {"3pl", "api", "erp", "hris", "nv1", "nv2", "sap", "sql", "uat", "wms"}
)


def _normalize_capability_token(value: str) -> str:
    return compact_whitespace(value).lower()


def _capability_level_lookup(active_profile: Optional[dict]) -> dict[str, str]:
    labels = load_ui_labels().get("level_labels", {})
    if not isinstance(active_profile, dict):
        return {}
    rules = active_profile.get("candidate_capabilities")
    if not isinstance(rules, list):
        return {}
    lookup: dict[str, str] = {}
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        raw_level = str(rule.get("level") or "").strip().lower()
        if not raw_level:
            continue
        if raw_level not in labels:
            raise ValueError(f"ui_labels.json level_labels is missing a value for {raw_level!r}")
        level_label = str(labels[raw_level]).strip()
        for value in [rule.get("name"), *((rule.get("aliases") or []) if isinstance(rule.get("aliases"), list) else [])]:
            normalized = _normalize_capability_token(str(value or ""))
            if normalized:
                lookup[normalized] = level_label
    return lookup


def _render_scoring_audit_html(record: dict, active_profile: dict) -> str:
    """Render the scoring inputs and decision conversion without changing judgement."""

    diagnostics = requirement_fit_diagnostics(record, active_profile)
    has_debug_match_details = any(
        row.get("match_source_label") not in {"", "Unresolved"}
        or row.get("matched_profile_term_label") not in {"", "Unresolved"}
        for row in diagnostics["rows"]
    )
    row_html = ""
    for row in diagnostics["rows"]:
        requirement_weight = f"{float(row['requirement_weight']):g}"
        credit_fraction = f"{float(row['credit_fraction']):g}"
        weighted_credit = f"{float(row['weighted_credit']):g}"
        evidence_html = "".join(
            f"<li>{safe_html(value)}</li>" for value in (row["profile_support"] or [])
        ) or "<li>No profile evidence returned</li>"
        row_html += (
            "<tr>"
            f"<td>{safe_html(row['requirement'])}</td>"
            f"<td>{safe_html(row['importance_label'])}</td>"
            f"<td>{safe_html(row['requirement_type_label'])}</td>"
            f"<td>{safe_html(row['status_label'])}</td>"
            f"<td>{safe_html(row['mapping_label'])}</td>"
            + (
                f"<td>{safe_html(row['match_source_label'])}</td>"
                f"<td>{safe_html(row['matched_profile_term_label'])}</td>"
                if has_debug_match_details
                else ""
            )
            + (
            f"<td>{safe_html(row['candidate_level_label'])}</td>"
            f"<td>{safe_html(requirement_weight)}</td>"
            f"<td>{safe_html(credit_fraction)}</td>"
            f"<td>{safe_html(weighted_credit)}</td>"
            f"<td>{safe_html(row['calculation_label'])}</td>"
            f"<td><ul>{evidence_html}</ul></td>"
            "</tr>"
            )
        )

    audit_table = ""
    if row_html:
        earned_weighted_credit = f"{float(diagnostics['earned_weighted_credit']):g}"
        total_requirement_weight = f"{float(diagnostics['total_requirement_weight']):g}"
        audit_table = (
            '<div class="job-insight-group is-secondary scoring-audit">'
            "<strong>Scoring audit</strong>"
            '<div class="scoring-audit-scroll"><table>'
            "<thead><tr>"
            "<th>Requirement</th><th>Importance</th><th>Requirement type</th><th>Status</th>"
            "<th>Mapped profile capability or eligibility</th>"
            + (
                "<th>Matched via</th><th>Matched term</th>"
                if has_debug_match_details
                else ""
            )
            + "<th>Candidate level</th>"
            "<th>Requirement weight</th><th>Credit fraction</th><th>Weighted credit</th>"
            "<th>Calculation</th><th>Profile evidence used</th>"
            "</tr></thead>"
            f"<tbody>{row_html}</tbody>"
            "</table></div></div>"
        )
        audit_table += (
            '<div class="job-insight-group is-secondary scoring-audit-summary">'
            "<ul>"
            f"<li>Earned weighted credit: {safe_html(earned_weighted_credit)}</li>"
            f"<li>Total requirement weight: {safe_html(total_requirement_weight)}</li>"
            f"<li>Calculation: {safe_html(diagnostics['final_calculation_label'])}</li>"
            f"<li>Final Requirement Fit: {safe_html(str(diagnostics['final_requirement_fit']))}%</li>"
            "</ul>"
            "</div>"
        )

    llm_decision = compact_whitespace(str(record.get(RECORD_LLM_DECISION_KEY) or ""))
    final_decision = compact_whitespace(str(record.get(RECORD_DECISION_KEY) or ""))
    review_source = compact_whitespace(str(record.get(RECORD_REVIEW_SOURCE_KEY) or ""))
    title_reason = compact_whitespace(str(record.get(RECORD_TITLE_REASON_KEY) or ""))
    reject_reason = compact_whitespace(str(record.get(RECORD_REJECT_REASON_KEY) or ""))
    full_llm_review = "Run" if llm_decision else "Not run"
    conversion = (
        f"{llm_decision} → {final_decision}"
        if llm_decision and final_decision and llm_decision != final_decision
        else final_decision or llm_decision or "Unavailable"
    )
    trace_items = [
        f"Title review: {title_reason or 'Unavailable'}",
        f"Review source: {review_source or 'Unavailable'}",
        f"Full LLM review: {full_llm_review}",
        f"LLM decision: {llm_decision or 'Unavailable'}",
        f"Final conversion: {conversion}",
    ]
    if reject_reason:
        trace_items.append(f"Rejection reason: {reject_reason}")
    trace_html = "".join(f"<li>{safe_html(item)}</li>" for item in trace_items)
    return (
        '<div class="job-insight-group is-secondary scoring-decision-trace">'
        "<strong>Decision trace</strong>"
        f"<ul>{trace_html}</ul></div>"
        f"{audit_table}"
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
    "potential_jobs_empty_state",
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
    "last_run_llm_cost_label",
    "last_run_input_tokens_label",
    "last_run_output_tokens_label",
    "crawler_stats_heading",
    "crawler_stats_helper",
    "crawler_stats_cards_seen_label",
    "crawler_stats_ads_reviewed_label",
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
ARCHIVE_LABEL = "Previously Saved Searches"
ARCHIVE_BADGE_TOOLTIP = "This role was saved from an earlier search and kept on your workspace."
ARCHIVE_CONTEXT_PREFIX = "Previously Saved Searches"


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
    raise ValueError(f"ui_labels.json is missing {group}.{key}")


def _workspace_job_card_id(job_key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", compact_whitespace(job_key).lower()).strip("-")
    return f"job-card-{slug}" if slug else "job-card"


def _duplicate_match_label(matched_on: str) -> str:
    key = f"match_on_{matched_on}"
    return _workspace_label("duplicate_labels", key, matched_on.replace("_", " "))


_NV1_PATTERNS = re.compile(r"\bnv\s*1\b|\bnegative\s+vetting\s*1\b", re.IGNORECASE)
_CLEARANCE_PATTERNS = re.compile(
    r"\b(baseline|nv\s*2|top\s+secret|protected)\s*(clearance)?\b|\bclearance\s+required\b",
    re.IGNORECASE,
)


def _humanize_check_item(text: str) -> str:
    """Convert raw hard-block / risk text into plain-English check items."""
    t = compact_whitespace(unescape(text))
    lower = text.lower()
    if (
        "explicitly required but not shown" in lower
        or "required but not shown" in lower
        or "appears required" in lower
        or lower.startswith("critical missing requirement")
        or lower.startswith("missing mandatory requirement")
    ):
        requirement_warning = _humanize_missing_requirement_warning(text)
        if requirement_warning:
            return requirement_warning
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


def _humanize_requirement_label(text: str) -> str:
    cleaned = compact_whitespace(text)
    if not cleaned:
        return ""

    cleaned = re.sub(
        r"^(critical missing requirement|missing mandatory requirement)\s*:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s+(explicitly required but not shown|required but not shown|appears required)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    humanized_parts: list[str] = []
    for part in re.split(r"(\s+|[-/,&()])", cleaned):
        if not part or part.isspace() or part in {"-", "/", ",", "&", "(", ")"}:
            humanized_parts.append(part)
            continue
        lowered = part.lower()
        if lowered in _MANDATORY_REQUIREMENT_ACRONYMS:
            humanized_parts.append(part.upper())
        elif part.isupper():
            humanized_parts.append(part)
        elif any(ch.isdigit() for ch in part):
            humanized_parts.append(part.upper())
        else:
            humanized_parts.append(part[:1].upper() + part[1:].lower())
    return "".join(humanized_parts)


def _humanize_missing_requirement_warning(text: str) -> str:
    requirement = _humanize_requirement_label(text)
    if not requirement:
        return ""
    return f"Missing mandatory requirement: {requirement}"


def _build_checks_before_applying_items(
    history_warning_signals: list[str],
    description_issue: bool,
    is_possible_repost: bool,
    similar_applied_record: Optional[dict],
    candidate_history: Optional[dict],
    missing_profile_support: list[str],
    salary_fit_state: str,
    requirement_coverage: Optional[list[dict]] = None,
    soft_risk_reasons: Optional[list[str]] = None,
    job_quality_signals: Optional[list[dict]] = None,
) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = compact_whitespace(value)
        if not cleaned:
            return
        normalized = compact_whitespace(cleaned).lower()
        if normalized in seen:
            return
        seen.add(normalized)
        items.append(cleaned)

    if isinstance(requirement_coverage, list):
        for row in requirement_coverage:
            if not isinstance(row, dict):
                continue
            # Eligibility rows (clearances, work rights, etc.) are surfaced exclusively
            # by the dedicated Clearances panel — skip them here to avoid double-counting
            # the same fact in both places.
            if compact_whitespace(str(row.get("requirement_type") or "")).lower() == "eligibility":
                continue
            requirement = compact_whitespace(
                str(row.get("requirement") or row.get("capability_name") or "")
            )
            if not requirement:
                continue
            status = compact_whitespace(str(row.get("status") or "")).lower()
            importance = compact_whitespace(str(row.get("importance") or "")).lower()
            label = friendly_capability_label(requirement) or requirement
            if status == "invalid":
                add(f"Needs review: {label}")
                continue
            if importance == "mandatory" and status in {"mismatch", "not_shown"}:
                add(_humanize_missing_requirement_warning(requirement))
            elif status == "partially_supported":
                add(f"Partly matches your profile: {label}")
            elif status == "mismatch":
                add(f"Not in your profile: {label}")
            elif status == "not_shown" and importance not in {"nice_to_have"}:
                add(f"Not shown in your profile: {label}")

    for reason in history_warning_signals:
        cleaned = compact_whitespace(reason)
        if cleaned.lower().startswith("potential red flag:"):
            cleaned = compact_whitespace(cleaned.removeprefix("Potential red flag:"))
        if cleaned and cleaned[-1] not in ".!?":
            cleaned = f"{cleaned}."
        add(cleaned)

    if description_issue:
        add("Description issue: full job description was not captured clearly.")

    if is_possible_repost and similar_applied_record:
        repost_title = compact_whitespace(str(similar_applied_record.get("title") or ""))
        repost_company = compact_whitespace(str(similar_applied_record.get("company") or ""))
        repost_source = get_source_display_label(
            str(similar_applied_record.get("source") or "").strip().lower()
        )
        repost_bits = [bit for bit in [repost_title, repost_company, repost_source] if bit]
        add(
            "Possible repost of applied job"
            + (f": {' — '.join(repost_bits)}" if repost_bits else ".")
        )
    elif is_possible_repost:
        add("Possible repost of applied job.")

    if isinstance(candidate_history, dict) and candidate_history:
        cand_company = compact_whitespace(str(candidate_history.get("llm_company") or ""))
        cand_role = compact_whitespace(str(candidate_history.get("llm_role") or ""))
        cand_status = compact_whitespace(
            str(candidate_history.get("llm_application_status") or "")
        ).lower()
        cand_confidence = compact_whitespace(str(candidate_history.get("llm_confidence") or "")).lower()
        if cand_company or cand_role:
            history_label = (
                "Rejected before"
                if cand_status == "rejection" and cand_confidence != "low"
                else "Possible previous application"
            )
            history_bits = [bit for bit in [cand_company, cand_role] if bit]
            add(
                history_label
                + (f": {' — '.join(history_bits)}" if history_bits else "")
            )

    if salary_fit_state == "below":
        add("Salary below target.")

    for item in missing_profile_support:
        add(_humanize_check_item(str(item)))

    for item in soft_risk_reasons or []:
        add(_humanize_check_item(str(item)))

    for signal in job_quality_signals or []:
        add(compact_whitespace(str(signal.get("evidence") or signal.get("label") or "")))

    return items[:6]


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
    if lowered.startswith("[") and "requirement partially supported:" in lowered:
        match = re.search(
            r"requirement partially supported:\s*(.*?)(?:\s*\|\s*capability:.*)?$",
            cleaned,
            re.IGNORECASE,
        )
        if match:
            requirement = compact_whitespace(match.group(1))
            if requirement:
                return f"Requirement partly supported: {requirement}"
    if cleaned == "Passed content filters":
        return "Passed content filters"
    if cleaned == "Already viewed by you":
        return "Already viewed by you"
    return cleaned


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
    key = str(threshold)
    if key not in labels:
        raise ValueError(f"ui_labels.json posted_threshold_labels is missing a value for {key!r}")
    return labels[key]


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
    jobs_per_page_label = load_workspace_page_labels()["LABEL_WS_JOBS_PER_PAGE_LABEL"].lower()
    options = []
    for size in (12, 24, 48, 96):
        selected = " selected" if size == 12 else ""
        options.append(
            f'<option value="{size}"{selected}>{size} {safe_html(jobs_per_page_label)}</option>'
        )
    return "".join(options)


def render_page_size_select_html() -> str:
    labels = load_workspace_page_labels()
    jobs_per_page_label = safe_html(labels["LABEL_WS_JOBS_PER_PAGE_LABEL"])
    return (
        '<label class="panel-select-control panel-select-control--page-size" for="page_size_select">'
        f'<span class="panel-select-label">{jobs_per_page_label}</span>'
        f'<select id="page_size_select" class="jh-select" aria-label="{jobs_per_page_label}">'
        f"{render_page_size_options()}"
        "</select>"
        "</label>"
    )


def render_workspace_tabs_html(
    shortlist_count: int,
    applied_count: int,
    hidden_count: int,
    *,
    active_target: str = "potential",
) -> str:
    tabs = [
        ("potential", "Potential Jobs", shortlist_count),
        ("applied", "Applied", applied_count),
        ("hidden", "Hidden", hidden_count),
    ]
    buttons = []
    for target, label, count in tabs:
        active_class = " is-active" if active_target == target else ""
        buttons.append(
            f'<button class="scope-tab{active_class}" type="button" data-workspace-target="{target}">'
            f"{safe_html(label)} ({count})"
            "</button>"
        )
    return '<div class="scope-tabs" aria-label="Top-level workspace views">' + "".join(buttons) + "</div>"


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
    stored_snapshot = clean_display_text(
        record.get("role_snapshot") or record.get("teaser") or "N/A"
    )
    if stored_snapshot in {"", "N/A"}:
        stored_snapshot = synthesize_role_snapshot(record)
    fit_confidence_level = full_description_confidence(record)
    trusted_desc = get_trusted_full_description(record)
    trusted_display_desc = _get_trusted_display_description(record)

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
        (
            soft_risk_reasons,
            missing_profile_support,
            missing_clearance_support,
        ) = build_risk_and_missing_profile_support(
            trusted_desc,
            title_reason,
            active_profile,
            competitive_signals=display_record.get("competitive_signals")
            if isinstance(display_record.get("competitive_signals"), list)
            else None,
            requirement_coverage=record.get(RECORD_REQUIREMENT_COVERAGE_KEY)
            if isinstance(record.get(RECORD_REQUIREMENT_COVERAGE_KEY), list)
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
        missing_clearance_support = []
        blocking_reasons = []

    similar_applied_record = None
    is_possible_repost = False
    if not applied_record and applied_pool:
        similar_applied_record = find_confirmed_duplicate(record, applied_pool)
        is_possible_repost = similar_applied_record is not None
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
    display_record["missing_clearance_support"] = missing_clearance_support
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
    teaser_attr = safe_html(clean_display_text(str(record.get("teaser") or "")))
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
    block_title_hint = safe_html(normalize_title_block_phrase(str(record.get("title") or "")))
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
    channel_source = str(channel_signal.get("source") or "").strip().lower()
    channel_evidence = [
        str(item).strip()
        for item in (
            channel_signal.get("text_evidence")
            or channel_signal.get("weak_text_matches")
            or []
        )
        if str(item).strip()
    ]
    has_channel_evidence = bool(channel_evidence)
    if channel_kind == "agency_or_recruiter":
        if channel_source in {"metadata_first", "company_or_domain_indicator"} and not channel_signal.get("needs_review"):
            badges.append(
                render_badge(
                    _workspace_label(
                        "workspace_card_labels",
                        "posting_channel_agency_recruiter_badge",
                        "Agency recruiter",
                    ),
                    "badge-source-neutral",
                    _workspace_label(
                        "workspace_card_labels",
                        "posting_channel_agency_recruiter_tooltip",
                        "Posted via a recruitment agency or third-party recruiter.",
                    ),
                )
            )
        else:
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
    elif channel_kind == "direct_employer":
        badges.append(
            render_badge("Company", "badge-source-neutral", "Posted directly by the employer.")
        )
    elif channel_signal.get("needs_review") or has_channel_evidence:
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
            "match_confidence": str(_cand_hist.get("_match_confidence") or "").strip().lower(),
            "match_reason": str(_cand_hist.get("_company_match_reason") or "").strip(),
        }
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
    contract_duration_display = display_contract_duration_label(display_record)
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
        (
            _workspace_label("workspace_meta_labels", "contract_duration", "Contract term"),
            contract_duration_display,
            False,
        ),
        (
            "Salary",
            format_salary_display(
                str(display_record.get("salary") or "N/A"),
                work_type=str(display_record.get("work_type") or ""),
            ),
            False,
        ),
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
                "Salary below target.",
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
    display_trusted_desc = trusted_display_desc
    if display_trusted_desc and compact_whitespace(display_trusted_desc) != compact_whitespace(role_summary):
        summary_html = (
            '<details class="job-summary-expand">'
            '<summary class="job-summary">'
            f'<span class="job-summary-text">{safe_html(role_summary)}</span>'
            '<span class="job-summary-toggle" aria-hidden="true">'
            '<span class="job-summary-toggle-icon"></span>'
            '<span class="job-summary-toggle-label job-summary-toggle-label--closed">Show more</span>'
            '<span class="job-summary-toggle-label job-summary-toggle-label--open">Show less</span>'
            '</span>'
            "</summary>"
            f'<div class="job-summary-expanded">{_render_full_description_html(display_trusted_desc)}</div>'
            "</details>"
        )
    reviewed_signal_matches = reviewed_signal_match_summary(display_record, scoring_profile)
    check_items = _build_checks_before_applying_items(
        history_warning_signals,
        description_issue,
        is_possible_repost,
        similar_applied_record,
        _cand_hist,
        missing_profile_support,
        salary_fit_state,
        display_record.get(RECORD_REQUIREMENT_COVERAGE_KEY),
        soft_risk_reasons,
        job_quality_signals,
    )
    job_requirements_html = ""
    raw_coverage = display_record.get(RECORD_REQUIREMENT_COVERAGE_KEY)
    merged_requirement_rows: dict[str, dict[str, Any]] = {}
    merged_requirement_order: list[str] = []
    has_requirement_subtitles = False
    capability_level_lookup = _capability_level_lookup(active_profile)
    # When requirement_coverage is available, show only those rows (they are more
    # detailed and LLM-verified). Skip the short job_requirements bullets to avoid
    # showing the same requirements twice with different text.
    has_coverage = isinstance(raw_coverage, list) and len(raw_coverage) > 0
    coverage_status_labels = {
        "supported": "In profile",
        "partially_supported": "Partial match",
        "not_shown": "",
        "mismatch": "Not in profile",
        "invalid": "Needs review",
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

    def _requirement_sort_key(row: dict[str, Any]) -> tuple[int, str]:
        importance = compact_whitespace(str(row.get("importance") or "")).lower()
        requirement = compact_whitespace(str(row.get("requirement") or "")).lower()
        if importance == "mandatory":
            bucket = 0
        elif importance in {"strongly_preferred", "preferred"}:
            bucket = 1
        else:
            bucket = 2
        return (bucket, requirement)

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
            row["profile_name"] = compact_whitespace(str(item.get("profile_name") or ""))
            row["capability_name"] = compact_whitespace(str(item.get("capability_name") or ""))
            row["eligibility_name"] = compact_whitespace(str(item.get("eligibility_name") or ""))
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
        sorted_requirement_keys = sorted(
            merged_requirement_order,
            key=lambda key: _requirement_sort_key(merged_requirement_rows.get(key) or {}),
        )
        for key in sorted_requirement_keys:
            row = merged_requirement_rows.get(key)
            if not isinstance(row, dict):
                continue
            req_text = compact_whitespace(str(row.get("requirement") or ""))
            if not req_text:
                continue
            profile_status = str(row.get("profile_status") or "").strip()
            coverage_status = str(row.get("coverage_status") or "").strip().lower()
            importance = str(row.get("importance") or "").strip().lower()
            profile_name = compact_whitespace(
                str(
                    row.get("profile_name")
                    or row.get("capability_name")
                    or row.get("eligibility_name")
                    or ""
                )
            )
            matched_text = compact_whitespace(str(row.get("matched_job_text") or ""))
            level_label = capability_level_lookup.get(
                _normalize_capability_token(profile_name), ""
            )

            if coverage_status == "supported":
                css_modifier = "supported"
            elif coverage_status == "partially_supported":
                css_modifier = "partially-supported"
            elif coverage_status == "mismatch":
                css_modifier = "mismatch"
            elif coverage_status == "invalid":
                css_modifier = "invalid"
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
            if profile_name:
                profile_detail = profile_name
                if level_label:
                    profile_detail = f"{profile_detail} ({level_label})"
                detail_parts.append(profile_detail)
            if matched_text and compact_whitespace(matched_text).lower() != req_text.lower():
                detail_parts.append(f'"{matched_text}"')
            if detail_parts:
                has_requirement_subtitles = True
            detail_html = (
                f'<span class="req-coverage-detail">{safe_html(" · ".join(detail_parts))}</span>'
                if active_debug_mode and detail_parts
                else ""
            )
            importance_html = (
                f'<span class="job-req-importance job-req-importance--{safe_html(importance.replace("_", "-"))}">{safe_html(importance_label)}</span>'
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
            badges_html = ""
            if importance_html or status_html or add_to_profile_html:
                badges_html = (
                    f'<div class="job-requirement-badges">'
                    f"{importance_html}"
                    f"{status_html}"
                    f"{add_to_profile_html}"
                    f"</div>"
                )
            requirement_items_html += (
                f'<li class="job-requirement-item job-requirement-item--{safe_html(css_modifier)}">'
                f'<span class="job-requirement-text">{safe_html(req_text)}{detail_html}</span>'
                f"{badges_html}"
                f"</li>"
            )

        if requirement_items_html:
            requirement_hint_html = ""
            if not active_debug_mode and has_requirement_subtitles:
                requirement_hint_html = (
                    f'<p class="job-requirements-hint">{safe_html(_workspace_label("workspace_card_labels", "job_requirements_detail_hint", "The hidden subtitle is the small grey line under a requirement row. It shows the matched capability name and the quoted job text, and debug mode turns it back on."))}</p>'
                )
            job_requirements_html = (
                '<details class="job-insights job-requirements-panel">'
                f"<summary>{safe_html(_workspace_label('workspace_card_labels', 'job_requirements_summary', 'Job Requirements'))}</summary>"
                f'{requirement_hint_html}'
                f'<div class="job-insight-group is-secondary"><ul class="job-requirement-list">{requirement_items_html}</ul></div>'
                "</details>"
            )
        else:
            job_requirements_html = (
                '<details class="job-insights job-requirements-panel">'
                f"<summary>{safe_html(_workspace_label('workspace_card_labels', 'job_requirements_summary', 'Job Requirements'))}</summary>"
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
    check_items_html = "".join(f"<li>{safe_html(item)}</li>" for item in check_items)

    risk_html = (
        '<details class="job-insights job-risk-panel">'
        f"<summary>{safe_html(_workspace_label('workspace_card_labels', 'risk_panel_summary', 'Checks before applying'))}</summary>"
        f'<div class="job-insight-group job-insight-warning"><ul>{check_items_html}</ul></div>'
        "</details>"
        if check_items_html
        else ""
    )

    clearance_items_html = "".join(
        f"<li>{safe_html(item)}</li>"
        for item in display_record.get("missing_clearance_support") or []
    )
    clearance_html = (
        '<details class="job-insights job-clearance-panel">'
        f"<summary>{safe_html(_workspace_label('workspace_card_labels', 'clearance_panel_summary', 'Clearances'))}</summary>"
        f'<div class="job-insight-group job-insight-warning"><ul>{clearance_items_html}</ul></div>'
        "</details>"
        if clearance_items_html
        else ""
    )

    llm_review_html = ""
    has_llm_review_data = any(
        record.get(key)
        for key in (
            RECORD_LLM_DECISION_KEY,
            RECORD_LLM_FIT_GRADE_KEY,
        )
    )
    if active_debug_mode and (has_llm_review_data or score_breakdown):
        llm_review_parts = []
        if has_llm_review_data:
            llm_decision = str(record.get(RECORD_LLM_DECISION_KEY) or "").strip().upper()
            final_decision = (
                "KEPT"
                if llm_decision == "KEEP"
                else ("REJECTED" if llm_decision == "REJECT" else llm_decision or "UNKNOWN")
            )
            llm_grade = str(record.get(RECORD_LLM_FIT_GRADE_KEY) or "").strip().upper() or "UNKNOWN"
            summary_items = [
                f"<li>Final decision: {safe_html(final_decision)}</li>",
                f"<li>Final score: {safe_html(str(fit_points))}</li>",
                f"<li>LLM fit grade: {safe_html(llm_grade)}</li>",
            ]
            eligibility_gate = eligibility_gate_diagnostics(display_record, active_profile)
            summary_items.append(
                f"<li>Eligibility gate: {safe_html(eligibility_gate['label'])} — {safe_html(str(eligibility_gate['reason'] or ''))}</li>"
            )
            occupation_scoring_rules = get_scoring_rules(active_profile)
            occupation_alignment = occupation_alignment_diagnostics(display_record, occupation_scoring_rules)
            requirement_fit_points = requirement_fit_diagnostics(display_record, active_profile)[
                "final_requirement_fit"
            ]
            occupation_calculation = (
                f"{requirement_fit_points} + ({occupation_alignment['adjustment']:+d}) = {fit_points}"
            )
            summary_items.append(
                f"<li>Occupation alignment: {safe_html(occupation_alignment['alignment_label'])} — "
                f"{safe_html(occupation_alignment['reason'])} "
                f"(adjustment {occupation_alignment['adjustment']:+d}, {safe_html(occupation_calculation)})</li>"
            )
            llm_elapsed_ms = record.get(RECORD_LLM_ELAPSED_MS_KEY)
            llm_cost_usd = record.get(RECORD_LLM_COST_USD_KEY)
            llm_input_tokens = record.get(RECORD_LLM_INPUT_TOKENS_KEY)
            llm_output_tokens = record.get(RECORD_LLM_OUTPUT_TOKENS_KEY)
            if llm_elapsed_ms not in (None, ""):
                summary_items.append(
                    f"<li>{safe_html(_workspace_label('workspace_card_labels', 'debug_llm_time_label', 'LLM time'))}: {safe_html(str(llm_elapsed_ms))} ms</li>"
                )
            if llm_cost_usd not in (None, ""):
                summary_items.append(
                    f"<li>{safe_html(_workspace_label('workspace_card_labels', 'debug_llm_cost_label', 'LLM cost'))}: ${float(llm_cost_usd):.6f}</li>"
                )
            if llm_input_tokens not in (None, ""):
                summary_items.append(
                    f"<li>{safe_html(_workspace_label('workspace_card_labels', 'debug_llm_input_tokens_label', 'Input tokens'))}: {safe_html(str(llm_input_tokens))}</li>"
                )
            if llm_output_tokens not in (None, ""):
                summary_items.append(
                    f"<li>{safe_html(_workspace_label('workspace_card_labels', 'debug_llm_output_tokens_label', 'Output tokens'))}: {safe_html(str(llm_output_tokens))}</li>"
                )
            llm_review_parts.append(
                f'<div class="job-insight-group is-secondary"><ul>{"".join(summary_items)}</ul></div>'
            )
        if score_breakdown:
            score_breakdown_html = "".join(
                f"<li>{safe_html(_humanize_score_breakdown_label(re.sub(r'\\s*\\[alias:[^\\]]*\\]', '', str(item['label'])).strip(), active_profile))}: {'{:+d}'.format(int(item['value']))}</li>"
                for item in score_breakdown
                if int(item["value"]) != 0
            )
            if score_breakdown_html:
                llm_review_parts.append(
                    '<div class="job-insight-group is-secondary">'
                    f"<strong>{safe_html(_workspace_label('workspace_card_labels', 'debug_score_breakdown_summary', 'Score breakdown'))}</strong>"
                    f"<ul>{score_breakdown_html}</ul>"
                    "</div>"
                )
        llm_review_parts.append(_render_scoring_audit_html(display_record, active_profile))
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
        _ch_match_confidence = _cand_hist_details["match_confidence"]
        _ch_match_reason = _cand_hist_details["match_reason"]
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
            if _ch_match_confidence:
                _ch_items.append(f"Company match confidence: {_ch_match_confidence}")
            if _ch_match_reason:
                _ch_items.append(f"Company match reason: {_ch_match_reason}")
            if _cand_hist_review_reason:
                _ch_items.append(f"Review reason: {_cand_hist_review_reason}")
            candidate_history_html = (
                '<details class="job-candidate-history">'
                "<summary>Candidate application history</summary>"
                f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in _ch_items)}</ul>"
                "</details>"
            )

    if applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-undo workspace-action-button workspace-action-button--primary workspace-action-button--selected" type="button" data-review-action="unapply" {button_data_attrs}>Undo Applied</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif hidden_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-undo workspace-action-button workspace-action-button--neutral" type="button" data-review-action="unhide" {button_data_attrs}>Unhide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif not applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-applied workspace-action-button workspace-action-button--primary" type="button" data-review-action="applied" {button_data_attrs}>Applied</button>'
            f'<button class="review-button review-not-for-me workspace-action-button workspace-action-button--danger" type="button" data-review-action="not_for_me" {button_data_attrs} title="Marks this role as not a fit and stores it as learning feedback">Not For Me</button>'
            f'<button class="review-button review-hide workspace-action-button workspace-action-button--neutral" type="button" data-review-action="hidden" {button_data_attrs} title="Hide this one job only. You can unhide it later from Hidden jobs.">Hide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    else:
        actions_html = ""

    card_classes = f"job-card {fit_tone_class}" + (
        " is-description-issue" if description_issue else ""
    )
    card_dom_id = _workspace_job_card_id(job_key)
    title_block_panel_id = f"{card_dom_id}-title-block"

    return (
        f'<article id="{safe_html(card_dom_id)}" class="{safe_html(card_classes)}" data-fit-score="{fit_points}" data-posted-age="{posted_age_days if posted_age_days is not None else 9999}" data-salary-sort="{salary_value}" data-salary-fit="{safe_html(salary_fit_state)}" data-work-mode="{safe_html(work_mode.lower())}" data-work-type="{safe_html(display_work_type_label(record).lower())}" data-viewed="{1 if seen_by_you else 0}" data-record-kind="{record_kind}" data-fit-label="{safe_html(fit_label.lower())}" data-title-search="{safe_html((record.get("title") or "").lower())}" data-company-search="{safe_html(company_display.lower())}" data-source="{safe_html(source)}" data-apply-method="{safe_html(apply_method or "unknown")}">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        '<div class="job-header-row">'
        '<div class="job-header-copy">'
        '<div class="job-title-row">'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">{title}</a>'
        + (
            f'<button class="title-block-btn chip-button" type="button" data-review-action="block_similar" {button_data_attrs} aria-expanded="false" aria-controls="{safe_html(title_block_panel_id)}" title="{safe_html(_workspace_label("workspace_card_labels", "title_block_button_tooltip", "Hide future roles whose titles contain exact phrases you choose before Job Hunter spends time reading the full ad."))}">{safe_html(_workspace_label("workspace_card_labels", "title_block_button_label", "Hide similar titles"))}</button>'
            f'<div id="{safe_html(title_block_panel_id)}" class="block-confirm" data-block-confirm hidden>'
            f'<p class="block-confirm-copy">{safe_html(_workspace_label("workspace_card_labels", "title_block_prompt_copy", TITLE_BLOCK_PROMPT_COPY))}</p>'
            '<details class="block-confirm-help">'
            f'<summary>{safe_html(_workspace_label("workspace_card_labels", "title_block_help_summary", TITLE_BLOCK_HELP_SUMMARY))}</summary>'
            f'<p>{safe_html(_workspace_label("workspace_card_labels", "title_block_guidance_copy", TITLE_BLOCK_GUIDANCE_COPY))}</p>'
            "</details>"
            f'<p class="block-confirm-copy">Current title: <strong>{title}</strong></p>'
            '<div class="block-manual-row">'
            '<span class="block-manual-label">Exact title phrase</span>'
            f'<input class="block-manual-input" type="text" data-block-manual-input placeholder="e.g. sap, payroll, contract management" value="{block_title_hint}">'
            f'<span class="block-manual-help">{safe_html(_workspace_label("workspace_card_labels", "title_block_manual_help", TITLE_BLOCK_MANUAL_HELP))}</span>'
            "</div>"
            '<p class="block-impact" data-block-impact></p>'
            f'<p class="block-confirm-sub">{safe_html(_workspace_label("workspace_card_labels", "title_block_strong_filter_copy", TITLE_BLOCK_STRONG_FILTER_COPY))}</p>'
            '<div class="block-confirm-actions">'
            '<button class="mini-button mini-button-primary" type="button" data-confirm-block disabled>Block Matching Titles</button>'
            '<button class="mini-button" type="button" data-cancel-block>Cancel</button>'
            "</div>"
            "</div>"
            '<span class="block-status" aria-live="polite"></span>'
            if (not applied_record and not hidden_record)
            else ""
        )
        + "</div>"
        + f'<div class="job-company">{safe_html(company_display)}</div>'
        "</div>"
        f"{score_html}"
        "</div>"
        f"{summary_html}"
        f"{potential_duplicate_callout}"
        f'<div class="job-meta">{"".join(meta_items)}</div>'
        f"{risk_html}"
        f"{clearance_html}"
        f"{job_requirements_html}"
        f"{llm_review_html}"
        f"{profile_gaps_html}"
        f"{candidate_history_html}"
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
    debug_mode: Optional[bool] = None,
    header_tools_html: str = "",
    header_nav_html: str = "",
) -> str:
    header_tools = (
        f'<div class="section-head-tools">{header_tools_html}</div>' if header_tools_html else ""
    )
    header_nav = header_nav_html or ""
    panelized = bool(header_tools_html)
    section_classes = "section job-section"
    if panelized:
        section_classes += " section--results-panel"
    panel_open = '<div class="results-section-panel">' if panelized else ""
    panel_close = "</div>" if panelized else ""
    panel_body_open = '<div class="results-section-body">' if panelized else ""
    panel_body_close = "</div>" if panelized else ""
    if panelized:
        results_header = (
            '<div class="results-header">'
            '<div class="results-header__left">'
            f"<h2>{safe_html(title)}</h2>"
            f"{header_tools}"
            f"{header_nav}"
            "</div>"
            '<div class="section-tools">'
            '<span class="pagination-label pagination-page-label"></span>'
            '<span class="pagination-match-count"></span>'
            '<button class="pagination-button" type="button" data-page-direction="prev">Prev</button>'
            '<button class="pagination-button" type="button" data-page-direction="next">Next</button>'
            "</div>"
            "</div>"
        )
    else:
        results_header = (
            '<div class="section-head section-head--with-nav">'
            f"{header_nav}"
            f"<h2>{safe_html(title)}</h2>"
            f"{header_tools}"
            "</div>"
        )
    if not records:
        return (
            f'<section class="{section_classes if panelized else "section"}">'
            f"{panel_open}"
            f"{results_header}"
            f'<p class="empty-state">{safe_html(empty_message)}</p>'
            f"{panel_close}"
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
    return (
        f'<section class="{section_classes}" data-section-id="{safe_html(dom_id)}">'
        f"{panel_open}"
        f"{results_header}"
        f"{panel_body_open}"
        f'<div class="job-grid">{cards}</div>'
        f"{panel_body_close}"
        f"{panel_close}"
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
