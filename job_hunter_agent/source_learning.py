from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

from job_hunter_agent.hard_blocker_rules import find_hard_block_matches, generalize_hard_block_pattern
from job_hunter_agent.llm_gate import (
    build_llm_cache_key,
    llm_is_enabled,
    llm_should_consider_learning_candidates,
    llm_should_consider_with_learning,
    normalize_llm_review_payload,
)
from job_hunter_agent.profile_store import get_scoring_rules
from job_hunter_agent.scoring_utils import (
    get_deterministic_review_thresholds,
)
from job_hunter_agent.profile_learning import build_role_title_review_token
from job_hunter_agent.record_schema import (
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_REASON_KEY,
)
from job_hunter_agent.signal_detection import _extract_government_context_learning_signals
from job_hunter_agent.signal_registry import (
    filter_registerable_signals,
    register_signals,
    signal_in_approved_knowledge,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_GOVERNMENT_CONTEXT,
    CATEGORY_HARD_BLOCKER_PATTERN,
    CATEGORY_ROLE_TITLE_TOKEN,
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE,
    CATEGORY_TITLE_PARSE_BLOCKER,
    LEARNING_CATEGORY_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    TITLE_REASON_POTENTIAL_MATCH,
)
from job_hunter_agent.title_normalization_rules import classify_title_normalization_candidate
from job_hunter_agent.text_processing import compact_whitespace
from job_hunter_agent.global_settings import get_llm_max_chars


def deterministic_review_outcome(
    record: dict, 
    profile: dict, 
    fit_highlights: list[str], 
    missing_evidence: list[str], 
    soft_risk_reasons: list[str]
) -> Optional[dict]:
    title_reason = str(record.get(RECORD_TITLE_REASON_KEY) or "")
    strong_signal_count = len([item for item in fit_highlights if item])
    high_risks = len(missing_evidence)
    medium_risks = len(soft_risk_reasons)
    
    scoring_rules = get_scoring_rules(profile)
    limits = get_deterministic_review_thresholds(scoring_rules)

    title = str(record.get(RECORD_TITLE_KEY) or "")

    def _log(rule: str, decision: str, grade: str) -> dict:
        logger.info(
            "[det-review] %s/%s\n"
            "  via=%s\n"
            "  strong=%d high=%d medium=%d\n"
            "  title_reason=%s\n"
            "  %s",
            decision,
            grade,
            rule,
            strong_signal_count,
            high_risks,
            medium_risks,
            title_reason,
            title,
        )
        return {"decision": decision, "grade": grade, "det_rule": rule}

    if high_risks >= limits["min_high_risks_for_mismatch"] and strong_signal_count <= limits["max_strong_signals_for_mismatch"]:
        return _log("mismatch", "REJECT", "MISMATCH")
    if title_reason == TITLE_REASON_POTENTIAL_MATCH and high_risks >= limits["min_high_risks_for_poor"] and strong_signal_count <= limits["max_strong_signals_for_poor"]:
        return _log("poor_potential", "REJECT", "POOR")
    if title_reason == "OK" and strong_signal_count >= limits["min_strong_signals_for_strong_keep"] and high_risks == 0:
        return _log("strong", "KEEP", "STRONG")
    if title_reason == "OK" and strong_signal_count >= limits["min_strong_signals_for_solid_keep"] and high_risks == 0 and medium_risks <= limits["max_medium_risks_for_solid_keep"]:
        return _log("solid", "KEEP", "SOLID")
    return None


def register_hard_blocker_learning_from_rejection(
    record: dict,
    reject_reason: str,
    details_text: str = "",
    hard_block_matches: Optional[list[dict]] = None,
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


def build_ad_learning_signals(
    record: dict,
    details_text: str,
    profile: Optional[dict] = None,
) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(signal_val: str, suggested_cat: str, original_texts: list[str]) -> None:
        key = compact_whitespace(signal_val or "").lower()
        if not key or key in seen:
            return
        known, _ = signal_in_approved_knowledge(suggested_cat, key)
        if known:
            return
        seen.add(key)
        pending.append(
            {
                LEARNING_SIGNAL_KEY: compact_whitespace(signal_val),
                LEARNING_SUGGESTED_CATEGORY_KEY: suggested_cat,
                LEARNING_ORIGINAL_TEXTS_KEY: [compact_whitespace(t) for t in original_texts if compact_whitespace(t)],
            }
        )

    for obs in (record.get("skill_observations") or []):
        skill = compact_whitespace((obs.get("skill") or "") if isinstance(obs, dict) else "")
        if skill:
            _add(skill, CATEGORY_CAPABILITY_CONCEPT, [skill])

    gov_record = dict(record)
    if details_text and not gov_record.get(RECORD_FULL_DESCRIPTION_KEY):
        gov_record[RECORD_FULL_DESCRIPTION_KEY] = details_text
    for item in _extract_government_context_learning_signals(gov_record):
        sig = compact_whitespace(item.get(LEARNING_SIGNAL_KEY) or "")
        texts = item.get(LEARNING_ORIGINAL_TEXTS_KEY) or [sig]
        if sig:
            key = sig.lower()
            if key not in seen:
                seen.add(key)
                pending.append(
                    {
                        LEARNING_SIGNAL_KEY: sig,
                        LEARNING_SUGGESTED_CATEGORY_KEY: item.get(LEARNING_CATEGORY_KEY) or CATEGORY_GOVERNMENT_CONTEXT,
                        LEARNING_ORIGINAL_TEXTS_KEY: [compact_whitespace(t) for t in texts if compact_whitespace(t)],
                    }
                )

    title = compact_whitespace(record.get("title") or "")
    title_reason = compact_whitespace(record.get("title_reason") or "").upper()
    if title:
        if title_reason == TITLE_REASON_POTENTIAL_MATCH:
            token = build_role_title_review_token(title)
            if token:
                _add(token, CATEGORY_ROLE_TITLE_TOKEN, [title])
        else:
            candidate = classify_title_normalization_candidate(title)
            if candidate:
                cand_val = compact_whitespace(candidate.get("value") or "")
                if cand_val:
                    _add(cand_val, CATEGORY_TITLE_NORMALIZATION_CANDIDATE, candidate.get("evidence") or [title])

    return pending


def has_high_value_ambiguous_learning_candidate(signals: list[dict[str, Any]]) -> bool:
    interesting_categories = {
        CATEGORY_ROLE_TITLE_TOKEN,
        CATEGORY_TITLE_NORMALIZATION_CANDIDATE,
        CATEGORY_TITLE_PARSE_BLOCKER,
    }
    for signal in signals or []:
        if not isinstance(signal, dict):
            continue
        category = compact_whitespace(signal.get("suggested_category") or signal.get(LEARNING_CATEGORY_KEY) or "").lower()
        if category in interesting_categories:
            return True
    return False


def merge_pending_learning_signals(*signal_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def register_pending_learning_signals(signals: list[dict[str, Any]]) -> None:
    filtered = filter_registerable_signals(signals)
    if filtered:
        register_signals(filtered)


def resolve_llm_review_payload(
    record: dict,
    llm_cache: dict,
    *,
    learning_only: bool = False,
) -> dict[str, Any]:
    title_text = str(record.get(RECORD_TITLE_KEY) or "").strip()
    body_text = record.get(RECORD_FULL_DESCRIPTION_KEY) or record.get(RECORD_FIT_SOURCE_TEXT_KEY) or ""
    llm_input_text = "\n".join(part for part in [title_text, str(body_text).strip()] if part)
    max_llm_chars = get_llm_max_chars()
    llm_fp = build_llm_cache_key(llm_input_text[:max_llm_chars])
    cached = normalize_llm_review_payload(llm_cache.get(llm_fp)) if llm_fp in llm_cache else None

    if cached:
        if learning_only and cached.get("learning_candidates"):
            return {**cached, "payload_source": "cache"}
        if not learning_only and cached.get("fit_review"):
            return {**cached, "payload_source": "cache"}

    if not llm_is_enabled():
        raise RuntimeError("LLM review requested but OPENAI_API_KEY is missing")

    if learning_only:
        payload = {"fit_review": None, "learning_candidates": llm_should_consider_learning_candidates(llm_input_text[:max_llm_chars])}
    else:
        payload = llm_should_consider_with_learning(llm_input_text[:max_llm_chars])

    if cached:
        merged = dict(cached)
        if payload.get("fit_review"):
            merged["fit_review"] = payload["fit_review"]
        if payload.get("learning_candidates"):
            merged["learning_candidates"] = payload["learning_candidates"]
        if payload.get("contextual_capability_matches") is not None:
            merged["contextual_capability_matches"] = payload["contextual_capability_matches"]
        merged["payload_source"] = "cache+llm"
        return merged

    payload["payload_source"] = "llm"
    return payload

