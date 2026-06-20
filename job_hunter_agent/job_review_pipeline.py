"""Helpers for job review pipeline."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Optional

from job_hunter_agent.config import DEBUG_MODE

logger = logging.getLogger(__name__)

_PIPELINE_LOG_CORE_FIELDS = ("source", "job_key", "title", "company")

# Human-readable translations for internal pipeline reason codes.
# Codes not listed fall back to the raw code in parentheses.
_REASON_LABELS: dict[str, str] = {
    "TITLE_NOT_TARGET": "title not in your target roles",
    "TITLE_EMPTY": "job title is missing",
    "TITLE_BAD_KEYWORD": "title contains a blocked keyword",
    "TITLE_REASON_POTENTIAL_MATCH": "title is a potential match",
    "ONET_FAR_OCCUPATION": "occupation too far from your targets",
    "HARD_BLOCK": "matched a hard blocker rule",
    "HARD_BLOCK_REQUIRED_SKILL": "requires a skill you flagged as blocking",
    "DETAILS_CHALLENGE_PAGE": "description page was a bot challenge",
    "DETAILS_BLOCKED_PAGE": "description page was blocked",
    "DETAILS_NAVIGATION_ERROR": "description page failed to load",
    "NO_DETAILS": "could not read job description",
    "NO_DESCRIPTION_TRUST": "description too short to score reliably",
    "CONTENT_REJECT": "description did not pass content filters",
    "LLM_REJECT": "LLM reviewer rejected",
    "LLM_ERROR": "LLM review failed with an error",
    "LLM_UNAVAILABLE": "LLM review unavailable",
    "REVIEW_FAILED_TIMEOUT": "LLM review timed out — not reviewed, will retry next run",
    "DET_REJECT": "deterministic reviewer rejected",
    "ALREADY_APPLIED": "you already applied to this one",
    "DUPLICATE_URL": "duplicate listing",
    "DUPLICATE_JOB_KEY": "duplicate listing",
    "JOB_CLOSED": "no longer accepting applications",
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


def _job_tag(source: str, title: str, company: str, job_key: str) -> str:
    src = source.upper() if source else "?"
    name = f'"{title}"' if title else "(no title)"
    co = f" @ {company}" if company else ""
    key = f" [{job_key}]" if job_key and job_key != "unknown" else ""
    return f"{name}{co}  ({src}{key})"


from job_hunter_agent.capability_matching import (
    build_risk_and_missing_profile_support,
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
    fit_score_and_breakdown_displayed,
    fit_score_breakdown_frozen,
    fit_score_frozen,
)
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.history import apply_kept_job_reuse, can_reuse_kept_job, finalize_record
from job_hunter_agent.job_types import infer_work_type_from_description
from job_hunter_agent.job_quality import detect_external_date_signals, load_dodgy_job_rules
from job_hunter_agent.llm_gate import (
    LLMCallError,
    get_session_cost_usd,
    llm_extract_job_requirements,
)
from job_hunter_agent.logging_utils import format_log_block
from job_hunter_agent.match_labels import score_to_match_label
from job_hunter_agent.occupation_taxonomy import (
    RESULT_FAR,
    format_onet_response,
)
from job_hunter_agent.occupation_taxonomy import (
    classify_title as _onet_classify_title,
)
from job_hunter_agent.preferences import passes_preference_filters
from job_hunter_agent.profile_store import get_match_levels
from job_hunter_agent.record_schema import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    DETAILS_STATUS_OK,
    RECORD_CARD_SALARY_KEY,
    RECORD_COMPANY_KEY,
    RECORD_COMPETITIVE_SIGNALS_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_DECISION_KEY,
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
    RECORD_LOCATION_KEY,
    RECORD_MISSING_PROFILE_SUPPORT_KEY,
    RECORD_ONET_CLASSIFICATION_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
    RECORD_ROLE_SNAPSHOT_KEY,
    RECORD_SALARY_KEY,
    RECORD_SOFT_RISK_REASONS_KEY,
    RECORD_TEASER_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_MATCH_METADATA_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_TYPE_KEY,
)
from job_hunter_agent.role_analysis import infer_posting_channel
from job_hunter_agent.salary_utils import preferred_salary_display
from job_hunter_agent.score_labels import score_to_tone_class
from job_hunter_agent.signal_detection import (
    detect_competitive_signals,
    evaluate_competitive_signal_alignment,
    extract_skill_observations,
    hard_block_entries,
)
from job_hunter_agent.signal_schema import TITLE_REASON_POTENTIAL_MATCH
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
from job_hunter_agent.utils import extract_salary

HookFn = Callable[[dict, "ReviewPipelineContext"], None]


# Opening separator marks start of each job; closing marks end.
_SEP_OPEN = "═" * 72
_SEP_CLOSE = "─" * 72
_job_start_times: dict[str, float] = {}
_job_start_costs: dict[str, float] = {}


def close_job_block(job_key: str) -> None:
    """Print the closing separator for a job block. Called by seek_runner after all output."""
    logger.info("%s\n", _SEP_CLOSE)


def _pipeline_log(stage: str, record: dict, source_name: str = "", **kwargs: Any) -> None:
    source = source_name or str(record.get("source") or "")
    job_key = str(record.get(RECORD_JOB_KEY) or "unknown")
    title = str(record.get(RECORD_TITLE_KEY) or "(no title)")
    company = str(record.get(RECORD_COMPANY_KEY) or "")
    result = str(kwargs.get("result") or "")
    reason = str(kwargs.get("reason") or "")
    decision = str(kwargs.get("decision") or "")

    # ── Open a new job block ──────────────────────────────────────────────────
    if stage == "CARD_SEEN":
        _job_start_times[job_key] = time.monotonic()
        _job_start_costs[job_key] = get_session_cost_usd()
        src = source.upper() if source else "?"
        logger.info("\n%s\n  %s  @  %s\n  %s | %s\n", _SEP_OPEN, title, company, src, job_key)
        return

    # ── Title gate ────────────────────────────────────────────────────────────
    if stage == "TITLE_GATE":
        if result == "REJECT":
            elapsed = _elapsed(job_key)
            cost = _job_cost(job_key)
            logger.info(
                "  title: %s\n  ✗ REJECTED — title filtered out\n  time: %s  |  LLM: %s\n%s",
                _reason_label(reason),
                elapsed,
                cost,
                _SEP_CLOSE,
            )
        elif result == "REVIEW":
            label = _REASON_LABELS.get(reason.split(":")[0], reason)
            logger.info("  title: %s — will read description", label)
        return

    # ── Card gate (pre-description) ───────────────────────────────────────────
    if stage == "CARD_GATE":
        if result == "REJECT":
            elapsed = _elapsed(job_key)
            cost = _job_cost(job_key)
            logger.info(
                "  ✗ REJECTED before reading — %s\n  time: %s  |  LLM: %s",
                _reason_label(reason),
                elapsed,
                cost,
            )
        return

    # ── Final outcome — closing separator printed by seek_runner after score output ──
    if stage == "FINAL_DECISION":
        elapsed = _elapsed(job_key)
        cost = _job_cost(job_key)
        start_time = _job_start_times.pop(job_key, None)
        _job_start_costs.pop(job_key, None)
        total_job_ms = int((time.monotonic() - start_time) * 1000) if start_time is not None else 0
        if decision == "KEEP":
            grade = str(kwargs.get("grade") or "")
            review_source = str(kwargs.get("review_source") or "")
            parts = [f"grade {grade}" if grade else "", review_source]
            detail = "  |  ".join(p for p in parts if p)
            logger.info(
                "  ✓ KEPT%s\n  time: %s  |  LLM: %s",
                f"  —  {detail}" if detail else "",
                elapsed,
                cost,
            )
        elif decision == "REJECT":
            logger.info(
                "  ✗ REJECTED — %s\n  time: %s  |  LLM: %s", _reason_label(reason), elapsed, cost
            )
        logger.info(
            format_log_block(
                "PIPELINE][FINAL_DECISION",
                {
                    "source": source,
                    "job_key": job_key,
                    "decision": decision,
                    "reason": reason,
                    "total_job_ms": total_job_ms,
                },
            )
        )
        return

    # ── LLM call outcome ──────────────────────────────────────────────────────
    if stage == "LLM_CALL_DONE":
        call = str(kwargs.get("call") or "")
        elapsed_ms = int(kwargs.get("elapsed_ms") or 0)
        payload_source = str(kwargs.get("payload_source") or "llm")
        logger.info("  llm %s: elapsed=%dms  source=%s", call, elapsed_ms, payload_source)
        return

    # ── Debug-only: show raw stage data for anything else ─────────────────────
    if DEBUG_MODE:
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
        logger.info("\n".join(lines))


def _elapsed(job_key: str) -> str:
    start = _job_start_times.get(job_key)
    if start is None:
        return "?"
    secs = time.monotonic() - start
    return f"{secs:.1f}s"


def _job_cost(job_key: str) -> str:
    start_cost = _job_start_costs.get(job_key)
    if start_cost is None:
        return "$0.0000"
    delta = get_session_cost_usd() - start_cost
    return f"${max(delta, 0.0):.4f}"


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


def _source_tag(context: ReviewPipelineContext) -> str:
    return f"[{context.source_name}]"


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
    }


def _freeze_fit_score_fields(record: dict, profile: dict) -> None:
    # Guard: cannot score without an LLM grade (e.g. very old history snapshots that predate
    # grade capture, or future code paths that call this before review). Existing frozen
    # fields from the snapshot are preserved as-is; the display path reads those directly.
    if not str(record.get("llm_fit_grade") or "").strip():
        return
    fit_points = fit_score_frozen(record, profile)
    record[RECORD_FIT_SCORE_KEY] = fit_points
    record[RECORD_FIT_SCORE_BREAKDOWN_KEY] = fit_score_breakdown_frozen(record, profile)
    record[RECORD_FIT_LABEL_KEY] = score_to_match_label(fit_points, get_match_levels(profile))
    record[RECORD_FIT_TONE_CLASS_KEY] = score_to_tone_class(fit_points, profile)


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
        logger.info(
            "[COMPACTION] job=%s original=%d compacted=%d removed=%s",
            record.get(RECORD_JOB_KEY, "<unknown>"),
            compaction_meta["original_char_count"],
            compaction_meta["compacted_char_count"],
            compaction_meta["removed_section_labels"],
        )
    elif compaction_meta.get("skip_reason"):
        logger.info(
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


def _apply_source_metadata_to_record(record: dict, details_text: str) -> None:
    channel_signal = infer_posting_channel(record, details_text)
    record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] = {
        "trusted_metadata": list(channel_signal.get("trusted_metadata") or []),
        "weak_text_matches": list(channel_signal.get("weak_text_matches") or []),
        "needs_review": bool(channel_signal.get("needs_review")),
    }


def _apply_work_type_inference(record: dict, details_text: str) -> None:
    """Refine work_type using description evidence after the description has been fetched.

    Only applies when the card-declared work type is in the trigger list (e.g. 'Full time').
    The inference rules and contract-signal keywords live in data/knowledge/job_type.json.
    """
    original = str(record.get(RECORD_WORK_TYPE_KEY) or "").strip()
    result = infer_work_type_from_description(original, details_text)
    if result is None:
        return
    record[RECORD_WORK_TYPE_KEY] = result["inferred_type"]
    record["work_type_inference_source"] = "description"
    record["work_type_inference_original"] = original
    record["work_type_inference_rule"] = result["rule_id"]
    record["work_type_inference_evidence"] = result["evidence"]
    logger.info(
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
        details_text, record[RECORD_LOCATION_KEY], title_reason
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
        extract_salary(details_text),
    )
    return skill_observations


def _apply_preference_result(
    record: dict, profile: dict, context: ReviewPipelineContext
) -> tuple[bool, str]:
    ok_pref, pref_reason = passes_preference_filters(record, profile)
    if not ok_pref:
        print(
            f"{_source_tag(context)} REJECTED (preference gate) "
            f"[{pref_reason}] {record.get(RECORD_TITLE_KEY)} @ {record.get(RECORD_COMPANY_KEY)}"
        )
        return False, pref_reason
    return True, "OK"


def _apply_fit_summary_enrichment(
    record: dict, details_text: str, profile: dict, title_reason: str
) -> None:
    record[RECORD_ROLE_SNAPSHOT_KEY] = build_role_summary(record, details_text, profile)
    record[RECORD_FIT_HIGHLIGHTS_KEY] = build_fit_highlights(record, details_text, profile)
    record[RECORD_SOFT_RISK_REASONS_KEY], record[RECORD_MISSING_PROFILE_SUPPORT_KEY] = (
        build_risk_and_missing_profile_support(
            details_text,
            title_reason,
            profile,
            competitive_signals=record[RECORD_COMPETITIVE_SIGNALS_KEY],
        )
    )


def _evaluate_job_fit(record: dict, profile: dict, llm_cache: dict) -> dict:
    deterministic_review = deterministic_review_outcome(
        record,
        profile,
        record[RECORD_FIT_HIGHLIGHTS_KEY],
        record[RECORD_MISSING_PROFILE_SUPPORT_KEY],
        record[RECORD_SOFT_RISK_REASONS_KEY],
    )
    record["llm_learning_candidates"] = []
    record[RECORD_JOB_REQUIREMENTS_KEY] = []
    record[RECORD_REQUIREMENT_COVERAGE_KEY] = []
    debug_reason = ""
    llm_elapsed_ms = None
    llm_cost_usd = None

    if deterministic_review is not None:
        review = deterministic_review
        source = "rule"
        if not record[RECORD_JOB_REQUIREMENTS_KEY]:
            try:
                _pipeline_log("LLM_CALL_START", record, call="job_requirements")
                _t0 = time.monotonic()
                record[RECORD_JOB_REQUIREMENTS_KEY] = llm_extract_job_requirements(
                    record.get("full_description") or record.get("fit_source_text") or ""
                )
                _pipeline_log(
                    "LLM_CALL_DONE",
                    record,
                    call="job_requirements",
                    elapsed_ms=int((time.monotonic() - _t0) * 1000),
                )
            except Exception as llm_exc:
                _pipeline_log(
                    "LLM_CALL_DONE",
                    record,
                    call="job_requirements",
                    result="ERROR",
                    error=type(llm_exc).__name__,
                )
                print(f"[LLM][JOB_REQUIREMENTS_ERROR] {type(llm_exc).__name__}: {llm_exc}")
    else:
        _pipeline_log("LLM_CALL_START", record, call="fit_review")
        _t0 = time.monotonic()
        payload = resolve_llm_review_payload(record, llm_cache)
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
        debug_reason = str(payload.get("debug_reason") or "")
        llm_cost_usd = float(payload.get("llm_cost_usd") or 0.0)
        source = str(payload.get("payload_source") or "llm")
        record["_obs_llm_called"] = True
        record["_obs_llm_cache_hit"] = source == "cache"
        record[RECORD_LLM_ELAPSED_MS_KEY] = llm_elapsed_ms
        record[RECORD_LLM_COST_USD_KEY] = llm_cost_usd
        credited_capabilities: list[str] = []
        imp_status_counts: dict[str, int] = {}
        for item in record[RECORD_REQUIREMENT_COVERAGE_KEY]:
            status = str(item.get("status") or "not_shown").strip().lower()
            importance = str(item.get("importance") or "preferred").strip().lower()
            key = f"{importance}.{status}"
            imp_status_counts[key] = imp_status_counts.get(key, 0) + 1
            capability_name = str(item.get("capability_name") or "").strip()
            if capability_name and status in {"supported", "partially_supported"}:
                credited_capabilities.append(capability_name)
        logger.info(
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
                    "debug_reason": debug_reason or "(none)",
                },
            )
        )

    return {
        "llm_decision": review["decision"],
        "llm_fit_grade": review["grade"],
        RECORD_LLM_DEBUG_REASON_KEY: debug_reason,
        "review_source": source,
        "decision": "KEEP" if review["decision"] != "REJECT" else "REJECT",
        RECORD_JOB_REQUIREMENTS_KEY: record[RECORD_JOB_REQUIREMENTS_KEY],
        RECORD_REQUIREMENT_COVERAGE_KEY: record[RECORD_REQUIREMENT_COVERAGE_KEY],
        RECORD_LLM_ELAPSED_MS_KEY: llm_elapsed_ms,
        RECORD_LLM_COST_USD_KEY: llm_cost_usd,
    }


def review_pre_detail_normalized_job(
    record: dict,
    context: ReviewPipelineContext,
    hooks: ReviewPipelineHooks | None = None,
) -> tuple[dict, dict, list[dict], bool]:
    profile = context.profile
    title = str(record.get(RECORD_TITLE_KEY) or "")
    company = str(record.get(RECORD_COMPANY_KEY) or "N/A")
    source_tag = _source_tag(context)
    skill_observations: list[dict] = []

    _pipeline_log("CARD_SEEN", record, context.source_name)

    if not record.get(RECORD_JOB_KEY):
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = "NO_JOB_KEY"
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations, False

    if not record.get(RECORD_URL_KEY):
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = "NO_URL"
        _finalize(record, context)
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
        print(
            f"{source_tag} REJECTED (closed) [{reject_reason}] {title} @ {company} "
            "(no longer accepting applications)"
        )
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations, False

    title_analysis = analyze_title_filters(title, profile)
    ok_title = bool(title_analysis.get("ok"))
    title_reason = str(title_analysis.get("reason") or "")
    record[RECORD_TITLE_REASON_KEY] = title_reason
    record[RECORD_TITLE_MATCH_METADATA_KEY] = title_analysis
    _pipeline_log(
        "TITLE_GATE",
        record,
        context.source_name,
        result="PASS" if ok_title else "REVIEW",
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
            logger.info(
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
                print(f"{source_tag} REJECTED (onet far) [{reject_reason}] {title}")
                record[RECORD_DECISION_KEY] = "REJECT"
                record[RECORD_REJECT_REASON_KEY] = reject_reason
                _finalize(record, context)
                return _build_outcome(record), record, skill_observations, False
            # near or uncertain: description and LLM decide; treat as potential match
            record[RECORD_TITLE_REASON_KEY] = TITLE_REASON_POTENTIAL_MATCH
        else:
            # TITLE_EMPTY, TITLE_BAD_KEYWORD, user-configured reject_title_rules — hard gates
            print(f"{source_tag} REJECTED (title) [{title_reason}] {title}")
            record[RECORD_DECISION_KEY] = "REJECT"
            record[RECORD_REJECT_REASON_KEY] = title_reason
            _finalize(record, context)
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
            print(f"{source_tag} SKIPPED (duplicate job key) {title} @ {company}")
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
            print(f"{source_tag} SKIPPED (duplicate URL) {title} @ {company}")
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
    )
    _pipeline_log(
        "CARD_GATE",
        record,
        context.source_name,
        result="PASS" if ok_card else "REJECT",
        reason=card_reason,
    )
    if not ok_card:
        print(f"{source_tag} REJECTED (card gate) [{card_reason}] {title} @ {company}")
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = card_reason
        record["_obs_card_rejected"] = True
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations, False

    history_entry = context.job_history.get(job_key, {})
    if can_reuse_kept_job(history_entry, record, profile):
        record = apply_kept_job_reuse(record, history_entry)
        _freeze_fit_score_fields(record, profile)
        _finalize(record, context)
        print(f"{source_tag} KEPT (history reuse) {title} @ {company}")
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
    company = str(record.get(RECORD_COMPANY_KEY) or "N/A")
    source_tag = _source_tag(context)
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
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations

    _apply_source_metadata_to_record(record, details_text)
    _apply_work_type_inference(record, details_text)
    _call_hook(hooks, "before_common_review", record, context)
    _call_hook(hooks, "after_description_loaded", record, context)

    ok, reason = _apply_content_filter_result(record, details_text, profile, title_reason)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize(record, context)
        print(f"{source_tag} REJECTED (content) [{reason}] {title} @ {company}")
        _pipeline_log(
            "FINAL_DECISION", record, context.source_name, decision="REJECT", reason=reason
        )
        return _build_outcome(record), record, skill_observations

    _apply_competitive_signal_enrichment(record, details_text, profile)

    ok, reason = _apply_hard_block_result(record, details_text, profile)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize(record, context)
        print(
            f"{source_tag} REJECTED (hard block) [{reason}] {title} @ {company} | "
            f"{'; '.join(record.get(RECORD_HARD_BLOCK_REASONS_KEY) or [])}"
        )
        _pipeline_log(
            "FINAL_DECISION", record, context.source_name, decision="REJECT", reason=reason
        )
        return _build_outcome(record), record, skill_observations

    skill_observations = _apply_learning_signal_enrichment(record, details_text, profile)

    _call_hook(hooks, "before_preference_filters", record, context)

    ok, reason = _apply_preference_result(record, profile, context)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize(record, context)
        _pipeline_log(
            "FINAL_DECISION", record, context.source_name, decision="REJECT", reason=reason
        )
        return _build_outcome(record), record, skill_observations

    _call_hook(hooks, "after_preference_filters", record, context)

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
                    "company": company,
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
        _finalize(record, context)
        _pipeline_log(
            "FINAL_DECISION", record, context.source_name, decision="REJECT", reason=_reject_reason
        )
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
                    "company": company,
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
        _finalize(record, context)
        _pipeline_log(
            "FINAL_DECISION",
            record,
            context.source_name,
            decision="REJECT",
            reason=record[RECORD_REJECT_REASON_KEY],
        )
        return _build_outcome(record), record, skill_observations

    record.update(fit_eval)
    record[RECORD_JOB_REQUIREMENTS_KEY] = record.get(RECORD_JOB_REQUIREMENTS_KEY) or []

    if record[RECORD_DECISION_KEY] == "REJECT":
        print(f"{source_tag} REJECTED ({record['review_source']}) {title} @ {company}")
        record[RECORD_REJECT_REASON_KEY] = (
            "LLM_REJECT" if record["review_source"] == "llm" else "DET_REJECT"
        )
        register_pending_learning_signals(
            merge_pending_learning_signals(
                record.get("ad_learning_signals") or [],
                record.get("llm_learning_candidates") or [],
            )
        )
        _finalize(record, context)
        _pipeline_log(
            "FINAL_DECISION",
            record,
            context.source_name,
            decision="REJECT",
            reason=record[RECORD_REJECT_REASON_KEY],
            review_source=record.get("review_source", ""),
            grade=record.get(RECORD_LLM_FIT_GRADE_KEY, ""),
        )
        return _build_outcome(record), record, skill_observations

    _freeze_fit_score_fields(record, profile)
    pending_signals = merge_pending_learning_signals(
        record.get("ad_learning_signals") or [],
        record.get("llm_learning_candidates") or [],
    )
    register_pending_learning_signals(pending_signals)
    record.pop("skill_observations", None)
    record.pop("ad_learning_signals", None)
    record.pop("llm_learning_candidates", None)
    _finalize(record, context)
    print(
        f"{source_tag} KEPT {title} @ {company} | "
        f"{record.get('posted')} | {record.get('location')} | {record.get('work_type')} | "
        f"{record.get(RECORD_SALARY_KEY) or 'N/A'}"
    )
    _pipeline_log(
        "FINAL_DECISION",
        record,
        context.source_name,
        decision="KEEP",
        review_source=record.get("review_source", ""),
        grade=record.get(RECORD_LLM_FIT_GRADE_KEY, ""),
    )
    return _build_outcome(record), record, skill_observations


# ─── Human-readable per-job summary ──────────────────────────────────────────


def print_job_human_summary(
    record: dict,
    profile: dict,
    elapsed_s: float = 0.0,
    score: int | None = None,
    llm_cost: float = 0.0,
    breakdown: list | None = None,
) -> None:
    """Single curated block printed to stdout at the end of every job's processing.

    All structured machine logs still emit independently. This is the human view.
    """
    from job_hunter_agent.occupation_taxonomy import RESULT_FAR, RESULT_UNCERTAIN

    title = str(record.get(RECORD_TITLE_KEY) or "(no title)")
    company = str(record.get(RECORD_COMPANY_KEY) or "")
    source = str(record.get("source") or "").upper()
    decision = str(record.get(RECORD_DECISION_KEY) or "")
    reject_reason = str(record.get(RECORD_REJECT_REASON_KEY) or "")
    title_reason = str(record.get(RECORD_TITLE_REASON_KEY) or "")

    targets = [str(r).strip() for r in (profile.get("target_roles") or []) if str(r).strip()]
    also = [str(r).strip() for r in (profile.get("also_consider_roles") or []) if str(r).strip()]
    target_str = ", ".join(targets[:4]) or "(not set)"
    also_str = "  |  also: " + ", ".join(also[:3]) if also else ""

    lines: list[str] = [
        "",
        f"  {'─' * 70}",
        f"  {title}  ·  {company}  ({source})",
        f"  You target:  {target_str}{also_str}",
        "",
    ]

    # ── Title gate ────────────────────────────────────────────────────────────
    if title_reason in {"TITLE_EMPTY", "TITLE_BAD_KEYWORD"}:
        lines.append(f"  [✗] Title rejected  ({_reason_label(title_reason)})")
    elif title_reason == "TITLE_NOT_TARGET":
        onet = record.get(RECORD_ONET_CLASSIFICATION_KEY) or {}
        onet_result = str(onet.get("result") or "")
        onet_code = str(onet.get("matched_occupation_code") or "—")
        onet_src = str(onet.get("reason") or "")
        if onet_result == RESULT_FAR:
            lines.append(f"  [✗] Title not in target roles  →  occupation too far ({onet_code})")
        elif onet_result == RESULT_UNCERTAIN:
            lines.append(
                f"  [?] Title not in target roles  →  ONET uncertain ({onet_src}), description decides"
            )
        else:
            lines.append(
                f"  [?] Title not in target roles  →  ONET near ({onet_code}), description decides"
            )
    elif title_reason == TITLE_REASON_POTENTIAL_MATCH:
        lines.append("  [?] Title is a potential match  →  description decides")
    elif title_reason == "OK":
        lines.append("  [✓] Title matched your target roles")

    # ── Description fetch ─────────────────────────────────────────────────────
    details_status = str(record.get(RECORD_DETAILS_STATUS_KEY) or "")
    details_length = int(record.get(RECORD_DETAILS_LENGTH_KEY) or 0)
    fetch_ms = int(record.get("_obs_detail_fetch_ms") or 0)
    if details_length:
        fetch_note = f"  ({fetch_ms / 1000:.1f}s)" if fetch_ms else ""
        lines.append(f"  [✓] Description fetched  {details_length:,} chars{fetch_note}")
    elif details_status and details_status not in {"", "ok"}:
        lines.append(f"  [✗] Description {details_status}")

    # ── Content / hard blocks ─────────────────────────────────────────────────
    hard_blocks = list(record.get(RECORD_HARD_BLOCK_REASONS_KEY) or [])
    content_reason = str(record.get(RECORD_CONTENT_REASON_KEY) or "")
    if hard_blocks:
        blocks_str = "; ".join(str(b) for b in hard_blocks[:2])
        lines.append(f"  [✗] Hard blocked: {blocks_str}")
    elif content_reason and content_reason not in {"OK", ""}:
        lines.append(f"  [✗] Content rejected  ({content_reason})")
    elif details_length:
        lines.append("  [✓] Content passed, no hard blockers")

    # ── Review outcome ────────────────────────────────────────────────────────
    review_source = str(record.get("review_source") or "")
    llm_grade = str(record.get(RECORD_LLM_FIT_GRADE_KEY) or "")
    if review_source:
        src_label = {"rule": "deterministic rule", "llm": "LLM", "cache": "LLM (cached)"}.get(
            review_source, review_source
        )
        grade_note = f" · {llm_grade}" if llm_grade else ""
        cost_note = f"  (LLM: ${llm_cost:.4f})" if llm_cost > 0.00005 else ""
        if decision == "KEEP":
            lines.append(f"  [✓] Review: KEEP{grade_note}  ·  via {src_label}{cost_note}")
        else:
            lines.append(f"  [✗] Review: REJECT{grade_note}  ·  via {src_label}{cost_note}")
    elif reject_reason == "REVIEW_FAILED_TIMEOUT":
        cost_note = f"  (LLM: ${llm_cost:.4f})" if llm_cost > 0.00005 else ""
        lines.append(f"  [~] Not reviewed — LLM timed out. Will retry next run.{cost_note}")
    elif reject_reason == "LLM_ERROR":
        cost_note = f"  (LLM: ${llm_cost:.4f})" if llm_cost > 0.00005 else ""
        lines.append(f"  [!] LLM review failed (API error){cost_note}")
    elif reject_reason == "LLM_UNAVAILABLE":
        cost_note = f"  (LLM: ${llm_cost:.4f})" if llm_cost > 0.00005 else ""
        lines.append(f"  [~] LLM review unavailable — no provider key configured{cost_note}")

    lines.append("")

    # ── Score breakdown ───────────────────────────────────────────────────────
    if decision == "KEEP" and breakdown:
        from job_hunter_agent.score_labels import format_score_breakdown_console

        lines.extend(format_score_breakdown_console(breakdown))
        lines.append("")

    # ── Final line ────────────────────────────────────────────────────────────
    time_note = f"  ·  {elapsed_s:.1f}s" if elapsed_s else ""
    cost_line = f"  ·  LLM: ${llm_cost:.4f}" if llm_cost > 0.00005 else ""
    if decision == "KEEP":
        score_note = f"  ·  score {score}/100" if score is not None else ""
        lines.append(f"  ✓  KEPT{score_note}{time_note}{cost_line}")
    else:
        lines.append(f"  ✗  REJECTED — {_reason_label(reject_reason)}{time_note}{cost_line}")

    logger.info("\n".join(lines))
