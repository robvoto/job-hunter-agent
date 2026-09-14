"""Helpers for source learning."""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


from job_hunter_agent.global_settings import get_llm_max_chars
from job_hunter_agent.hard_blocker_rules import (
    find_hard_block_matches,
    generalize_hard_block_pattern,
)
from job_hunter_agent.llm_gate import (
    build_llm_cache_key,
    build_posting_channel_cache_key,
    llm_classify_posting_channel,
    llm_is_enabled,
    llm_should_consider_learning_candidates,
    llm_should_consider_with_learning,
    normalize_llm_posting_channel,
    normalize_llm_review_payload,
)
from job_hunter_agent.logging_utils import format_log_block
from job_hunter_agent.profile_store import KEY_ROLE_EXPERIENCE, get_scoring_rules, load_profile
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    RECORD_REQUIREMENT_COVERAGE_HIDDEN_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_REASON_KEY,
    SOURCE_POSTER_COMPANY_INDUSTRY_KEY,
)
from job_hunter_agent.scoring_utils import (
    get_deterministic_review_thresholds,
)
from job_hunter_agent.signal_registry import (
    filter_registerable_signals,
    register_signals,
    signal_in_approved_knowledge,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_HARD_BLOCKER_PATTERN,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
)
from job_hunter_agent.text_processing import compact_whitespace
from job_hunter_agent.runtime_helpers import is_desktop_runtime
from job_hunter_agent.role_analysis import infer_posting_channel


_llm_truncation_count = 0


def get_llm_truncation_count() -> int:
    return _llm_truncation_count


def reset_llm_truncation_count() -> None:
    global _llm_truncation_count
    _llm_truncation_count = 0


def _is_location_fit_highlight(text: str) -> bool:
    cleaned = compact_whitespace(text).lower()
    return cleaned.startswith("location matches") or "location matches primary preference" in cleaned


def deterministic_review_outcome(
    record: dict,
    profile: dict,
    fit_highlights: list[str],
    missing_profile_support: list[str],
    soft_risk_reasons: list[str],
    missing_clearance_support: list[str] | None = None,
) -> Optional[dict]:

    title_reason = str(record.get(RECORD_TITLE_REASON_KEY) or "")

    strong_signal_count = len(
        [item for item in fit_highlights if item and not _is_location_fit_highlight(item)]
    )

    # A clearance/eligibility gap is still a hard-block risk for the purpose of the
    # cheap deterministic-KEEP shortcut, even though it's now displayed separately
    # from missing_profile_support — an unresolved clearance concern must still force
    # the full LLM review rather than being shortcut past silently.
    high_risks = len(missing_profile_support) + len(missing_clearance_support or [])

    medium_risks = len(soft_risk_reasons)

    scoring_rules = get_scoring_rules(profile)

    limits = get_deterministic_review_thresholds(scoring_rules)

    title = str(record.get(RECORD_TITLE_KEY) or "")

    def _log(rule: str, decision: str, grade: str) -> dict:

        logger.debug(
            format_log_block(
                "det-review",
                {
                    "decision": decision,
                    "grade": grade,
                    "via": rule,
                    "strong": strong_signal_count,
                    "high": high_risks,
                    "medium": medium_risks,
                    "title_reason": title_reason,
                    "title": title,
                },
            )
        )

        return {"decision": decision, "grade": grade, "det_rule": rule}

    # This shortcut is keep-candidate only. Weak or ambiguous roles must proceed
    # to full LLM review instead of being hard-rejected by heuristic scoring.
    if (
        title_reason == "OK"
        and strong_signal_count >= limits["min_strong_signals_for_strong_keep"]
        and high_risks == 0
    ):
        return _log("strong", "KEEP", "STRONG")

    if (
        title_reason == "OK"
        and strong_signal_count >= limits["min_strong_signals_for_solid_keep"]
        and high_risks == 0
        and medium_risks <= limits["max_medium_risks_for_solid_keep"]
    ):
        return _log("solid", "KEEP", "SOLID")

    return None


def register_hard_blocker_learning_from_rejection(
    record: dict,
    reject_reason: str,
    details_text: str = "",
    hard_block_matches: Optional[list[dict]] = None,
    profile: Optional[dict] = None,
    deferred_signals: Optional[list[dict[str, Any]]] = None,
) -> None:

    reason = compact_whitespace(reject_reason)

    if not reason:
        return
    if is_desktop_runtime():
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
                "original_texts": [compact_whitespace(original_text)]
                if compact_whitespace(original_text)
                else [],
            }
        )

    if prefix in {"DESC_HARD_BLOCK_RULE", "DESC_HARD_BLOCK"}:
        profile_terms = (profile or {}).get("must_not_require_skills", [])

        matches = hard_block_matches or find_hard_block_matches(details_text, profile_terms)

        for match in matches:
            term = str(match.get("matched_term") or "").replace("_", " ")

            pattern = (
                generalize_hard_block_pattern(details_text, term)
                or str(match.get("value") or "").strip()
            )

            add_signal(pattern, str(match.get("context") or details_text or reason))

    elif prefix == "LEARNED_REJECT" and detail:
        token = detail.split(":")[-1].strip()

        if token:
            pattern = generalize_hard_block_pattern(details_text, token.replace("_", " "))

            if pattern:
                add_signal(pattern, token.replace("_", " "))

    if signals:
        if deferred_signals is not None:
            deferred_signals.extend(signals)
        else:
            register_signals(signals)


def build_ad_learning_signals(
    record: dict,
    details_text: str,
    profile: Optional[dict] = None,
) -> list[dict[str, Any]]:

    pending: list[dict[str, Any]] = []

    seen: set[str] = set()

    def _add(
        signal_val: str,
        suggested_cat: str,
        original_texts: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:

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
                LEARNING_ORIGINAL_TEXTS_KEY: [
                    compact_whitespace(t) for t in original_texts if compact_whitespace(t)
                ],
                **(metadata or {}),
            }
        )

    for obs in record.get("skill_observations") or []:
        skill = compact_whitespace((obs.get("skill") or "") if isinstance(obs, dict) else "")

        if skill:
            _add(skill, CATEGORY_CAPABILITY_CONCEPT, [skill])

    # Deterministic pending capability_concept Signals from the fit-review
    # requirement decomposition: elements the LLM was unsure name a reusable
    # capability (capability_judgement="uncertain"), and mandatory non_capability
    # rows the normalizer could not resolve to a defensible reusable concept.
    # The LLM never names a signal category — this derivation is all deterministic.
    # See docs/REQUIREMENT_DECOMPOSITION_RATIONALE.md.
    # JH-298: RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY is deliberately NOT
    # merged in. Behavioural-expectation wording ("works autonomously",
    # "willingness to embrace AI") must never mint a pending capability_concept
    # signal; structural exclusion by omission is the guarantee.
    coverage_rows = [
        *(record.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []),
        *(record.get(RECORD_REQUIREMENT_COVERAGE_HIDDEN_KEY) or []),
    ]
    for row in coverage_rows:
        if not isinstance(row, dict):
            continue
        row_job_text = compact_whitespace(row.get("matched_job_text") or "")
        decomposition = row.get("decomposition")
        decomposition = decomposition if isinstance(decomposition, dict) else {}
        operator = compact_whitespace(decomposition.get("operator") or "")
        elements = decomposition.get("elements") or []
        mandatory_unresolved = bool(row.get("mandatory_non_capability_unresolved"))

        # A mandatory AND/OR requirement the normalizer could not resolve to any
        # safe single capability becomes ONE pending capability_concept Signal
        # that keeps every branch and the relationship word — never one
        # misleading capability minted from a single branch.
        if mandatory_unresolved and operator in ("and", "or"):
            branch_labels: list[str] = []
            branch_texts: list[str] = []
            for element in elements:
                if not isinstance(element, dict):
                    continue
                concept = compact_whitespace(element.get("canonical_concept") or "")
                element_text = compact_whitespace(element.get("text") or "")
                label = concept or element_text
                if label:
                    branch_labels.append(label)
                if element_text:
                    branch_texts.append(element_text)
            if branch_labels:
                _add(
                    f" {operator} ".join(branch_labels),
                    CATEGORY_CAPABILITY_CONCEPT,
                    [*branch_texts, row_job_text],
                )
            continue

        for element in elements:
            if not isinstance(element, dict):
                continue
            judgement = compact_whitespace(element.get("capability_judgement") or "")
            concept = compact_whitespace(element.get("canonical_concept") or "")
            element_text = compact_whitespace(element.get("text") or "")
            candidate = concept or element_text
            if not candidate:
                continue
            if judgement == "uncertain":
                _add(
                    candidate,
                    CATEGORY_CAPABILITY_CONCEPT,
                    [element_text or candidate, row_job_text],
                )
            elif judgement == "non_capability" and mandatory_unresolved:
                _add(
                    candidate,
                    CATEGORY_CAPABILITY_CONCEPT,
                    [element_text or candidate, row_job_text],
                )

    return pending


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
    if is_desktop_runtime():
        return

    filtered = filter_registerable_signals(signals)

    if filtered:
        register_signals(filtered)


def _fit_review_source_context(record: dict) -> list[str]:
    """Return factual publisher context for posting-channel interpretation.

    These lines describe source metadata only; they do not decide whether the
    publisher is the employer or an agency. That semantic decision stays with
    the posting-channel LLM contract.
    """
    company = compact_whitespace(record.get(RECORD_COMPANY_KEY) or "")
    metadata = record.get(RECORD_SOURCE_METADATA_KEY)
    metadata = metadata if isinstance(metadata, dict) else {}
    poster_company = compact_whitespace(metadata.get("poster_company") or "")
    hiring_company = compact_whitespace(metadata.get("hiring_company") or "")
    poster_industry = compact_whitespace(metadata.get(SOURCE_POSTER_COMPANY_INDUSTRY_KEY) or "")

    lines: list[str] = []
    if company:
        lines.append(f"Source-listed company/advertiser: {company}")
    if poster_company and poster_company != company:
        lines.append(f"Source-listed poster company: {poster_company}")
    if poster_industry:
        lines.append(f"Source-listed poster industry: {poster_industry}")
    if hiring_company:
        lines.append(f"Source-listed explicit hiring company: {hiring_company}")
    return lines


def _posting_channel_review_input(record: dict) -> str:
    """Build bounded source-only input without candidate-profile content."""
    title_text = str(record.get(RECORD_TITLE_KEY) or "").strip()
    body_text = str(
        record.get(RECORD_FIT_SOURCE_TEXT_KEY) or record.get(RECORD_FULL_DESCRIPTION_KEY) or ""
    ).strip()
    source_text = "\n".join(
        part for part in [title_text, *_fit_review_source_context(record), body_text] if part
    )
    return source_text[: get_llm_max_chars()]


def _merge_fresh_llm_usage(payload: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    """Add only usage from a provider call made during this resolution."""
    merged = dict(payload)
    if usage.get(RECORD_LLM_INPUT_TOKENS_KEY) not in (None, ""):
        merged[RECORD_LLM_INPUT_TOKENS_KEY] = int(merged.get(RECORD_LLM_INPUT_TOKENS_KEY) or 0) + int(
            usage[RECORD_LLM_INPUT_TOKENS_KEY]
        )
    if usage.get(RECORD_LLM_OUTPUT_TOKENS_KEY) not in (None, ""):
        merged[RECORD_LLM_OUTPUT_TOKENS_KEY] = int(merged.get(RECORD_LLM_OUTPUT_TOKENS_KEY) or 0) + int(
            usage[RECORD_LLM_OUTPUT_TOKENS_KEY]
        )
    if usage.get(RECORD_LLM_COST_USD_KEY) not in (None, ""):
        merged[RECORD_LLM_COST_USD_KEY] = round(
            float(merged.get(RECORD_LLM_COST_USD_KEY) or 0) + float(usage[RECORD_LLM_COST_USD_KEY]),
            6,
        )
    return merged


def _resolve_unresolved_posting_channel(
    record: dict,
    payload: dict[str, Any],
    llm_cache: dict,
) -> dict[str, Any]:
    """Run the posting-only LLM only when current evidence is still unresolved."""
    combined_signal = payload.get("posting_channel")
    if not isinstance(combined_signal, dict):
        return payload
    if str(combined_signal.get("kind") or "").strip().lower() != "unknown":
        return payload
    if infer_posting_channel(record, combined_signal).get("kind") != "unknown":
        return payload

    posting_input = _posting_channel_review_input(record)
    if not posting_input:
        return payload

    posting_fp = build_posting_channel_cache_key(posting_input)
    cached_posting = llm_cache.get(posting_fp)
    if isinstance(cached_posting, dict):
        dedicated_signal = normalize_llm_posting_channel(cached_posting)
        logger.debug(
            "[POSTING_CHANNEL][FALLBACK] job_key=%s cache=HIT kind=%s",
            str(record.get(RECORD_JOB_KEY) or "unknown"),
            dedicated_signal.get("kind"),
        )
    else:
        logger.debug(
            "[POSTING_CHANNEL][FALLBACK] job_key=%s cache=MISS",
            str(record.get(RECORD_JOB_KEY) or "unknown"),
        )
        dedicated_result = llm_classify_posting_channel(posting_input)
        if dedicated_result is None:
            logger.warning(
                "[POSTING_CHANNEL][FALLBACK] job_key=%s dedicated classification failed; "
                "leaving source unresolved",
                str(record.get(RECORD_JOB_KEY) or "unknown"),
            )
            return payload
        dedicated_signal = normalize_llm_posting_channel(dedicated_result)
        llm_cache[posting_fp] = dedicated_signal
        payload = _merge_fresh_llm_usage(payload, dedicated_result)

    return {**payload, "posting_channel": dedicated_signal}


def resolve_llm_review_payload(
    record: dict,
    llm_cache: dict,
    *,
    profile: dict | None = None,
    learning_only: bool = False,
) -> dict[str, Any]:
    """Build and resolve the bounded LLM review payload for one normalized job.

    Fit review includes board-supplied company identity for posting-channel
    classification; learning-only mode deliberately excludes that identity.
    """

    job_key = str(record.get(RECORD_JOB_KEY) or "unknown")

    title = str(record.get(RECORD_TITLE_KEY) or "")

    company = str(record.get(RECORD_COMPANY_KEY) or "")

    source = str(record.get("source") or "")

    call_type = "learning_only" if learning_only else "fit_review"

    title_text = str(record.get(RECORD_TITLE_KEY) or "").strip()

    # fit_source_text holds the compacted description (set by _apply_detail_payload_to_record).
    # Fall back to full_description for records that predate compaction.
    body_text = (
        record.get(RECORD_FIT_SOURCE_TEXT_KEY) or record.get(RECORD_FULL_DESCRIPTION_KEY) or ""
    )

    # Fit review gets canonical source facts as context for posting-channel
    # interpretation. Learning-only calls remain title/description-only so source
    # identity cannot become a learned requirement or candidate capability.
    source_context = [] if learning_only else _fit_review_source_context(record)
    llm_input_text = "\n".join(
        part for part in [title_text, *source_context, str(body_text).strip()] if part
    )

    max_llm_chars = get_llm_max_chars()

    description_chars_fetched = len(str(body_text).strip())

    truncated_input = llm_input_text[:max_llm_chars]

    description_chars_sent = len(truncated_input)

    truncation_applied = len(llm_input_text) > max_llm_chars

    if truncation_applied:
        global _llm_truncation_count
        _llm_truncation_count += 1

    llm_fp = build_llm_cache_key(truncated_input)

    cached = (
        normalize_llm_review_payload(
            llm_cache.get(llm_fp),
            role_experience=(profile or load_profile()).get(KEY_ROLE_EXPERIENCE, []),
        )
        if llm_fp in llm_cache
        else None
    )

    if cached:
        if learning_only and cached.get("learning_candidates"):
            logger.debug(
                "[REVIEW][PAYLOAD] source=%s job_key=%s title=%r company=%r mode=%s cache=HIT",
                source,
                job_key,
                title,
                company,
                call_type,
            )

            return {**cached, "payload_source": "cache"}

        if not learning_only and cached.get("fit_review"):
            logger.debug(
                "[REVIEW][PAYLOAD] source=%s job_key=%s title=%r company=%r mode=%s cache=HIT",
                source,
                job_key,
                title,
                company,
                call_type,
            )
            raw_cached = llm_cache.get(llm_fp)
            resolved_cached = (
                _resolve_unresolved_posting_channel(record, cached, llm_cache)
                if isinstance(raw_cached, dict) and "posting_channel" in raw_cached
                else cached
            )
            if resolved_cached.get("posting_channel") != cached.get("posting_channel"):
                llm_cache[llm_fp] = {
                    **llm_cache[llm_fp],
                    "posting_channel": resolved_cached.get("posting_channel"),
                }
            return {**resolved_cached, "payload_source": "cache"}

    if not llm_is_enabled():
        raise RuntimeError("LLM review requested but no provider key is configured")

    logger.debug(
        "[REVIEW][PAYLOAD] source=%s job_key=%s title=%r company=%r mode=%s cache=MISS"
        " description_chars_fetched=%d description_chars_sent_to_llm=%d truncation_applied=%s",
        source,
        job_key,
        title,
        company,
        call_type,
        description_chars_fetched,
        description_chars_sent,
        str(truncation_applied).lower(),
    )
    if truncation_applied:
        logger.warning(
            "[REVIEW][TRUNCATION] source=%s job_key=%s truncated %d → %d chars (limit=%d)",
            source,
            job_key,
            len(llm_input_text),
            description_chars_sent,
            max_llm_chars,
        )

    if learning_only:
        payload = {
            "fit_review": None,
            "learning_candidates": llm_should_consider_learning_candidates(truncated_input),
        }

    else:
        payload = llm_should_consider_with_learning(truncated_input)
        payload = _resolve_unresolved_posting_channel(record, payload, llm_cache)

    # Persist the freshly computed payload so later equivalent jobs (same
    # profile fingerprint + description) hit the cache instead of paying for
    # another LLM call. Merge over any stale/partial cached entry rather than
    # discarding it outright.
    llm_cache[llm_fp] = {**(cached or {}), **payload}

    payload["payload_source"] = "llm"

    return payload
