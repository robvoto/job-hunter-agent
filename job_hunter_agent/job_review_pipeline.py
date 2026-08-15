"""Helpers for job review pipeline."""

from __future__ import annotations

import logging
import re
import time
import textwrap
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from job_hunter_agent import occupation_taxonomy

logger = logging.getLogger(__name__)

_PIPELINE_LOG_CORE_FIELDS = ("source", "job_key", "title", "company")
_HUMAN_JOB_SEPARATOR = "=" * 72

# Human-readable translations for internal pipeline reason codes.
# Codes not listed fall back to the raw code in parentheses.
_REASON_LABELS: dict[str, str] = {
    "TITLE_NOT_TARGET": "title not in your target roles",
    "TITLE_EMPTY": "job title is missing",
    "TITLE_BAD_KEYWORD": "title contains a blocked keyword",
    "TITLE_REASON_POTENTIAL_MATCH": "title is a potential match",
    "ONET_FAR_OCCUPATION": "occupation too far from your targets",
    "LLM_TITLE_NOT_TARGET": "title judged a clear mismatch for your target roles",
    "HARD_BLOCK": "matched a hard blocker rule",
    "HARD_BLOCK_REQUIRED_SKILL": "requires a skill you flagged as blocking",
    "REQUIRED_ELIGIBILITY_FAILED": "required eligibility requirement is not met",
    "REQUIRED_ELIGIBILITY_UNRESOLVED": "required eligibility requirement could not be confirmed",
    "DETAILS_CHALLENGE_PAGE": "description page was a bot challenge",
    "DETAILS_BLOCKED_PAGE": "description page was blocked",
    "DETAILS_NAVIGATION_ERROR": "description page failed to load",
    "NO_DETAILS": "could not read job description",
    "NO_DESCRIPTION_TRUST": "description too short to score reliably",
    "CONTENT_REJECT": "description did not pass content filters",
    "LLM_REJECT": "LLM reviewer rejected",
    "LLM_ERROR": "LLM review failed with an error",
    "LLM_INVALID_REVIEW": "LLM review returned incomplete fit data",
    "LLM_UNAVAILABLE": "LLM review unavailable",
    "REVIEW_FAILED_TIMEOUT": "LLM review timed out — not reviewed, will retry next run",
    "DET_REJECT": "deterministic reviewer rejected",
    "ALREADY_APPLIED": "you already applied to this one",
    "DUPLICATE_URL": "duplicate listing",
    "DUPLICATE_JOB_KEY": "duplicate listing",
    "JOB_CLOSED": "no longer accepting applications",
    "STALE_REPOST": "stale repost outside the search age",
    "NO_JOB_KEY": "missing job ID",
    "NO_URL": "missing job URL",
    "OK": "passed",
}


def _reason_label(code: str) -> str:
    if not code:
        return ""
    # Handle parameterised codes like POSTED_TOO_OLD:3
    base = code.split(":")[0]
    suffix = code[len(base) :]
    label = _REASON_LABELS.get(base)
    if label:
        return f"{label}{' (' + suffix.lstrip(':') + ' days)' if suffix else ''} ({code})"
    return f"({code})"


def _human_reason_label(code: str) -> str:
    if not code:
        return ""
    base = code.split(":")[0]
    suffix = code[len(base) :]
    label = _REASON_LABELS.get(base)
    if label:
        if suffix:
            return f"{label} ({suffix.lstrip(':')} days)"
        return label
    return compact_whitespace(code.replace("_", " ")).lower()


def _job_tag(source: str, title: str, company: str, job_key: str) -> str:
    src = source.upper() if source else "?"
    name = f'"{title}"' if title else "(no title)"
    co = f" @ {company}" if company else ""
    key = f" [{job_key}]" if job_key and job_key != "unknown" else ""
    return f"{name}{co}  ({src}{key})"


def _job_source_prefix(source: str) -> str:
    return f"[{source.upper() if source else '?'}]"


def _job_url(record: dict[str, Any]) -> str:
    return str(record.get(RECORD_URL_KEY) or "").strip()


from job_hunter_agent.capability_matching import (
    build_pre_review_risk_signals,
    reviewed_signal_matches_for_text,
)
from job_hunter_agent.description_compactor import compact_description
from job_hunter_agent.description_trust import (
    get_min_trusted_description_length,
    get_trusted_sources,
)
from job_hunter_agent.filters import (
    analyze_title_filters,
    passes_content_filters,
    passes_quick_card_filters,
)
from job_hunter_agent.fit_scoring import (
    build_fit_highlights,
    eligibility_gate_diagnostics,
    fit_score_and_breakdown_frozen,
    format_occupation_alignment_diagnostics_block,
    format_requirement_fit_diagnostics_block,
)
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.history import apply_kept_job_reuse, can_reuse_kept_job, finalize_record
from job_hunter_agent.job_types import infer_work_type_from_description
from job_hunter_agent.job_quality import (
    detect_external_date_signals,
    extract_external_original_posting_date,
    fetch_external_html,
    load_dodgy_job_rules,
)
from job_hunter_agent.llm_gate import (
    LLMCallError,
    LLMReviewValidationError,
    build_title_judgment_cache_key,
    get_session_cost_usd,
    llm_judge_title,
    normalize_llm_title_judgment,
)
from job_hunter_agent.llm_review_state import has_complete_llm_keep_data
from job_hunter_agent.logging_utils import format_debug_marker, format_log_block
from job_hunter_agent.match_labels import score_to_match_label
from job_hunter_agent.occupation_taxonomy import (
    OccupationClassification,
    RESULT_FAR,
    RESULT_UNCERTAIN,
    format_onet_response,
)
from job_hunter_agent.occupation_taxonomy import (
    classify_title as _onet_classify_title,
)
from job_hunter_agent.onet_taxonomy_import import normalize_title as normalize_occupation_title
from job_hunter_agent.paths import UNCERTAINTY_LOG_PATH
from job_hunter_agent.preferences import passes_preference_filters
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_CAPABILITIES,
    KEY_EXPLORE_ADJACENT_ROLES,
    get_match_levels,
)
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EXTERNAL_APPLY,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    DETAILS_STATUS_OK,
    ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED,
    ORIGINAL_POSTED_DATE_STATUS_VERIFIED,
    RECORD_APPLY_METHOD_KEY,
    RECORD_CARD_SALARY_KEY,
    RECORD_COMPANY_KEY,
    RECORD_COMPETITIVE_SIGNALS_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_DECISION_KEY,
    RECORD_DECISION_EXPLANATION_KEY,
    RECORD_DESCRIPTION_COMPACTION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_LENGTH_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_FIT_CONFIDENCE_KEY,
    RECORD_FIT_HIGHLIGHTS_KEY,
    RECORD_FIT_LABEL_KEY,
    RECORD_FIT_SCORE_BREAKDOWN_KEY,
    RECORD_FIT_SCORE_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FIT_TONE_CLASS_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_JOB_KEY,
    RECORD_JOB_QUALITY_SIGNALS_KEY,
    RECORD_JOB_REQUIREMENTS_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_DEBUG_REASON_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_ELAPSED_MS_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    RECORD_LLM_TITLE_JUDGMENT_KEY,
    RECORD_LOCATION_KEY,
    RECORD_MISSING_CLEARANCE_SUPPORT_KEY,
    RECORD_MISSING_PROFILE_SUPPORT_KEY,
    RECORD_OCCUPATION_ALIGNMENT_KEY,
    RECORD_OCCUPATION_ALIGNMENT_REASON_KEY,
    RECORD_ONET_CLASSIFICATION_KEY,
    RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY,
    RECORD_ORIGINAL_POSTED_DATE_KEY,
    RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_REVIEW_SOURCE_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
    RECORD_ROLE_SNAPSHOT_KEY,
    RECORD_SALARY_KEY,
    RECORD_SOFT_RISK_REASONS_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_TEASER_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_MATCH_METADATA_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_TYPE_KEY,
)
from job_hunter_agent.llm_protocol import LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE
from job_hunter_agent.role_analysis import infer_posting_channel
from job_hunter_agent.run_control import pause_for_step_through
from job_hunter_agent.salary_utils import preferred_salary_display
from job_hunter_agent.score_labels import score_to_tone_class
from job_hunter_agent.signal_detection import (
    detect_competitive_signals,
    evaluate_competitive_signal_alignment,
    extract_skill_observations,
    hard_block_entries,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_SUGGESTED_VALUES_KEY,
    TITLE_REASON_POTENTIAL_MATCH,
)
from job_hunter_agent.source_learning import (
    build_ad_learning_signals,
    deterministic_review_outcome,
    merge_pending_learning_signals,
    register_hard_blocker_learning_from_rejection,
    register_pending_learning_signals,
    resolve_llm_review_payload,
)
from job_hunter_agent.text_processing import (
    build_role_summary,
    compact_whitespace,
    dedupe_preserve_order,
)
from job_hunter_agent.runtime_helpers import append_uncertainty_log, build_uncertainty_entry
from job_hunter_agent.source_registry import get_source_display_label

HookFn = Callable[[dict, "ReviewPipelineContext"], None]


_job_start_times: dict[str, float] = {}
_job_start_costs: dict[str, float] = {}


def _log_title_classification_uncertainty(
    record: dict[str, Any],
    profile: dict[str, Any],
    onet: OccupationClassification,
) -> None:
    title = str(record.get(RECORD_TITLE_KEY) or "").strip()
    target_queries = occupation_taxonomy._profile_target_occupation_queries(profile)
    target_codes = sorted(
        occupation_taxonomy._derive_target_occupation_codes(
            target_queries,
            occupation_taxonomy._load_index(),
        )
    )
    entry = build_uncertainty_entry(
        reason_code="TITLE_UNCLEAR",
        stage="title_classification",
        field="title",
        raw_value=title or "<empty>",
        normalized_value=normalize_occupation_title(title),
        detail="O*NET title classification was uncertain — letting the job continue to detail review.",
        source="review_pre_detail_normalized_job",
        job_key=str(record.get(RECORD_JOB_KEY) or ""),
    )
    entry["title"] = title
    entry["target_occupation_queries"] = target_queries
    entry["target_occupation_codes"] = target_codes
    entry["onet_result"] = onet.result
    entry["onet_reason"] = onet.reason
    entry["onet_lookup_source"] = onet.lookup_source
    append_uncertainty_log(UNCERTAINTY_LOG_PATH, entry)


def _human_result_summary(record: dict[str, Any], decision: str, reason: str) -> str:
    if decision == "KEEP":
        score = record.get(RECORD_FIT_SCORE_KEY)
        grade = str(record.get(RECORD_LLM_FIT_GRADE_KEY) or "").strip().upper()
        if score is not None and grade:
            return f"KEEP | Score {score} | LLM grade {grade}"
        if score is not None:
            return f"KEEP | Score {score}"
        if grade:
            return f"KEEP | LLM grade {grade}"
        return "KEEP"

    summary_map = {
        "LLM_TITLE_NOT_TARGET": "REJECTED - Title does not match your target roles",
        "TITLE_NOT_TARGET": "REJECTED - Title does not match your target roles",
        "TITLE_BAD_KEYWORD": "REJECTED - Title matches a blocked role",
        "TITLE_EMPTY": "REJECTED - Job title is missing",
        "ONET_FAR_OCCUPATION": "REJECTED - Title is outside your target role family",
        "NO_DETAILS": "REJECTED - Job description could not be read",
        "DETAILS_CHALLENGE_PAGE": "REJECTED - Job description could not be read",
        "DETAILS_BLOCKED_PAGE": "REJECTED - Job description could not be read",
        "DETAILS_NAVIGATION_ERROR": "REJECTED - Job description could not be read",
        "NO_DESCRIPTION_TRUST": "REJECTED - Job description was too weak to review",
        "CONTENT_REJECT": "REJECTED - Job description failed the content checks",
        "LLM_REJECT": "REJECTED - Full fit review rejected this role",
        "DET_REJECT": "REJECTED - Rule review rejected this role",
        "LLM_ERROR": "REJECTED - Full fit review failed",
        "LLM_INVALID_REVIEW": "REJECTED - Full fit review returned invalid data",
        "LLM_UNAVAILABLE": "REJECTED - Full fit review was unavailable",
        "REVIEW_FAILED_TIMEOUT": "REJECTED - Full fit review timed out",
        "HARD_BLOCK": "REJECTED - Job has a hard blocker",
    }
    base = reason.split(":")[0]
    return summary_map.get(base, f"REJECTED - {_human_reason_label(reason).capitalize()}")


def _decision_explanation(record: dict[str, Any], reason: str, explanation: str) -> str:
    explicit = compact_whitespace(explanation)
    if explicit:
        return explicit
    stored = compact_whitespace(str(record.get(RECORD_DECISION_EXPLANATION_KEY) or ""))
    if stored:
        return stored
    if reason == "LLM_TITLE_NOT_TARGET":
        title_judgment = record.get(RECORD_LLM_TITLE_JUDGMENT_KEY) or {}
        return compact_whitespace(str(title_judgment.get("reason") or ""))
    if reason == "ONET_FAR_OCCUPATION":
        onet = record.get(RECORD_ONET_CLASSIFICATION_KEY) or {}
        return compact_whitespace(str(onet.get("reason") or ""))
    if reason.startswith("DESC_HARD_BLOCK_RULE"):
        blockers = record.get(RECORD_HARD_BLOCK_REASONS_KEY) or []
        if blockers:
            return f"Blocked by: {compact_whitespace(str(blockers[0]))}"
    return ""


def render_human_job_result(
    record: dict[str, Any],
    *,
    decision: str,
    reason: str = "",
    explanation: str = "",
    grade: str = "",
    score: int | None = None,
    elapsed: str = "",
    llm_cost: str = "",
) -> str:
    title = compact_whitespace(str(record.get(RECORD_TITLE_KEY) or "(no title)"))
    company = compact_whitespace(str(record.get(RECORD_COMPANY_KEY) or ""))
    source = get_source_display_label(str(record.get("source") or ""))
    url = _job_url(record)
    result_summary = _human_result_summary(record, decision, reason)
    details = _decision_explanation(record, reason, explanation)
    if decision == "KEEP":
        if score is None:
            raw_score = record.get(RECORD_FIT_SCORE_KEY)
            score = int(raw_score) if raw_score is not None else None
        if not grade:
            grade = str(record.get(RECORD_LLM_FIT_GRADE_KEY) or "").strip().upper()
    lines = [
        _HUMAN_JOB_SEPARATOR,
        "",
        title,
        company,
        source,
        "",
        result_summary,
    ]
    if details:
        lines.extend(["", "Why:"])
        for paragraph in textwrap.wrap(details, width=72):
            lines.append(paragraph)
    if url:
        lines.extend(["", url])
    meta_bits: list[str] = []
    if elapsed:
        meta_bits.append(f"Time: {elapsed}")
    if llm_cost:
        meta_bits.append(f"LLM cost: {llm_cost}")
    if meta_bits:
        lines.extend(["", " | ".join(meta_bits)])
    lines.extend(["", _HUMAN_JOB_SEPARATOR])
    return "\n".join(lines)


def _finalize_job_result(
    record: dict[str, Any],
    context: ReviewPipelineContext,
    *,
    reason: str = "",
    explanation: str = "",
) -> None:
    record[RECORD_DECISION_EXPLANATION_KEY] = compact_whitespace(explanation)
    _finalize(record, context)
    _pipeline_log(
        "FINAL_DECISION",
        record,
        context.source_name,
        decision=str(record.get(RECORD_DECISION_KEY) or ""),
        reason=reason or str(record.get(RECORD_REJECT_REASON_KEY) or ""),
        explanation=record[RECORD_DECISION_EXPLANATION_KEY],
        review_source=str(record.get(RECORD_REVIEW_SOURCE_KEY) or ""),
        grade=str(record.get(RECORD_LLM_FIT_GRADE_KEY) or ""),
        score=record.get(RECORD_FIT_SCORE_KEY),
    )


def _pipeline_log(stage: str, record: dict, source_name: str = "", **kwargs: Any) -> None:
    source = source_name or str(record.get("source") or "")
    job_key = str(record.get(RECORD_JOB_KEY) or "unknown")
    title = str(record.get(RECORD_TITLE_KEY) or "(no title)")
    company = str(record.get(RECORD_COMPANY_KEY) or "")
    job_url = _job_url(record)
    result = str(kwargs.get("result") or "")
    reason = str(kwargs.get("reason") or "")
    decision = str(kwargs.get("decision") or "")
    if stage == "CARD_SEEN":
        _job_start_times[job_key] = time.monotonic()
        _job_start_costs[job_key] = get_session_cost_usd()
        src = source.upper() if source else "?"
        logger.debug(
            format_debug_marker(
                "JOB_START",
                {
                    "source": src,
                    "job_key": job_key,
                    "title": title,
                    "company": company,
                    "url": job_url or "(url unavailable)",
                },
            )
        )
        return

    if stage == "TITLE_GATE":
        logger.debug(
            format_log_block(
                "PIPELINE][TITLE_GATE",
                {
                    "source": source,
                    "job_key": job_key,
                    "title": title,
                    "company": company,
                    "result": result,
                    "reason": reason,
                    **kwargs,
                },
            )
        )
        return

    if stage == "CARD_GATE":
        logger.debug(
            format_log_block(
                "PIPELINE][CARD_GATE",
                {
                    "source": source,
                    "job_key": job_key,
                    "title": title,
                    "company": company,
                    "result": result,
                    "reason": reason,
                    **kwargs,
                },
            )
        )
        return

    if stage == "FINAL_DECISION":
        start_time = _job_start_times.get(job_key)
        total_job_ms = int((time.monotonic() - start_time) * 1000) if start_time is not None else 0
        elapsed = _elapsed(job_key) if start_time is not None else ""
        llm_cost = _job_cost(job_key) if start_time is not None else ""
        if llm_cost == "$0.000000":
            llm_cost = ""
        # Stashed on the record (same convention as the other _obs_* fields) so
        # scrape_finalize can render the per-job human report at run end without
        # re-deriving per-job timing/cost from the now-discarded tracking dicts.
        record["_obs_elapsed"] = elapsed
        record["_obs_llm_cost"] = llm_cost
        pause_for_step_through(f"{title} @ {company} ({source}) — {decision or reason}")
        logger.debug(
            format_log_block(
                "PIPELINE][FINAL_DECISION",
                {
                    "source": source,
                    "job_key": job_key,
                    "url": job_url,
                    "decision": decision,
                    "reason": reason,
                    "total_job_ms": total_job_ms,
                },
            )
        )
        logger.debug(
            format_debug_marker(
                "JOB_END",
                {
                    "source": source.upper() if source else "?",
                    "job_key": job_key,
                    "decision": decision,
                    "reason": reason,
                    "total_job_ms": total_job_ms,
                    "llm_cost_usd": _job_cost(job_key),
                },
            )
        )
        return

    if stage == "LLM_CALL_DONE":
        call = str(kwargs.get("call") or "")
        elapsed_ms = int(kwargs.get("elapsed_ms") or 0)
        payload_source = str(kwargs.get("payload_source") or "llm")
        logger.debug(
            format_log_block(
                "PIPELINE][LLM_CALL_DONE",
                {
                    "source": source,
                    "job_key": job_key,
                    "title": title,
                    "company": company,
                    "call": call,
                    "elapsed_ms": elapsed_ms,
                    "payload_source": payload_source,
                },
            )
        )
        _job_start_times.pop(job_key, None)
        _job_start_costs.pop(job_key, None)
        return

    # ── Debug-only: show raw stage data for anything else ─────────────────────
    fields: dict[str, Any] = {
        "source": source,
        "job_key": job_key,
        "title": title,
        "company": company,
    }
    fields.update(kwargs)
    label_width = max(len(k) for k in fields) if fields else 0
    lines = [f"  [DEBUG][{stage}]"]
    for label in _PIPELINE_LOG_CORE_FIELDS:
        lines.append(f"    {label.ljust(label_width)}  {fields[label]}")
    for label, value in kwargs.items():
        lines.append(f"    {label.ljust(label_width)}  {value}")
    logger.debug("\n".join(lines))


def _elapsed(job_key: str) -> str:
    start = _job_start_times.get(job_key)
    if start is None:
        return "?"
    secs = time.monotonic() - start
    return f"{secs:.1f}s"


def _job_cost(job_key: str) -> str:
    start_cost = _job_start_costs.get(job_key)
    if start_cost is None:
        return "$0.000000"
    delta = get_session_cost_usd() - start_cost
    return f"${max(delta, 0.0):.6f}"


def _job_time_summary(job_key: str) -> str:
    elapsed = _elapsed(job_key)
    start_cost = _job_start_costs.get(job_key)
    if start_cost is None:
        return f"time: {elapsed}"
    delta = max(get_session_cost_usd() - start_cost, 0.0)
    if delta <= 0.0:
        return f"time: {elapsed}"
    return f"time: {elapsed}  |  LLM: ${delta:.6f}"


@dataclass(slots=True)
class ReviewPipelineHooks:
    before_common_review: HookFn | None = None
    after_description_loaded: HookFn | None = None
    before_preference_filters: HookFn | None = None
    after_preference_filters: HookFn | None = None
    before_llm_review: HookFn | None = None


@dataclass(slots=True)
class ReviewPipelineContext:
    profile: dict
    job_history: dict[str, dict]
    audit_rows: list[dict]
    llm_cache: dict[str, Any]
    applied_job_keys: set[str]
    hidden_job_keys: set[str]
    seen_job_keys: set[str] | None = None
    seen_urls: set[str] | None = None
    run_iso: str = ""
    date_range_days: int = 0
    source_name: str = ""


_DETAILS_STATUS_REJECT_REASON = {
    "challenge_page": "DETAILS_CHALLENGE_PAGE",
    "blocked_page": "DETAILS_BLOCKED_PAGE",
    "navigation_error": "DETAILS_NAVIGATION_ERROR",
    "empty": "NO_DETAILS",
}


def _has_job_closed_signal(record: dict) -> bool:
    for signal in record.get(RECORD_JOB_QUALITY_SIGNALS_KEY) or []:
        if not isinstance(signal, dict):
            continue
        if str(signal.get("kind") or "").strip().lower() == "job_closed":
            return True

    rules = load_dodgy_job_rules()
    job_text_candidates = [
        record.get(RECORD_DETAILS_TEXT_KEY),
        record.get(RECORD_FULL_DESCRIPTION_KEY),
        record.get(RECORD_TEASER_KEY),
    ]
    for text in job_text_candidates:
        cleaned = compact_whitespace(text)
        if not cleaned:
            continue
        if any(
            signal.get("kind") == "job_closed"
            for signal in detect_external_date_signals(cleaned, None, rules, date.today())
        ):
            return True
    return False


def _source_key(record: dict) -> str:
    return str(record.get("source") or "").strip().lower()


def _defer_keep_reuse_until_post_detail(record: dict) -> bool:
    # Reuse must wait for the post-detail stale-repost check whenever that check
    # will actually run for this record, so a KEEP snapshot is never reused
    # without first re-verifying the listing isn't a stale repost. Derived
    # directly from _should_check_external_posting_date rather than kept as an
    # independent source list, so the two can't drift apart again (this is what
    # previously left SEEK deferred to post-detail long after SEEK was excluded
    # from the external posting-date check itself).
    return _should_check_external_posting_date(record)


def _should_check_external_posting_date(record: dict) -> bool:
    # SEEK blocks fetch_external_html's unauthenticated request with a 403 every time
    # (no browser session/cookies), so the check can never succeed for SEEK records.
    # Bridged off here on purpose until it's rerouted through an authenticated fetch.
    return (
        _source_key(record) == "linkedin"
        and str(record.get(RECORD_APPLY_METHOD_KEY) or "").strip().lower() == APPLY_METHOD_EXTERNAL_APPLY
    )


def _mark_original_posted_date_unverified(record: dict) -> None:
    record[RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY] = ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED
    record[RECORD_ORIGINAL_POSTED_DATE_KEY] = ""
    record[RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY] = None


def _apply_external_posting_date_filter(
    record: dict,
    context: ReviewPipelineContext,
) -> tuple[bool, str, str]:
    if not _should_check_external_posting_date(record):
        return True, "", ""

    source_metadata = (
        record.get(RECORD_SOURCE_METADATA_KEY)
        if isinstance(record.get(RECORD_SOURCE_METADATA_KEY), dict)
        else {}
    )
    apply_url = str(source_metadata.get("apply_url") or "").strip()
    canonical_url = str(record.get(RECORD_URL_KEY) or "").strip()
    if not apply_url or apply_url == canonical_url:
        _mark_original_posted_date_unverified(record)
        return True, "", ""

    external_html = str(record.get("_external_apply_html") or "").strip()
    if not external_html:
        external_html = fetch_external_html(apply_url)
        if external_html:
            record["_external_apply_html"] = external_html
    if not external_html:
        _mark_original_posted_date_unverified(record)
        return True, "", ""

    verification = extract_external_original_posting_date(
        external_html,
        date.fromisoformat(context.run_iso[:10]),
    )
    if verification is None:
        _mark_original_posted_date_unverified(record)
        return True, "", ""

    original_age_days = float(verification["age_days"])
    record[RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY] = ORIGINAL_POSTED_DATE_STATUS_VERIFIED
    record[RECORD_ORIGINAL_POSTED_DATE_KEY] = str(verification["posted_on"])
    record[RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY] = original_age_days
    if original_age_days > context.date_range_days:
        return (
            False,
            "STALE_REPOST",
            (
                f"External apply page shows this role was originally posted on "
                f"{verification['posted_on']}, outside the {context.date_range_days}-day search window."
            ),
        )
    return True, "", ""


def _call_hook(
    hooks: ReviewPipelineHooks | None, hook_name: str, record: dict, context: ReviewPipelineContext
) -> None:
    if hooks is None:
        return
    hook = getattr(hooks, hook_name, None)
    if hook is None:
        return
    hook(record, context)


def _finalize(record: dict, context: ReviewPipelineContext) -> None:
    finalize_record(context.job_history, context.audit_rows, record, context.run_iso)


def _build_outcome(record: dict) -> dict[str, Any]:
    return {
        "decision": record.get(RECORD_DECISION_KEY),
        "reject_reason": record.get(RECORD_REJECT_REASON_KEY),
        "title_reason": record.get(RECORD_TITLE_REASON_KEY),
        "content_reason": record.get(RECORD_CONTENT_REASON_KEY),
        "hard_block_reasons": list(record.get(RECORD_HARD_BLOCK_REASONS_KEY) or []),
        "llm_decision": record.get(RECORD_LLM_DECISION_KEY),
        "llm_fit_grade": record.get(RECORD_LLM_FIT_GRADE_KEY),
        "review_source": record.get("review_source"),
        RECORD_REQUIREMENT_COVERAGE_KEY: list(record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []),
        RECORD_OCCUPATION_ALIGNMENT_KEY: record.get(RECORD_OCCUPATION_ALIGNMENT_KEY),
        RECORD_OCCUPATION_ALIGNMENT_REASON_KEY: record.get(RECORD_OCCUPATION_ALIGNMENT_REASON_KEY),
    }


def _freeze_fit_score_fields(record: dict, profile: dict) -> None:
    # Guard: cannot score without an LLM grade (e.g. very old history snapshots that predate
    # grade capture, or future code paths that call this before review). Existing frozen
    # fields from the snapshot are preserved as-is; the display path reads those directly.
    if not str(record.get("llm_fit_grade") or "").strip():
        return
    fit_points, breakdown = fit_score_and_breakdown_frozen(record, profile)
    record[RECORD_FIT_SCORE_KEY] = fit_points
    record[RECORD_FIT_SCORE_BREAKDOWN_KEY] = breakdown
    record[RECORD_FIT_LABEL_KEY] = score_to_match_label(fit_points, get_match_levels(profile))
    record[RECORD_FIT_TONE_CLASS_KEY] = score_to_tone_class(fit_points, profile)
    logger.debug(format_occupation_alignment_diagnostics_block(record, fit_points, profile))


def _apply_detail_payload_to_record(
    record: dict, details_text: str, details_status: str
) -> tuple[bool, str]:
    record[RECORD_DETAILS_STATUS_KEY] = details_status
    record[RECORD_DETAILS_LENGTH_KEY] = len(details_text)

    if details_status != DETAILS_STATUS_OK or not details_text:
        reject_reason = _DETAILS_STATUS_REJECT_REASON.get(details_status, "NO_DETAILS")
        record[RECORD_CONTENT_REASON_KEY] = reject_reason
        return False, reject_reason

    record[RECORD_FULL_DESCRIPTION_KEY] = details_text
    compacted, compaction_meta = compact_description(
        details_text, min_compacted_chars=get_min_trusted_description_length()
    )
    record[RECORD_FIT_SOURCE_TEXT_KEY] = compacted
    record[RECORD_DESCRIPTION_COMPACTION_KEY] = compaction_meta
    if compaction_meta["applied"]:
        logger.debug(
            "[COMPACTION] job=%s original=%d compacted=%d removed=%s",
            record.get(RECORD_JOB_KEY, "<unknown>"),
            compaction_meta["original_char_count"],
            compaction_meta["compacted_char_count"],
            compaction_meta["removed_section_labels"],
        )
    elif compaction_meta.get("skip_reason"):
        logger.debug(
            "[COMPACTION][SKIPPED] job=%s status=%s skip_reason=%s removed_candidates=%s",
            record.get(RECORD_JOB_KEY, "<unknown>"),
            compaction_meta.get("compaction_status", ""),
            compaction_meta["skip_reason"],
            compaction_meta["removed_section_labels"],
        )
    record[RECORD_DESCRIPTION_SOURCE_KEY] = record.get(RECORD_DESCRIPTION_SOURCE_KEY) or ""
    source = str(record.get(RECORD_DESCRIPTION_SOURCE_KEY) or "").strip().lower()
    is_trusted = (
        source in get_trusted_sources()
        and len(details_text) >= get_min_trusted_description_length()
    )
    record[RECORD_FIT_CONFIDENCE_KEY] = CONFIDENCE_HIGH if is_trusted else CONFIDENCE_LOW
    record[RECORD_CONTENT_REASON_KEY] = "OK"
    return True, "OK"


def _apply_source_metadata_to_record(record: dict, llm_posting_channel: dict | None) -> None:
    channel_signal = infer_posting_channel(record, llm_posting_channel)
    record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] = {
        "kind": str(channel_signal.get("kind") or "unknown"),
        "source": str(channel_signal.get("source") or ""),
        "trusted_metadata": list(channel_signal.get("trusted_metadata") or []),
        "text_evidence": list(channel_signal.get("text_evidence") or []),
        "needs_review": bool(channel_signal.get("needs_review")),
    }


def _apply_work_type_inference(record: dict, details_text: str) -> None:
    """Refine work_type using title/description evidence after the description has been fetched.

    Only applies when the card-declared work type is in the trigger list (e.g. 'Full time').
    The inference rules and contract-signal keywords live in data/knowledge/job_type.json.
    Title is included because contract/fixed-term signals are often stated only in the
    title (e.g. "... - Fixed Term to June 2027") and never repeated in the body text.
    """
    original = str(record.get(RECORD_WORK_TYPE_KEY) or "").strip()
    title = str(record.get(RECORD_TITLE_KEY) or "").strip()
    signal_text = f"{title}\n{details_text}" if title else details_text
    result = infer_work_type_from_description(original, signal_text)
    if result is None:
        return
    record[RECORD_WORK_TYPE_KEY] = result["inferred_type"]
    record["work_type_inference_source"] = "description"
    record["work_type_inference_original"] = original
    record["work_type_inference_rule"] = result["rule_id"]
    record["work_type_inference_evidence"] = result["evidence"]
    logger.debug(
        format_log_block(
            "WORK_TYPE][INFERENCE",
            {
                "source": record.get("source", ""),
                "job_key": record.get(RECORD_JOB_KEY, ""),
                "title": record.get(RECORD_TITLE_KEY, ""),
                "original": original,
                "inferred": result["inferred_type"],
                "rule": result["rule_id"],
                "evidence": result["evidence"],
            },
        )
    )


def _apply_content_filter_result(
    record: dict, details_text: str, profile: dict, title_reason: str
) -> tuple[bool, str]:
    ok_desc, desc_reason = passes_content_filters(
        details_text, record[RECORD_LOCATION_KEY], title_reason, profile=profile
    )
    if not ok_desc:
        if desc_reason.startswith("DESC_HARD_BLOCK_RULE"):
            knowledge_matches = find_hard_block_matches(
                details_text, profile.get("must_not_require_skills", [])
            )
            record[RECORD_HARD_BLOCK_REASONS_KEY] = dedupe_preserve_order(
                [
                    compact_whitespace(match.get("value") or match.get("matched_term") or "")
                    for match in knowledge_matches
                ]
            )[:3]
        register_hard_blocker_learning_from_rejection(
            record, desc_reason, details_text, profile=profile
        )
        return False, desc_reason
    return True, "OK"


def _apply_competitive_signal_enrichment(record: dict, details_text: str, profile: dict) -> None:
    record[RECORD_COMPETITIVE_SIGNALS_KEY] = [
        evaluate_competitive_signal_alignment(signal, profile)
        for signal in detect_competitive_signals(details_text, profile)
    ]
    record[RECORD_REVIEWED_SIGNAL_MATCHES_KEY] = reviewed_signal_matches_for_text(details_text)


def _apply_hard_block_result(record: dict, details_text: str, profile: dict) -> tuple[bool, str]:
    hard_block_matches = hard_block_entries(record, profile)
    record[RECORD_HARD_BLOCK_REASONS_KEY] = [entry["text"] for entry in hard_block_matches]
    if record[RECORD_HARD_BLOCK_REASONS_KEY]:
        term = compact_whitespace(record[RECORD_HARD_BLOCK_REASONS_KEY][0]).lower()
        reason_code = (
            f"DESC_HARD_BLOCK_RULE:{re.sub(r'[^a-z0-9]+', '_', term).strip('_') or 'hard_block'}"
        )
        register_hard_blocker_learning_from_rejection(
            record, reason_code, details_text, hard_block_matches, profile=profile
        )
        return False, reason_code
    return True, "OK"


def _apply_learning_signal_enrichment(record: dict, details_text: str, profile: dict) -> list[dict]:
    skill_observations = extract_skill_observations(record, profile)
    record["skill_observations"] = skill_observations
    record["ad_learning_signals"] = build_ad_learning_signals(record, details_text, profile)
    record[RECORD_SALARY_KEY] = preferred_salary_display(
        str(record.get(RECORD_SALARY_KEY) or ""),
        str(record.get(RECORD_CARD_SALARY_KEY) or ""),
    )
    return skill_observations


def _build_requirement_classification_review_signals(record: dict) -> list[dict]:
    """Surface job requirements the deterministic classifier could not resolve.

    These never contribute to scoring or an "Add eligibility" prompt (see
    normalize_llm_requirement_coverage / workspace_renderer) — they only
    become a pending Learning/Needs Review signal so a human can confirm
    capability vs eligibility.
    """
    signals: list[dict] = []
    seen: set[str] = set()
    for item in record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []:
        if not isinstance(item, dict):
            continue
        if item.get("requirement_type") != LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE:
            continue
        requirement = str(item.get("requirement") or "").strip()
        key = requirement.lower()
        if not requirement or key in seen:
            continue
        seen.add(key)
        proposed_type = str(item.get("llm_proposed_requirement_type") or "capability").strip()
        signals.append(
            {
                LEARNING_SIGNAL_KEY: requirement,
                LEARNING_SUGGESTED_CATEGORY_KEY: CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW,
                LEARNING_ORIGINAL_TEXTS_KEY: [requirement],
                LEARNING_SUGGESTED_VALUES_KEY: [proposed_type],
            }
        )
    return signals


def _apply_preference_result(
    record: dict, profile: dict, context: ReviewPipelineContext
) -> tuple[bool, str]:
    ok_pref, pref_reason = passes_preference_filters(record, profile)
    if not ok_pref:
        return False, pref_reason
    return True, "OK"


def _apply_fit_summary_enrichment(
    record: dict, details_text: str, profile: dict, title_reason: str
) -> None:
    record[RECORD_ROLE_SNAPSHOT_KEY] = build_role_summary(record, details_text, profile)
    record[RECORD_FIT_HIGHLIGHTS_KEY] = build_fit_highlights(record, details_text, profile)
    (
        record[RECORD_SOFT_RISK_REASONS_KEY],
        record[RECORD_MISSING_PROFILE_SUPPORT_KEY],
        record[RECORD_MISSING_CLEARANCE_SUPPORT_KEY],
    ) = build_pre_review_risk_signals(
        details_text,
        title_reason,
        profile,
        competitive_signals=record[RECORD_COMPETITIVE_SIGNALS_KEY],
    )


def _evaluate_job_fit(record: dict, profile: dict, llm_cache: dict) -> dict:
    deterministic_review = deterministic_review_outcome(
        record,
        profile,
        record[RECORD_FIT_HIGHLIGHTS_KEY],
        record[RECORD_MISSING_PROFILE_SUPPORT_KEY],
        record[RECORD_SOFT_RISK_REASONS_KEY],
        record[RECORD_MISSING_CLEARANCE_SUPPORT_KEY],
    )
    record["llm_learning_candidates"] = []
    record[RECORD_JOB_REQUIREMENTS_KEY] = []
    record[RECORD_REQUIREMENT_COVERAGE_KEY] = []
    record[RECORD_OCCUPATION_ALIGNMENT_KEY] = ""
    record[RECORD_OCCUPATION_ALIGNMENT_REASON_KEY] = ""
    debug_reason = ""
    llm_elapsed_ms = None
    llm_cost_usd = None
    llm_input_tokens = None
    llm_output_tokens = None
    llm_posting_channel = None

    if deterministic_review is not None and deterministic_review["decision"] == "REJECT":
        review = deterministic_review
        source = "rule"
    else:
        if deterministic_review is not None:
            logger.debug(
                format_log_block(
                    "PIPELINE][DET_KEEP_CANDIDATE",
                    {
                        "job_key": record.get(RECORD_JOB_KEY, ""),
                        "title": record.get(RECORD_TITLE_KEY, ""),
                        "decision": deterministic_review["decision"],
                        "grade": deterministic_review["grade"],
                        "det_rule": deterministic_review.get("det_rule", ""),
                        "next_step": "full_llm_fit_review",
                    },
                )
            )
        _pipeline_log("LLM_CALL_START", record, call="fit_review")
        _t0 = time.monotonic()
        payload = resolve_llm_review_payload(record, llm_cache, profile=profile)
        llm_elapsed_ms = int((time.monotonic() - _t0) * 1000)
        _pipeline_log(
            "LLM_CALL_DONE",
            record,
            call="fit_review",
            elapsed_ms=llm_elapsed_ms,
            payload_source=payload.get("payload_source", "llm"),
        )
        review = payload["fit_review"]
        record["llm_learning_candidates"] = []
        record[RECORD_JOB_REQUIREMENTS_KEY] = payload.get("job_requirements") or []
        record[RECORD_REQUIREMENT_COVERAGE_KEY] = payload.get("requirement_coverage") or []
        record[RECORD_OCCUPATION_ALIGNMENT_KEY] = str(payload.get("occupation_alignment") or "")
        record[RECORD_OCCUPATION_ALIGNMENT_REASON_KEY] = str(
            payload.get("occupation_alignment_reason") or ""
        )
        debug_reason = str(payload.get("debug_reason") or "")
        llm_posting_channel = payload.get("posting_channel")
        llm_cost_raw = payload.get("llm_cost_usd")
        llm_cost_usd = None if llm_cost_raw in (None, "") else float(llm_cost_raw)
        llm_input_raw = payload.get(RECORD_LLM_INPUT_TOKENS_KEY)
        llm_output_raw = payload.get(RECORD_LLM_OUTPUT_TOKENS_KEY)
        llm_input_tokens = None if llm_input_raw in (None, "") else int(llm_input_raw)
        llm_output_tokens = None if llm_output_raw in (None, "") else int(llm_output_raw)
        source = str(payload.get("payload_source") or "llm")
        record["_obs_llm_called"] = True
        record["_obs_llm_cache_hit"] = source == "cache"
        record[RECORD_LLM_ELAPSED_MS_KEY] = llm_elapsed_ms
        record[RECORD_LLM_COST_USD_KEY] = llm_cost_usd
        record[RECORD_LLM_INPUT_TOKENS_KEY] = llm_input_tokens
        record[RECORD_LLM_OUTPUT_TOKENS_KEY] = llm_output_tokens
        credited_capabilities: list[str] = []
        imp_status_counts: dict[str, int] = {}
        eligibility_gate = eligibility_gate_diagnostics(record, profile)
        for item in record[RECORD_REQUIREMENT_COVERAGE_KEY]:
            status = str(item.get("status") or "not_shown").strip().lower()
            importance = str(item.get("importance") or "preferred").strip().lower()
            key = f"{importance}.{status}"
            imp_status_counts[key] = imp_status_counts.get(key, 0) + 1
            capability_name = str(item.get("capability_name") or "").strip()
            if capability_name and status in {"supported", "partially_supported"}:
                credited_capabilities.append(capability_name)
        logger.debug(
            format_log_block(
                "fit-review",
                {
                    "job_key": record.get(RECORD_JOB_KEY, ""),
                    "title": record.get(RECORD_TITLE_KEY, ""),
                    "grade": review.get("grade", ""),
                    "decision": review.get("decision", ""),
                    "capabilities_used": ", ".join(credited_capabilities) or "(none)",
                    "requirement_breakdown": " ".join(
                        f"{k}={v}" for k, v in sorted(imp_status_counts.items())
                    )
                    or "(empty)",
                    "eligibility_gate": eligibility_gate["label"],
                    "eligibility_reason": eligibility_gate["reason"],
                    "occupation_alignment": record[RECORD_OCCUPATION_ALIGNMENT_KEY] or "(none)",
                    "occupation_alignment_reason": record[RECORD_OCCUPATION_ALIGNMENT_REASON_KEY]
                    or "(none)",
                    "debug_reason": debug_reason or "(none)",
                },
            )
        )
        logger.debug(
            format_requirement_fit_diagnostics_block(
                record,
                profile,
                decision=str(review.get("decision", "")),
                grade=str(review.get("grade", "")),
                debug_reason=debug_reason,
            )
        )

    eligibility_reject_reason = ""
    if source != "rule":
        eligibility_gate = eligibility_gate_diagnostics(record, profile)
        if eligibility_gate["status"] == "fail":
            eligibility_reject_reason = "REQUIRED_ELIGIBILITY_FAILED"
        elif eligibility_gate["status"] == "unresolved":
            eligibility_reject_reason = "REQUIRED_ELIGIBILITY_UNRESOLVED"

    fit_eval = {
        "llm_decision": review["decision"],
        "llm_fit_grade": review["grade"],
        RECORD_LLM_DEBUG_REASON_KEY: debug_reason,
        "review_source": source,
        "decision": (
            "REJECT"
            if review["decision"] == "REJECT" or eligibility_reject_reason
            else "KEEP"
        ),
        "_eligibility_gate_reject_reason": eligibility_reject_reason,
        "_eligibility_gate_reason": (
            eligibility_gate.get("reason", "") if source != "rule" else ""
        ),
        RECORD_JOB_REQUIREMENTS_KEY: record[RECORD_JOB_REQUIREMENTS_KEY],
        RECORD_REQUIREMENT_COVERAGE_KEY: record[RECORD_REQUIREMENT_COVERAGE_KEY],
        RECORD_OCCUPATION_ALIGNMENT_KEY: record[RECORD_OCCUPATION_ALIGNMENT_KEY],
        RECORD_OCCUPATION_ALIGNMENT_REASON_KEY: record[RECORD_OCCUPATION_ALIGNMENT_REASON_KEY],
        "posting_channel": llm_posting_channel,
        RECORD_LLM_ELAPSED_MS_KEY: llm_elapsed_ms,
        RECORD_LLM_COST_USD_KEY: llm_cost_usd,
        RECORD_LLM_INPUT_TOKENS_KEY: llm_input_tokens,
        RECORD_LLM_OUTPUT_TOKENS_KEY: llm_output_tokens,
    }
    if fit_eval["decision"] == "KEEP" and not has_complete_llm_keep_data(fit_eval):
        raise LLMReviewValidationError("Final KEEP review requires complete LLM keep data")
    return fit_eval


def review_pre_detail_normalized_job(
    record: dict,
    context: ReviewPipelineContext,
    hooks: ReviewPipelineHooks | None = None,
) -> tuple[dict, dict, list[dict], bool]:
    profile = context.profile
    title = str(record.get(RECORD_TITLE_KEY) or "")
    company = str(record.get(RECORD_COMPANY_KEY) or "N/A")
    skill_observations: list[dict] = []

    _pipeline_log("CARD_SEEN", record, context.source_name)

    if not record.get(RECORD_JOB_KEY):
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = "NO_JOB_KEY"
        _finalize_job_result(record, context)
        return _build_outcome(record), record, skill_observations, False

    if not record.get(RECORD_URL_KEY):
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = "NO_URL"
        _finalize_job_result(record, context)
        return _build_outcome(record), record, skill_observations, False

    if _has_job_closed_signal(record):
        reject_reason = "JOB_CLOSED"
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reject_reason
        _pipeline_log(
            "CARD_GATE",
            record,
            context.source_name,
            result="REJECT",
            reason=reject_reason,
        )
        _finalize_job_result(
            record,
            context,
            reason=reject_reason,
            explanation="The listing appears to be closed and no longer accepting applications.",
        )
        return _build_outcome(record), record, skill_observations, False

    title_analysis = analyze_title_filters(title, profile)
    ok_title = bool(title_analysis.get("ok"))
    title_reason = str(title_analysis.get("reason") or "")
    record[RECORD_TITLE_REASON_KEY] = title_reason
    record[RECORD_TITLE_MATCH_METADATA_KEY] = title_analysis
    title_needs_review = (not ok_title) and title_reason == "TITLE_NOT_TARGET"
    _pipeline_log(
        "TITLE_GATE",
        record,
        context.source_name,
        result="PASS" if ok_title else ("REVIEW" if title_needs_review else "REJECT"),
        reason=title_reason,
    )
    if not ok_title:
        if title_reason == "TITLE_NOT_TARGET":
            # Downgraded gate: TITLE_NOT_TARGET alone is not a hard reject.
            # Consult O*NET to decide between a cheap skip (far occupation family)
            # and fetching the description (near or uncertain).
            _onet_t0 = time.monotonic()
            onet = _onet_classify_title(title, profile)
            _onet_elapsed_ms = int((time.monotonic() - _onet_t0) * 1000)
            record[RECORD_ONET_CLASSIFICATION_KEY] = {
                "result": onet.result,
                "matched_occupation_code": onet.matched_occupation_code,
                "confidence": onet.confidence,
                "reason": onet.reason,
            }
            _onet_outcome = "REJECT" if onet.result == RESULT_FAR else "FETCH_DETAILS"
            logger.debug(
                format_log_block(
                    "PIPELINE][ONET_DECISION",
                    {
                        "source": context.source_name,
                        "job_key": record.get(RECORD_JOB_KEY, ""),
                        "title": title,
                        "title_reason": title_reason,
                        "onet_result": onet.result,
                        "onet_response": format_onet_response(onet),
                        "onet_reason": onet.reason,
                        "matched_occupation_code": onet.matched_occupation_code,
                        "lookup_source": onet.lookup_source,
                        "elapsed_ms": _onet_elapsed_ms,
                        "outcome": _onet_outcome,
                    },
                )
            )
            if onet.result == RESULT_UNCERTAIN:
                _log_title_classification_uncertainty(record, profile, onet)
            if onet.result == RESULT_FAR:
                reject_reason = "ONET_FAR_OCCUPATION"
                _pipeline_log(
                    "TITLE_GATE",
                    record,
                    context.source_name,
                    result="REJECT",
                    reason=reject_reason,
                    onet_code=onet.matched_occupation_code,
                )
                record[RECORD_DECISION_KEY] = "REJECT"
                record[RECORD_REJECT_REASON_KEY] = reject_reason
                _finalize_job_result(
                    record,
                    context,
                    reason=reject_reason,
                    explanation=str(onet.reason or ""),
                )
                return _build_outcome(record), record, skill_observations, False

            # Near/uncertain titles get one cheap semantic check before detail fetch.
            # Strict mode keeps the original role-list contract; exploration mode may
            # use candidate capability names only to decide whether an unfamiliar title
            # is plausible enough to inspect, never to score or accept the job here.
            _title_judgment_t0 = time.monotonic()
            title_capability_names = [
                str(rule.get("name") or "").strip()
                for rule in (profile.get(KEY_CANDIDATE_CAPABILITIES) or [])
                if isinstance(rule, dict) and str(rule.get("name") or "").strip()
            ]
            target_roles = profile.get("target_roles")
            secondary_roles = profile.get("also_consider_roles")
            explore_adjacent_roles = bool(profile.get(KEY_EXPLORE_ADJACENT_ROLES, False))
            title_cache_key = build_title_judgment_cache_key(
                title,
                target_roles,
                secondary_roles,
                title_capability_names,
                explore_adjacent_roles=explore_adjacent_roles,
            )
            title_judgment = normalize_llm_title_judgment(context.llm_cache.get(title_cache_key))
            title_cache_hit = title_judgment is not None
            if not title_cache_hit:
                title_judgment = llm_judge_title(
                    title,
                    target_roles,
                    secondary_roles,
                    title_capability_names,
                    explore_adjacent_roles=explore_adjacent_roles,
                )
                if title_judgment is not None:
                    context.llm_cache[title_cache_key] = title_judgment
            _title_judgment_elapsed_ms = int((time.monotonic() - _title_judgment_t0) * 1000)
            if title_judgment is not None:
                record[RECORD_LLM_TITLE_JUDGMENT_KEY] = title_judgment
            logger.debug(
                format_log_block(
                    "PIPELINE][LLM_TITLE_JUDGMENT",
                    {
                        "source": context.source_name,
                        "job_key": record.get(RECORD_JOB_KEY, ""),
                        "title": title,
                        "target_roles": profile.get("target_roles") or [],
                        "also_consider_roles": profile.get("also_consider_roles") or [],
                        "verdict": (title_judgment or {}).get("verdict", "unavailable"),
                        "llm_reason": (title_judgment or {}).get("reason", ""),
                        "cache": "HIT" if title_cache_hit else "MISS",
                        "elapsed_ms": _title_judgment_elapsed_ms,
                    },
                )
            )
            if title_judgment is not None and title_judgment.get("verdict") == "no_match":
                reject_reason = "LLM_TITLE_NOT_TARGET"
                llm_reason = str(title_judgment.get("reason") or "")
                _pipeline_log(
                    "TITLE_GATE",
                    record,
                    context.source_name,
                    result="REJECT",
                    reason=reject_reason,
                    llm_reason=llm_reason,
                )
                record[RECORD_DECISION_KEY] = "REJECT"
                record[RECORD_REJECT_REASON_KEY] = reject_reason
                _finalize_job_result(
                    record,
                    context,
                    reason=reject_reason,
                    explanation=llm_reason,
                )
                return _build_outcome(record), record, skill_observations, False
            # match, uncertain, or LLM unavailable/failed: description and LLM decide; treat as potential match
            record[RECORD_TITLE_REASON_KEY] = TITLE_REASON_POTENTIAL_MATCH
        else:
            # TITLE_EMPTY, TITLE_BAD_KEYWORD, user-configured reject_title_rules — hard gates
            record[RECORD_DECISION_KEY] = "REJECT"
            record[RECORD_REJECT_REASON_KEY] = title_reason
            _finalize_job_result(record, context, reason=title_reason)
            return _build_outcome(record), record, skill_observations, False

    job_key = record[RECORD_JOB_KEY]
    if job_key in context.applied_job_keys:
        record[RECORD_DECISION_KEY] = "SKIP"
        record[RECORD_REJECT_REASON_KEY] = "ALREADY_APPLIED"
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations, False
    if job_key in context.hidden_job_keys:
        record[RECORD_DECISION_KEY] = "SKIP"
        record[RECORD_REJECT_REASON_KEY] = "MANUALLY_HIDDEN"
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations, False
    if context.seen_job_keys is not None:
        if job_key in context.seen_job_keys:
            record[RECORD_DECISION_KEY] = "SKIP"
            record[RECORD_REJECT_REASON_KEY] = "DUPLICATE_JOB_KEY"
            _finalize(record, context)
            return _build_outcome(record), record, skill_observations, False
        context.seen_job_keys.add(job_key)

    posted_age_days = record.get(RECORD_POSTED_AGE_DAYS_KEY)
    if posted_age_days is not None and posted_age_days > context.date_range_days:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = f"POSTED_TOO_OLD:{context.date_range_days}"
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations, False

    url = str(record.get(RECORD_URL_KEY) or "").strip()
    if url and context.seen_urls is not None:
        if url in context.seen_urls:
            record[RECORD_DECISION_KEY] = "SKIP"
            record[RECORD_REJECT_REASON_KEY] = "DUPLICATE_URL"
            _finalize(record, context)
            return _build_outcome(record), record, skill_observations, False
        context.seen_urls.add(url)

    ok_card, card_reason = passes_quick_card_filters(
        title=title,
        teaser=record.get(RECORD_TEASER_KEY) or "",
        company=company,
        location=record.get(RECORD_LOCATION_KEY) or "",
        work_mode=record.get(RECORD_WORK_MODE_KEY) or "",
        work_type=record.get(RECORD_WORK_TYPE_KEY) or "",
        salary=record.get(RECORD_CARD_SALARY_KEY) or record.get(RECORD_SALARY_KEY) or "",
        profile=profile,
    )
    _pipeline_log(
        "CARD_GATE",
        record,
        context.source_name,
        result="PASS" if ok_card else "REJECT",
        reason=card_reason,
    )
    if not ok_card:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = card_reason
        record["_obs_card_rejected"] = True
        _finalize_job_result(record, context, reason=card_reason)
        return _build_outcome(record), record, skill_observations, False

    history_entry = context.job_history.get(job_key, {})
    if not _defer_keep_reuse_until_post_detail(record) and can_reuse_kept_job(
        history_entry, record, profile
    ):
        record = apply_kept_job_reuse(record, history_entry)
        _freeze_fit_score_fields(record, profile)
        _finalize_job_result(record, context)
        return _build_outcome(record), record, skill_observations, False

    record[RECORD_DECISION_KEY] = "KEEP"
    return _build_outcome(record), record, skill_observations, True


def review_post_detail_normalized_job(
    record: dict,
    context: ReviewPipelineContext,
    hooks: ReviewPipelineHooks | None = None,
) -> tuple[dict, dict, list[dict]]:
    profile = context.profile
    title = str(record.get(RECORD_TITLE_KEY) or "")
    hooks = hooks or ReviewPipelineHooks()
    skill_observations: list[dict] = []
    title_reason = str(record.get(RECORD_TITLE_REASON_KEY) or "")

    details_text = str(record.get(RECORD_DETAILS_TEXT_KEY) or "")
    details_status = str(
        record.get(RECORD_DETAILS_STATUS_KEY) or ("ok" if details_text else "empty")
    )

    ok, reason = _apply_detail_payload_to_record(record, details_text, details_status)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize_job_result(record, context, reason=reason)
        return _build_outcome(record), record, skill_observations

    _apply_work_type_inference(record, details_text)
    _call_hook(hooks, "before_common_review", record, context)
    _call_hook(hooks, "after_description_loaded", record, context)

    ok, reason = _apply_content_filter_result(record, details_text, profile, title_reason)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize_job_result(record, context, reason=reason)
        return _build_outcome(record), record, skill_observations

    _apply_competitive_signal_enrichment(record, details_text, profile)

    ok, reason = _apply_hard_block_result(record, details_text, profile)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize_job_result(record, context, reason=reason)
        return _build_outcome(record), record, skill_observations

    skill_observations = _apply_learning_signal_enrichment(record, details_text, profile)

    _call_hook(hooks, "before_preference_filters", record, context)

    ok, reason = _apply_preference_result(record, profile, context)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize_job_result(record, context, reason=reason)
        return _build_outcome(record), record, skill_observations

    _call_hook(hooks, "after_preference_filters", record, context)

    ok, reason, explanation = _apply_external_posting_date_filter(record, context)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize_job_result(record, context, reason=reason, explanation=explanation)
        return _build_outcome(record), record, skill_observations

    history_entry = context.job_history.get(str(record.get(RECORD_JOB_KEY) or ""), {})
    if can_reuse_kept_job(history_entry, record, profile):
        record = apply_kept_job_reuse(record, history_entry)
        _freeze_fit_score_fields(record, profile)
        _finalize_job_result(record, context)
        return _build_outcome(record), record, skill_observations

    _apply_fit_summary_enrichment(record, details_text, profile, title_reason)

    _call_hook(hooks, "before_llm_review", record, context)

    _llm_t0 = time.monotonic()
    try:
        fit_eval = _evaluate_job_fit(record, profile, context.llm_cache)
    except LLMCallError as llm_exc:
        _llm_elapsed_ms = int((time.monotonic() - _llm_t0) * 1000)
        _reject_reason = "REVIEW_FAILED_TIMEOUT" if llm_exc.is_timeout else "LLM_ERROR"
        logger.error(
            format_log_block(
                "PIPELINE][LLM_CALL_ERROR",
                {
                    "source": context.source_name,
                    "job_key": record.get(RECORD_JOB_KEY, ""),
                    "title": title,
                    "company": record.get(RECORD_COMPANY_KEY, "N/A"),
                    "purpose": llm_exc.purpose,
                    "model": llm_exc.model,
                    "error_type": type(llm_exc).__name__,
                    "error_message": str(llm_exc),
                    "status_code": llm_exc.status_code,
                    "elapsed_ms": _llm_elapsed_ms,
                },
            )
        )
        record["_obs_llm_called"] = True
        record["_obs_llm_error"] = True
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = _reject_reason
        _finalize_job_result(record, context, reason=_reject_reason)
        return _build_outcome(record), record, skill_observations
    except LLMReviewValidationError as llm_exc:
        _llm_elapsed_ms = int((time.monotonic() - _llm_t0) * 1000)
        logger.error(
            format_log_block(
                "PIPELINE][LLM_INVALID_REVIEW",
                {
                    "source": context.source_name,
                    "job_key": record.get(RECORD_JOB_KEY, ""),
                    "title": title,
                    "company": record.get(RECORD_COMPANY_KEY, "N/A"),
                    "purpose": "fit_review",
                    "error_type": type(llm_exc).__name__,
                    "error_message": str(llm_exc),
                    "elapsed_ms": _llm_elapsed_ms,
                },
            )
        )
        record["_obs_llm_called"] = True
        record["_obs_llm_error"] = True
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = "LLM_INVALID_REVIEW"
        _finalize_job_result(record, context, reason="LLM_INVALID_REVIEW")
        return _build_outcome(record), record, skill_observations
    except Exception as llm_exc:
        _llm_elapsed_ms = int((time.monotonic() - _llm_t0) * 1000)
        no_provider_key = (
            isinstance(llm_exc, RuntimeError)
            and str(llm_exc) == "LLM review requested but no provider key is configured"
        )
        log_level = logger.warning if no_provider_key else logger.error
        log_level(
            format_log_block(
                "PIPELINE][LLM_CALL_ERROR",
                {
                    "source": context.source_name,
                    "job_key": record.get(RECORD_JOB_KEY, ""),
                    "title": title,
                    "company": record.get(RECORD_COMPANY_KEY, "N/A"),
                    "purpose": "fit_review",
                    "model": "",
                    "error_type": type(llm_exc).__name__,
                    "error_message": str(llm_exc),
                    "status_code": None,
                    "elapsed_ms": _llm_elapsed_ms,
                },
            )
        )
        record["_obs_llm_called"] = True
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = "LLM_UNAVAILABLE" if no_provider_key else "LLM_ERROR"
        if not no_provider_key:
            record["_obs_llm_error"] = True
        _finalize_job_result(record, context, reason=record[RECORD_REJECT_REASON_KEY])
        return _build_outcome(record), record, skill_observations

    record.update(fit_eval)
    record[RECORD_JOB_REQUIREMENTS_KEY] = record.get(RECORD_JOB_REQUIREMENTS_KEY) or []
    _apply_source_metadata_to_record(record, record.pop("posting_channel", None))

    if record[RECORD_DECISION_KEY] == "REJECT":
        eligibility_reject_reason = str(record.pop("_eligibility_gate_reject_reason", "") or "")
        eligibility_reason = str(record.pop("_eligibility_gate_reason", "") or "")
        record[RECORD_REJECT_REASON_KEY] = eligibility_reject_reason or (
            "LLM_REJECT" if record["review_source"] == "llm" else "DET_REJECT"
        )
        if eligibility_reject_reason and eligibility_reason:
            record[RECORD_DECISION_EXPLANATION_KEY] = eligibility_reason
        register_pending_learning_signals(
            merge_pending_learning_signals(
                record.get("ad_learning_signals") or [],
                record.get("llm_learning_candidates") or [],
                _build_requirement_classification_review_signals(record),
            )
        )
        _finalize_job_result(
            record,
            context,
            reason=record[RECORD_REJECT_REASON_KEY],
            explanation=eligibility_reason,
        )
        return _build_outcome(record), record, skill_observations

    _freeze_fit_score_fields(record, profile)
    pending_signals = merge_pending_learning_signals(
        record.get("ad_learning_signals") or [],
        record.get("llm_learning_candidates") or [],
        _build_requirement_classification_review_signals(record),
    )
    register_pending_learning_signals(pending_signals)
    record.pop("skill_observations", None)
    record.pop("ad_learning_signals", None)
    record.pop("llm_learning_candidates", None)
    _finalize_job_result(record, context)
    return _build_outcome(record), record, skill_observations
