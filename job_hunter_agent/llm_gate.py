"""LLM fit-decision gateway.

This module provides a gateway for interacting with Large Language Models (LLMs)
to perform various job-hunting related tasks. It handles the construction of
LLM prompts, caching of LLM responses, and normalization of LLM outputs.

Key functionalities include:
- Building compact candidate context for LLM prompts.
- Requesting constrained decisions and graded description-fit tiers from LLMs.
- Maintaining prompt structure and cache keys aligned with the current profile state.
- Extracting job requirements and suggesting rejection blockers.
- Naming capability clusters and classifying CV section labels.

It ensures that deterministic filters are applied before LLM processing and
prioritizes AI fit briefs over raw background text to optimize cost and reduce noise.
Error handling is implemented to catch and report exceptions during LLM interactions,
preventing silent failures and aiding in debugging.

"""

from __future__ import annotations

import os
import hashlib
import json as _json_mod
import logging
import re
import sys
from typing import Any, Dict

from openai import APIStatusError, APITimeoutError, OpenAI
from pydantic import BaseModel, Field, ValidationError

from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.global_settings import (
    KEY_LLM_PRICING_PER_1M,
    KEY_LLM_PROMPT_EVIDENCE_TIERS,
    KEY_LLM_PROMPT_SETTINGS,
    KEY_LLM_PROMPT_TEMPLATES,
    KEY_LLM_SETTINGS,
    get_llm_capability_naming_aliases_max_items,
    get_llm_capability_naming_max_output_tokens,
    get_llm_capability_rule_aliases_max_items,
    get_llm_capability_rules_max_items,
    get_llm_fit_decision_max_output_tokens,
    get_llm_job_description_max_chars,
    get_llm_job_requirements_max_items,
    get_llm_job_requirements_max_output_tokens,
    get_llm_learning_candidates_max_items,
    get_llm_learning_candidates_max_output_tokens,
    get_llm_max_chars,
    get_llm_profile_brief_max_chars,
    get_llm_raw_output_log_max_chars,
    get_llm_rejection_blocker_suggestions_max_items,
    get_llm_rejection_blocker_suggestions_max_output_tokens,
    get_llm_rejection_blocker_suggestions_max_words,
    get_llm_title_judgment_max_output_tokens,
    load_global_settings,
)
from job_hunter_agent.hard_blocker_rules import (
    normalize_rejection_blocker_suggestions as _normalize_rejection_blocker_suggestions,
)
from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_COVERAGE_IMPORTANCES,
    LLM_ALLOWED_DECISIONS,
    LLM_ALLOWED_GRADES,
    LLM_ALLOWED_TITLE_JUDGMENT_VERDICTS,
    LLM_FIT_REVIEW_PROMPT_SHAPE,
    LLM_JOB_REQUIREMENTS_PROMPT_SHAPE,
    LLM_LEARNING_ONLY_PROMPT_SHAPE,
    LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER,
    LLM_PROMPT_CAPABILITY_LEVELS_HEADER,
    LLM_PROMPT_CAPABILITY_NAMING_INTRO,
    LLM_PROMPT_CLUSTERS_HEADER,
    LLM_PROMPT_DEBUG_REASON_INTRO,
    LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER,
    LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER,
    LLM_PROMPT_DO_NOT_INVENT,
    LLM_PROMPT_DO_NOT_SAVE,
    LLM_PROMPT_FIT_REVIEW_ONLY_INTRO,
    LLM_PROMPT_JOB_DESCRIPTION_PREFIX,
    LLM_PROMPT_JSON_ONLY,
    LLM_PROMPT_LEARNING_PENDING_ONLY,
    LLM_PROMPT_MATCH_PREFERENCES_HEADER,
    LLM_PROMPT_NO_FIT_DECISION_REQUIRED,
    LLM_PROMPT_SYSTEM_REVIEW_INTRO,
    LLM_PROMPT_USE_VISIBLE_STRINGS,
    LLM_REJECTION_SUGGESTIONS_JSON_SHAPE,
    LLM_SECTION_LABEL_CLASSIFICATION_SHAPE,
    LLM_TITLE_JUDGMENT_SHAPE,
)
from job_hunter_agent.paths import LLM_COSTS_PATH as _LLM_COSTS_PATH
from job_hunter_agent.runtime_helpers import is_desktop_runtime

# Import at module level to allow monkeypatching in tests
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_CAPABILITIES,
    get_candidate_profile_tier_weights,
    get_candidate_profile_tiers,
    load_profile,
)
from job_hunter_agent.runtime_helpers import (
    CLI_FLAG_NO_LLM,
    append_llm_cost_log,
    build_llm_cost_entry,
    has_cli_flag,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_HARD_BLOCKER_PATTERN,
    LEARNING_CONFIDENCE_KEY,
    LEARNING_CONTEXT_TERMS_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_SUGGESTED_VALUES_KEY,
    PATTERN_SIGNAL_CATEGORIES,
    VALID_SIGNAL_CATEGORIES,
)
from job_hunter_agent.text_processing import compact_whitespace
from job_hunter_agent.user_settings import DEFAULT_USER_SETTINGS, load_user_settings

logger = logging.getLogger(__name__)

_NO_LLM_MODE = has_cli_flag(sys.argv, CLI_FLAG_NO_LLM)

MODEL_FALLBACK = DEFAULT_USER_SETTINGS["llm"]["model"]


_profile_fingerprint_cache: str | None = None

# Cost logging --------------------------------------------------------
_session_cost_usd: float = 0.0


def _get_llm_pricing_per_1m() -> dict[str, dict[str, float]]:
    pricing = load_global_settings().get(KEY_LLM_SETTINGS, {}).get(KEY_LLM_PRICING_PER_1M, {})
    if not isinstance(pricing, dict) or not pricing:
        raise ValueError("No LLM pricing is configured in Admin.")
    return pricing  # type: ignore[return-value]


def _get_llm_pricing_token_unit_divisor() -> int:
    llm_settings = load_global_settings().get(KEY_LLM_SETTINGS, {})
    if not isinstance(llm_settings, dict):
        raise ValueError("LLM settings must be configured in Admin.")
    metadata = llm_settings.get("pricing_metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("LLM pricing metadata must be configured in Admin.")
    unit = str(metadata.get("unit") or "").strip().lower()
    if unit in {"per_1m_tokens", "per_million_tokens", "per_1000000_tokens"}:
        return 1_000_000
    if unit in {"per_1k_tokens", "per_thousand_tokens", "per_1000_tokens"}:
        return 1_000
    raise ValueError(
        "Unsupported LLM pricing unit. Configure llm_settings.pricing_metadata.unit as "
        "'per_1m_tokens' or 'per_1k_tokens'."
    )


def _calculate_llm_cost_usd(tok_in: int, tok_out: int, prices: dict[str, float]) -> float:
    divisor = _get_llm_pricing_token_unit_divisor()
    if "input" not in prices or "output" not in prices:
        raise ValueError("LLM pricing for selected model must include input and output prices.")
    return (tok_in * prices["input"] + tok_out * prices["output"]) / divisor


def _get_llm_prompt_settings() -> dict[str, Any]:
    prompt_settings = (
        load_global_settings().get(KEY_LLM_SETTINGS, {}).get(KEY_LLM_PROMPT_SETTINGS, {})
    )
    if not isinstance(prompt_settings, dict) or not prompt_settings:
        raise ValueError("No LLM prompt settings are configured in Admin.")
    return prompt_settings


def _log_llm_call(resp: Any, purpose: str, model: str) -> None:
    global _session_cost_usd
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    # Responses API uses input_tokens/output_tokens; Chat uses prompt_tokens/completion_tokens
    tok_in = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0
    tok_out = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0
    prices = _get_llm_pricing_per_1m()[model]
    cost = _calculate_llm_cost_usd(tok_in, tok_out, prices)
    _session_cost_usd += cost

    entry = build_llm_cost_entry(
        purpose=purpose,
        model=model,
        tok_in=tok_in,
        tok_out=tok_out,
        cost_usd=cost,
        session_usd=_session_cost_usd,
    )
    append_llm_cost_log(_LLM_COSTS_PATH, entry)
    if DEBUG_MODE:
        logger.info(
            "[LLM][COST] purpose=%s model=%s input_tokens=%d output_tokens=%d call_cost_usd=%.6f session_cost_usd=%.6f",
            purpose,
            model,
            tok_in,
            tok_out,
            cost,
            _session_cost_usd,
        )
    else:
        logger.info(
            "[LLM] %-30s  $%.4f  (%d in + %d out tokens)  session: $%.4f",
            purpose,
            cost,
            tok_in,
            tok_out,
            _session_cost_usd,
        )


def get_session_cost_usd() -> float:
    return round(_session_cost_usd, 6)


def reset_session_cost() -> None:
    global _session_cost_usd
    _session_cost_usd = 0.0


def _profile_fingerprint() -> str:
    """Cheap fingerprint of the profile row - updated_at from DB.
    Cached for the lifetime of the process so repeated cache-key lookups in a
    single scraping run are O(1) after the first call.
    """
    global _profile_fingerprint_cache
    if _profile_fingerprint_cache is not None:
        return _profile_fingerprint_cache
    try:
        from job_hunter_agent.database import db_conn
        from job_hunter_agent.paths import get_active_user_id

        user_id = get_active_user_id()
        with db_conn() as conn:
            row = conn.execute(
                "SELECT updated_at FROM user_profile WHERE user_id = ?", (user_id,)
            ).fetchone()
        raw = row["updated_at"] if row else "no-profile"
    except Exception:
        raw = "no-profile"
    _profile_fingerprint_cache = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return _profile_fingerprint_cache


def get_llm_model() -> str:
    """Return the configured model, falling back to MODEL_FALLBACK."""
    return load_user_settings(None).get("llm", {}).get("model", MODEL_FALLBACK)


_llm_model_logged = False


def _log_llm_model_once() -> str:
    """Print the active model to the terminal on first use. Returns the model string."""
    global _llm_model_logged
    model = get_llm_model()
    if not _llm_model_logged:
        logger.info("[LLM][MODEL] using model=%s (source=user settings)", model)
        _llm_model_logged = True
    return model


class _LLMLearningCandidate(BaseModel):
    signal: str
    suggested_category: str
    suggested_values: list[str] = Field(default_factory=list)
    context_terms: list[str] = Field(default_factory=list)
    confidence: str = ""
    needs_review: bool = True
    original_texts: list[str] = Field(default_factory=list)


class _LLMReviewDecision(BaseModel):
    decision: str
    grade: str


class _LLMRequirementCoverageItem(BaseModel):
    requirement: str
    importance: str = "preferred"
    status: str
    capability_name: str = ""
    matched_job_text: str = ""
    profile_support: list[str] = Field(default_factory=list)


class _LLMJobRequirementsPayload(BaseModel):
    job_requirements: list[str] = Field(default_factory=list)


class _LLMReviewPayload(BaseModel):
    fit_review: _LLMReviewDecision | None = None
    learning_candidates: list[_LLMLearningCandidate] = Field(default_factory=list)


class _LLMFitReviewPayload(BaseModel):
    fit_review: _LLMReviewDecision
    debug_reason: str = ""
    requirement_coverage: list[_LLMRequirementCoverageItem] = Field(default_factory=list)
    job_requirements: list[str] = Field(default_factory=list)


class LLMCallError(RuntimeError):
    """LLM API call failed. Carries metadata for structured pipeline logging."""

    def __init__(
        self,
        message: str,
        *,
        purpose: str,
        model: str,
        status_code: int | None = None,
        is_timeout: bool = False,
    ) -> None:
        super().__init__(message)
        self.purpose = purpose
        self.model = model
        self.status_code = status_code
        self.is_timeout = is_timeout


class LLMReviewValidationError(ValueError):
    """LLM review payload failed required fit-review invariants."""


def _is_retryable_llm_payload_error(exc: Exception) -> bool:
    if isinstance(exc, ValidationError):
        return True
    message = str(exc).lower()
    return "json_invalid" in message or "invalid json" in message or "eof while parsing" in message


def _build_openai_client() -> OpenAI | None:
    """Return the configured LLM client.

    Desktop runtime intentionally stays offline. Normal server/runtime entrypoints
    load `.env` before importing this module, so a configured OPENAI_API_KEY is
    available here without relying on ad hoc shell state.
    """
    if is_desktop_runtime():
        return None

    api_key = str(os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    return OpenAI(api_key=api_key)


client = _build_openai_client()
ALLOWED_LEARNING_CATEGORIES = frozenset(VALID_SIGNAL_CATEGORIES - {CATEGORY_HARD_BLOCKER_PATTERN})


def _load_managed_prompt_lines(key: str) -> tuple[str, ...]:
    from job_hunter_agent.knowledge_store import get_knowledge

    payload = get_knowledge(key)
    if payload is None:
        raise RuntimeError(f"Knowledge '{key}' not found in knowledge table — seed the DB first")
    lines = payload.get("lines")
    if not isinstance(lines, list):
        raise ValueError(f"Knowledge '{key}' must contain a lines list")
    cleaned = tuple(str(line).strip() for line in lines if str(line).strip())
    if not cleaned:
        raise ValueError(f"Knowledge '{key}' must define at least one prompt line")
    return cleaned


FIT_REVIEW_DEFAULT_LINES = _load_managed_prompt_lines("llm_fit_review_defaults")
CAPABILITY_NAMING_DEFAULT_LINES = _load_managed_prompt_lines("llm_capability_naming_defaults")
JOB_REQUIREMENTS_DEFAULT_LINES = _load_managed_prompt_lines("llm_job_requirements_defaults")
LEARNING_DEFAULT_LINES = _load_managed_prompt_lines("llm_learning_defaults")
REJECTION_SUGGESTIONS_DEFAULT_LINES = _load_managed_prompt_lines(
    "llm_rejection_suggestions_defaults"
)
REQUIREMENT_COVERAGE_DEFAULT_LINES = _load_managed_prompt_lines("llm_requirement_coverage_defaults")
FIT_REVIEW_GRADE_DEFAULT_LINES = _load_managed_prompt_lines("llm_fit_review_grade_defaults")


def llm_is_enabled() -> bool:
    return client is not None


def build_profile_prompt_context() -> str:
    from job_hunter_agent.profile_store import (
        KEY_CANDIDATE_CAPABILITIES,
        KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
    )

    profile = load_profile()
    llm_profile_brief = str(profile.get("llm_profile_brief") or "").strip()
    star_evidence_text = str(profile.get("star_evidence_text") or "").strip()
    evidence_tiers = get_candidate_profile_tiers(profile)
    evidence_weights = get_candidate_profile_tier_weights(profile)
    prompt_settings = _get_llm_prompt_settings()
    prompt_templates = prompt_settings[KEY_LLM_PROMPT_TEMPLATES]
    prompt_evidence_tiers = prompt_settings[KEY_LLM_PROMPT_EVIDENCE_TIERS]
    capability_rules = profile.get(KEY_CANDIDATE_CAPABILITIES, [])
    salary_preferences = profile.get("salary_preferences", {})
    match_preferences = (
        profile.get("match_preferences", {})
        if isinstance(profile.get("match_preferences", {}), dict)
        else {}
    )

    parts = []
    if llm_profile_brief:
        parts.append(LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER)
        parts.append(llm_profile_brief[: get_llm_profile_brief_max_chars()])

    if isinstance(capability_rules, list) and capability_rules:
        parts.append(LLM_PROMPT_CAPABILITY_LEVELS_HEADER)
        for rule in capability_rules[: get_llm_capability_rules_max_items()]:
            if not isinstance(rule, dict):
                continue
            name = str(rule.get("name") or "").strip()
            level = str(rule.get("level") or "").strip()
            fit = str(rule.get("fit") or "").strip()
            raw_aliases = rule.get("aliases", [])
            aliases_list = raw_aliases if isinstance(raw_aliases, list) else []
            aliases = ", ".join(
                str(alias).strip()
                for alias in aliases_list[: get_llm_capability_rule_aliases_max_items()]
                if str(alias).strip()
            )
            if name and level:
                label = f"- {name}: {level}"
                if fit:
                    label += f", {fit}"
                if aliases:
                    label += f" ({aliases})"
                parts.append(label)

    minimum_salary_yearly = int(salary_preferences.get("minimum_salary_yearly", 0) or 0)
    minimum_daily_rate = int(salary_preferences.get("minimum_daily_rate", 0) or 0)
    preference_lines = []
    if minimum_salary_yearly > 0 or minimum_daily_rate > 0:
        if minimum_salary_yearly > 0:
            preference_lines.append(
                prompt_templates["compensation_target_yearly"].format(value=minimum_salary_yearly)
            )
        if minimum_daily_rate > 0:
            preference_lines.append(
                prompt_templates["compensation_target_daily"].format(value=minimum_daily_rate)
            )
    home_location = str(match_preferences.get("home_location") or "").strip()
    if home_location:
        preference_lines.append(
            prompt_templates["home_location"].format(home_location=home_location)
        )
    if match_preferences.get("prefer_permanent"):
        preference_lines.append(prompt_templates["prefer_permanent"])
    if preference_lines:
        parts.append(LLM_PROMPT_MATCH_PREFERENCES_HEADER)
        parts.extend(f"- {line}" for line in preference_lines)

    # star_evidence_text intentionally excluded from fit-scoring prompt.
    # Field is preserved in the runtime profile for future application/CV generation.
    # See docs/ARCHITECTURE.md parked decisions.

    primary_evidence = str(evidence_tiers.get(KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT) or "").strip()
    secondary_evidence = str(
        evidence_tiers.get(KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT) or ""
    ).strip()
    background_evidence = str(
        evidence_tiers.get(KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT) or ""
    ).strip()

    tier_text_by_key = {
        KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT: primary_evidence,
        KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT: secondary_evidence,
        KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT: background_evidence,
    }
    for tier in prompt_evidence_tiers:
        tier_key = str(tier.get("profile_key") or "").strip()
        tier_label = str(tier.get("label") or "").strip()
        weight_label = str(tier.get("weight_label") or "").strip()
        tier_weight = float(tier.get("default_weight") or 0.0)
        tier_limit = int(tier.get("limit") or 0)
        tier_text = str(tier_text_by_key.get(tier_key) or "").strip()
        if not tier_key or not tier_label or not tier_limit or not tier_text:
            continue
        parts.append(
            f"{tier_label} ({weight_label} weight {evidence_weights.get(tier_key, tier_weight):.2f}):"
        )
        parts.append(tier_text[:tier_limit])

    return "\n".join(part for part in parts if part)


def build_job_requirements_prompt() -> str:
    parts = [
        LLM_PROMPT_JSON_ONLY,
        LLM_PROMPT_DO_NOT_INVENT,
        LLM_PROMPT_USE_VISIBLE_STRINGS,
        build_job_requirements_guidance(),
        f"Return exactly this shape: {LLM_JOB_REQUIREMENTS_PROMPT_SHAPE}",
        f"Use at most {get_llm_job_requirements_max_items()} job_requirements.",
    ]
    return "\n".join(parts)


def build_fit_review_guidance(profile: dict[str, Any] | None = None) -> str:
    parts = [LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER]
    parts.extend(f"- {line}" for line in FIT_REVIEW_DEFAULT_LINES)
    return "\n".join(parts)


def build_requirement_coverage_guidance() -> str:
    return "\n".join(f"- {line}" for line in REQUIREMENT_COVERAGE_DEFAULT_LINES)


def build_job_requirements_guidance() -> str:
    return "\n".join(f"- {line}" for line in JOB_REQUIREMENTS_DEFAULT_LINES)


def build_fit_review_grade_guidance() -> str:
    return "\n".join(f"- {line}" for line in FIT_REVIEW_GRADE_DEFAULT_LINES)


def build_learning_guidance() -> str:
    return "\n".join(LEARNING_DEFAULT_LINES)


def build_rejection_suggestions_guidance() -> str:
    return "\n".join(f"- {line}" for line in REJECTION_SUGGESTIONS_DEFAULT_LINES)


def build_capability_naming_guidance() -> str:
    parts = [
        LLM_PROMPT_CAPABILITY_NAMING_INTRO,
        "",
        LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER,
    ]
    parts.extend(f"- {line}" for line in CAPABILITY_NAMING_DEFAULT_LINES)
    parts.extend(["", LLM_PROMPT_CLUSTERS_HEADER])
    return "\n".join(parts)


def build_llm_cache_key(job_description_text: str) -> str:
    desc_hash = hashlib.sha256(
        str(job_description_text or "").encode("utf-8", errors="ignore")
    ).hexdigest()
    return f"{_profile_fingerprint()}:{desc_hash}"


def _require_fit_review(value: Any) -> Dict[str, str]:
    if isinstance(value, dict):
        decision = str(value.get("decision") or "").strip().upper()
        grade = str(value.get("grade") or "").strip().upper()
        if not decision:
            raise ValueError("LLM fit review is missing decision")
        if not grade:
            raise ValueError("LLM fit review is missing grade")
        if decision not in LLM_ALLOWED_DECISIONS:
            raise ValueError(
                f"LLM fit review decision must be one of {sorted(LLM_ALLOWED_DECISIONS)}: {decision!r}"
            )
        if grade not in LLM_ALLOWED_GRADES:
            raise ValueError(
                f"LLM fit review grade must be one of {sorted(LLM_ALLOWED_GRADES)}: {grade!r}"
            )
        return {"decision": decision, "grade": grade}

    if isinstance(value, str):
        text = value.strip().upper()
        if "|" not in text:
            raise ValueError("LLM fit review must be DECISION|GRADE")
        decision, _, grade = text.partition("|")
        return _require_fit_review({"decision": decision, "grade": grade})

    raise ValueError(
        f"LLM fit review must be a dict or DECISION|GRADE string, got {type(value).__name__}"
    )


def normalize_llm_review(value: Any) -> Dict[str, str]:
    return _require_fit_review(value)


def _clean_learning_candidate_text(value: Any) -> str:
    return compact_whitespace(value)


def normalize_llm_learning_candidates(
    value: Any, max_items: int | None = None
) -> list[dict[str, Any]]:
    if max_items is None:
        max_items = get_llm_learning_candidates_max_items()
    if isinstance(value, dict):
        value = value.get("learning_candidates") or value.get("candidates") or []
    if isinstance(value, str):
        try:
            value = _json_mod.loads(_strip_json_fence(value))
        except Exception:
            return []
    if not isinstance(value, list):
        return []

    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        signal = _clean_learning_candidate_text(
            item.get(LEARNING_SIGNAL_KEY) or item.get("value") or item.get("name")
        )
        category = (
            re.sub(
                r"[^a-z0-9_]+",
                "_",
                _clean_learning_candidate_text(item.get(LEARNING_SUGGESTED_CATEGORY_KEY)),
            )
            .strip("_")
            .lower()
        )
        suggested_values = []
        raw_suggested_values = (
            item.get(LEARNING_SUGGESTED_VALUES_KEY) or item.get("suggested_values") or []
        )
        if isinstance(raw_suggested_values, str):
            raw_suggested_values = [raw_suggested_values]
        if isinstance(raw_suggested_values, list):
            seen_suggested: set[str] = set()
            for text in raw_suggested_values:
                cleaned = _clean_learning_candidate_text(text)
                lowered = cleaned.lower()
                if not cleaned or lowered in seen_suggested:
                    continue
                seen_suggested.add(lowered)
                suggested_values.append(cleaned)
        context_terms = []
        raw_context_terms = item.get(LEARNING_CONTEXT_TERMS_KEY) or item.get("context_terms") or []
        if isinstance(raw_context_terms, str):
            raw_context_terms = [raw_context_terms]
        if isinstance(raw_context_terms, list):
            seen_context_terms: set[str] = set()
            for text in raw_context_terms:
                cleaned = _clean_learning_candidate_text(text)
                lowered = cleaned.lower()
                if not cleaned or lowered in seen_context_terms:
                    continue
                seen_context_terms.add(lowered)
                context_terms.append(cleaned)
        confidence = compact_whitespace(
            item.get(LEARNING_CONFIDENCE_KEY) or item.get("confidence")
        ).lower()
        needs_review = bool(item.get(LEARNING_NEEDS_REVIEW_KEY, True))
        if not signal or category not in ALLOWED_LEARNING_CATEGORIES:
            continue
        if any(char in signal for char in "\r\n") or re.search(r"[.!?]", signal):
            continue
        if category in PATTERN_SIGNAL_CATEGORIES and "[*]" not in signal:
            continue
        key = (signal.lower(), category)
        if key in seen:
            continue
        original_texts = []
        seen_texts: set[str] = set()
        raw_originals = item.get(LEARNING_ORIGINAL_TEXTS_KEY) or []
        if isinstance(raw_originals, str):
            raw_originals = [raw_originals]
        if not isinstance(raw_originals, list):
            raw_originals = []
        for text in [signal, *raw_originals]:
            cleaned = _clean_learning_candidate_text(text)
            lowered = cleaned.lower()
            if not cleaned or lowered in seen_texts:
                continue
            seen_texts.add(lowered)
            original_texts.append(cleaned)
        seen.add(key)
        candidates.append(
            {
                LEARNING_SIGNAL_KEY: signal,
                LEARNING_SUGGESTED_CATEGORY_KEY: category,
                LEARNING_SUGGESTED_VALUES_KEY: suggested_values,
                LEARNING_CONTEXT_TERMS_KEY: context_terms,
                LEARNING_CONFIDENCE_KEY: confidence,
                LEARNING_NEEDS_REVIEW_KEY: needs_review,
                LEARNING_ORIGINAL_TEXTS_KEY: original_texts or [signal],
            }
        )
        if len(candidates) >= max_items:
            break
    return candidates


_ALLOWED_REQUIREMENT_COVERAGE_STATUSES = frozenset(
    {"supported", "partially_supported", "not_shown", "mismatch"}
)

# Importance weights used by derive_fit_review_grade.
# mandatory requirements dominate the grade; nice_to_have items barely affect it.
_IMPORTANCE_WEIGHTS: dict[str, float] = {
    "mandatory": 3.0,
    "strongly_preferred": 2.0,
    "preferred": 1.0,
    "nice_to_have": 0.25,
}


def _build_valid_capability_lookup(
    valid_capability_names: dict[str, str] | None,
) -> dict[str, str] | None:
    if valid_capability_names is None:
        return None
    lookup: dict[str, str] = {}
    for key, value in valid_capability_names.items():
        normalized_key = compact_whitespace(key).lower()
        canonical_value = compact_whitespace(value)
        if normalized_key and canonical_value:
            lookup[normalized_key] = canonical_value
    return lookup


def _normalize_capability_name(
    value: Any, valid_capability_names: dict[str, str] | None = None
) -> str:
    cleaned = compact_whitespace(value)
    if not cleaned:
        return ""
    normalized = cleaned.lower()
    if valid_capability_names is None:
        return normalized
    return valid_capability_names.get(normalized, "")


def normalize_llm_requirement_coverage(
    value: Any,
    valid_capability_names: dict[str, str] | None = None,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    if max_items is None:
        max_items = get_llm_job_requirements_max_items()
    if isinstance(value, dict):
        value = value.get("requirement_coverage") or value.get("coverage") or []
    if isinstance(value, str):
        try:
            value = _json_mod.loads(_strip_json_fence(value))
        except Exception:
            return []
    if not isinstance(value, list):
        return []

    valid_lookup = _build_valid_capability_lookup(valid_capability_names)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        requirement = _clean_job_requirement_text(
            item.get("requirement") or item.get("job_requirement") or item.get("text")
        )
        raw_importance = compact_whitespace(item.get("importance")).lower()
        importance = (
            raw_importance if raw_importance in LLM_ALLOWED_COVERAGE_IMPORTANCES else "preferred"
        )
        status = compact_whitespace(item.get("status")).lower()
        capability_name = _normalize_capability_name(item.get("capability_name"), valid_lookup)
        matched_job_text = compact_whitespace(
            item.get("matched_job_text") or item.get("matched_text")
        )
        raw_support = item.get("profile_support") or []
        if isinstance(raw_support, str):
            raw_support = [raw_support]
        profile_support: list[str] = []
        seen_support: set[str] = set()
        if isinstance(raw_support, list):
            for text in raw_support:
                cleaned = compact_whitespace(text)
                lowered = cleaned.lower()
                if not cleaned or lowered in seen_support:
                    continue
                seen_support.add(lowered)
                profile_support.append(cleaned)
        if not requirement or status not in _ALLOWED_REQUIREMENT_COVERAGE_STATUSES:
            continue
        if status in {"supported", "partially_supported"} and not capability_name:
            logger.warning(
                "[LLM][WARN] purpose=fit_review requirement_coverage_missing_capability requirement=%r status=%s importance=%s",
                requirement,
                status,
                importance,
            )
            continue
        key = requirement.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "requirement": requirement,
                "importance": importance,
                "status": status,
                "capability_name": capability_name,
                "matched_job_text": matched_job_text,
                "profile_support": profile_support,
            }
        )
        if len(results) >= max_items:
            break
    return results


def derive_fit_review_grade(
    requirement_coverage: list[dict[str, Any]],
    job_requirements: list[str] | None = None,
) -> str:
    """Derive grade from importance-weighted requirement coverage.

    Importance weights: mandatory=3, strongly_preferred=2, preferred=1, nice_to_have=0.25.
    Any mismatch caps at WEAK. mandatory+not_shown lowers the ratio but does not auto-reject.
    Items without an importance field default to 'preferred' (weight 1.0).
    """
    total_items = max(len(requirement_coverage), len(job_requirements or []))
    if total_items <= 0:
        return "POOR"

    supported_count = 0
    partial_count = 0
    mismatch_count = 0
    support_score = 0.0
    max_score = 0.0

    for item in requirement_coverage:
        status = str(item.get("status") or "").strip().lower()
        importance = str(item.get("importance") or "preferred").strip().lower()
        weight = _IMPORTANCE_WEIGHTS.get(importance, _IMPORTANCE_WEIGHTS["preferred"])

        if status == "supported":
            supported_count += 1
            support_score += weight
        elif status == "partially_supported":
            partial_count += 1
            support_score += weight * 0.5
        elif status == "mismatch":
            mismatch_count += 1
        # not_shown: 0 contribution, weight still counted in max_score

        max_score += weight

    # Uncovered items (in job_requirements but absent from coverage) count at default weight.
    uncovered = max(total_items - len(requirement_coverage), 0)
    max_score += uncovered * _IMPORTANCE_WEIGHTS["preferred"]

    covered_count = supported_count + partial_count

    if covered_count <= 0:
        return "MISMATCH" if mismatch_count else "POOR"

    if mismatch_count:
        # Any mismatch caps at WEAK regardless of importance or support ratio.
        return "WEAK"

    support_ratio = support_score / max_score if max_score > 0 else 0

    if supported_count == total_items and partial_count == 0:
        return "EXCELLENT" if total_items >= 3 else "STRONG"

    if support_ratio >= 0.8 and partial_count <= 1 and supported_count >= max(2, total_items - 1):
        return "STRONG"

    if support_ratio >= 0.5:
        return "SOLID"

    return "WEAK"


def _clean_job_requirement_text(value: Any) -> str:
    cleaned = compact_whitespace(value)
    cleaned = re.sub(r"^[•\-\u2013\u2014]+\s*", "", cleaned).strip()
    cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned).strip()
    return cleaned


def normalize_llm_job_requirements(value: Any, max_items: int | None = None) -> list[str]:
    if max_items is None:
        max_items = get_llm_job_requirements_max_items()
    if isinstance(value, dict):
        value = value.get("job_requirements") or value.get("requirements") or []
    if isinstance(value, str):
        try:
            value = _json_mod.loads(_strip_json_fence(value))
        except Exception:
            return []
    if not isinstance(value, list):
        return []

    requirements: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = _clean_job_requirement_text(item)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        requirements.append(cleaned)
        if len(requirements) >= max_items:
            break
    return requirements


def _normalize_llm_review_text(value: Any, *, max_chars: int) -> str:
    cleaned = compact_whitespace(value)
    if not cleaned:
        return ""
    return cleaned[:max_chars]


def _require_complete_keep_requirement_coverage(
    fit_review: dict[str, str], requirement_coverage: list[dict[str, Any]]
) -> None:
    decision = str(fit_review.get("decision") or "").strip().upper()
    if decision != "KEEP":
        return
    if requirement_coverage:
        return
    raise LLMReviewValidationError(
        "LLM KEEP review requires non-empty requirement_coverage"
    )


def normalize_llm_review_payload(
    value: Any, valid_capability_names: dict[str, str] | None = None
) -> dict[str, Any]:
    if isinstance(value, dict):
        fit_review = value.get("fit_review")
        has_explicit_fit_review = (
            isinstance(fit_review, dict) or "decision" in value or "grade" in value
        )
        if has_explicit_fit_review:
            if fit_review is None:
                fit_review = {
                    "decision": value.get("decision"),
                    "grade": value.get("grade"),
                }
            requirement_coverage = normalize_llm_requirement_coverage(
                value.get("requirement_coverage"),
                valid_capability_names=valid_capability_names,
            )
            job_requirements = normalize_llm_job_requirements(value.get("job_requirements"))
            derived_grade = derive_fit_review_grade(requirement_coverage, job_requirements)
            fit_review_normalized = _require_fit_review(fit_review)
            _require_complete_keep_requirement_coverage(
                fit_review_normalized, requirement_coverage
            )
            cited_capabilities = list(
                dict.fromkeys(
                    str(_item.get("capability_name") or "").strip()
                    for _item in requirement_coverage
                    if _item.get("capability_name")
                    and _item.get("status") in {"supported", "partially_supported"}
                )
            )
            grade_to_use = (
                derived_grade
                if requirement_coverage
                else derived_grade
            )
            # Count by importance × status for structured logging.
            _imp_status: dict[str, int] = {}
            for _item in requirement_coverage:
                _key = f"{_item.get('importance', 'preferred')}.{_item.get('status', 'not_shown')}"
                _imp_status[_key] = _imp_status.get(_key, 0) + 1
            _imp_status_str = " ".join(f"{k}={v}" for k, v in sorted(_imp_status.items()))
            logger.info(
                "[LLM][COVERAGE] purpose=fit_review grade_used=%s derived_grade=%s model_grade=%s"
                " coverage_source=%s total=%d breakdown=[%s] capabilities=%s",
                grade_to_use,
                derived_grade,
                fit_review_normalized["grade"],
                "derived",
                len(requirement_coverage),
                _imp_status_str or "empty",
                ", ".join(cited_capabilities) or "(none)",
            )
            return {
                "fit_review": {**fit_review_normalized, "grade": grade_to_use},
                "debug_reason": _normalize_llm_review_text(
                    value.get("debug_reason"), max_chars=300
                ),
                "requirement_coverage": requirement_coverage,
                "job_requirements": job_requirements,
            }

        if "learning_candidates" in value or value.get("learning_only") or "fit_review" in value:
            return {
                "fit_review": None,
                "learning_candidates": normalize_llm_learning_candidates(
                    value.get("learning_candidates")
                ),
                "requirement_coverage": [],
                "job_requirements": [],
            }

        raise ValueError("LLM review payload is missing fit_review")

    raise ValueError(f"LLM review payload must be a dict, got {type(value).__name__}")


def _strip_json_fence(value: str) -> str:
    raw = str(value or "").strip()
    # Use regex to find content inside triple backticks, potentially with 'json' identifier
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw


def normalize_rejection_blocker_suggestions(value: Any, max_items: int | None = None) -> list[str]:
    if max_items is None:
        max_items = get_llm_rejection_blocker_suggestions_max_items()
    max_words = get_llm_rejection_blocker_suggestions_max_words()
    if isinstance(value, str):
        value = _strip_json_fence(value)
    return _normalize_rejection_blocker_suggestions(
        value,
        max_items=max_items,
        max_words=max_words,
    )


def llm_suggest_rejection_blockers(job_description_text: str, llm_client: Any = None) -> list[str]:
    active_client = llm_client or client
    description = str(job_description_text or "").strip()
    if active_client is None or not description:
        return []

    system_prompt = "\n".join(
        part
        for part in [
            build_rejection_suggestions_guidance(),
            f"{LLM_PROMPT_JSON_ONLY}, in this exact shape: {LLM_REJECTION_SUGGESTIONS_JSON_SHAPE}. Return an empty array if unsure.",
            build_profile_prompt_context(),
        ]
        if part
    )

    try:
        model = _log_llm_model_once()
        _desc_limit = get_llm_job_description_max_chars()
        _desc_truncated = description[:_desc_limit]
        logger.info(
            "[LLM][REQUEST] purpose=rejection_suggestions model=%s description_chars_fetched=%d"
            " description_chars_sent_to_llm=%d truncation_applied=%s max_output_tokens=%d",
            model,
            len(description),
            len(_desc_truncated),
            str(len(description) > _desc_limit).lower(),
            get_llm_rejection_blocker_suggestions_max_output_tokens(),
        )
        resp = active_client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": LLM_PROMPT_JOB_DESCRIPTION_PREFIX + _desc_truncated,
                },
            ],
            max_output_tokens=get_llm_rejection_blocker_suggestions_max_output_tokens(),
        )
        _log_llm_call(resp, "rejection_suggestions", model)
    except Exception as exc:
        logger.error("[LLM][FAIL] purpose=rejection_suggestions error=%s", exc)
        return []

    suggestions = normalize_rejection_blocker_suggestions(getattr(resp, "output_text", ""))
    raw_output = str(getattr(resp, "output_text", "") or "").strip()
    if raw_output:
        logger.info(
            "[LLM][RESULT] purpose=rejection_suggestions raw=%r",
            raw_output[: get_llm_raw_output_log_max_chars()],
        )
    logger.info("[LLM][RESULT] purpose=rejection_suggestions normalized=%s", suggestions)
    if not suggestions and str(getattr(resp, "output_text", "") or "").strip():
        logger.warning(
            "[LLM][WARN] purpose=rejection_suggestions output_could_not_be_normalized=%r",
            str(resp.output_text).strip()[: get_llm_raw_output_log_max_chars()],
        )
    return suggestions


def name_capability_clusters(clusters: list[dict[str, Any]], llm_client: Any = None) -> list[str]:
    """Use the LLM only to label pre-selected deterministic capability clusters."""
    active_client = llm_client or client
    if active_client is None or not clusters:
        return []

    payload: list[dict[str, Any]] = []
    for item in clusters:
        seed = str(item.get("name") or "").strip().lower()
        aliases = [
            str(alias).strip().lower()
            for alias in (item.get("aliases") or [])
            if str(alias).strip()
        ]
        if not seed:
            continue
        payload.append(
            {
                "seed": seed,
                "aliases": aliases[: get_llm_capability_naming_aliases_max_items()],
            }
        )
    if not payload:
        return []

    prompt = build_capability_naming_guidance()

    try:
        _model = get_llm_model()
        logger.info(
            "[LLM][REQUEST] purpose=capability_naming model=%s input_clusters=%d max_output_tokens=%d",
            _model,
            len(payload),
            get_llm_capability_naming_max_output_tokens(),
        )
        resp = active_client.responses.create(
            model=_model,
            input=[
                {"role": "user", "content": prompt + _json_mod.dumps(payload, ensure_ascii=False)}
            ],
            max_output_tokens=get_llm_capability_naming_max_output_tokens(),
        )
        _log_llm_call(resp, "capability_naming", _model)
        raw = (resp.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        labels = _json_mod.loads(raw)
        if not isinstance(labels, list):  # Catches any exception during JSON loading
            logger.warning(
                "[LLM][CAPABILITY_NAMING][WARN] LLM returned non-list for capability naming: %r",
                raw[:200],
            )
            return []
        return [str(label).strip().lower() for label in labels[: len(payload)]]
    except Exception as exc:
        logger.error("[LLM][FAIL] purpose=capability_naming error=%s", exc)
        return []


def llm_should_consider(job_description_text: str) -> Dict[str, str]:
    return normalize_llm_review(
        llm_should_consider_with_learning(job_description_text).get("fit_review")
    )


def _build_learning_prompt(job_description_text: str, *, fit_review: bool) -> str:
    parts = [
        LLM_PROMPT_SYSTEM_REVIEW_INTRO
        if fit_review
        else "You help decide whether a candidate should apply for a job and identify only pending learning signals."
    ]
    parts.append(LLM_PROMPT_JSON_ONLY)
    if fit_review:
        parts.extend(
            [
                LLM_PROMPT_FIT_REVIEW_ONLY_INTRO,
                build_fit_review_guidance(),
                LLM_PROMPT_DEBUG_REASON_INTRO,
                f"Return exactly this shape: {LLM_FIT_REVIEW_PROMPT_SHAPE}",
                build_requirement_coverage_guidance(),
                build_fit_review_grade_guidance(),
                build_job_requirements_guidance(),
                f"Use at most {get_llm_job_requirements_max_items()} job_requirements.",
            ]
        )
    else:
        parts.extend(
            [
                LLM_PROMPT_DO_NOT_SAVE,
                LLM_PROMPT_DO_NOT_INVENT,
                LLM_PROMPT_USE_VISIBLE_STRINGS,
            ]
        )
        parts.append(LLM_PROMPT_LEARNING_PENDING_ONLY)
        parts.extend(
            [
                build_learning_guidance(),
                f"Return exactly this shape: {LLM_LEARNING_ONLY_PROMPT_SHAPE}",
                LLM_PROMPT_NO_FIT_DECISION_REQUIRED,
                f"Use at most {get_llm_learning_candidates_max_items()} learning candidates.",
            ]
        )
    parts.append(build_profile_prompt_context())
    return "\n".join(part for part in parts if part)


def _request_learning_payload(job_description_text: str, *, fit_review: bool) -> dict[str, Any]:
    if client is None:
        raise RuntimeError("LLM review requested but no provider key is configured")

    valid_capability_names: dict[str, str] | None = None
    if fit_review:
        profile = load_profile()
        valid_capability_names = {
            str(r.get("name") or "").strip().lower(): str(r.get("name") or "").strip()
            for r in profile.get(KEY_CANDIDATE_CAPABILITIES, [])
            if isinstance(r, dict) and str(r.get("name") or "").strip()
        }
        if not valid_capability_names:
            raise ValueError(
                "Fit review cannot run because the candidate profile has no capability rules "
                "(candidate_capabilities is empty). Complete onboarding or seed the profile first."
            )

    model = _log_llm_model_once()
    purpose = "fit_review" if fit_review else "learning_candidates"
    max_output_tokens = (
        get_llm_fit_decision_max_output_tokens()
        if fit_review
        else get_llm_learning_candidates_max_output_tokens()
    )
    max_attempts = 2 if fit_review else 1
    resp = None
    for attempt in range(1, max_attempts + 1):
        try:
            # job_description_text is already truncated by the caller
            # (source_learning.resolve_llm_review_payload). Log its length directly.
            logger.info(
                "[LLM][REQUEST] purpose=%s model=%s input_chars=%d max_output_tokens=%d attempt=%d/%d",
                purpose,
                model,
                len(job_description_text),
                max_output_tokens,
                attempt,
                max_attempts,
            )
            resp = client.responses.parse(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": _build_learning_prompt(job_description_text, fit_review=fit_review),
                    },
                    {
                        "role": "user",
                        "content": LLM_PROMPT_JOB_DESCRIPTION_PREFIX + job_description_text,
                    },
                ],
                max_output_tokens=max_output_tokens,
                text_format=_LLMFitReviewPayload if fit_review else _LLMReviewPayload,
            )
            _log_llm_call(
                resp, "job_review_with_learning" if fit_review else "job_learning_candidates", model
            )
            break
        except APITimeoutError as exc:
            raise LLMCallError(
                "APITimeoutError: Request timed out.",
                purpose=purpose,
                model=model,
                is_timeout=True,
            ) from exc
        except APIStatusError as exc:
            raise LLMCallError(
                f"HTTP {exc.status_code} — {exc.message}",
                purpose=purpose,
                model=model,
                status_code=exc.status_code,
            ) from exc
        except Exception as exc:
            if fit_review and attempt < max_attempts and _is_retryable_llm_payload_error(exc):
                logger.warning(
                    "[LLM][RETRY] purpose=%s model=%s attempt=%d/%d reason=%s",
                    purpose,
                    model,
                    attempt + 1,
                    max_attempts,
                    f"{type(exc).__name__}: {exc}",
                )
                continue
            raise LLMCallError(
                f"{type(exc).__name__}: {exc}",
                purpose=purpose,
                model=model,
            ) from exc

    parsed = getattr(resp, "output_parsed", None)
    if parsed is None:
        raise ValueError("LLM review payload is missing parsed output")

    payload = normalize_llm_review_payload(
        parsed.model_dump(), valid_capability_names=valid_capability_names
    )
    if fit_review:
        if payload.get("fit_review") is None:
            raise ValueError("LLM fit review payload is missing fit_review")
    return payload


def llm_extract_job_requirements(job_description_text: str, llm_client: Any = None) -> list[str]:
    active_client = llm_client or client
    description = str(job_description_text or "").strip()
    if active_client is None or not description:
        return []

    system_prompt = "\n".join(
        [
            "You extract only the explicit job requirements visible in the ad.",
            build_job_requirements_prompt(),
        ]
    )

    try:
        model = _log_llm_model_once()
        _desc_limit = get_llm_job_description_max_chars()
        _desc_truncated = description[:_desc_limit]
        logger.info(
            "[LLM][REQUEST] purpose=job_requirements model=%s description_chars_fetched=%d"
            " description_chars_sent_to_llm=%d truncation_applied=%s max_output_tokens=%d",
            model,
            len(description),
            len(_desc_truncated),
            str(len(description) > _desc_limit).lower(),
            get_llm_job_requirements_max_output_tokens(),
        )
        resp = active_client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": LLM_PROMPT_JOB_DESCRIPTION_PREFIX + _desc_truncated},
            ],
            max_output_tokens=get_llm_job_requirements_max_output_tokens(),
            text_format=_LLMJobRequirementsPayload,
        )
        _log_llm_call(resp, "job_requirements", model)
    except Exception as exc:
        logger.error("[LLM][FAIL] purpose=job_requirements error=%s", exc)
        return []

    parsed = getattr(resp, "output_parsed", None)
    if parsed is None:
        return []
    raw_output = str(getattr(resp, "output_text", "") or "").strip()
    if raw_output:
        logger.info(
            "[LLM][RESULT] purpose=job_requirements raw=%r",
            raw_output[: get_llm_raw_output_log_max_chars()],
        )
    return normalize_llm_job_requirements(parsed.model_dump())


def llm_should_consider_with_learning(job_description_text: str) -> dict[str, Any]:
    return _request_learning_payload(job_description_text, fit_review=True)


def llm_should_consider_learning_candidates(job_description_text: str) -> list[dict[str, Any]]:
    return normalize_llm_review_payload(
        _request_learning_payload(job_description_text, fit_review=False)
    ).get("learning_candidates", [])


def llm_classify_section_label(label: str, llm_client: Any = None) -> dict[str, Any] | None:
    """Classify an unknown CV section heading into primary/secondary/supplementary.

    Returns {"bucket": str, "confident": bool} or None if LLM unavailable or output unparseable.
    """
    active_client = llm_client or client
    label = str(label or "").strip()
    if active_client is None or not label:
        return None

    system_prompt = "\n".join(
        [
            "You are routing a CV section heading to one of three profile support tiers for a job-match assistant.",
            "primary: current or recent work experience (roles, projects, achievements).",
            "secondary: older or supporting work experience.",
            "supplementary: education, certifications, training, or non-work background sections.",
            f"Return JSON only, shape: {LLM_SECTION_LABEL_CLASSIFICATION_SHAPE}",
            "Set confident=true only if the heading unambiguously maps to one tier.",
            "Set confident=false if the heading is ambiguous (e.g. Overview, Profile, Summary).",
        ]
    )

    try:
        model = _log_llm_model_once()
        logger.info(
            "[LLM][REQUEST] purpose=section_label_classification model=%s input_chars=%d max_output_tokens=%d",
            model,
            len(label),
            50,
        )
        resp = active_client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'Section heading: "{label}"'},
            ],
            max_output_tokens=50,
        )
        _log_llm_call(resp, "section_label_classification", model)
    except Exception as exc:
        logger.error("[LLM][FAIL] purpose=section_label_classification error=%s", exc)
        return None

    raw = str(getattr(resp, "output_text", "") or "").strip()
    if not raw:
        return None

    try:
        parsed = _json_mod.loads(raw)
    except _json_mod.JSONDecodeError:
        logger.warning("[LLM][WARN] purpose=section_label_classification parse_error=%r", raw[:200])
        return None

    bucket = str(parsed.get("bucket") or "").strip().lower()
    confident = bool(parsed.get("confident"))
    if bucket not in {"primary", "secondary", "supplementary"}:
        logger.warning("[LLM][WARN] purpose=section_label_classification invalid_bucket=%r", bucket)
        return None

    logger.info(
        "[LLM][RESULT] purpose=section_label_classification label=%r bucket=%s confident=%s",
        label,
        bucket,
        confident,
    )
    return {"bucket": bucket, "confident": confident}


def llm_judge_title(
    title: str,
    target_roles: list[str] | None,
    secondary_roles: list[str] | None,
    llm_client: Any = None,
) -> dict[str, Any] | None:
    """Cheap title-only check of a job title against the candidate's target/secondary target roles.

    Runs after O*NET occupation classification returns near/uncertain, before the expensive
    detail fetch + full fit review. Returns {"verdict": "match"|"no_match"|"uncertain", "reason": str}
    or None if the LLM is unavailable, the title is empty, or the output is unparseable — callers
    must treat None the same as "uncertain" and never hard-reject on an LLM failure.
    """
    active_client = llm_client or client
    title = str(title or "").strip()
    if active_client is None or not title:
        return None

    target_roles = [str(r).strip() for r in (target_roles or []) if str(r).strip()]
    secondary_roles = [str(r).strip() for r in (secondary_roles or []) if str(r).strip()]
    if not target_roles and not secondary_roles:
        return None

    system_prompt = "\n".join(
        [
            "You are a cheap pre-filter checking whether a job title plausibly matches a candidate's target roles, before the full job description is fetched.",
            f"Target roles: {', '.join(target_roles) or 'none'}",
            f"Secondary target roles: {', '.join(secondary_roles) or 'none'}",
            f"Return JSON only, shape: {LLM_TITLE_JUDGMENT_SHAPE}",
            "verdict=match: the title clearly matches or is a close variant of a target/secondary role.",
            "verdict=no_match: the title is for a distinctly different role or seniority/function, even if it shares generic words.",
            "verdict=uncertain: title alone is not enough to tell — a job description could plausibly change the answer.",
            "Judge on the title alone. Do not guess at duties not implied by the title.",
        ]
    )

    max_output_tokens = get_llm_title_judgment_max_output_tokens()
    try:
        model = _log_llm_model_once()
        logger.info(
            "[LLM][REQUEST] purpose=title_judgment model=%s input_chars=%d max_output_tokens=%d",
            model,
            len(title),
            max_output_tokens,
        )
        resp = active_client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'Job title: "{title}"'},
            ],
            max_output_tokens=max_output_tokens,
        )
        _log_llm_call(resp, "title_judgment", model)
    except Exception as exc:
        logger.error("[LLM][FAIL] purpose=title_judgment error=%s", exc)
        return None

    raw = str(getattr(resp, "output_text", "") or "").strip()
    if not raw:
        return None

    try:
        parsed = _json_mod.loads(raw)
    except _json_mod.JSONDecodeError:
        logger.warning("[LLM][WARN] purpose=title_judgment parse_error=%r", raw[:200])
        return None

    verdict = str(parsed.get("verdict") or "").strip().lower()
    reason = str(parsed.get("reason") or "").strip()
    if verdict not in LLM_ALLOWED_TITLE_JUDGMENT_VERDICTS:
        logger.warning("[LLM][WARN] purpose=title_judgment invalid_verdict=%r", verdict)
        return None

    logger.info(
        "[LLM][RESULT] purpose=title_judgment title=%r verdict=%s reason=%r",
        title,
        verdict,
        reason,
    )
    return {"verdict": verdict, "reason": reason}


def get_cost_summary() -> dict[str, Any]:
    """Read llm_costs.jsonl and return totals by purpose - useful for debugging."""
    totals: dict[str, dict[str, Any]] = {}
    try:
        with open(_LLM_COSTS_PATH, encoding="utf-8") as fh:
            for line in fh:
                entry = _json_mod.loads(line)
                p = entry.get("purpose", "unknown")
                if p not in totals:
                    totals[p] = {"calls": 0, "tok_in": 0, "tok_out": 0, "cost_usd": 0.0}
                totals[p]["calls"] += 1
                totals[p]["tok_in"] += entry.get("tok_in", 0)
                totals[p]["tok_out"] += entry.get("tok_out", 0)
                totals[p]["cost_usd"] += entry.get("cost_usd", 0.0)
    except FileNotFoundError:
        pass
    grand = sum(v["cost_usd"] for v in totals.values())
    return {"by_purpose": totals, "grand_total_usd": round(grand, 6)}
