"""Workspace HTML rendering helpers.

Purpose: render the results fragment, job cards, filters, and supporting labels
that are injected into the workspace shell.
"""

import logging
import re
from datetime import datetime
from functools import lru_cache
from html import escape, unescape
from string import Template
from typing import Any, Dict, List, Optional

from job_hunter_agent.capability_matching import build_display_competitive_risks
from job_hunter_agent.company_normalization import normalize_company_name
from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.detail_page_text import looks_like_browser_interstitial_text
from job_hunter_agent.description_trust import (
    full_description_confidence,
    get_min_trusted_description_length,
    get_trusted_full_description,
    get_trusted_sources,
)
from job_hunter_agent.filters import suggest_title_block_phrase
from job_hunter_agent.fit_scoring import (
    build_fit_highlights,
    eligibility_gate_diagnostics,
    fit_score_and_breakdown_displayed,
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
    board_posted_display_label,
    current_posted_age_days,
    format_timestamp_label,
    linkedin_freshness_is_unknown,
    linkedin_original_posted_is_unverified,
    original_posted_display_label,
    posted_display_label,
)
from job_hunter_agent.preferences import (
    display_contract_duration_label,
    display_work_type_label,
)
from job_hunter_agent.profile_gaps import (
    CUSTOM_BLOCKER_REASON_AMBIGUOUS,
    CUSTOM_BLOCKER_REASON_INVALID_INPUT,
    CUSTOM_BLOCKER_REASON_NOT_REQUIRED,
    CUSTOM_BLOCKER_REASON_NO_MATCH,
    CUSTOM_BLOCKER_REASON_RESOLVED,
)
from job_hunter_agent.profile_store import (
    ENGAGEMENT_TYPE_OPTIONS,
    KEY_MUST_NOT_REQUIRED_SKILLS,
    get_match_levels,
    get_scoring_rules,
    load_profile,
)
from job_hunter_agent.role_analysis import posting_channel_evidence_is_current
from job_hunter_agent.requirement_classification import load_default_eligibility_subtype
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EASY_APPLY,
    APPLY_METHOD_QUICK_APPLY,
    ORIGINAL_POSTED_DATE_STATUS_VERIFIED,
    RECORD_APPLY_METHOD_KEY,
    RECORD_DECISION_KEY,
    RECORD_DUPLICATE_LINKS_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_ELAPSED_MS_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY,
    RECORD_IS_REPOSTED_KEY,
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
from job_hunter_agent.text_processing import (
    build_role_summary,
    clean_display_text,
    clean_display_text_preserving_blocks,
    compact_whitespace,
    dedupe_preserve_order,
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


def _workspace_int(value: Any) -> int:
    return int(value)


def _match_level_minimum_score(level: dict[str, object]) -> int:
    return _workspace_int(level.get("minimum_score", 0) or 0)


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


def _clean_job_card_text(value: object, *, preserve_blocks: bool = False) -> str:
    cleaner = clean_display_text_preserving_blocks if preserve_blocks else clean_display_text
    cleaned = cleaner(value or "")
    if looks_like_browser_interstitial_text(cleaned):
        return ""
    return cleaned


def _get_trusted_display_description(record: dict) -> str:
    """Return trusted description text while preserving source line structure for display."""

    full_description = _clean_job_card_text(record.get("full_description") or "", preserve_blocks=True)
    if full_description:
        return full_description

    source = str(record.get("description_source") or "").strip().lower()
    fallback_text = _clean_job_card_text(record.get("fit_source_text") or "", preserve_blocks=True)
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


_REQUIRED_REQUIREMENT_ACRONYMS = frozenset(
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


def _render_scoring_audit_html(
    record: dict, active_profile: dict, *, debug_mode: bool = False
) -> str:
    """Render the scoring inputs and decision conversion without changing judgement."""

    if not debug_mode:
        return ""

    def _audit_label(key: str) -> str:
        return _workspace_label("scoring_audit_labels", key)

    diagnostics = requirement_fit_diagnostics(record, active_profile)
    # Eligibility/clearance requirements are a pass/fail gate, not part of the
    # weighted score (their requirement_weight is always 0) — the gate result is
    # already shown in the decision trace above, so listing them here with a
    # column of zeros only makes the "what fed the score" table read as wrong.
    scored_rows = [row for row in diagnostics["rows"] if not row.get("is_eligibility_gate")]
    has_debug_match_details = any(
        row.get("match_source_label") not in {"", "Unresolved"}
        or row.get("matched_profile_term_label") not in {"", "Unresolved"}
        for row in scored_rows
    )
    row_html = ""
    for row in scored_rows:
        requirement_weight = f"{float(row['requirement_weight']):g}"
        credit_fraction = f"{float(row['credit_fraction']):g}"
        weighted_credit = f"{float(row['weighted_credit']):g}"
        evidence_html = "".join(
            f"<li>{safe_html(value)}</li>" for value in (row["profile_support"] or [])
        ) or f"<li>{safe_html(_audit_label('no_profile_evidence_returned'))}</li>"
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
            f"<strong>{safe_html(_audit_label('scoring_audit_heading'))}</strong>"
            '<div class="scoring-audit-scroll"><table>'
            "<thead><tr>"
            f"<th>{safe_html(_audit_label('column_requirement'))}</th>"
            f"<th>{safe_html(_audit_label('column_importance'))}</th>"
            f"<th>{safe_html(_audit_label('column_requirement_type'))}</th>"
            f"<th>{safe_html(_audit_label('column_status'))}</th>"
            f"<th>{safe_html(_audit_label('column_mapped_profile_capability'))}</th>"
            + (
                f"<th>{safe_html(_audit_label('column_matched_via'))}</th>"
                f"<th>{safe_html(_audit_label('column_matched_term'))}</th>"
                if has_debug_match_details
                else ""
            )
            + f"<th>{safe_html(_audit_label('column_candidate_level'))}</th>"
            f"<th>{safe_html(_audit_label('column_requirement_weight'))}</th>"
            f"<th>{safe_html(_audit_label('column_credit_fraction'))}</th>"
            f"<th>{safe_html(_audit_label('column_weighted_credit'))}</th>"
            f"<th>{safe_html(_audit_label('column_calculation'))}</th>"
            f"<th>{safe_html(_audit_label('column_profile_evidence_used'))}</th>"
            "</tr></thead>"
            f"<tbody>{row_html}</tbody>"
            "</table></div></div>"
        )
        audit_table += (
            '<div class="job-insight-group is-secondary scoring-audit-summary">'
            "<ul>"
            f"<li>{safe_html(_audit_label('earned_weighted_credit_prefix'))} {safe_html(earned_weighted_credit)}"
            f" {safe_html(_audit_label('sum_of_weighted_credit_column_suffix'))}</li>"
            f"<li>{safe_html(_audit_label('total_requirement_weight_prefix'))} {safe_html(total_requirement_weight)}"
            f" {safe_html(_audit_label('sum_of_requirement_weight_column_suffix'))}</li>"
            f"<li>{safe_html(_audit_label('calculation_prefix'))} {safe_html(diagnostics['final_calculation_label'])}"
            f" = {safe_html(str(diagnostics['final_requirement_fit']))}%</li>"
            "</ul>"
            "</div>"
        )

    llm_decision = compact_whitespace(str(record.get(RECORD_LLM_DECISION_KEY) or ""))
    final_decision = compact_whitespace(str(record.get(RECORD_DECISION_KEY) or ""))
    review_source = compact_whitespace(str(record.get(RECORD_REVIEW_SOURCE_KEY) or ""))
    title_reason = compact_whitespace(str(record.get(RECORD_TITLE_REASON_KEY) or ""))
    reject_reason = compact_whitespace(str(record.get(RECORD_REJECT_REASON_KEY) or ""))
    unavailable_label = _audit_label("unavailable_label")
    full_llm_review = _audit_label("run_label") if llm_decision else _audit_label("not_run_label")
    conversion = (
        f"{llm_decision} → {final_decision}"
        if llm_decision and final_decision and llm_decision != final_decision
        else final_decision or llm_decision or unavailable_label
    )
    trace_items = [
        f"{_audit_label('title_review_prefix')} {title_reason or unavailable_label}",
        f"{_audit_label('review_source_prefix')} {review_source or unavailable_label}",
        f"{_audit_label('full_llm_review_prefix')} {full_llm_review}",
        f"{_audit_label('llm_decision_prefix')} {llm_decision or unavailable_label}",
        f"{_audit_label('final_conversion_prefix')} {conversion}",
    ]
    if reject_reason:
        trace_items.append(f"{_audit_label('rejection_reason_prefix')} {reject_reason}")
    trace_html = "".join(f"<li>{safe_html(item)}</li>" for item in trace_items)
    return (
        '<div class="job-insight-group is-secondary scoring-decision-trace">'
        f"<strong>{safe_html(_audit_label('decision_trace_heading'))}</strong>"
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
    "quick_filters_label",
    "quick_filter_new_to_you",
    "quick_filter_direct_employer",
    "quick_filter_easy_apply",
    "more_filters_label",
    "job_boards_label",
    "job_boards_all_label",
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
    "last_run_cards_seen_label",
    "last_run_details_checked_label",
    "last_run_accepted_label",
    "last_run_rejected_label",
    "last_run_llm_cost_label",
    "last_run_input_tokens_label",
    "last_run_output_tokens_label",
    "workspace_status_heading",
    "workspace_status_helper",
    "workspace_visible_label",
    "workspace_new_label",
    "workspace_opened_label",
    "workspace_saved_label",
    "lifetime_llm_heading",
    "lifetime_llm_helper",
    "lifetime_llm_cost_label",
    "lifetime_input_tokens_label",
    "lifetime_output_tokens_label",
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
    "profile_gap_added_new_template",
    "profile_gap_added_existing_template",
    "profile_gap_already_present_template",
    "profile_gap_not_have_saved_template",
    "profile_gap_error_label",
)


@lru_cache(maxsize=1)
def _workspace_ui_labels() -> dict:
    return load_ui_labels()


def load_workspace_page_labels() -> dict[str, str]:
    payload = _workspace_ui_labels()
    raw_labels = payload.get("workspace_page_labels", {})
    if not isinstance(raw_labels, dict):
        raise ValueError("ui_labels.json is missing workspace_page_labels")
    work_mode_labels = payload.get("work_mode_labels", {})
    if not isinstance(work_mode_labels, dict):
        raise ValueError("ui_labels.json is missing work_mode_labels")
    card_labels = payload.get("workspace_card_labels", {})
    if not isinstance(card_labels, dict):
        raise ValueError("ui_labels.json is missing workspace_card_labels")
    # work_mode_labels and workspace_card_labels are the canonical sources for these
    # option/tab strings so they stay in sync with the same text used elsewhere in the app.
    labels = {
        **raw_labels,
        "work_mode_option_remote": work_mode_labels.get("remote_label", ""),
        "work_mode_option_hybrid": work_mode_labels.get("hybrid_label", ""),
        "work_mode_option_on_site": work_mode_labels.get("onsite_label", ""),
        "applied_jobs_tab": card_labels.get("applied_badge", ""),
        "hidden_jobs_tab": card_labels.get("hidden_badge", ""),
    }
    missing = [key for key in _WORKSPACE_PAGE_LABEL_KEYS if not str(labels.get(key, "")).strip()]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing workspace_page_labels values: {', '.join(missing)}"
        )
    return {
        f"LABEL_WS_{key.upper()}": escape(str(labels[key]).strip())
        for key in _WORKSPACE_PAGE_LABEL_KEYS
    }


def _workspace_label(group: str, key: str) -> str:
    payload = _workspace_ui_labels().get(group, {})
    if isinstance(payload, dict):
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value)
    raise ValueError(f"ui_labels.json is missing {group}.{key}")


def _render_job_insights_panel(
    summary_label: str,
    body_html: str,
    *,
    modifier_class: str = "",
) -> str:
    """Render the shared expandable panel shell used inside job cards.

    Panel-specific styling belongs in modifier classes such as
    ``job-risk-panel``; the structural markup stays identical.
    """
    if not body_html:
        return ""
    classes = "job-insights"
    modifier = compact_whitespace(modifier_class)
    if modifier:
        classes = f"{classes} {modifier}"
    return (
        f'<details class="{safe_html(classes)}">'
        f"<summary>{safe_html(summary_label)}</summary>"
        f"{body_html}"
        "</details>"
    )


ARCHIVE_LABEL = _workspace_label("workspace_page_labels", "archive_label")
ARCHIVE_BADGE_TOOLTIP = _workspace_label("workspace_card_labels", "archive_badge_tooltip")


def _workspace_job_card_id(job_key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", compact_whitespace(job_key).lower()).strip("-")
    return f"job-card-{slug}" if slug else "job-card"


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
        or lower.startswith("missing required requirement")
    ):
        requirement_warning = _humanize_missing_requirement_warning(text)
        if requirement_warning:
            return requirement_warning
    if _NV1_PATTERNS.search(lower):
        return _workspace_label("check_item_labels", "clearance_requirement_warning").format(
            clearance="NV1"
        )
    if _CLEARANCE_PATTERNS.search(lower):
        return _workspace_label("check_item_labels", "clearance_requirement_warning").format(
            clearance="a security"
        )
    return t


def _humanize_requirement_label(text: str) -> str:
    cleaned = compact_whitespace(text)
    if not cleaned:
        return ""

    cleaned = re.sub(
        r"^(critical missing requirement|missing required requirement)\s*:\s*",
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
        if lowered in _REQUIRED_REQUIREMENT_ACRONYMS:
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
    return f"Missing required requirement: {requirement}"


def _build_checks_before_applying_items(
    history_warning_signals: list[str],
    description_issue: bool,
    is_possible_repost: bool,
    similar_applied_record: Optional[dict],
    candidate_history: Optional[dict],
    hard_block_reasons_list: list[str],
    salary_fit_state: str,
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

    for reason in history_warning_signals:
        cleaned = compact_whitespace(reason)
        if cleaned.lower().startswith("potential red flag:"):
            cleaned = compact_whitespace(cleaned.removeprefix("Potential red flag:"))
        if cleaned and cleaned[-1] not in ".!?":
            cleaned = f"{cleaned}."
        add(cleaned)

    if description_issue:
        add(_workspace_label("check_item_labels", "description_capture_issue"))

    possible_repost_prefix = _workspace_label("check_item_labels", "possible_repost_prefix")
    if is_possible_repost and similar_applied_record:
        repost_title = compact_whitespace(str(similar_applied_record.get("title") or ""))
        repost_company = compact_whitespace(str(similar_applied_record.get("company") or ""))
        repost_source = get_source_display_label(
            str(similar_applied_record.get("source") or "").strip().lower()
        )
        repost_bits = [bit for bit in [repost_title, repost_company, repost_source] if bit]
        add(
            possible_repost_prefix
            + (f": {' — '.join(repost_bits)}" if repost_bits else ".")
        )
    elif is_possible_repost:
        add(f"{possible_repost_prefix}.")

    if isinstance(candidate_history, dict) and candidate_history:
        cand_company = compact_whitespace(str(candidate_history.get("llm_company") or ""))
        cand_role = compact_whitespace(str(candidate_history.get("llm_role") or ""))
        cand_status = compact_whitespace(
            str(candidate_history.get("llm_application_status") or "")
        ).lower()
        cand_confidence = compact_whitespace(str(candidate_history.get("llm_confidence") or "")).lower()
        if cand_company or cand_role:
            history_label = (
                _workspace_label("check_item_labels", "rejected_before_label")
                if cand_status == "rejection" and cand_confidence != "low"
                else _workspace_label("check_item_labels", "possible_previous_application_label")
            )
            history_bits = [bit for bit in [cand_company, cand_role] if bit]
            add(
                history_label
                + (f": {' — '.join(history_bits)}" if history_bits else "")
            )

    if salary_fit_state == "below":
        add(_workspace_label("check_item_labels", "salary_below_target"))

    for item in hard_block_reasons_list:
        add(_humanize_check_item(str(item)))

    for item in soft_risk_reasons or []:
        add(_humanize_check_item(str(item)))

    for signal in job_quality_signals or []:
        add(compact_whitespace(str(signal.get("evidence") or signal.get("label") or "")))

    return items


def _render_posted_age_meta(age_days: Optional[float]) -> str:
    """Render freshness beside the posted date instead of as a separate badge."""

    if age_days is None:
        return ""
    display_days = max(int(age_days), 0)
    if display_days == 0:
        label = _workspace_label("workspace_card_labels", "posted_age_meta_today")
    elif display_days == 1:
        label = Template(
            _workspace_label("workspace_card_labels", "posted_age_meta_singular_template")
        ).substitute(days=display_days)
    else:
        label = Template(
            _workspace_label("workspace_card_labels", "posted_age_meta_template")
        ).substitute(days=display_days)
    return f'<span class="job-posted-age"> · {safe_html(label)}</span>'


def render_custom_blocker_preview(resolution: dict, debug_mode: bool = False) -> str:
    """Render the save/reject preview for a custom "Not For Me" blocker term.

    resolution is the dict returned by profile_gaps.resolve_custom_blocker.
    Debug mode additionally surfaces the raw input, matched job evidence, and
    the exact value that would be persisted, so a human can audit the
    resolution without reading server logs.
    """
    reason_code = str(resolution.get("reason_code") or "")
    canonical_requirement = str(resolution.get("canonical_requirement") or "")
    requirement_type = str(resolution.get("requirement_type") or "")
    importance = str(resolution.get("importance") or "")

    is_resolved = bool(resolution.get("ok")) and reason_code == CUSTOM_BLOCKER_REASON_RESOLVED
    preview_state_class = "custom-blocker-preview--resolved" if is_resolved else "custom-blocker-preview--rejected"
    parts: List[str] = [f'<div class="custom-blocker-preview {preview_state_class}">']
    if is_resolved:
        requirement_type_label = _workspace_label(
            "workspace_card_labels", f"custom_blocker_requirement_type_{requirement_type}"
        )
        importance_label = _workspace_label("workspace_card_labels", f"importance_{importance}")
        heading = Template(
            _workspace_label("workspace_card_labels", "custom_blocker_preview_heading_template")
        ).substitute(importance=importance_label, requirement_type=requirement_type_label)
        save_as_label = _workspace_label("workspace_card_labels", "custom_blocker_preview_save_as_label")
        parts.append(f'<div class="custom-blocker-preview-name">{safe_html(canonical_requirement)}</div>')
        parts.append(
            f'<span class="jh-badge job-req-importance job-req-importance--{safe_html(importance)}">'
            f"{safe_html(heading)}</span>"
        )
        parts.append(f'<div class="custom-blocker-preview-save-as">{safe_html(save_as_label)}</div>')
    else:
        if reason_code == CUSTOM_BLOCKER_REASON_NOT_REQUIRED:
            importance_label = _workspace_label("workspace_card_labels", f"importance_{importance}")
            reason_text = Template(
                _workspace_label("workspace_card_labels", "custom_blocker_reason_not_required_template")
            ).substitute(importance=importance_label)
        elif reason_code == CUSTOM_BLOCKER_REASON_AMBIGUOUS:
            reason_text = _workspace_label("workspace_card_labels", "custom_blocker_reason_ambiguous")
        elif reason_code == CUSTOM_BLOCKER_REASON_INVALID_INPUT:
            reason_text = _workspace_label("workspace_card_labels", "custom_blocker_reason_invalid_input")
        else:
            # CUSTOM_BLOCKER_REASON_NO_MATCH and any unexpected code both fall back here.
            reason_text = _workspace_label("workspace_card_labels", "custom_blocker_reason_no_match")
        parts.append(f'<div class="custom-blocker-preview-rejected">{safe_html(reason_text)}</div>')

    if debug_mode:
        raw_input_label = _workspace_label("workspace_card_labels", "custom_blocker_debug_raw_input_label")
        resolved_label = _workspace_label("workspace_card_labels", "custom_blocker_debug_resolved_label")
        requirement_type_debug_label = _workspace_label(
            "workspace_card_labels", "custom_blocker_debug_requirement_type_label"
        )
        importance_debug_label = _workspace_label("workspace_card_labels", "custom_blocker_debug_importance_label")
        matched_evidence_label = _workspace_label(
            "workspace_card_labels", "custom_blocker_debug_matched_evidence_label"
        )
        validation_result_label = _workspace_label(
            "workspace_card_labels", "custom_blocker_debug_validation_result_label"
        )
        profile_field_label = _workspace_label("workspace_card_labels", "custom_blocker_debug_profile_field_label")
        persisted_value_label = _workspace_label(
            "workspace_card_labels", "custom_blocker_debug_persisted_value_label"
        )
        persisted_value = canonical_requirement if resolution.get("ok") else ""
        debug_rows = [
            (raw_input_label, str(resolution.get("raw_input") or "")),
            (resolved_label, canonical_requirement),
            (requirement_type_debug_label, requirement_type),
            (importance_debug_label, importance),
            (matched_evidence_label, str(resolution.get("matched_job_text") or "")),
            (validation_result_label, reason_code),
            (profile_field_label, KEY_MUST_NOT_REQUIRED_SKILLS),
            (persisted_value_label, persisted_value),
        ]
        parts.append('<dl class="custom-blocker-preview-debug">')
        for row_label, row_value in debug_rows:
            parts.append(f"<dt>{safe_html(row_label)}</dt><dd>{safe_html(row_value)}</dd>")
        parts.append("</dl>")

    parts.append("</div>")
    return "".join(parts)


def score_filter_option_label(threshold: int, scoring_profile: Optional[dict] = None) -> str:
    active_profile = scoring_profile or load_profile()
    match_levels = get_match_levels(active_profile)
    label = score_to_match_label(threshold, match_levels)
    highest_threshold = max(_match_level_minimum_score(level) for level in match_levels)
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
        return [_match_level_minimum_score(level) for level in match_levels]
    return [
        _match_level_minimum_score(level)
        for level in match_levels
        if _match_level_minimum_score(level) >= active_workspace_min_score
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
    previous_count = -1
    for threshold in [1, 3, 7, 14, 30]:
        count = sum(
            1
            for record in records
            if (age_days := current_posted_age_days(record, now)) is not None
            and age_days <= threshold
        )
        if count == previous_count:
            # A wider window that captures no additional jobs is a duplicate
            # of the narrower option already shown — offering it just repeats
            # the same count and implies a distinction that doesn't exist.
            continue
        options.append(
            f'<option value="{threshold}">'
            f"{safe_html(posted_filter_option_label(threshold))} ({count})</option>"
        )
        previous_count = count
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


def render_job_board_filter_choices() -> str:
    """Render workspace board choices from the managed source registry."""
    from job_hunter_agent.source_registry import load_source_registry

    labels = load_source_registry()["source_display_labels"]
    choices = [
        '<button class="jh-filter-choice" type="button" data-source-filter="all" aria-pressed="true">'
        f'{safe_html(_workspace_label("workspace_page_labels", "job_boards_all_label"))}</button>'
    ]
    for source, label in labels.items():
        choices.append(
            f'<button class="jh-filter-choice" type="button" data-source-filter="{safe_html(source)}" '
            f'aria-pressed="false">{safe_html(label)}</button>'
        )
    return "".join(choices)


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
        ("potential", _workspace_label("workspace_page_labels", "potential_jobs_tab"), shortlist_count),
        ("applied", _workspace_label("workspace_card_labels", "applied_badge"), applied_count),
        ("hidden", _workspace_label("workspace_card_labels", "hidden_badge"), hidden_count),
    ]
    buttons = []
    for target, label, count in tabs:
        active_class = " is-active" if active_target == target else ""
        safe_label = safe_html(label)
        buttons.append(
            f'<button class="scope-tab{active_class}" type="button" '
            f'data-workspace-target="{target}" data-tab-label="{safe_label}">'
            f"{safe_label} ({count})"
            "</button>"
        )
    aria_label = safe_html(_workspace_label("workspace_page_labels", "top_level_workspace_views_aria_label"))
    return f'<div class="scope-tabs" aria-label="{aria_label}">' + "".join(buttons) + "</div>"


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
        return _workspace_label("title_match_labels", "secondary_match")
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
    applied_record = bool(record.get("applied"))
    archived = bool(record.get("archived"))
    hidden_record = bool(record.get("hidden"))
    is_stale = bool(record.get("is_stale"))
    seen_by_you = viewed_by_user(record)
    teaser_text = _clean_job_card_text(record.get("teaser") or "")
    stored_snapshot = _clean_job_card_text(record.get("role_snapshot") or "")
    if not stored_snapshot:
        stored_snapshot = teaser_text or "N/A"
    if stored_snapshot in {"", "N/A"}:
        snapshot_record = dict(record)
        snapshot_record["teaser"] = teaser_text
        stored_snapshot = synthesize_role_snapshot(snapshot_record)
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
        soft_risk_reasons = build_display_competitive_risks(
            display_record.get("competitive_signals")
            if isinstance(display_record.get("competitive_signals"), list)
            else None
        )
        blocking_reasons = hard_block_reasons(display_record, active_profile)
    else:
        role_summary = stored_snapshot
        display_record["fit_confidence"] = "LOW"
        display_record["competitive_signals"] = []
        fit_highlights = []
        soft_risk_reasons = []
        blocking_reasons = []

    similar_applied_record = None
    is_possible_repost = False
    if not applied_record and applied_pool:
        similar_applied_record = find_confirmed_duplicate(record, applied_pool)
        is_possible_repost = similar_applied_record is not None
    _record_source = str(record.get("source") or "").lower().strip()
    if linkedin_freshness_is_unknown(record):
        # LinkedIn listings always carry a posted date; a missing posted_age_days here means
        # the backfill fetch/parse failed for this job, not that the post has no date. That's
        # a scrape-side gap worth investigating, not a risk to surface to the user on the card.
        logger.warning(
            "[RENDERER] job=%s title=%r LinkedIn posted_age_days missing — freshness backfill "
            "did not resolve a post date for this listing",
            record.get("job_key", "<unknown>"),
            str(record.get("title") or "").strip(),
        )
    elif linkedin_original_posted_is_unverified(record):
        soft_risk_reasons = dedupe_preserve_order([
            *soft_risk_reasons,
            _workspace_label("check_item_labels", "linkedin_freshness_unverified_warning"),
        ])
    display_record["hard_block_reasons"] = blocking_reasons
    display_record["role_snapshot"] = role_summary
    display_record["fit_highlights"] = fit_highlights
    display_record["soft_risk_reasons"] = soft_risk_reasons
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
    teaser_attr = safe_html(teaser_text)
    card_sector = "unknown"
    channel_signal = display_record.get("posting_channel_evidence")
    if not posting_channel_evidence_is_current(channel_signal):
        # Saved workspace rows can outlive the classifier contract that produced
        # their badge. Do not present stale derived classification as current;
        # the next job review will repopulate it under the active contract.
        channel_signal = {}
    raw_coverage = display_record.get(RECORD_REQUIREMENT_COVERAGE_KEY)
    raw_coverage_is_list = isinstance(raw_coverage, list)
    coverage_rows = raw_coverage if isinstance(raw_coverage, list) else []
    duplicate_links = record.get(RECORD_DUPLICATE_LINKS_KEY)
    if not isinstance(duplicate_links, list):
        duplicate_links = []
    potential_duplicate_links = record.get(RECORD_POTENTIAL_DUPLICATE_LINKS_KEY)
    if not isinstance(potential_duplicate_links, list):
        potential_duplicate_links = []
    block_title_hint = safe_html(
        suggest_title_block_phrase(str(record.get("title") or ""), active_profile)
    )
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
        badges.append(
            render_badge(
                _workspace_label("workspace_card_labels", "applied_badge"),
                "badge-viewed",
                _workspace_label("workspace_card_labels", "applied_badge_tooltip"),
            )
        )
    elif hidden_record:
        badges.append(
            render_badge(
                _workspace_label("workspace_card_labels", "hidden_badge"),
                "badge-hidden",
                _workspace_label("workspace_card_labels", "hidden_badge_tooltip"),
            )
        )
    if not applied_record and not seen_by_you:
        badges.append(
            render_badge(
                _workspace_label("workspace_card_labels", "new_to_you_badge"),
                "badge-new",
                _workspace_label("workspace_card_labels", "new_to_you_badge_tooltip"),
            )
        )
    if seen_by_you:
        badges.append(viewed_badge_html())
    apply_method = str(record.get(RECORD_APPLY_METHOD_KEY) or "").strip()
    if apply_method == APPLY_METHOD_EASY_APPLY:
        apply_method_label = _workspace_label("workspace_card_labels", "apply_method_easy_apply_badge")
        apply_method_tooltip = _workspace_label("workspace_card_labels", "apply_method_easy_apply_tooltip")
    elif apply_method == APPLY_METHOD_QUICK_APPLY:
        apply_method_label = _workspace_label("workspace_card_labels", "apply_method_quick_apply_badge")
        apply_method_tooltip = _workspace_label("workspace_card_labels", "apply_method_quick_apply_tooltip")
    else:
        apply_method_label = ""
        apply_method_tooltip = ""
    if apply_method_label:
        source_badge_label = _workspace_label(
            "workspace_card_labels", "source_badge_with_apply_method_label"
        ).format(source=source_label, apply_method=apply_method_label)
        source_badge_tooltip = _workspace_label(
            "workspace_card_labels", "source_badge_with_apply_method_tooltip"
        ).format(source=source_label, apply_tooltip=apply_method_tooltip)
    else:
        source_badge_label = source_label
        source_badge_tooltip = _workspace_label("workspace_card_labels", "source_badge_tooltip").format(
            source=source_label
        )
    badges.append(render_badge(source_badge_label, f"badge-source-{source}", source_badge_tooltip))
    if record.get(RECORD_IS_REPOSTED_KEY) is True and not applied_record:
        badges.append(
            render_badge(
                _workspace_label("workspace_card_labels", "reposted_badge"),
                "badge-warning",
                _workspace_label("workspace_card_labels", "reposted_badge_tooltip"),
            )
        )
    channel_kind = channel_signal.get("kind", "")
    if channel_kind == "agency_or_recruiter":
        if channel_signal.get("needs_review"):
            badges.append(
                render_badge(
                    _workspace_label(
                        "workspace_card_labels",
                        "posting_channel_likely_recruiter_badge",
                    ),
                    "badge-warning",
                    _workspace_label(
                        "workspace_card_labels",
                        "posting_channel_likely_recruiter_tooltip",
                    ),
                )
            )
        else:
            badges.append(
                render_badge(
                    _workspace_label(
                        "workspace_card_labels",
                        "posting_channel_agency_recruiter_badge",
                    ),
                    "badge-source-neutral",
                    _workspace_label(
                        "workspace_card_labels",
                        "posting_channel_agency_recruiter_tooltip",
                    ),
                )
            )
    elif channel_kind == "direct_employer":
        badges.append(
            render_badge(
                _workspace_label("workspace_card_labels", "posting_channel_direct_employer_badge"),
                "badge-source-neutral",
                _workspace_label("workspace_card_labels", "posting_channel_direct_employer_tooltip"),
            )
        )
    elif channel_kind:
        badges.append(
            render_badge(
                _workspace_label(
                    "workspace_card_labels", "posting_channel_unknown_badge"),
                "badge-archive",
                _workspace_label(
                    "workspace_card_labels",
                    "posting_channel_unknown_tooltip",
                ),
            )
        )
    history_warning_signals = assess_history_warning_signals(record, history_clusters)
    if duplicate_links:
        duplicate_tooltip = _workspace_label(
            "duplicate_labels",
            "confirmed_tooltip",
        )
        badges.append(
            render_badge(
                _workspace_label("duplicate_labels", "confirmed_badge"),
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
            )
        badges.append(
            render_badge(
                f'{_workspace_label("duplicate_labels", "potential_badge")} ({_pd_count})',
                "badge-warning",
                potential_tooltip,
            )
        )
    related_cards_html = ""
    if potential_duplicate_links:
        related_rows: list[str] = []
        for related in potential_duplicate_links:
            related_title = str(related.get("related_title") or "").strip()
            related_company = (
                normalize_company_name(str(related.get("related_company") or ""))
                or str(related.get("related_company") or "").strip()
            )
            related_job_key = str(related.get("related_job_key") or "").strip()
            related_url = str(related.get("related_url") or "").strip()
            related_card_target = _workspace_job_card_id(related_job_key) if related_job_key else ""
            if related_card_target:
                related_href = f"#{related_card_target}"
                related_action_attrs = (
                    f' data-related-card-target="{safe_html(related_card_target)}"'
                )
                related_external_attrs = ""
            elif related_url:
                related_href = related_url
                related_action_attrs = ""
                related_external_attrs = ' target="_blank" rel="noopener noreferrer"'
            else:
                related_href = "#"
                related_action_attrs = ""
                related_external_attrs = ""
            related_rows.append(
                '<div class="job-related-card-row">'
                '<div class="job-related-card-copy">'
                f'<strong class="job-related-card-title">{safe_html(related_title)}</strong>'
                f'<span class="job-related-card-company">{safe_html(related_company)}</span>'
                "</div>"
                f'<a class="jh-button jh-button--secondary jh-button--compact job-related-card-action" '
                f'href="{safe_html(related_href)}"{related_action_attrs}{related_external_attrs}>'
                f'{safe_html(_workspace_label("duplicate_labels", "callout_prefix"))}'
                '<span aria-hidden="true">&#8594;</span>'
                "</a>"
                "</div>"
            )
        related_cards_html = _render_job_insights_panel(
            _workspace_label("duplicate_labels", "potential_badge"),
            f'<div class="job-related-card-list">{"".join(related_rows)}</div>',
            modifier_class="job-related-cards-panel",
        )
    job_quality_signals = [
        s for s in (record.get("job_quality_signals") or []) if isinstance(s, dict)
    ]
    debug_status = _record_debug_status(record)
    if active_debug_mode and debug_status:
        if debug_status == "hard-blocked":
            badges.append(
                render_badge(
                    _workspace_label("workspace_card_labels", "hard_blocked_badge"),
                    "badge-hidden",
                    _workspace_label(
                        "workspace_card_labels",
                        "hard_blocked_tooltip",
                    ),
                )
            )
        else:
            badges.append(
                render_badge(
                    _workspace_label("workspace_card_labels", "debug_only_badge"),
                    "badge-source-neutral",
                    _workspace_label(
                        "workspace_card_labels",
                        "debug_only_tooltip",
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
            _workspace_label("check_item_labels", "rejected_before_label")
            if _ch_status == "rejection" and _ch_confidence != "low"
            else _workspace_label("check_item_labels", "possible_previous_application_label")
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
    _original_posted_verified = (
        str(record.get(RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY) or "").strip().lower()
        == ORIGINAL_POSTED_DATE_STATUS_VERIFIED
    )
    _linkedin_original_unverified = linkedin_original_posted_is_unverified(record)
    _is_reposted = record.get(RECORD_IS_REPOSTED_KEY) is True
    _board_posted_display = board_posted_display_label(record) if _original_posted_verified else ""
    _original_posted_display = (
        original_posted_display_label(record) if _original_posted_verified else ""
    )
    posted_age_meta = _render_posted_age_meta(posted_age_days)
    contract_duration_display = display_contract_duration_label(display_record)
    normalized_work_type_signature = re.sub(
        r"[^a-z0-9]+",
        " ",
        compact_whitespace(display_work_type_label(display_record)).lower(),
    ).strip()
    normalized_contract_duration_signature = re.sub(
        r"[^a-z0-9]+",
        " ",
        compact_whitespace(contract_duration_display).lower(),
    ).strip()
    meta_items = []
    if _is_reposted and not applied_record and _board_posted_display and _original_posted_display:
        meta_items.append(
            f'<span class="job-meta-item"><strong>{safe_html(source_label)} {safe_html(_workspace_label("workspace_meta_labels", "reposted_suffix"))}</strong> {safe_html(str(_board_posted_display))}{posted_age_meta}</span>'
        )
        meta_items.append(
            f'<span class="job-meta-item"><strong>{safe_html(_workspace_label("workspace_meta_labels", "originally_posted"))}</strong> {safe_html(str(_original_posted_display))}</span>'
        )
    elif posted_display:
        posted_label = _workspace_label("workspace_page_labels", "posted_label")
        posted_value = posted_display
        if _linkedin_original_unverified:
            posted_label = _workspace_label("workspace_meta_labels", "linkedin_listed")
            posted_value = board_posted_display_label(record) or posted_display
        meta_items.append(
            f'<span class="job-meta-item"><strong>{safe_html(posted_label)}</strong> {safe_html(str(posted_value))}{posted_age_meta}</span>'
        )
    else:
        logger.warning(
            "[RENDERER] job=%s title=%r source=%s missing posted display; omitting posted meta item",
            display_record.get("job_key", "<unknown>"),
            str(display_record.get("title") or "").strip(),
            source,
        )
    for label, value, always_show in [
        (_workspace_label("workspace_meta_labels", "location"), display_record.get("location"), False),
        (
            _workspace_label("workspace_page_labels", "work_mode_sidebar_label"),
            display_work_mode_label(display_record),
            False,
        ),
        (
            _workspace_label("workspace_page_labels", "work_type_sidebar_label"),
            display_work_type_label(display_record),
            False,
        ),
        (
            _workspace_label("workspace_meta_labels", "contract_duration"),
            contract_duration_display,
            False,
        ),
        (
            _workspace_label("workspace_meta_labels", "salary"),
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
                _workspace_label("check_item_labels", "salary_below_target"),
            ]
        )
    if seen_by_you and record.get("last_viewed_at"):
        context_bits.append(
            f"{_workspace_label('workspace_card_labels', 'opened_by_you_prefix')} "
            f"{format_timestamp_label(record.get('last_viewed_at'), include_time=False)}"
        )
    if applied_record and record.get("last_applied_at"):
        context_bits.append(
            f"{_workspace_label('workspace_card_labels', 'applied_badge')} "
            f"{format_timestamp_label(record.get('last_applied_at'))}"
        )
    if hidden_record and record.get("last_hidden_at"):
        context_bits.append(
            f"{_workspace_label('workspace_card_labels', 'hidden_badge')} "
            f"{format_timestamp_label(record.get('last_hidden_at'))}"
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
            '<span class="job-summary-toggle">'
            '<span class="job-summary-toggle-icon" aria-hidden="true"></span>'
            f'<span class="job-summary-toggle-label job-summary-toggle-label--closed">{safe_html(_workspace_label("workspace_card_labels", "show_more_label"))}</span>'
            f'<span class="job-summary-toggle-label job-summary-toggle-label--open">{safe_html(_workspace_label("workspace_card_labels", "show_less_label"))}</span>'
            '</span>'
            "</summary>"
            f'<div class="job-summary-expanded">{_render_full_description_html(display_trusted_desc)}</div>'
            "</details>"
        )
    check_items = _build_checks_before_applying_items(
        history_warning_signals,
        description_issue,
        is_possible_repost,
        similar_applied_record,
        _cand_hist,
        blocking_reasons,
        salary_fit_state,
        soft_risk_reasons,
        job_quality_signals,
    )
    job_requirements_html = ""
    merged_requirement_rows: dict[str, dict[str, Any]] = {}
    merged_requirement_order: list[str] = []
    qualification_coverage_rows: dict[str, dict[str, Any]] = {}
    qualification_coverage_order: list[str] = []
    eligibility_coverage_rows_by_subtype: dict[str, dict[str, dict[str, Any]]] = {}
    eligibility_coverage_order_by_subtype: dict[str, list[str]] = {}
    has_unclassified_coverage = False
    taxonomy_payload: dict[str, Any] = {}
    capability_level_lookup = _capability_level_lookup(active_profile)
    # When requirement_coverage is available, show only those rows (they are more
    # detailed and LLM-verified). Use requirement_coverage as the only requirement source to avoid
    # showing the same requirements twice with different text.
    has_coverage = len(coverage_rows) > 0
    importance_label_keys = {
        "required": "importance_required",
        "expected": "importance_expected",
        "preferred": "importance_preferred",
        "bonus": "importance_bonus",
    }
    # Ordering only (not display text) — keeps each importance tier visually
    # clustered within a requirement group instead of merging preferred tiers.
    importance_sort_buckets = {
        "required": 0,
        "expected": 1,
        "preferred": 2,
        "bonus": 3,
    }
    matched_css_modifiers = {"supported", "confirmed-have"}
    def _requirement_key(value: str) -> str:
        return compact_whitespace(value).lower()

    def _importance_bucket(importance: str) -> int:
        return importance_sort_buckets.get(importance, importance_sort_buckets["preferred"])

    def _requirement_sort_key(row: dict[str, Any]) -> tuple[int, str]:
        importance = compact_whitespace(str(row.get("importance") or "")).lower()
        requirement = compact_whitespace(str(row.get("requirement") or "")).lower()
        return (_importance_bucket(importance), requirement)

    def _is_structured_meta_requirement(req_text: str) -> bool:
        requirement_signature = re.sub(
            r"[^a-z0-9]+",
            " ",
            compact_whitespace(req_text).lower(),
        ).strip()
        if not requirement_signature:
            return False
        if normalized_work_type_signature and requirement_signature == normalized_work_type_signature:
            return True
        if normalized_work_type_signature and normalized_contract_duration_signature:
            structured_signatures = {
                f"{normalized_work_type_signature} {normalized_contract_duration_signature}".strip(),
                f"{normalized_contract_duration_signature} {normalized_work_type_signature}".strip(),
            }
            if requirement_signature in structured_signatures:
                return True
        return False

    def _css_modifier_for_row(row: dict[str, Any]) -> str:
        coverage_status = str(row.get("coverage_status") or "").strip().lower()
        importance = str(row.get("importance") or "").strip().lower()
        if coverage_status == "supported":
            return "supported"
        if coverage_status == "partially_supported":
            return "partially-supported"
        if coverage_status == "mismatch":
            return "mismatch"
        if coverage_status == "invalid":
            return "invalid"
        if coverage_status == "not_shown" and importance == "required":
            return "required-not-shown"
        if coverage_status == "not_shown":
            return "not-shown"
        return "unknown"

    def _render_requirement_row_html(row: dict[str, Any]) -> tuple[str, bool]:
        req_text = compact_whitespace(str(row.get("requirement") or ""))
        if not req_text:
            return "", False
        if _is_structured_meta_requirement(req_text):
            return "", False
        importance = str(row.get("importance") or "").strip().lower()
        matched_candidate_fact = compact_whitespace(
            str(
                row.get("matched_candidate_fact")
                or row.get("profile_name")
                or row.get("capability_name")
                or row.get("eligibility_name")
                or ""
            )
        )
        matched_text = compact_whitespace(str(row.get("matched_job_text") or ""))
        level_label = capability_level_lookup.get(
            _normalize_capability_token(matched_candidate_fact), ""
        )
        required_experience_months = _workspace_int(row.get("required_experience_months") or 0)
        matched_role_experience_title = compact_whitespace(
            str(row.get("matched_role_experience_title") or "")
        )
        matched_role_experience_months = _workspace_int(
            row.get("matched_role_experience_months") or 0
        )
        matched_role_experience_end_year = _workspace_int(
            row.get("matched_role_experience_end_year") or 0
        )
        experience_requirement_review_needed = bool(
            row.get("experience_requirement_review_needed")
        )

        css_modifier = _css_modifier_for_row(row)

        is_uncertain_classification = row.get("requirement_type") == "uncertain"

        importance_label = ""
        if importance:
            importance_label = _workspace_label(
                "workspace_card_labels",
                importance_label_keys.get(importance, "importance_preferred"),
            )

        detail_html_parts: list[str] = []
        if active_debug_mode and matched_candidate_fact:
            profile_detail = matched_candidate_fact
            if level_label:
                profile_detail = f"{profile_detail} ({level_label})"
            detail_html_parts.append(
                f'<span class="req-coverage-tag jh-badge">{safe_html(profile_detail)}</span>'
            )
        if (
            active_debug_mode
            and matched_text
            and compact_whitespace(matched_text).lower() != req_text.lower()
        ):
            detail_html_parts.append(
                f'<span class="req-coverage-tag jh-badge req-coverage-tag--muted">{safe_html(_workspace_label("workspace_card_labels", "job_requirements_ad_wording_badge"))}</span>'
                f'<span class="req-coverage-detail-text">"{safe_html(matched_text)}"</span>'
            )
        detail_html = (
            '<span class="req-coverage-detail">' + "".join(detail_html_parts) + "</span>"
            if detail_html_parts
            else ""
        )
        experience_note_html = ""
        if required_experience_months > 0:
            required_years = required_experience_months / 12.0
            if matched_role_experience_title:
                experience_note = (
                    f"Role history proves {matched_role_experience_months} months in "
                    f"{matched_role_experience_title} against {required_experience_months} required months"
                )
                if matched_role_experience_end_year > 0:
                    experience_note += f" (most recent end year {matched_role_experience_end_year})"
            elif experience_requirement_review_needed:
                experience_note = (
                    f"Role history could not prove a matching role family for this "
                    f"{required_years:g}-year requirement."
                )
            else:
                experience_note = f"This requirement asks for {required_years:g} years of role history."
            experience_note_html = (
                f'<span class="job-requirement-note">{safe_html(experience_note)}</span>'
            )
        importance_html = (
            f'<span class="job-req-importance jh-badge job-req-importance--{safe_html(importance.replace("_", "-"))}">{safe_html(importance_label)}</span>'
            if importance_label
            else ""
        )
        profile_review_html = ""
        canonical_requirement = compact_whitespace(str(row.get("canonical_requirement") or ""))
        # profile_action_allowed (not canonical_requirement truthiness alone) is the
        # safety gate: an unresolved/vague group can still carry a display label
        # without being safe to prefill into the candidate's profile.
        if canonical_requirement and row.get("profile_action_allowed") and css_modifier in (
            "mismatch",
            "not-shown",
            "required-not-shown",
            "unknown",
            "invalid",
        ) and not is_uncertain_classification:
            is_eligibility = bool(row.get("is_eligibility"))
            is_qualification = bool(row.get("is_qualification"))
            action_label_key = (
                "add_to_qualification_action_label"
                if is_qualification
                else (
                    "add_to_eligibility_action_label"
                    if is_eligibility
                    else "add_to_profile_action_label"
                )
            )
            action_title_key = (
                "add_to_qualification_action_title"
                if is_qualification
                else (
                    "add_to_eligibility_action_title"
                    if is_eligibility
                    else "add_to_profile_action_title"
                )
            )
            confirm_have_html = (
                '<button type="button" class="jh-button jh-button--primary jh-button--micro job-requirement-action gap-btn" '
                f'data-action="confirm_have" data-capability-name="{safe_html(canonical_requirement)}" '
                f'title="{safe_html(_workspace_label("workspace_card_labels", action_title_key))}">'
                '<span aria-hidden="true">+</span>'
                f'<span>{safe_html(_workspace_label("workspace_card_labels", action_label_key))}</span></button>'
            )
            not_have_label = safe_html(
                _workspace_label("workspace_card_labels", "gap_confirm_not_have_label")
            )
            confirm_not_have_html = (
                f'<button type="button" class="jh-button jh-button--danger jh-button--micro job-requirement-action gap-btn" '
                f'data-action="confirm_do_not_have" data-capability-name="{safe_html(canonical_requirement)}">'
                f"{not_have_label}</button>"
            )
            profile_review_html = (
                '<span class="req-coverage-detail req-coverage-detail--profile-review">'
                '<span class="req-coverage-detail-text">'
                f'<strong>{safe_html(_workspace_label("workspace_card_labels", "profile_evidence_label"))}</strong> '
                f'{safe_html(_workspace_label("workspace_card_labels", "profile_evidence_unconfirmed_label"))}'
                '</span>'
                f'{confirm_have_html}{confirm_not_have_html}'
                '</span>'
            )
        html = (
            f'<li class="job-requirement-item job-requirement-item--{safe_html(css_modifier)}">'
            f'<span class="job-requirement-text">'
            f'<span class="job-requirement-title-line">'
            f'{safe_html(req_text)}{importance_html}'
            f'</span>'
            f'{profile_review_html}{detail_html}{experience_note_html}'
            f"</span>"
            f"</li>"
        )
        return html, bool(detail_html_parts)

    def _render_requirement_group_block(
        heading_label: str,
        items_html: str,
        tone: str,
    ) -> str:
        if not items_html:
            return ""
        return (
            f'<div class="job-insight-group is-secondary job-requirement-group '
            f'job-requirement-group--{safe_html(tone)}">'
            f'<strong class="job-requirement-group-heading">{safe_html(heading_label)}</strong>'
            f'<ul class="job-requirement-list">{items_html}</ul>'
            f"</div>"
        )

    def _render_requirement_sections_html(
        order: list[str],
        rows: dict[str, dict[str, Any]],
        attention_prefix_html: str = "",
    ) -> str:
        """Split rows into a 'needs attention' group (surfaced first) and a
        'matched' group, each internally sorted by importance tier. This keeps
        Job Requirements, Eligibility, and Qualifications panels consistent: gaps are
        always the first thing a user sees, regardless of which panel."""
        partial_keys: list[str] = []
        attention_keys: list[str] = []
        matched_keys: list[str] = []
        for key in order:
            row = rows.get(key)
            if not isinstance(row, dict):
                continue
            modifier = _css_modifier_for_row(row)
            if modifier in matched_css_modifiers:
                matched_keys.append(key)
            elif modifier == "partially-supported":
                partial_keys.append(key)
            else:
                attention_keys.append(key)
        partial_keys.sort(key=lambda key: _requirement_sort_key(rows[key]))
        attention_keys.sort(key=lambda key: _requirement_sort_key(rows[key]))
        matched_keys.sort(key=lambda key: _requirement_sort_key(rows[key]))

        partial_items_html = ""
        for key in partial_keys:
            row_html, _ = _render_requirement_row_html(rows[key])
            partial_items_html += row_html
        attention_items_html = attention_prefix_html
        for key in attention_keys:
            row_html, _ = _render_requirement_row_html(rows[key])
            attention_items_html += row_html
        matched_items_html = ""
        for key in matched_keys:
            row_html, _ = _render_requirement_row_html(rows[key])
            matched_items_html += row_html

        return (
            _render_requirement_group_block(
                _workspace_label("workspace_card_labels", "requirement_group_partial_heading"),
                partial_items_html,
                "partial",
            )
            + _render_requirement_group_block(
                _workspace_label("workspace_card_labels", "requirement_group_attention_heading"),
                attention_items_html,
                "attention",
            )
            + _render_requirement_group_block(
                _workspace_label("workspace_card_labels", "requirement_group_matched_heading"),
                matched_items_html,
                "matched",
            )
        )

    if has_coverage:
        # Coverage path: one row per coverage entry, no job_requirements duplication.
        # The top-level taxonomy is Capability/Eligibility/Qualification. Eligibility
        # keeps its subtype so managed clearances remain visible without becoming a
        # fourth top-level requirement type.
        raw_taxonomy_payload = _workspace_ui_labels().get("requirement_taxonomy_labels", {})
        taxonomy_payload = raw_taxonomy_payload if isinstance(raw_taxonomy_payload, dict) else {}
        subtype_labels = taxonomy_payload.get("eligibility_subtype_labels", {})
        if not isinstance(subtype_labels, dict) or not subtype_labels:
            raise ValueError(
                "ui_labels.json is missing requirement_taxonomy_labels.eligibility_subtype_labels"
            )
        default_eligibility_subtype = load_default_eligibility_subtype()
        if default_eligibility_subtype not in subtype_labels:
            raise ValueError(
                "ui_labels.json is missing requirement_taxonomy_labels.eligibility_subtype_labels.other"
            )

        for item in coverage_rows:
            if not isinstance(item, dict):
                continue
            req_text = compact_whitespace(str(item.get("requirement") or ""))
            if not req_text:
                continue
            raw_requirement_type = compact_whitespace(
                str(item.get("requirement_type") or "")
            ).lower()
            is_eligibility = raw_requirement_type == "eligibility"
            is_qualification = raw_requirement_type == "qualification"
            classification_review = raw_requirement_type not in {"capability", "eligibility", "qualification"}
            has_unclassified_coverage = has_unclassified_coverage or classification_review

            if is_eligibility:
                requirement_subtype = compact_whitespace(
                    str(item.get("requirement_subtype") or "")
                ).lower()
                if requirement_subtype not in subtype_labels:
                    requirement_subtype = default_eligibility_subtype
                target_rows = eligibility_coverage_rows_by_subtype.setdefault(
                    requirement_subtype, {}
                )
                target_order = eligibility_coverage_order_by_subtype.setdefault(
                    requirement_subtype, []
                )
            elif is_qualification:
                requirement_subtype = ""
                target_rows = qualification_coverage_rows
                target_order = qualification_coverage_order
            else:
                requirement_subtype = ""
                target_rows = merged_requirement_rows
                target_order = merged_requirement_order

            key = _requirement_key(req_text)
            if key not in target_rows:
                target_rows[key] = {"requirement": req_text}
                target_order.append(key)
            row = target_rows[key]
            row["coverage_status"] = str(item.get("status") or "not_shown").strip().lower()
            row["requirement_type"] = raw_requirement_type
            row["requirement_subtype"] = requirement_subtype
            row["canonical_requirement"] = compact_whitespace(str(item.get("canonical_requirement") or ""))
            # Set by normalize_llm_requirement_coverage: whether canonical_requirement
            # is one clear, candidate-confirmable fact and not a vague/invented group
            # label. Add-to-profile must gate on this, not just on canonical_requirement
            # being non-empty.
            row["profile_action_allowed"] = bool(item.get("profile_action_allowed"))
            row["importance"] = str(item.get("importance") or "preferred").strip().lower()
            row["is_eligibility"] = is_eligibility
            row["is_qualification"] = is_qualification
            row["classification_review"] = classification_review
            row["matched_candidate_fact"] = compact_whitespace(
                str(item.get("matched_candidate_fact") or item.get("profile_name") or "")
            )
            row["capability_name"] = compact_whitespace(str(item.get("capability_name") or ""))
            row["eligibility_name"] = compact_whitespace(str(item.get("eligibility_name") or ""))
            row["qualification_name"] = compact_whitespace(str(item.get("qualification_name") or ""))
            row["matched_job_text"] = compact_whitespace(str(item.get("matched_job_text") or ""))
            row["required_experience_months"] = _workspace_int(
                item.get("required_experience_months") or 0
            )
            row["matched_role_experience_title"] = compact_whitespace(
                str(item.get("matched_role_experience_title") or "")
            )
            row["matched_role_experience_months"] = _workspace_int(
                item.get("matched_role_experience_months") or 0
            )
            row["matched_role_experience_end_year"] = _workspace_int(
                item.get("matched_role_experience_end_year") or 0
            )
            row["experience_requirement_review_needed"] = bool(
                item.get("experience_requirement_review_needed")
            )

    occupation_row_html = ""
    occupation_alignment = occupation_alignment_diagnostics(
        display_record, get_scoring_rules(active_profile)
    )
    if occupation_alignment["is_classified"] and occupation_alignment["alignment"] != "same":
        occ_modifier = (
            "mismatch" if occupation_alignment["alignment"] == "different" else "partially-supported"
        )
        occ_label = _workspace_label(
            "workspace_card_labels", "occupation_alignment_row_label")
        occ_text = (
            f"{occ_label}: {occupation_alignment['alignment_label']} — "
            f"{occupation_alignment['reason']}"
        )
        occupation_row_html = (
            f'<li class="job-requirement-item job-requirement-item--{occ_modifier}">'
            f'<span class="job-requirement-text">{safe_html(occ_text)}</span></li>'
        )

    show_job_requirements_panel = (
        bool(merged_requirement_rows or occupation_row_html)
        if has_coverage
        else bool(raw_coverage_is_list or occupation_row_html)
    )
    if show_job_requirements_panel:
        requirement_sections_html = _render_requirement_sections_html(
            merged_requirement_order,
            merged_requirement_rows,
            attention_prefix_html=occupation_row_html,
        )
        requirements_panel_label = _workspace_label(
            "workspace_card_labels", "job_requirements_summary"
        )
        if has_coverage and not has_unclassified_coverage:
            requirements_panel_label = str(taxonomy_payload.get("capability_panel_label") or "").strip()
            if not requirements_panel_label:
                raise ValueError(
                    "ui_labels.json is missing requirement_taxonomy_labels.capability_panel_label"
                )

        panel_body_html = requirement_sections_html or (
            '<div class="job-insight-group is-secondary">'
            f'<p class="job-requirements-empty">{safe_html(_workspace_label("workspace_card_labels", "job_requirements_empty_state"))}</p>'
            "</div>"
        )
        job_requirements_html = _render_job_insights_panel(
            requirements_panel_label,
            panel_body_html,
            modifier_class="job-requirements-panel",
        )

    check_items_html = "".join(f"<li>{safe_html(item)}</li>" for item in check_items)
    risk_html = ""

    if not taxonomy_payload:
        raw_taxonomy_payload = _workspace_ui_labels().get("requirement_taxonomy_labels", {})
        taxonomy_payload = raw_taxonomy_payload if isinstance(raw_taxonomy_payload, dict) else {}
    if not taxonomy_payload:
        raise ValueError("ui_labels.json is missing requirement_taxonomy_labels")
    subtype_labels = taxonomy_payload.get("eligibility_subtype_labels", {})
    if not isinstance(subtype_labels, dict) or not subtype_labels:
        raise ValueError(
            "ui_labels.json is missing requirement_taxonomy_labels.eligibility_subtype_labels"
        )

    eligibility_subtype_blocks: list[str] = []
    for subtype, subtype_label in subtype_labels.items():
        subtype_rows = eligibility_coverage_rows_by_subtype.get(str(subtype), {})
        subtype_order = eligibility_coverage_order_by_subtype.get(str(subtype), [])
        subtype_sections_html = _render_requirement_sections_html(subtype_order, subtype_rows)
        if not subtype_sections_html:
            continue
        eligibility_subtype_blocks.append(
            '<section class="job-requirement-subtype">'
            f'<strong class="job-requirement-subtype-heading">{safe_html(str(subtype_label))}</strong>'
            f"{subtype_sections_html}"
            "</section>"
        )
    eligibility_sections_html = "".join(eligibility_subtype_blocks)
    eligibility_panel_label = str(taxonomy_payload.get("eligibility_panel_label") or "").strip()
    if eligibility_sections_html and not eligibility_panel_label:
        raise ValueError("ui_labels.json is missing requirement_taxonomy_labels.eligibility_panel_label")
    eligibility_html = _render_job_insights_panel(
        eligibility_panel_label,
        eligibility_sections_html,
        modifier_class="job-eligibility-panel",
    )

    qualification_sections_html = _render_requirement_sections_html(
        qualification_coverage_order, qualification_coverage_rows
    )
    qualification_panel_label = str(taxonomy_payload.get("qualification_panel_label") or "").strip()
    if qualification_sections_html and not qualification_panel_label:
        raise ValueError("ui_labels.json is missing requirement_taxonomy_labels.qualification_panel_label")
    qualification_html = _render_job_insights_panel(
        qualification_panel_label,
        qualification_sections_html,
        modifier_class="job-qualification-panel",
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
            unknown_decision_label = _workspace_label("scoring_audit_labels", "decision_label_unknown")
            llm_decision = str(record.get(RECORD_LLM_DECISION_KEY) or "").strip().upper()
            final_decision = (
                _workspace_label("scoring_audit_labels", "decision_label_kept")
                if llm_decision == "KEEP"
                else (
                    _workspace_label("scoring_audit_labels", "decision_label_rejected")
                    if llm_decision == "REJECT"
                    else llm_decision or unknown_decision_label
                )
            )
            llm_grade = str(record.get(RECORD_LLM_FIT_GRADE_KEY) or "").strip().upper() or unknown_decision_label
            summary_items = [
                f"<li>{safe_html(_workspace_label('scoring_audit_labels', 'final_decision_prefix'))} {safe_html(final_decision)}</li>",
                f"<li>{safe_html(_workspace_label('scoring_audit_labels', 'final_score_prefix'))} {safe_html(str(fit_points))}</li>",
                f"<li>{safe_html(_workspace_label('scoring_audit_labels', 'llm_fit_grade_prefix'))} {safe_html(llm_grade)}</li>",
            ]
            eligibility_gate = eligibility_gate_diagnostics(display_record, active_profile)
            summary_items.append(
                f"<li>{safe_html(_workspace_label('scoring_audit_labels', 'eligibility_gate_prefix'))} "
                f"{safe_html(eligibility_gate['label'])} — {safe_html(str(eligibility_gate['reason'] or ''))}</li>"
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
                f"<li>{safe_html(_workspace_label('scoring_audit_labels', 'occupation_alignment_prefix'))} "
                f"{safe_html(occupation_alignment['alignment_label'])} — "
                f"{safe_html(occupation_alignment['reason'])} "
                f"(adjustment {occupation_alignment['adjustment']:+d}, {safe_html(occupation_calculation)})</li>"
            )
            llm_elapsed_ms = record.get(RECORD_LLM_ELAPSED_MS_KEY)
            llm_cost_usd = record.get(RECORD_LLM_COST_USD_KEY)
            llm_input_tokens = record.get(RECORD_LLM_INPUT_TOKENS_KEY)
            llm_output_tokens = record.get(RECORD_LLM_OUTPUT_TOKENS_KEY)
            if llm_elapsed_ms not in (None, ""):
                summary_items.append(
                    f"<li>{safe_html(_workspace_label('workspace_card_labels', 'debug_llm_time_label'))}: {safe_html(str(llm_elapsed_ms))} ms</li>"
                )
            if llm_cost_usd not in (None, ""):
                summary_items.append(
                    f"<li>{safe_html(_workspace_label('workspace_page_labels', 'last_run_llm_cost_label'))}: ${float(llm_cost_usd):.6f}</li>"
                )
            if llm_input_tokens not in (None, ""):
                summary_items.append(
                    f"<li>{safe_html(_workspace_label('workspace_page_labels', 'last_run_input_tokens_label'))}: {safe_html(str(llm_input_tokens))}</li>"
                )
            if llm_output_tokens not in (None, ""):
                summary_items.append(
                    f"<li>{safe_html(_workspace_label('workspace_page_labels', 'last_run_output_tokens_label'))}: {safe_html(str(llm_output_tokens))}</li>"
                )
            llm_review_parts.append(
                f'<div class="job-insight-group is-secondary"><ul>{"".join(summary_items)}</ul></div>'
            )
        if score_breakdown:
            score_breakdown_items: list[str] = []
            for raw_item in score_breakdown:
                if not isinstance(raw_item, dict):
                    continue
                label = compact_whitespace(str(raw_item.get("label") or ""))
                if not label:
                    continue
                score_value = _workspace_int(raw_item.get("value", 0) or 0)
                if score_value == 0:
                    continue
                score_breakdown_items.append(
                    f"<li>{safe_html(label)}: {'{:+d}'.format(score_value)}</li>"
                )
            score_breakdown_html = "".join(score_breakdown_items)
            if score_breakdown_html:
                llm_review_parts.append(
                    '<div class="job-insight-group is-secondary">'
                    f"<strong>{safe_html(_workspace_label('workspace_card_labels', 'debug_score_breakdown_summary'))}</strong>"
                    f"<ul>{score_breakdown_html}</ul>"
                    "</div>"
                )
        llm_review_parts.append(
            _render_scoring_audit_html(
                display_record,
                active_profile,
                debug_mode=active_debug_mode,
            )
        )
        llm_review_html = _render_job_insights_panel(
            _workspace_label("scoring_audit_labels", "debug_llm_review_summary"),
            "".join(llm_review_parts),
            modifier_class="job-llm-review",
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
            _ch_formatted_date = (
                format_timestamp_label(_ch_run_date, include_time=False)
                if _ch_run_date
                else ""
            )
            _ch_items = []
            _ch_header_parts = [p for p in [_ch_company, _ch_formatted_date] if p]
            if _ch_header_parts:
                _ch_items.append(" — ".join(_ch_header_parts))
            if _ch_role:
                _ch_items.append(f"{_workspace_label('candidate_history_labels', 'role_prefix')} {_ch_role}")
            if _ch_evidence_raw:
                _ch_items.append(
                    f"{_workspace_label('candidate_history_labels', 'evidence_prefix')} {_ch_evidence}"
                )
            # Keep application-history diagnostics in the record for debugging,
            # but keep them out of the normal candidate-facing card details.
            if active_debug_mode:
                if _ch_confidence:
                    _ch_items.append(
                        f"{_workspace_label('candidate_history_labels', 'confidence_prefix')} {_ch_confidence}"
                    )
                if _ch_match_confidence:
                    _ch_items.append(
                        f"{_workspace_label('candidate_history_labels', 'company_match_confidence_prefix')} "
                        f"{_ch_match_confidence}"
                    )
                if _ch_match_reason:
                    _ch_items.append(
                        f"{_workspace_label('candidate_history_labels', 'company_match_reason_prefix')} "
                        f"{_ch_match_reason}"
                    )
                if _cand_hist_review_reason:
                    _ch_items.append(
                        f"{_workspace_label('candidate_history_labels', 'review_reason_prefix')} "
                        f"{_cand_hist_review_reason}"
                    )
            candidate_history_html = (
                '<div class="job-insight-group is-secondary job-candidate-history">'
                f"<strong>{safe_html(_workspace_label('candidate_history_labels', 'summary'))}</strong>"
                f"<ul>{''.join(f'<li>{safe_html(item)}</li>' for item in _ch_items)}</ul>"
                "</div>"
            )

    risk_body_html = ""
    if check_items_html:
        risk_body_html += (
            f'<div class="job-insight-group job-insight-warning"><ul>{check_items_html}</ul></div>'
        )
    risk_body_html += candidate_history_html
    risk_html = _render_job_insights_panel(
        _workspace_label("workspace_card_labels", "risk_panel_summary"),
        risk_body_html,
        modifier_class="job-risk-panel",
    )

    if applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-undo jh-button jh-button--primary jh-button--compact review-button--selected" type="button" data-review-action="unapply" {button_data_attrs}>'
            f'{safe_html(_workspace_label("workspace_card_labels", "action_undo_applied_label"))}</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif hidden_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-undo jh-button jh-button--secondary jh-button--compact" type="button" data-review-action="unhide" {button_data_attrs}>'
            f'{safe_html(_workspace_label("workspace_card_labels", "action_unhide_label"))}</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    elif not applied_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-applied jh-button jh-button--primary jh-button--compact" type="button" data-review-action="applied" {button_data_attrs}>'
            f'{safe_html(_workspace_label("workspace_card_labels", "applied_badge"))}</button>'
            f'<button class="review-button review-not-for-me jh-button jh-button--danger jh-button--compact" type="button" data-review-action="not_for_me" {button_data_attrs} '
            f'title="{safe_html(_workspace_label("workspace_card_labels", "action_not_for_me_tooltip"))}">'
            f'{safe_html(_workspace_label("workspace_card_labels", "action_not_for_me_label"))}</button>'
            f'<button class="review-button review-hide jh-button jh-button--secondary jh-button--compact" type="button" data-review-action="hidden" {button_data_attrs} '
            f'title="{safe_html(_workspace_label("workspace_card_labels", "action_hide_tooltip"))}">'
            f'{safe_html(_workspace_label("workspace_card_labels", "action_hide_label"))}</button>'
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
        f'<article id="{safe_html(card_dom_id)}" class="{safe_html(card_classes)}" data-fit-score="{fit_points}" data-posted-age="{posted_age_days if posted_age_days is not None else 9999}" data-salary-sort="{salary_value}" data-salary-fit="{safe_html(salary_fit_state)}" data-work-mode="{safe_html(work_mode.lower())}" data-work-type="{safe_html(display_work_type_label(record).lower())}" data-viewed="{1 if seen_by_you else 0}" data-record-kind="{record_kind}" data-fit-label="{safe_html(fit_label.lower())}" data-title-search="{safe_html((record.get("title") or "").lower())}" data-company-search="{safe_html(company_display.lower())}" data-source="{safe_html(source)}" data-posting-channel="{safe_html(channel_kind)}" data-apply-method="{safe_html(apply_method or "unknown")}">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        '<div class="job-header-row">'
        '<div class="job-header-copy">'
        '<div class="job-title-row">'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">{title}</a>'
        + (
            f'<button class="title-block-btn workspace-text-action workspace-text-action--muted" type="button" data-review-action="block_similar" {button_data_attrs} aria-expanded="false" aria-controls="{safe_html(title_block_panel_id)}" title="{safe_html(_workspace_label("workspace_card_labels", "title_block_button_tooltip"))}">{safe_html(_workspace_label("workspace_card_labels", "title_block_button_label"))}</button>'
            f'<div id="{safe_html(title_block_panel_id)}" class="block-confirm" data-block-confirm hidden>'
            f'<p class="block-confirm-heading">{safe_html(_workspace_label("workspace_card_labels", "title_block_button_label"))}</p>'
            f'<p class="block-confirm-copy">{safe_html(_workspace_label("workspace_card_labels", "title_block_prompt_copy"))}</p>'
            '<div class="block-manual-row">'
            f'<label class="block-manual-label" for="{safe_html(title_block_panel_id)}-input">{safe_html(_workspace_label("workspace_card_labels", "exact_title_phrase_label"))}</label>'
            f'<input id="{safe_html(title_block_panel_id)}-input" class="block-manual-input" type="text" data-block-manual-input placeholder="e.g. sap, payroll, contract management" value="{block_title_hint}">'
            f'<span class="block-manual-help">{safe_html(_workspace_label("workspace_card_labels", "title_block_manual_help"))}</span>'
            f'<p class="block-example-copy">{safe_html(_workspace_label("workspace_card_labels", "title_block_example_copy"))}</p>'
            "</div>"
            '<p class="block-impact" data-block-impact></p>'
            '<details class="block-confirm-help">'
            f'<summary>{safe_html(_workspace_label("workspace_card_labels", "title_block_help_summary"))}</summary>'
            f'<p>{safe_html(_workspace_label("workspace_card_labels", "title_block_guidance_copy"))}</p>'
            "</details>"
            '<div class="block-confirm-actions">'
            f'<button class="jh-button jh-button--primary jh-button--compact" type="button" data-confirm-block disabled>{safe_html(_workspace_label("workspace_card_labels", "action_block_matching_titles_label"))}</button>'
            f'<button class="jh-button jh-button--secondary jh-button--compact" type="button" data-cancel-block>{safe_html(_workspace_label("workspace_card_labels", "action_cancel_label"))}</button>'
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
        f'<div class="job-meta">{"".join(meta_items)}</div>'
        f"{related_cards_html}"
        f"{risk_html}"
        f"{job_requirements_html}"
        f"{eligibility_html}"
        f"{qualification_html}"
        f"{llm_review_html}"
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
    dom_id = section_dom_id(title)
    section_data_attribute = f' data-section-id="{safe_html(dom_id)}"' if panelized else ""
    pagination_match_count = '<span class="pagination-match-count"></span>'
    pagination_page_label = '<span class="pagination-label pagination-page-label"></span>'
    pagination_buttons = (
        f'<button class="pagination-button" type="button" data-page-direction="prev">{safe_html(_workspace_label("workspace_card_labels", "pagination_prev_label"))}</button>'
        f'<button class="pagination-button" type="button" data-page-direction="next">{safe_html(_workspace_label("workspace_card_labels", "pagination_next_label"))}</button>'
    )
    pagination_footer = (
        '<div class="results-pagination-footer"><div class="section-tools">'
        f'{pagination_page_label}{pagination_match_count}{pagination_buttons}'
        '</div></div>'
        if panelized
        else ""
    )
    if panelized:
        results_header = (
            '<div class="results-header">'
            '<div class="results-header__left">'
            f"<h2>{safe_html(title)}</h2>"
            f"{header_nav}"
            "</div>"
            '<div class="section-tools">'
            f"{pagination_match_count}"
            f"{header_tools}"
            f"{pagination_page_label}"
            f"{pagination_buttons}"
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
            f'<section class="{section_classes if panelized else "section"}"'
            f"{section_data_attribute}>"
            f"{panel_open}"
            f"{results_header}"
            f'<p class="empty-state">{safe_html(empty_message)}</p>'
            f"{panel_close}"
            f"</section>"
        )
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
    filtered_empty_state = (
        f'<p class="empty-state" hidden>{safe_html(empty_message)}</p>'
        if panelized
        else ""
    )
    return (
        f'<section class="{section_classes}" data-section-id="{safe_html(dom_id)}">'
        f"{panel_open}"
        f"{results_header}"
        f"{panel_body_open}"
        f'<div class="job-grid">{cards}</div>'
        f"{filtered_empty_state}"
        f"{panel_body_close}"
        f"{pagination_footer}"
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
