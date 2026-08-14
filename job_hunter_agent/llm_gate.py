"""LLM fit-decision gateway.

Purpose: build constrained prompts, normalize LLM outputs, and keep requirement
coverage structured so deterministic checks stay in control.
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
from pydantic import AliasChoices, BaseModel, Field, ValidationError

from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.experience_requirements import resolve_role_experience_requirement
from job_hunter_agent.requirement_classification import classify_requirement_type
from job_hunter_agent.global_settings import (
    get_llm_fit_review_debug_match_diagnostics_enabled,
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
    get_llm_max_retries,
    get_llm_raw_output_log_max_chars,
    get_llm_request_timeout_seconds,
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
    LLM_ALLOWED_COVERAGE_MATCH_SOURCES,
    LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES,
    LLM_COVERAGE_IMPORTANCE_BONUS,
    LLM_COVERAGE_IMPORTANCE_EXPECTED,
    LLM_COVERAGE_IMPORTANCE_PREFERRED,
    LLM_COVERAGE_IMPORTANCE_REQUIRED,
    LLM_ALLOWED_DECISIONS,
    LLM_ALLOWED_GRADES,
    LLM_ALLOWED_OCCUPATION_ALIGNMENTS,
    LLM_ALLOWED_POSTING_CHANNEL_KINDS,
    LLM_FIT_REVIEW_DEBUG_PROMPT_SHAPE,
    LLM_ALLOWED_TITLE_JUDGMENT_VERDICTS,
    LLM_INVALID_COVERAGE_REQUIREMENT_TYPE,
    LLM_INVALID_COVERAGE_STATUS,
    LLM_INVALID_OCCUPATION_ALIGNMENT,
    LLM_INVALID_POSTING_CHANNEL_KIND,
    LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE,
    LLM_FIT_REVIEW_PROMPT_SHAPE,
    LLM_JOB_REQUIREMENTS_PROMPT_SHAPE,
    LLM_LEARNING_ONLY_PROMPT_SHAPE,
    LLM_PROMPT_CAPABILITY_LEVELS_HEADER,
    LLM_PROMPT_CAPABILITY_NAMING_INTRO,
    LLM_PROMPT_CLUSTERS_HEADER,
    LLM_PROMPT_DEBUG_REASON_INTRO,
    LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER,
    LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER,
    LLM_PROMPT_ELIGIBILITY_HEADER,
    LLM_PROMPT_DO_NOT_INVENT,
    LLM_PROMPT_DO_NOT_SAVE,
    LLM_PROMPT_FIT_REVIEW_ONLY_INTRO,
    LLM_PROMPT_JOB_DESCRIPTION_PREFIX,
    LLM_PROMPT_JSON_ONLY,
    LLM_PROMPT_LEARNING_PENDING_ONLY,
    LLM_PROMPT_MATCH_PREFERENCES_HEADER,
    LLM_PROMPT_NO_FIT_DECISION_REQUIRED,
    LLM_PROMPT_OCCUPATION_ALIGNMENT_INTRO,
    LLM_PROMPT_POSTING_CHANNEL_INTRO,
    LLM_PROMPT_ROLE_EXPERIENCE_HEADER,
    LLM_PROMPT_SYSTEM_REVIEW_INTRO,
    LLM_PROMPT_TARGET_ROLES_HEADER,
    LLM_PROMPT_USE_VISIBLE_STRINGS,
    LLM_REJECTION_SUGGESTIONS_JSON_SHAPE,
    LLM_SECTION_LABEL_CLASSIFICATION_SHAPE,
    LLM_TITLE_JUDGMENT_SHAPE,
)
from job_hunter_agent.paths import LLM_COSTS_PATH as _LLM_COSTS_PATH
from job_hunter_agent.runtime_helpers import is_desktop_runtime
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)

# Import at module level to allow monkeypatching in tests
from job_hunter_agent.profile_item_names import normalize_profile_item_name
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_CAPABILITIES,
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_ELIGIBILITY_FACTS,
    KEY_CANDIDATE_QUALIFICATIONS,
    KEY_ROLE_EXPERIENCE,
    get_candidate_profile_tier_weights,
    get_candidate_profile_tiers,
    load_clearance_ui_options,
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
    logger.debug(
        "[LLM][COST] purpose=%s model=%s input_tokens=%d output_tokens=%d call_cost_usd=%.6f session_cost_usd=%.6f",
        purpose,
        model,
        tok_in,
        tok_out,
        cost,
        _session_cost_usd,
    )


def _llm_usage_summary(resp: Any, model: str) -> dict[str, Any]:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return {}
    tok_in = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0
    tok_out = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0
    prices = _get_llm_pricing_per_1m()[model]
    cost = _calculate_llm_cost_usd(tok_in, tok_out, prices)
    return {
        "llm_input_tokens": int(tok_in),
        "llm_output_tokens": int(tok_out),
        "llm_cost_usd": round(cost, 6),
    }


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
        logger.debug("[LLM][MODEL] using model=%s (source=user settings)", model)
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


class _LLMTitleJudgment(BaseModel):
    """Structured pre-detail title-gate response owned by llm_judge_title."""

    verdict: str
    reason: str = ""


class _LLMRequirementCoverageItem(BaseModel):
    requirement: str
    importance: str = "preferred"
    requirement_type: str = "capability"
    canonical_requirement: str = ""
    # Structural signal for whether this row is one clear fact or a vague
    # group: the specific named alternatives/examples the ad lists (e.g.
    # ["IIBA","CBAP","CCBA","CSPO","PSM"]), empty for an atomic requirement.
    # Normalization gates profile-learning actions on this, not on whether
    # canonical_requirement merely happens to be non-empty.
    named_alternatives: list[str] = Field(default_factory=list)
    # Explicit LLM judgement: true only when canonical_requirement names a
    # single reusable profile concept the model actually resolved, not the
    # ad sentence restated. Deterministic code must not guess this from text
    # equality — it only trusts the flag. Missing/false keeps the row
    # visible but blocks profile-learning actions on it.
    profile_fact_resolved: bool = False
    status: str
    matched_candidate_fact: str = Field(
        default="",
        validation_alias=AliasChoices("matched_candidate_fact", "profile_name"),
    )
    matched_job_text: str = ""
    profile_support: list[str] = Field(default_factory=list)
    covered_requirement_elements: list[str] = Field(default_factory=list)
    role_defining: bool = False
    role_defining_group: str = ""


class _LLMRequirementCoverageDebugItem(_LLMRequirementCoverageItem):
    match_source: str = ""
    matched_profile_term: str = ""


class _LLMJobRequirementsPayload(BaseModel):
    job_requirements: list[str] = Field(default_factory=list)


class _LLMReviewPayload(BaseModel):
    fit_review: _LLMReviewDecision | None = None
    learning_candidates: list[_LLMLearningCandidate] = Field(default_factory=list)


class _LLMPostingChannel(BaseModel):
    kind: str = "unknown"
    confident: bool = False
    evidence: str = ""


class _LLMFitReviewPayload(BaseModel):
    fit_review: _LLMReviewDecision
    occupation_alignment: str = ""
    occupation_alignment_reason: str = ""
    posting_channel: _LLMPostingChannel = Field(default_factory=_LLMPostingChannel)
    debug_reason: str = ""
    eligibility_requirements: list[_LLMRequirementCoverageItem] = Field(default_factory=list)
    requirement_coverage: list[_LLMRequirementCoverageItem] = Field(default_factory=list)
    job_requirements: list[str] = Field(default_factory=list)


class _LLMFitReviewDebugPayload(BaseModel):
    fit_review: _LLMReviewDecision
    occupation_alignment: str = ""
    occupation_alignment_reason: str = ""
    posting_channel: _LLMPostingChannel = Field(default_factory=_LLMPostingChannel)
    debug_reason: str = ""
    eligibility_requirements: list[_LLMRequirementCoverageDebugItem] = Field(default_factory=list)
    requirement_coverage: list[_LLMRequirementCoverageDebugItem] = Field(default_factory=list)
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
    return OpenAI(
        api_key=api_key,
        timeout=get_llm_request_timeout_seconds(),
        max_retries=get_llm_max_retries(),
    )


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
OCCUPATION_ALIGNMENT_DEFAULT_LINES = _load_managed_prompt_lines("llm_occupation_alignment_defaults")
POSTING_CHANNEL_DEFAULT_LINES = _load_managed_prompt_lines("llm_posting_channel_defaults")


def llm_is_enabled() -> bool:
    return client is not None


def build_profile_prompt_context() -> str:
    from job_hunter_agent.profile_store import (
        KEY_CANDIDATE_CAPABILITIES,
        KEY_CANDIDATE_ELIGIBILITY,
        KEY_CANDIDATE_QUALIFICATIONS,
        KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_PRIMARY_PATTERNS,
        KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_SECONDARY_PATTERNS,
        KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
    )

    profile = load_profile()
    evidence_tiers = get_candidate_profile_tiers(profile)
    evidence_weights = get_candidate_profile_tier_weights(profile)
    prompt_settings = _get_llm_prompt_settings()
    prompt_templates = prompt_settings[KEY_LLM_PROMPT_TEMPLATES]
    prompt_evidence_tiers = prompt_settings[KEY_LLM_PROMPT_EVIDENCE_TIERS]
    capability_rules = profile.get(KEY_CANDIDATE_CAPABILITIES, [])
    eligibility_rules = [
        *(profile.get(KEY_CANDIDATE_ELIGIBILITY, []) or []),
        *(profile.get(KEY_CANDIDATE_ELIGIBILITY_FACTS, []) or []),
    ]
    qualification_rules = profile.get(KEY_CANDIDATE_QUALIFICATIONS, [])
    role_experience = profile.get(KEY_ROLE_EXPERIENCE, [])
    salary_preferences = profile.get("salary_preferences", {})
    match_preferences = (
        profile.get("match_preferences", {})
        if isinstance(profile.get("match_preferences", {}), dict)
        else {}
    )

    parts = []
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

    if isinstance(eligibility_rules, list) and eligibility_rules:
        parts.append(LLM_PROMPT_ELIGIBILITY_HEADER)
        for rule in eligibility_rules[: get_llm_capability_rules_max_items()]:
            if not isinstance(rule, dict):
                continue
            name = str(rule.get("name") or "").strip()
            if not name:
                continue
            value = "true" if bool(rule.get("value", True)) else "false"
            evidence = rule.get("evidence") or []
            evidence_text = ""
            if isinstance(evidence, list):
                evidence_text = ", ".join(
                    str(item).strip()
                    for item in evidence[: get_llm_capability_rule_aliases_max_items()]
                    if str(item).strip()
                )
            label = f"- {name}: {value}"
            if evidence_text:
                label += f" [{evidence_text}]"
            parts.append(label)

    if isinstance(qualification_rules, list) and qualification_rules:
        parts.append("Qualifications matrix:")
        for rule in qualification_rules[: get_llm_capability_rules_max_items()]:
            if not isinstance(rule, dict):
                continue
            name = compact_whitespace(str(rule.get("name") or ""))
            if not name:
                continue
            value = "true" if bool(rule.get("value", True)) else "false"
            aliases = rule.get("aliases") or []
            alias_text = ", ".join(
                compact_whitespace(str(alias))
                for alias in aliases[: get_llm_capability_rule_aliases_max_items()]
                if compact_whitespace(str(alias))
            ) if isinstance(aliases, list) else ""
            label = f"- {name}: {value}"
            if alias_text:
                label += f" ({alias_text})"
            parts.append(label)

    if isinstance(role_experience, list) and role_experience:
        parts.append(LLM_PROMPT_ROLE_EXPERIENCE_HEADER)
        for row in role_experience[: get_llm_capability_rules_max_items()]:
            if not isinstance(row, dict):
                continue
            title = compact_whitespace(str(row.get("normalized_title") or ""))
            months = int(row.get("total_duration_months") or 0)
            end_year = int(row.get("most_recent_end_year") or 0)
            if not title or months <= 0:
                continue
            label = f"- {title}: {months} months"
            variants = row.get("title_variants") or []
            if isinstance(variants, list):
                variant_labels = []
                for variant in variants[:3]:
                    if not isinstance(variant, dict):
                        continue
                    variant_title = compact_whitespace(str(variant.get("normalized_title") or ""))
                    variant_months = int(variant.get("total_duration_months") or 0)
                    if not variant_title or variant_title == title or variant_months <= 0:
                        continue
                    variant_labels.append(f"{variant_title} {variant_months} months")
                if variant_labels:
                    label += f" (title variants: {', '.join(variant_labels)})"
            if end_year > 0:
                label += f", most recent end year {end_year}"
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

    target_roles = [str(r).strip() for r in (profile.get(KEY_PRIMARY_PATTERNS) or []) if str(r).strip()]
    secondary_roles = [
        str(r).strip() for r in (profile.get(KEY_SECONDARY_PATTERNS) or []) if str(r).strip()
    ]
    if target_roles or secondary_roles:
        parts.append(LLM_PROMPT_TARGET_ROLES_HEADER)
        parts.append(f"- Target roles: {', '.join(target_roles) or 'none'}")
        parts.append(f"- Secondary target roles: {', '.join(secondary_roles) or 'none'}")

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
    parts = [
        f"Use at most {get_llm_job_requirements_max_items()} capability/qualification requirement_coverage items. eligibility_requirements are separate and do not consume this limit.",
        "Use requirement_type=capability or qualification in requirement_coverage, and requirement_type=eligibility in eligibility_requirements.",
        "For qualification rows, importance must be required or preferred.",
        "Use matched_candidate_fact for the exact canonical capability or eligibility name shown in the profile matrix, or the exact qualification name shown in the qualifications matrix; never put an evidence sentence there.",
        "Canonical qualification names must be concise reusable concepts such as CBAP, PRINCE2, Bachelor of Information Technology, or Diploma of Project Management — never the raw requirement sentence or an alternatives list.",
        "When the ad states explicit years or months of experience, compare that threshold against the role experience matrix before choosing supported versus partially_supported.",
    ]
    parts.extend(f"- {line}" for line in REQUIREMENT_COVERAGE_DEFAULT_LINES)
    return "\n".join(parts)


def build_requirement_coverage_debug_guidance() -> str:
    parts = [
        'For debug match diagnostics: return match_source exactly as "capability_name", "related_skill", "eligibility", or "qualification".',
        'Existing debug consumers recognize the legacy source set: "match_source":"capability_name|related_skill|eligibility".',
        "For debug match diagnostics: return matched_profile_term as the exact capability name, related skill, eligibility fact, or qualification used.",
        "For debug match diagnostics: matched_candidate_fact must stay the canonical profile concept.",
        "For debug match diagnostics: profile_support must contain only actual candidate evidence text, never just the capability name or related skill label.",
    ]
    return "\n".join(parts)


def build_job_requirements_guidance() -> str:
    return "\n".join(f"- {line}" for line in JOB_REQUIREMENTS_DEFAULT_LINES)


def build_fit_review_grade_guidance() -> str:
    return "\n".join(f"- {line}" for line in FIT_REVIEW_GRADE_DEFAULT_LINES)


def build_occupation_alignment_guidance() -> str:
    parts = [
        LLM_PROMPT_OCCUPATION_ALIGNMENT_INTRO,
        f"occupation_alignment must be one of: {', '.join(sorted(LLM_ALLOWED_OCCUPATION_ALIGNMENTS))}.",
    ]
    parts.extend(f"- {line}" for line in OCCUPATION_ALIGNMENT_DEFAULT_LINES)
    return "\n".join(parts)


def build_posting_channel_guidance() -> str:
    parts = [
        LLM_PROMPT_POSTING_CHANNEL_INTRO,
        f"posting_channel.kind must be one of: {', '.join(sorted(LLM_ALLOWED_POSTING_CHANNEL_KINDS))}.",
    ]
    parts.extend(f"- {line}" for line in POSTING_CHANNEL_DEFAULT_LINES)
    return "\n".join(parts)


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


# Bump when the fit-review response shape changes so stale cache entries
# (missing new fields) are treated as misses and re-reviewed by the LLM.
LLM_CACHE_SCHEMA_VERSION = 2


def build_llm_cache_key(job_description_text: str) -> str:
    desc_hash = hashlib.sha256(
        str(job_description_text or "").encode("utf-8", errors="ignore")
    ).hexdigest()
    return f"v{LLM_CACHE_SCHEMA_VERSION}:{_profile_fingerprint()}:{desc_hash}"


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
    {"supported", "partially_supported", "not_shown", "mismatch", LLM_INVALID_COVERAGE_STATUS}
)

# Importance weights used by derive_fit_review_grade.
# required requirements dominate the grade; bonus items barely affect it.
_IMPORTANCE_WEIGHTS: dict[str, float] = {
    LLM_COVERAGE_IMPORTANCE_REQUIRED: 3.0,
    LLM_COVERAGE_IMPORTANCE_EXPECTED: 2.0,
    LLM_COVERAGE_IMPORTANCE_PREFERRED: 1.0,
    LLM_COVERAGE_IMPORTANCE_BONUS: 0.25,
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


def _build_valid_eligibility_lookup(
    valid_eligibility_names: dict[str, str] | None,
) -> dict[str, str] | None:
    if valid_eligibility_names is None:
        return None
    lookup: dict[str, str] = {}
    for key, value in valid_eligibility_names.items():
        normalized_key = compact_whitespace(key).lower()
        canonical_value = compact_whitespace(value)
        if normalized_key and canonical_value:
            lookup[normalized_key] = canonical_value
    return lookup


def _build_profile_eligibility_names(profile: dict[str, Any]) -> dict[str, str]:
    """Map profile-owned eligibility names and managed aliases to canonical facts."""

    managed_options = load_clearance_ui_options()
    managed_terms_by_key: dict[str, list[str]] = {}
    for option in managed_options:
        terms = [option["value"], option["label"], *option["aliases"]]
        for term in terms:
            key = compact_whitespace(term).casefold()
            if key:
                managed_terms_by_key[key] = terms

    valid_names: dict[str, str] = {}
    for source_key in (KEY_CANDIDATE_ELIGIBILITY, KEY_CANDIDATE_ELIGIBILITY_FACTS):
        for rule in profile.get(source_key, []) or []:
            if not isinstance(rule, dict):
                continue
            canonical = compact_whitespace(rule.get("name"))
            if not canonical:
                continue
            managed_terms = managed_terms_by_key.get(canonical.casefold(), [])
            raw_aliases = rule.get("aliases") or []
            aliases = [raw_aliases] if isinstance(raw_aliases, str) else raw_aliases
            for term in [canonical, *managed_terms, *aliases]:
                normalized_term = compact_whitespace(term).casefold()
                if normalized_term:
                    valid_names[normalized_term] = canonical
    return valid_names


def _build_profile_eligibility_values(profile: dict[str, Any]) -> dict[str, bool]:
    """Return canonical eligibility truth values from the candidate profile."""
    values: dict[str, bool] = {}
    for source_key in (KEY_CANDIDATE_ELIGIBILITY, KEY_CANDIDATE_ELIGIBILITY_FACTS):
        for rule in profile.get(source_key, []) or []:
            if not isinstance(rule, dict):
                continue
            canonical = compact_whitespace(rule.get("name"))
            if canonical:
                values[canonical.casefold()] = bool(rule.get("value", True))
    return values


def _build_valid_qualification_lookup(
    valid_qualification_names: dict[str, str] | None,
) -> dict[str, str] | None:
    if valid_qualification_names is None:
        return None
    lookup: dict[str, str] = {}
    for key, value in valid_qualification_names.items():
        normalized_key = compact_whitespace(key).lower()
        canonical_value = compact_whitespace(value)
        if normalized_key and canonical_value:
            lookup[normalized_key] = canonical_value
    return lookup


def _recover_capability_from_profile_support(
    profile_support: list[str],
    valid_capability_lookup: dict[str, str] | None,
) -> str:
    """Recover a canonical capability when the model put it in evidence text.

    The model must return the canonical name in ``matched_candidate_fact``. This
    narrow recovery path handles the observed shape where the same canonical name
    or an approved alias appears in ``profile_support`` instead. It only uses
    profile-owned names and aliases; it does not invent semantic matches.
    """
    if not profile_support or not valid_capability_lookup:
        return ""

    matches: list[tuple[int, str]] = []
    for evidence in profile_support:
        normalized_evidence = compact_whitespace(evidence).lower()
        if not normalized_evidence:
            continue
        for term, canonical in valid_capability_lookup.items():
            if not term:
                continue
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized_evidence):
                matches.append((len(term), canonical))

    if not matches:
        return ""
    matches.sort(key=lambda item: (-item[0], item[1].lower()))
    return matches[0][1]


def _record_requirement_coverage_warning(
    *,
    requirement: str,
    importance: str,
    requirement_type_before: str,
    requirement_type_after: str,
    status_before: str,
    status_after: str,
    proposed_matched_candidate_fact: str,
    proposed_capability_name: str,
    proposed_eligibility_name: str,
    matched_job_text: str,
    reason: str,
) -> None:
    message = (
        f"Rejected LLM requirement coverage mapping for {requirement!r}: "
        f"{requirement_type_before!r}/{status_before!r} -> "
        f"{requirement_type_after!r}/{status_after!r} ({reason})."
    )
    fingerprint = make_system_warning_fingerprint(
        requirement,
        requirement_type_before,
        status_before,
        proposed_matched_candidate_fact,
        matched_job_text,
    )
    record_system_warning(
        severity="info",
        category="llm_requirement_coverage",
        source="llm_gate",
        message=message,
        fingerprint=fingerprint,
        context={
            "requirement": requirement,
            "importance": importance,
            "requirement_type_before": requirement_type_before,
            "requirement_type_after": requirement_type_after,
            "status_before": status_before,
            "status_after": status_after,
            "proposed_matched_candidate_fact": proposed_matched_candidate_fact,
            "proposed_capability_name": proposed_capability_name,
            "proposed_eligibility_name": proposed_eligibility_name,
            "matched_job_text": matched_job_text,
            "reason": reason,
        },
    )


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


_SEMANTIC_MATCH_STOPWORDS = frozenset({
    "ability", "and", "are", "as", "at", "be", "been", "being", "by", "can",
    "candidate", "demonstrated", "experience", "experienced", "for", "from", "have",
    "having", "in", "including", "knowledge", "of", "on", "or", "required", "role",
    "skills", "strong", "the", "to", "using", "with", "work", "working", "years",
})


def _semantic_match_tokens(value: str) -> set[str]:
    """Return profession-neutral content tokens for conservative evidence checks."""
    tokens = re.findall(r"[a-z0-9]+", compact_whitespace(value).lower())
    normalized: set[str] = set()
    for token in tokens:
        if len(token) < 2 or token in _SEMANTIC_MATCH_STOPWORDS:
            continue
        for suffix in ("ments", "ment", "ations", "ation", "ing", "ed", "ies", "s"):
            if token.endswith(suffix) and len(token) - len(suffix) >= 4:
                token = token[: -len(suffix)]
                break
        normalized.add(token)
    return normalized


def _has_meaningful_requirement_evidence(
    requirement: str,
    matched_job_text: str,
    matched_candidate_fact: str,
    profile_support: list[str],
    covered_requirement_elements: list[str],
) -> bool:
    """Require evidence for an actual component of the requirement, not broad transferability."""
    requirement_text = " ".join(part for part in (requirement, matched_job_text) if part)
    evidence_text = " ".join(
        part for part in (matched_candidate_fact, *profile_support) if compact_whitespace(part)
    )
    requirement_tokens = _semantic_match_tokens(requirement_text)
    evidence_tokens = _semantic_match_tokens(evidence_text)
    if not requirement_tokens or not evidence_tokens:
        return False

    # Versioned or otherwise numbered identifiers are substantive requirement
    # elements: generic vendor/domain evidence cannot prove them by itself.
    # For example, "SAP" must not prove "SAP S/4HANA" without evidence of
    # the specific versioned platform.
    specific_requirement_tokens = {
        token for token in requirement_tokens if any(character.isdigit() for character in token)
    }
    if specific_requirement_tokens and not specific_requirement_tokens & evidence_tokens:
        return False
    if requirement_tokens & evidence_tokens:
        return True

    # The model may identify a narrower covered component, but it must be grounded
    # in both the requirement wording and candidate evidence.
    for element in covered_requirement_elements:
        element_tokens = _semantic_match_tokens(element)
        if element_tokens and element_tokens <= requirement_tokens and element_tokens & evidence_tokens:
            return True
    return False


def _known_profile_eligibility_mentions(
    values: list[str],
    valid_eligibility_lookup: dict[str, str] | None,
) -> list[str]:
    """Resolve exact eligibility mentions from profile-owned names and aliases only."""
    if not valid_eligibility_lookup:
        return []
    found: dict[str, str] = {}
    terms = sorted(valid_eligibility_lookup.items(), key=lambda item: (-len(item[0]), item[0]))
    for raw_value in values:
        normalized_value = compact_whitespace(raw_value).casefold()
        if not normalized_value:
            continue
        for term, canonical in terms:
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized_value):
                found.setdefault(canonical.casefold(), canonical)
    return list(found.values())


def _atomicize_known_eligibility_rows(
    rows: list[dict[str, Any]],
    valid_eligibility_names: dict[str, str] | None,
    eligibility_fact_values: dict[str, bool] | None = None,
) -> list[dict[str, Any]]:
    """Enforce one known eligibility fact per non-alternative eligibility row."""
    lookup = _build_valid_eligibility_lookup(valid_eligibility_names)
    if not lookup:
        return rows

    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("requirement_type") or "").strip().lower() != "eligibility":
            normalized_rows.append(row)
            continue

        values = [
            *[str(value) for value in (row.get("covered_requirement_elements") or [])],
            str(row.get("requirement") or ""),
            str(row.get("matched_job_text") or ""),
        ]
        mentions = _known_profile_eligibility_mentions(values, lookup)
        if len(mentions) <= 1 or (row.get("named_alternatives") or []):
            normalized_rows.append(row)
            continue

        original_fact = compact_whitespace(
            row.get("eligibility_name") or row.get("matched_candidate_fact")
        ).casefold()
        original_canonical = lookup.get(original_fact, "").casefold() if original_fact else ""
        for canonical in mentions:
            fact_value = (eligibility_fact_values or {}).get(canonical.casefold())
            status = row.get("status") if canonical.casefold() == original_canonical else "not_shown"
            if fact_value is True:
                status = "supported"
            elif fact_value is False:
                status = "not_shown"
            atomic = dict(row)
            atomic.update(
                requirement=canonical,
                canonical_requirement=canonical,
                matched_candidate_fact=canonical,
                eligibility_name=canonical,
                capability_name="",
                covered_requirement_elements=[canonical],
                profile_action_allowed=False,
                status=status,
            )
            normalized_rows.append(atomic)
        logger.warning(
            "[LLM][COVERAGE] split compound eligibility row requirement=%r facts=%s",
            row.get("requirement"),
            ", ".join(mentions),
        )
    return normalized_rows


def _merge_requirement_coverage(
    eligibility_rows: list[dict[str, Any]],
    general_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge dedicated eligibility rows before general coverage without duplicates."""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in [*eligibility_rows, *general_rows]:
        canonical = compact_whitespace(row.get("canonical_requirement")).casefold()
        requirement = compact_whitespace(row.get("requirement")).casefold()
        key = (str(row.get("requirement_type") or "").strip().lower(), canonical or requirement)
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged


def normalize_llm_requirement_coverage(
    value: Any,
    valid_capability_names: dict[str, str] | None = None,
    valid_eligibility_names: dict[str, str] | None = None,
    valid_qualification_names: dict[str, str] | None = None,
    role_experience: list[dict[str, Any]] | None = None,
    eligibility_fact_values: dict[str, bool] | None = None,
    max_items: int | None = None,
    include_debug_match_diagnostics: bool = False,
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

    valid_capability_lookup = _build_valid_capability_lookup(valid_capability_names)
    valid_eligibility_lookup = _build_valid_eligibility_lookup(valid_eligibility_names)
    valid_qualification_lookup = _build_valid_qualification_lookup(valid_qualification_names)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    non_eligibility_count = 0
    for item in value:
        if not isinstance(item, dict):
            continue
        requirement = _clean_job_requirement_text(
            item.get("requirement") or item.get("job_requirement") or item.get("text")
        )
        matched_job_text = compact_whitespace(
            item.get("matched_job_text") or item.get("matched_text")
        )
        raw_importance = compact_whitespace(item.get("importance")).lower()
        importance = (
            raw_importance if raw_importance in LLM_ALLOWED_COVERAGE_IMPORTANCES else "preferred"
        )
        status = compact_whitespace(item.get("status")).lower()
        raw_requirement_type = compact_whitespace(
            item.get("requirement_type") or item.get("type")
        ).lower()
        requirement_type_before = raw_requirement_type or "capability"
        status_before = status
        if raw_requirement_type:
            llm_requirement_type = raw_requirement_type
            llm_requirement_type_is_valid = (
                llm_requirement_type in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES
            )
        else:
            llm_requirement_type = "capability"
            llm_requirement_type_is_valid = True

        if llm_requirement_type_is_valid:
            # Deterministic validation runs regardless of what the LLM answered —
            # the LLM's classification is a proposal, not a source of truth.
            requirement_type = classify_requirement_type(
                requirement, matched_job_text, llm_requirement_type
            )
            requirement_type_is_valid = (
                requirement_type in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES
            )
            if requirement_type != llm_requirement_type:
                _record_requirement_coverage_warning(
                    requirement=requirement,
                    importance=importance,
                    requirement_type_before=requirement_type_before,
                    requirement_type_after=requirement_type,
                    status_before=status_before,
                    status_after=status,
                    proposed_matched_candidate_fact="",
                    proposed_capability_name="",
                    proposed_eligibility_name="",
                    matched_job_text=matched_job_text,
                    reason=(
                        "deterministic_classification_uncertain"
                        if requirement_type == LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE
                        else "deterministic_classification_override"
                    ),
                )
        else:
            requirement_type = LLM_INVALID_COVERAGE_REQUIREMENT_TYPE
            requirement_type_is_valid = False
        canonical_requirement = normalize_profile_item_name(item.get("canonical_requirement"))
        # Whether canonical_requirement resolves to a genuine single concept
        # (vs. the ad sentence restated) is a language-understanding question,
        # not a structural one — deterministic code must not guess it from
        # text equality (e.g. "Java" legitimately equals its own canonical
        # name). Trust the LLM's own explicit judgement instead.
        profile_fact_resolved = bool(item.get("profile_fact_resolved"))
        raw_named_alternatives = item.get("named_alternatives") or []
        if isinstance(raw_named_alternatives, str):
            raw_named_alternatives = [raw_named_alternatives]
        named_alternatives: list[str] = []
        if isinstance(raw_named_alternatives, list):
            seen_alternatives: set[str] = set()
            for text in raw_named_alternatives:
                cleaned_alternative = compact_whitespace(text)
                lowered_alternative = cleaned_alternative.lower()
                if not cleaned_alternative or lowered_alternative in seen_alternatives:
                    continue
                seen_alternatives.add(lowered_alternative)
                named_alternatives.append(cleaned_alternative)
        # canonical_requirement is a display/interpretation label only — it is
        # not proof the row is one safe factual profile candidate. Per the
        # named_alternatives field contract, ANY named alternative (not just
        # more than one) means the ad posed a disjunctive/example clause
        # rather than one atomic concept. profile_fact_resolved is the LLM's
        # own explicit confirmation that canonical_requirement is a genuinely
        # resolved concept, not restated ad prose. All three must hold for
        # profile-learning actions to be safe.
        profile_action_allowed = (
            bool(canonical_requirement) and not named_alternatives and profile_fact_resolved
        )
        matched_candidate_fact_raw = item.get("matched_candidate_fact") or item.get("profile_name")
        if not matched_candidate_fact_raw:
            matched_candidate_fact_raw = item.get("capability_name") or item.get("eligibility_name")
        matched_candidate_fact = compact_whitespace(matched_candidate_fact_raw)
        capability_name = ""
        eligibility_name = ""
        qualification_name = ""
        if requirement_type_is_valid and requirement_type == "eligibility":
            eligibility_name = (
                valid_eligibility_lookup.get(matched_candidate_fact.lower(), "")
                if valid_eligibility_lookup is not None
                else matched_candidate_fact.lower()
            )
            matched_candidate_fact = eligibility_name or matched_candidate_fact
        elif requirement_type_is_valid and requirement_type == "qualification":
            if importance not in {LLM_COVERAGE_IMPORTANCE_REQUIRED, LLM_COVERAGE_IMPORTANCE_PREFERRED}:
                importance = LLM_COVERAGE_IMPORTANCE_PREFERRED
            qualification_name = (
                valid_qualification_lookup.get(matched_candidate_fact.lower(), "")
                if valid_qualification_lookup is not None
                else matched_candidate_fact
            )
            matched_candidate_fact = qualification_name or matched_candidate_fact
        elif requirement_type_is_valid:
            capability_name = (
                valid_capability_lookup.get(matched_candidate_fact.lower(), "")
                if valid_capability_lookup is not None
                else matched_candidate_fact.lower()
            )
            matched_candidate_fact = capability_name or matched_candidate_fact
        elif requirement_type == LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE:
            logger.debug(
                "[LLM][COVERAGE] purpose=fit_review uncertain_requirement_type requirement=%r status=%s importance=%s",
                requirement,
                status,
                importance,
            )
            status = LLM_INVALID_COVERAGE_STATUS
        else:
            logger.warning(
                "[LLM][WARN] purpose=fit_review invalid_requirement_type requirement=%r requirement_type=%r status=%s importance=%s",
                requirement,
                raw_requirement_type,
                status,
                importance,
            )
            status = LLM_INVALID_COVERAGE_STATUS
        match_source = ""
        matched_profile_term = ""
        if include_debug_match_diagnostics:
            raw_match_source = compact_whitespace(item.get("match_source")).lower()
            if raw_match_source in LLM_ALLOWED_COVERAGE_MATCH_SOURCES:
                match_source = raw_match_source
            matched_profile_term = compact_whitespace(item.get("matched_profile_term"))
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
        raw_covered_elements = item.get("covered_requirement_elements") or []
        if isinstance(raw_covered_elements, str):
            raw_covered_elements = [raw_covered_elements]
        covered_requirement_elements = [
            compact_whitespace(value)
            for value in raw_covered_elements
            if compact_whitespace(value)
        ] if isinstance(raw_covered_elements, list) else []
        role_defining = bool(item.get("role_defining"))
        role_defining_group = compact_whitespace(item.get("role_defining_group"))
        if not requirement:
            continue
        known_eligibility_mentions: list[str] = []
        if requirement_type == "eligibility":
            known_eligibility_mentions = _known_profile_eligibility_mentions(
                [*covered_requirement_elements, requirement, matched_job_text],
                valid_eligibility_lookup,
            )
            if len(known_eligibility_mentions) == 1 and not eligibility_name:
                eligibility_name = known_eligibility_mentions[0]
                matched_candidate_fact = eligibility_name
                fact_value = (eligibility_fact_values or {}).get(eligibility_name.casefold())
                if fact_value is True:
                    status = "supported"
                elif fact_value is False:
                    status = "not_shown"
        if (
            requirement_type == "capability"
            and status in {"supported", "partially_supported"}
            and not capability_name
        ):
            recovered_capability = _recover_capability_from_profile_support(
                profile_support,
                valid_capability_lookup,
            )
            if recovered_capability:
                capability_name = recovered_capability
                matched_candidate_fact = recovered_capability
                logger.debug(
                    "[LLM][COVERAGE] recovered canonical capability=%r from profile_support for requirement=%r",
                    recovered_capability,
                    requirement,
                )
        if status not in _ALLOWED_REQUIREMENT_COVERAGE_STATUSES:
            if importance != LLM_COVERAGE_IMPORTANCE_REQUIRED:
                continue
            # Required wording is never discarded just because the model
            # returned an invalid/unknown status. It remains visible as an
            # unresolved item and cannot contribute support to scoring.
            status = LLM_INVALID_COVERAGE_STATUS
            matched_candidate_fact = ""
            capability_name = ""
            eligibility_name = ""
        if requirement_type == LLM_INVALID_COVERAGE_REQUIREMENT_TYPE:
            _record_requirement_coverage_warning(
                requirement=requirement,
                importance=importance,
                requirement_type_before=requirement_type_before,
                requirement_type_after=requirement_type,
                status_before=status_before,
                status_after=status,
                proposed_matched_candidate_fact=matched_candidate_fact,
                proposed_capability_name=capability_name,
                proposed_eligibility_name=eligibility_name,
                matched_job_text=matched_job_text,
                reason="invalid_requirement_type",
            )
            matched_candidate_fact = ""
            capability_name = ""
            eligibility_name = ""
        if (
            requirement_type == "eligibility"
            and status in {"supported", "partially_supported"}
            and not eligibility_name
            and not known_eligibility_mentions
        ):
            logger.warning(
                "[LLM][WARN] purpose=fit_review requirement_coverage_missing_eligibility requirement=%r status=%s importance=%s",
                requirement,
                status,
                importance,
            )
            _record_requirement_coverage_warning(
                requirement=requirement,
                importance=importance,
                requirement_type_before=requirement_type_before,
                requirement_type_after=requirement_type,
                status_before=status_before,
                status_after="not_shown",
                proposed_matched_candidate_fact=matched_candidate_fact,
                proposed_capability_name=capability_name,
                proposed_eligibility_name=eligibility_name,
                matched_job_text=matched_job_text,
                reason="invalid_eligibility_match",
            )
            status = "not_shown"
            matched_candidate_fact = ""
            capability_name = ""
            eligibility_name = ""
        if requirement_type == "qualification" and status in {"supported", "partially_supported"} and not qualification_name:
            logger.warning(
                "[LLM][WARN] purpose=fit_review requirement_coverage_missing_qualification requirement=%r status=%s importance=%s",
                requirement,
                status,
                importance,
            )
            _record_requirement_coverage_warning(
                requirement=requirement,
                importance=importance,
                requirement_type_before=requirement_type_before,
                requirement_type_after=requirement_type,
                status_before=status_before,
                status_after="not_shown",
                proposed_matched_candidate_fact=matched_candidate_fact,
                proposed_capability_name=capability_name,
                proposed_eligibility_name=qualification_name,
                matched_job_text=matched_job_text,
                reason="invalid_qualification_match",
            )
            status = "not_shown"
            matched_candidate_fact = ""
            qualification_name = ""
        if requirement_type == "capability" and status in {"supported", "partially_supported"} and not capability_name:
            logger.warning(
                "[LLM][WARN] purpose=fit_review requirement_coverage_missing_capability requirement=%r status=%s importance=%s",
                requirement,
                status,
                importance,
            )
            _record_requirement_coverage_warning(
                requirement=requirement,
                importance=importance,
                requirement_type_before=requirement_type_before,
                requirement_type_after=requirement_type,
                status_before=status_before,
                status_after="not_shown",
                proposed_matched_candidate_fact=matched_candidate_fact,
                proposed_capability_name=capability_name,
                proposed_eligibility_name=eligibility_name,
                matched_job_text=matched_job_text,
                reason="invalid_capability_match",
            )
            status = "not_shown"
            matched_candidate_fact = ""
            capability_name = ""
            eligibility_name = ""
        preliminary_experience_requirement = resolve_role_experience_requirement(
            requirement,
            matched_job_text,
            role_experience,
        )
        role_history_proves_requirement = bool(
            preliminary_experience_requirement
            and preliminary_experience_requirement.get("matched_role_experience_title")
        )
        if (
            requirement_type == "capability"
            and status in {"supported", "partially_supported"}
            and not role_history_proves_requirement
            and not _has_meaningful_requirement_evidence(
                requirement,
                matched_job_text,
                matched_candidate_fact,
                profile_support,
                covered_requirement_elements,
            )
        ):
            _record_requirement_coverage_warning(
                requirement=requirement,
                importance=importance,
                requirement_type_before=requirement_type_before,
                requirement_type_after=requirement_type,
                status_before=status_before,
                status_after="not_shown",
                proposed_matched_candidate_fact=matched_candidate_fact,
                proposed_capability_name=capability_name,
                proposed_eligibility_name=eligibility_name,
                matched_job_text=matched_job_text,
                reason="generic_transferable_capability_not_requirement_evidence",
            )
            status = "not_shown"
            matched_candidate_fact = ""
            capability_name = ""
            profile_support = []
            covered_requirement_elements = []
        key = requirement.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized_item = {
            "requirement": requirement,
            "importance": importance,
            "requirement_type": requirement_type,
            "canonical_requirement": canonical_requirement,
            # Renderer must gate Add-to-profile / future "I don't have this"
            # actions on this, not on canonical_requirement truthiness alone.
            "profile_action_allowed": profile_action_allowed,
            "status": status,
            "matched_candidate_fact": matched_candidate_fact,
            "capability_name": capability_name,
            "eligibility_name": eligibility_name,
            "matched_job_text": matched_job_text,
            "profile_support": profile_support,
        }
        if named_alternatives:
            normalized_item["named_alternatives"] = named_alternatives
        if qualification_name:
            normalized_item["qualification_name"] = qualification_name
        if covered_requirement_elements:
            normalized_item["covered_requirement_elements"] = covered_requirement_elements
        if role_defining:
            normalized_item["role_defining"] = True
        if role_defining_group:
            normalized_item["role_defining_group"] = role_defining_group
        if requirement_type == LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE:
            # Retained only so the pending-review signal can offer the LLM's
            # own (unverified) guess as the default suggested classification.
            normalized_item["llm_proposed_requirement_type"] = llm_requirement_type
        if include_debug_match_diagnostics:
            normalized_item["match_source"] = match_source
            normalized_item["matched_profile_term"] = matched_profile_term
        experience_requirement = preliminary_experience_requirement
        if experience_requirement:
            normalized_item.update(experience_requirement)
            if not normalized_item.get("matched_role_experience_title"):
                normalized_item["experience_requirement_review_needed"] = True
            if (
                normalized_item["status"] == "supported"
                and (
                    not normalized_item.get("matched_role_experience_title")
                    or int(normalized_item.get("matched_role_experience_months") or 0)
                    < int(normalized_item["required_experience_months"])
                )
            ):
                normalized_item["status"] = "partially_supported"
        if requirement_type != "eligibility":
            if non_eligibility_count >= max_items:
                continue
            non_eligibility_count += 1
        results.append(normalized_item)
    return _atomicize_known_eligibility_rows(
        results,
        valid_eligibility_names,
        eligibility_fact_values,
    )


def derive_fit_review_grade(
    requirement_coverage: list[dict[str, Any]],
    job_requirements: list[str] | None = None,
) -> str:
    """Derive grade from importance-weighted requirement coverage.

    Importance weights: required=3, expected=2, preferred=1, bonus=0.25.
    Any mismatch caps at WEAK. required+not_shown lowers the ratio but does not auto-reject,
    except an unresolved required eligibility fact (e.g. clearance, work rights), which also
    caps at WEAK — eligibility is a boolean gate, not a gradeable capability, so an unknown
    required eligibility fact must not be diluted away by unrelated supported requirements.
    Items without an importance field default to 'preferred' (weight 1.0).
    """
    total_items = max(len(requirement_coverage), len(job_requirements or []))
    if total_items <= 0:
        return "POOR"

    supported_count = 0
    partial_count = 0
    mismatch_count = 0
    required_eligibility_unresolved = False
    support_score = 0.0
    max_score = 0.0

    for item in requirement_coverage:
        status = str(item.get("status") or "").strip().lower()
        importance = str(item.get("importance") or "preferred").strip().lower()
        requirement_type = str(item.get("requirement_type") or "capability").strip().lower()
        weight = _IMPORTANCE_WEIGHTS.get(importance, _IMPORTANCE_WEIGHTS["preferred"])

        if status == "supported":
            supported_count += 1
            support_score += weight
        elif status == "partially_supported":
            partial_count += 1
            support_score += weight * 0.5
        elif status == "mismatch":
            mismatch_count += 1
        elif (
            status == "not_shown"
            and importance == LLM_COVERAGE_IMPORTANCE_REQUIRED
            and requirement_type in {"eligibility", "qualification"}
        ):
            required_eligibility_unresolved = True
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

    if required_eligibility_unresolved:
        return "WEAK"

    support_ratio = support_score / max_score if max_score > 0 else 0

    if supported_count == total_items and partial_count == 0:
        return "EXCELLENT" if total_items >= 3 else "STRONG"

    if support_ratio >= 0.8 and partial_count <= 1 and supported_count >= max(2, total_items - 1):
        return "STRONG"

    if support_ratio >= 0.5:
        return "SOLID"

    return "WEAK"


def has_eligibility_mismatch(requirement_coverage: list[dict[str, Any]]) -> bool:
    """Return True when a required boolean qualification/eligibility gate mismatches.

    Eligibility facts (clearance, work rights, etc.) are boolean gating facts, not
    gradeable capabilities: a mismatch means the candidate is not eligible, so this
    must force a hard reject regardless of the LLM's own decision or overall grade.
    """
    return any(
        (
            str(item.get("requirement_type") or "").strip().lower() == "eligibility"
            or (
                str(item.get("requirement_type") or "").strip().lower() == "qualification"
                and str(item.get("importance") or "").strip().lower() == LLM_COVERAGE_IMPORTANCE_REQUIRED
            )
        )
        and str(item.get("status") or "").strip().lower() == "mismatch"
        for item in requirement_coverage
    )


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


def _normalize_llm_occupation_alignment(value: Any) -> str:
    """Normalize the LLM's occupation_alignment classification to a validated value or an invalid sentinel.

    occupation_alignment never blocks a KEEP (see has_complete_llm_keep_data) — an invalid or
    missing classification degrades to LLM_INVALID_OCCUPATION_ALIGNMENT rather than raising, and
    is treated as a zero-adjustment "needs review" entry by the scoring layer.
    """
    cleaned = compact_whitespace(value).lower()
    if cleaned in LLM_ALLOWED_OCCUPATION_ALIGNMENTS:
        return cleaned
    logger.warning(
        "[LLM][WARN] purpose=fit_review invalid_occupation_alignment occupation_alignment=%r",
        value,
    )
    return LLM_INVALID_OCCUPATION_ALIGNMENT


def _normalize_llm_posting_channel(value: Any) -> dict[str, Any]:
    """Normalize the LLM's posting_channel classification to a validated dict.

    An invalid or missing kind degrades to LLM_INVALID_POSTING_CHANNEL_KIND rather than
    raising — posting channel never blocks a KEEP, it only drives the source badge shown
    in the workspace UI.
    """
    payload = value if isinstance(value, dict) else {}
    kind = compact_whitespace(payload.get("kind")).lower()
    if kind not in LLM_ALLOWED_POSTING_CHANNEL_KINDS:
        if kind:
            logger.warning(
                "[LLM][WARN] purpose=fit_review invalid_posting_channel_kind kind=%r",
                payload.get("kind"),
            )
        kind = LLM_INVALID_POSTING_CHANNEL_KIND
    return {
        "kind": kind,
        "confident": bool(payload.get("confident")),
        "evidence": _normalize_llm_review_text(payload.get("evidence"), max_chars=200),
    }


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
    value: Any,
    valid_capability_names: dict[str, str] | None = None,
    valid_eligibility_names: dict[str, str] | None = None,
    valid_qualification_names: dict[str, str] | None = None,
    role_experience: list[dict[str, Any]] | None = None,
    eligibility_fact_values: dict[str, bool] | None = None,
) -> dict[str, Any]:
    include_debug_match_diagnostics = get_llm_fit_review_debug_match_diagnostics_enabled()
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
            eligibility_requirements = normalize_llm_requirement_coverage(
                value.get("eligibility_requirements"),
                valid_capability_names=valid_capability_names,
                valid_eligibility_names=valid_eligibility_names,
                valid_qualification_names=valid_qualification_names,
                role_experience=role_experience,
                eligibility_fact_values=eligibility_fact_values,
                include_debug_match_diagnostics=include_debug_match_diagnostics,
            )
            requirement_coverage = normalize_llm_requirement_coverage(
                value.get("requirement_coverage"),
                valid_capability_names=valid_capability_names,
                valid_eligibility_names=valid_eligibility_names,
                valid_qualification_names=valid_qualification_names,
                role_experience=role_experience,
                eligibility_fact_values=eligibility_fact_values,
                include_debug_match_diagnostics=include_debug_match_diagnostics,
            )
            requirement_coverage = _merge_requirement_coverage(
                eligibility_requirements,
                requirement_coverage,
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
            # Coverage is the source of truth for grade when it exists; the model's raw
            # grade is only a fallback when there's no coverage to derive a grade from.
            grade_to_use = (
                derived_grade if requirement_coverage else fit_review_normalized["grade"]
            )
            # Count by importance × status for structured logging.
            _imp_status: dict[str, int] = {}
            for _item in requirement_coverage:
                _key = f"{_item.get('importance', 'preferred')}.{_item.get('status', 'not_shown')}"
                _imp_status[_key] = _imp_status.get(_key, 0) + 1
            _imp_status_str = " ".join(f"{k}={v}" for k, v in sorted(_imp_status.items()))
            logger.debug(
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
            decision_to_use = fit_review_normalized["decision"]
            # Normalized coverage is authoritative: a derived MISMATCH cannot remain KEEP/MAYBE.
            # This prevents model optimism from contradicting the deterministic final fit grade.
            if grade_to_use == "MISMATCH" and decision_to_use != "REJECT":
                logger.warning(
                    "[LLM][FIT_DECISION] purpose=fit_review model_decision=%s overridden_to=REJECT"
                    " reason=derived_grade_mismatch",
                    decision_to_use,
                )
                decision_to_use = "REJECT"
            if has_eligibility_mismatch(requirement_coverage) and decision_to_use != "REJECT":
                logger.warning(
                    "[LLM][ELIGIBILITY_GATE] purpose=fit_review model_decision=%s overridden_to=REJECT"
                    " reason=eligibility_mismatch",
                    decision_to_use,
                )
                decision_to_use = "REJECT"
            return {
                "fit_review": {
                    **fit_review_normalized,
                    "decision": decision_to_use,
                    "grade": grade_to_use,
                },
                "occupation_alignment": _normalize_llm_occupation_alignment(
                    value.get("occupation_alignment")
                ),
                "occupation_alignment_reason": _normalize_llm_review_text(
                    value.get("occupation_alignment_reason"), max_chars=300
                ),
                "posting_channel": _normalize_llm_posting_channel(value.get("posting_channel")),
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
        logger.debug(
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
        logger.debug(
            "[LLM][RESULT] purpose=rejection_suggestions raw=%r",
            raw_output[: get_llm_raw_output_log_max_chars()],
        )
    logger.debug("[LLM][RESULT] purpose=rejection_suggestions normalized=%s", suggestions)
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
        logger.debug(
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
    debug_match_diagnostics = (
        fit_review and get_llm_fit_review_debug_match_diagnostics_enabled()
    )
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
                (
                    f"Return exactly this shape: {LLM_FIT_REVIEW_DEBUG_PROMPT_SHAPE}"
                    if debug_match_diagnostics
                    else f"Return exactly this shape: {LLM_FIT_REVIEW_PROMPT_SHAPE}"
                ),
                build_requirement_coverage_guidance(),
                build_requirement_coverage_debug_guidance() if debug_match_diagnostics else "",
                build_fit_review_grade_guidance(),
                build_occupation_alignment_guidance(),
                build_posting_channel_guidance(),
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

    include_debug_match_diagnostics = (
        fit_review and get_llm_fit_review_debug_match_diagnostics_enabled()
    )
    valid_capability_names: dict[str, str] | None = None
    valid_eligibility_names: dict[str, str] | None = None
    valid_qualification_names: dict[str, str] | None = None
    eligibility_fact_values: dict[str, bool] | None = None
    if fit_review:
        profile = load_profile()
        valid_capability_names = {}
        for rule in profile.get(KEY_CANDIDATE_CAPABILITIES, []) or []:
            if not isinstance(rule, dict):
                continue
            canonical = str(rule.get("name") or "").strip()
            if not canonical:
                continue
            for term in [canonical, *(rule.get("aliases") or [])]:
                normalized_term = str(term or "").strip().lower()
                if normalized_term:
                    valid_capability_names[normalized_term] = canonical
        valid_eligibility_names = _build_profile_eligibility_names(profile)
        eligibility_fact_values = _build_profile_eligibility_values(profile)
        valid_qualification_names = {}
        for rule in profile.get(KEY_CANDIDATE_QUALIFICATIONS, []) or []:
            if not isinstance(rule, dict):
                continue
            canonical = str(rule.get("name") or "").strip()
            if not canonical:
                continue
            for term in [canonical, *(rule.get("aliases") or [])]:
                normalized_term = str(term or "").strip().lower()
                if normalized_term:
                    valid_qualification_names[normalized_term] = canonical
        role_experience = profile.get(KEY_ROLE_EXPERIENCE, [])
        if not valid_capability_names:
            raise ValueError(
                "Fit review cannot run because the candidate profile has no capability rules "
                "(candidate_capabilities is empty). Complete onboarding or seed the profile first."
            )
    else:
        role_experience = None

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
            logger.debug(
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
                text_format=(
                    _LLMFitReviewDebugPayload
                    if include_debug_match_diagnostics
                    else (_LLMFitReviewPayload if fit_review else _LLMReviewPayload)
                ),
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
        parsed.model_dump(),
        valid_capability_names=valid_capability_names,
        valid_eligibility_names=valid_eligibility_names,
        valid_qualification_names=valid_qualification_names,
        role_experience=role_experience,
        eligibility_fact_values=eligibility_fact_values,
    )
    payload.update(_llm_usage_summary(resp, model))
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
        logger.debug(
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
        logger.debug(
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
        logger.debug(
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

    logger.debug(
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
    candidate_capabilities: list[str] | None = None,
    *,
    explore_adjacent_roles: bool = False,
    llm_client: Any = None,
) -> dict[str, Any] | None:
    """Decide whether a near/uncertain title should reach full description review.

    Strict mode judges only against preferred/alternative role lists. Exploration mode may also
    use candidate capability names to avoid rejecting plausible adjacent titles merely because
    the exact title is unlisted. This function never scores or accepts the job; it only returns
    match/no_match/uncertain for the pre-detail gate. LLM failure or unparseable output returns
    None, which callers must treat like uncertain rather than hard-rejecting the job.
    """
    active_client = llm_client or client
    title = str(title or "").strip()
    if active_client is None or not title:
        return None

    target_roles = [str(r).strip() for r in (target_roles or []) if str(r).strip()]
    secondary_roles = [str(r).strip() for r in (secondary_roles or []) if str(r).strip()]
    candidate_capabilities = [
        str(value).strip() for value in (candidate_capabilities or []) if str(value).strip()
    ]
    if not target_roles and not secondary_roles:
        return None

    if explore_adjacent_roles:
        system_prompt = "\n".join(
            [
                "You are a conservative cheap pre-filter deciding whether a job title can be ruled out before the full job description is fetched.",
                f"Preferred role directions: {', '.join(target_roles) or 'none'}",
                f"Other explicitly interesting role directions: {', '.join(secondary_roles) or 'none'}",
                f"Candidate capability signals: {', '.join(candidate_capabilities) or 'none provided'}",
                "The role lists are positive direction signals, NOT an exhaustive whitelist of acceptable job titles.",
                f"Return JSON only, shape: {LLM_TITLE_JUDGMENT_SHAPE}",
                "verdict=match: the title clearly matches a preferred/interesting direction or is an obvious close variant.",
                "verdict=no_match: use only when the title itself clearly identifies a different profession, function, seniority, or specialisation that the candidate profile does not plausibly support.",
                "verdict=uncertain: use for unfamiliar or adjacent titles where the candidate's capabilities could plausibly transfer and the job description could change the answer.",
                "Do not reject merely because the exact title is absent from the preferred/interesting role lists.",
                "Judge only what the title supports. Do not invent duties that are not implied by the title.",
            ]
        )
    else:
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
        logger.debug(
            "[LLM][REQUEST] purpose=title_judgment model=%s input_chars=%d max_output_tokens=%d",
            model,
            len(title),
            max_output_tokens,
        )
        resp = active_client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f'Job title: "{title}"'},
            ],
            max_output_tokens=max_output_tokens,
            text_format=_LLMTitleJudgment,
        )
        _log_llm_call(resp, "title_judgment", model)
    except Exception as exc:
        logger.error("[LLM][FAIL] purpose=title_judgment error=%s", exc)
        return None

    parsed = getattr(resp, "output_parsed", None)
    if parsed is None:
        logger.warning("[LLM][WARN] purpose=title_judgment parsed_output_missing")
        return None

    payload = parsed.model_dump()
    verdict = str(payload.get("verdict") or "").strip().lower()
    reason = str(payload.get("reason") or "").strip()
    if verdict not in LLM_ALLOWED_TITLE_JUDGMENT_VERDICTS:
        logger.warning("[LLM][WARN] purpose=title_judgment invalid_verdict=%r", verdict)
        return None

    logger.debug(
        "[LLM][RESULT] purpose=title_judgment title=%r verdict=%s reason=%r",
        title,
        verdict,
        reason,
    )
    return {"verdict": verdict, "reason": reason}


def get_cost_summary() -> dict[str, Any]:
    """Read the LLM ledger and return per-purpose and lifetime totals."""
    totals: dict[str, dict[str, Any]] = {}
    grand_input_tokens = 0
    grand_output_tokens = 0
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
                grand_input_tokens += int(entry.get("tok_in", 0) or 0)
                grand_output_tokens += int(entry.get("tok_out", 0) or 0)
    except FileNotFoundError:
        pass
    grand = sum(v["cost_usd"] for v in totals.values())
    return {
        "by_purpose": totals,
        "grand_total_usd": round(grand, 6),
        "grand_input_tokens": grand_input_tokens,
        "grand_output_tokens": grand_output_tokens,
    }
