"""Helpers for job review pipeline."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_PIPELINE_LOG_CORE_FIELDS = ("source", "job_key", "title", "company")

from job_hunter_agent.capability_matching import build_risk_and_missing_evidence, reviewed_signal_matches_for_text
from job_hunter_agent.description_trust import get_min_trusted_description_length, get_trusted_sources
from job_hunter_agent.filters import analyze_title_filters, passes_content_filters, passes_quick_card_filters
from job_hunter_agent.fit_scoring import build_fit_highlights
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.history import apply_kept_job_reuse, can_reuse_kept_job, finalize_record
from job_hunter_agent.llm_gate import llm_extract_job_requirements
from job_hunter_agent.preferences import passes_preference_filters
from job_hunter_agent.occupation_taxonomy import RESULT_FAR, classify_title as _onet_classify_title
from job_hunter_agent.signal_schema import TITLE_REASON_POTENTIAL_MATCH
from job_hunter_agent.record_schema import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    DETAILS_STATUS_OK,
    RECORD_CARD_SALARY_KEY,
    RECORD_COMPANY_KEY,
    RECORD_COMPETITIVE_SIGNALS_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_CONTEXTUAL_CAPABILITY_MATCHES_KEY,
    RECORD_DECISION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_LENGTH_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_FIT_CONFIDENCE_KEY,
    RECORD_FIT_HIGHLIGHTS_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_JOB_KEY,
    RECORD_JOB_REQUIREMENTS_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LOCATION_KEY,
    RECORD_MISSING_EVIDENCE_KEY,
    RECORD_ONET_CLASSIFICATION_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_REJECT_REASON_KEY,
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
from job_hunter_agent.signal_detection import (
    detect_competitive_signals,
    evaluate_competitive_signal_alignment,
    extract_skill_observations,
    hard_block_entries,
)
from job_hunter_agent.source_learning import (
    build_ad_learning_signals,
    deterministic_review_outcome,
    merge_pending_learning_signals,
    register_hard_blocker_learning_from_rejection,
    register_pending_learning_signals,
    resolve_llm_review_payload,
)
from job_hunter_agent.text_processing import build_role_summary, compact_whitespace, dedupe_preserve_order
from job_hunter_agent.utils import extract_salary


HookFn = Callable[[dict, "ReviewPipelineContext"], None]


def _pipeline_log(stage: str, record: dict, source_name: str = "", **kwargs: Any) -> None:
    source = source_name or str(record.get("source") or "")
    job_key = str(record.get(RECORD_JOB_KEY) or "unknown")
    title = str(record.get(RECORD_TITLE_KEY) or "")
    company = str(record.get(RECORD_COMPANY_KEY) or "")
    fields: dict[str, Any] = {
        "source": source,
        "job_key": job_key,
        "title": title,
        "company": company,
    }
    fields.update(kwargs)
    label_width = max(len(label) for label in _PIPELINE_LOG_CORE_FIELDS + tuple(kwargs.keys())) if fields else 0
    lines = [f"[PIPELINE][{stage}]"]
    for label in _PIPELINE_LOG_CORE_FIELDS:
        lines.append(f"  {label.ljust(label_width)}  {fields[label]}")
    for label, value in kwargs.items():
        lines.append(f"  {label.ljust(label_width)}  {value}")
    logger.info("\n".join(lines))


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


def _source_tag(context: ReviewPipelineContext) -> str:
    return f"[{context.source_name}]"


def _call_hook(hooks: ReviewPipelineHooks | None, hook_name: str, record: dict, context: ReviewPipelineContext) -> None:
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
        RECORD_CONTEXTUAL_CAPABILITY_MATCHES_KEY: list(record.get(RECORD_CONTEXTUAL_CAPABILITY_MATCHES_KEY) or []),
    }


def _apply_detail_payload_to_record(record: dict, details_text: str, details_status: str) -> tuple[bool, str]:
    record[RECORD_DETAILS_STATUS_KEY] = details_status
    record[RECORD_DETAILS_LENGTH_KEY] = len(details_text)

    if details_status != DETAILS_STATUS_OK or not details_text:
        reject_reason = _DETAILS_STATUS_REJECT_REASON.get(details_status, "NO_DETAILS")
        record[RECORD_CONTENT_REASON_KEY] = reject_reason
        return False, reject_reason

    record[RECORD_FIT_SOURCE_TEXT_KEY] = details_text
    record[RECORD_FULL_DESCRIPTION_KEY] = details_text
    record[RECORD_DESCRIPTION_SOURCE_KEY] = record.get(RECORD_DESCRIPTION_SOURCE_KEY) or ""
    source = str(record.get(RECORD_DESCRIPTION_SOURCE_KEY) or "").strip().lower()
    is_trusted = source in get_trusted_sources() and len(details_text) >= get_min_trusted_description_length()
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


def _apply_content_filter_result(record: dict, details_text: str, profile: dict, title_reason: str) -> tuple[bool, str]:
    ok_desc, desc_reason = passes_content_filters(details_text, record[RECORD_LOCATION_KEY], title_reason)
    if not ok_desc:
        if desc_reason.startswith("DESC_HARD_BLOCK_RULE"):
            knowledge_matches = find_hard_block_matches(details_text, profile.get("must_not_require_skills", []))
            record[RECORD_HARD_BLOCK_REASONS_KEY] = dedupe_preserve_order(
                [
                    compact_whitespace(match.get("value") or match.get("matched_term") or "")
                    for match in knowledge_matches
                ]
            )[:3]
        register_hard_blocker_learning_from_rejection(record, desc_reason, details_text, profile=profile)
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
        reason_code = f"DESC_HARD_BLOCK_RULE:{re.sub(r'[^a-z0-9]+', '_', term).strip('_') or 'hard_block'}"
        register_hard_blocker_learning_from_rejection(record, reason_code, details_text, hard_block_matches, profile=profile)
        return False, reason_code
    return True, "OK"


def _apply_learning_signal_enrichment(record: dict, details_text: str, profile: dict) -> list[dict]:
    skill_observations = extract_skill_observations(record, profile)
    record["skill_observations"] = skill_observations
    record["ad_learning_signals"] = build_ad_learning_signals(record, details_text, profile)
    record[RECORD_SALARY_KEY] = preferred_salary_display(
        record.get(RECORD_SALARY_KEY),
        record.get(RECORD_CARD_SALARY_KEY),
        extract_salary(details_text),
    )
    return skill_observations


def _apply_preference_result(record: dict, profile: dict, context: ReviewPipelineContext) -> tuple[bool, str]:
    ok_pref, pref_reason = passes_preference_filters(record, profile)
    if not ok_pref:
        print(
            f"{_source_tag(context)} REJECTED (preference gate) "
            f"[{pref_reason}] {record.get(RECORD_TITLE_KEY)} @ {record.get(RECORD_COMPANY_KEY)}"
        )
        return False, pref_reason
    return True, "OK"


def _apply_fit_summary_enrichment(record: dict, details_text: str, profile: dict, title_reason: str) -> None:
    record[RECORD_ROLE_SNAPSHOT_KEY] = build_role_summary(record, details_text, profile)
    record[RECORD_FIT_HIGHLIGHTS_KEY] = build_fit_highlights(record, details_text, profile)
    record[RECORD_SOFT_RISK_REASONS_KEY], record[RECORD_MISSING_EVIDENCE_KEY] = build_risk_and_missing_evidence(
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
        record[RECORD_MISSING_EVIDENCE_KEY],
        record[RECORD_SOFT_RISK_REASONS_KEY],
    )
    record["llm_learning_candidates"] = []
    record[RECORD_JOB_REQUIREMENTS_KEY] = []
    contextual_capability_matches: list = []

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
                _pipeline_log("LLM_CALL_DONE", record, call="job_requirements",
                              elapsed_ms=int((time.monotonic() - _t0) * 1000))
            except Exception as llm_exc:
                _pipeline_log("LLM_CALL_DONE", record, call="job_requirements", result="ERROR", error=type(llm_exc).__name__)
                print(f"[LLM][JOB_REQUIREMENTS_ERROR] {type(llm_exc).__name__}: {llm_exc}")
    else:
        _pipeline_log("LLM_CALL_START", record, call="fit_review")
        _t0 = time.monotonic()
        payload = resolve_llm_review_payload(record, llm_cache)
        _pipeline_log("LLM_CALL_DONE", record, call="fit_review",
                      elapsed_ms=int((time.monotonic() - _t0) * 1000),
                      payload_source=payload.get("payload_source", "llm"))
        review = payload["fit_review"]
        record["llm_learning_candidates"] = payload.get("learning_candidates") or []
        record[RECORD_JOB_REQUIREMENTS_KEY] = payload.get("job_requirements") or []
        contextual_capability_matches = payload.get("contextual_capability_matches") or []
        source = str(payload.get("payload_source") or "llm")

    return {
        "llm_decision": review["decision"],
        "llm_fit_grade": review["grade"],
        "review_source": source,
        "decision": "KEEP" if review["decision"] != "REJECT" else "REJECT",
        "contextual_capability_matches": contextual_capability_matches,
        RECORD_JOB_REQUIREMENTS_KEY: record[RECORD_JOB_REQUIREMENTS_KEY],
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

    title_analysis = analyze_title_filters(title, profile)
    ok_title = bool(title_analysis.get("ok"))
    title_reason = str(title_analysis.get("reason") or "")
    record[RECORD_TITLE_REASON_KEY] = title_reason
    record[RECORD_TITLE_MATCH_METADATA_KEY] = title_analysis
    _pipeline_log("TITLE_GATE", record, context.source_name, result="PASS" if ok_title else "REVIEW", reason=title_reason)
    if not ok_title:
        if title_reason == "TITLE_NOT_TARGET":
            # Downgraded gate: TITLE_NOT_TARGET alone is not a hard reject.
            # Consult O*NET to decide between a cheap skip (far occupation family)
            # and fetching the description (near or uncertain).
            onet = _onet_classify_title(title, profile)
            record[RECORD_ONET_CLASSIFICATION_KEY] = {
                "result": onet.result,
                "matched_occupation_code": onet.matched_occupation_code,
                "confidence": onet.confidence,
                "reason": onet.reason,
            }
            if onet.result == RESULT_FAR:
                reject_reason = "ONET_FAR_OCCUPATION"
                _pipeline_log("TITLE_GATE", record, context.source_name, result="REJECT", reason=reject_reason,
                              onet_code=onet.matched_occupation_code)
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
    _pipeline_log("CARD_GATE", record, context.source_name, result="PASS" if ok_card else "REJECT", reason=card_reason)
    if not ok_card:
        print(f"{source_tag} REJECTED (card gate) [{card_reason}] {title} @ {company}")
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = card_reason
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations, False

    history_entry = context.job_history.get(job_key, {})
    if can_reuse_kept_job(history_entry, record, profile):
        record = apply_kept_job_reuse(record, history_entry)
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
    details_status = str(record.get(RECORD_DETAILS_STATUS_KEY) or ("ok" if details_text else "empty"))

    ok, reason = _apply_detail_payload_to_record(record, details_text, details_status)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize(record, context)
        return _build_outcome(record), record, skill_observations

    _apply_source_metadata_to_record(record, details_text)
    _call_hook(hooks, "before_common_review", record, context)
    _call_hook(hooks, "after_description_loaded", record, context)

    ok, reason = _apply_content_filter_result(record, details_text, profile, title_reason)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize(record, context)
        print(f"{source_tag} REJECTED (content) [{reason}] {title} @ {company}")
        _pipeline_log("FINAL_DECISION", record, context.source_name, decision="REJECT", reason=reason)
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
        _pipeline_log("FINAL_DECISION", record, context.source_name, decision="REJECT", reason=reason)
        return _build_outcome(record), record, skill_observations

    skill_observations = _apply_learning_signal_enrichment(record, details_text, profile)

    _call_hook(hooks, "before_preference_filters", record, context)

    ok, reason = _apply_preference_result(record, profile, context)
    if not ok:
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = reason
        _finalize(record, context)
        _pipeline_log("FINAL_DECISION", record, context.source_name, decision="REJECT", reason=reason)
        return _build_outcome(record), record, skill_observations

    _call_hook(hooks, "after_preference_filters", record, context)

    _apply_fit_summary_enrichment(record, details_text, profile, title_reason)

    _call_hook(hooks, "before_llm_review", record, context)

    try:
        fit_eval = _evaluate_job_fit(record, profile, context.llm_cache)
    except Exception as llm_exc:
        print(f"{source_tag} [LLM][ERROR] {type(llm_exc).__name__}: {llm_exc} - {title} @ {company}")
        record[RECORD_DECISION_KEY] = "REJECT"
        record[RECORD_REJECT_REASON_KEY] = "LLM_ERROR"
        _finalize(record, context)
        _pipeline_log("FINAL_DECISION", record, context.source_name, decision="REJECT", reason="LLM_ERROR")
        return _build_outcome(record), record, skill_observations

    record.update(fit_eval)
    record[RECORD_CONTEXTUAL_CAPABILITY_MATCHES_KEY] = fit_eval.get("contextual_capability_matches") or []
    record[RECORD_JOB_REQUIREMENTS_KEY] = record.get(RECORD_JOB_REQUIREMENTS_KEY) or []

    if record[RECORD_DECISION_KEY] == "REJECT":
        print(f"{source_tag} REJECTED ({record['review_source']}) {title} @ {company}")
        record[RECORD_REJECT_REASON_KEY] = "LLM_REJECT" if record["review_source"] == "llm" else "DET_REJECT"
        register_pending_learning_signals(
            merge_pending_learning_signals(
                record.get("ad_learning_signals") or [],
                record.get("llm_learning_candidates") or [],
            )
        )
        _finalize(record, context)
        _pipeline_log("FINAL_DECISION", record, context.source_name, decision="REJECT",
                      reason=record[RECORD_REJECT_REASON_KEY], review_source=record.get("review_source", ""),
                      grade=record.get(RECORD_LLM_FIT_GRADE_KEY, ""))
        return _build_outcome(record), record, skill_observations

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
    _pipeline_log("FINAL_DECISION", record, context.source_name, decision="KEEP",
                  review_source=record.get("review_source", ""), grade=record.get(RECORD_LLM_FIT_GRADE_KEY, ""))
    return _build_outcome(record), record, skill_observations
