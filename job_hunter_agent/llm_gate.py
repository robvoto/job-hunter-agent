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

import hashlib
import json as _json_mod
import os
import re
import sys
from typing import Any, Dict

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

from job_hunter_agent.user_settings import load_user_settings, DEFAULT_USER_SETTINGS
from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_DECISIONS,
    LLM_ALLOWED_GRADES,
    LLM_PROMPT_CAPABILITY_LEVELS_HEADER,
    LLM_PROMPT_CAPABILITY_NAMING_INTRO,
    LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER,
    LLM_PROMPT_CLUSTERS_HEADER,
    LLM_PROMPT_CONTEXTUAL_CAPABILITY_INTRO,
    LLM_PROMPT_DEFAULT_CAPABILITY_NAMING_GUIDANCE_HEADER,
    LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER,
    LLM_PROMPT_DO_NOT_INVENT,
    LLM_PROMPT_DO_NOT_SAVE,
    LLM_PROMPT_JOB_DESCRIPTION_PREFIX,
    LLM_PROMPT_JOB_REQUIREMENTS_INTRO,
    LLM_PROMPT_JSON_ONLY,
    LLM_PROMPT_LEARNING_PENDING_ONLY,
    LLM_PROMPT_MATCH_PREFERENCES_HEADER,
    LLM_PROMPT_NO_FIT_DECISION_REQUIRED,
    LLM_PROMPT_REVIEW_OUTPUT_FORMAT,
    LLM_PROMPT_ROLE_TITLE_PATTERN_GUIDANCE,
    LLM_PROMPT_SYSTEM_REVIEW_INTRO,
    LLM_PROMPT_USE_VISIBLE_STRINGS,

    LLM_FIT_REVIEW_PROMPT_SHAPE,
    LLM_JOB_REQUIREMENTS_PROMPT_SHAPE,
    LLM_LEARNING_ONLY_PROMPT_SHAPE,
    LLM_REVIEW_GRADE_GUIDANCE,
    LLM_REJECTION_SUGGESTIONS_JSON_SHAPE,
    LLM_SECTION_LABEL_CLASSIFICATION_SHAPE,
)
from job_hunter_agent.hard_blocker_rules import normalize_rejection_blocker_suggestions as _normalize_rejection_blocker_suggestions
from job_hunter_agent.global_settings import (
    KEY_LLM_PRICING_PER_1M,
    KEY_LLM_SETTINGS,
    KEY_LLM_PROMPT_EVIDENCE_TIERS,
    KEY_LLM_PROMPT_SETTINGS,
    KEY_LLM_PROMPT_TEMPLATES,
    get_llm_capability_naming_aliases_max_items,
    get_llm_capability_naming_max_output_tokens,
    get_llm_capability_rule_aliases_max_items,
    get_llm_capability_rules_max_items,
    get_llm_contextual_matches_max_items,
    get_llm_fit_decision_max_output_tokens,

    get_llm_job_description_max_chars,
    get_llm_job_requirements_max_items,
    get_llm_learning_candidates_max_items,
    get_llm_learning_candidates_max_output_tokens,
    get_llm_profile_brief_max_chars,
    get_llm_raw_output_log_max_chars,
    get_llm_rejection_blocker_suggestions_max_items,
    get_llm_rejection_blocker_suggestions_max_output_tokens,
    get_llm_rejection_blocker_suggestions_max_words,
    load_global_settings,
)
from job_hunter_agent.paths import (
    FIT_REVIEW_DEFAULTS_PATH as _FIT_REVIEW_DEFAULTS_PATH,
    LLM_CAPABILITY_NAMING_DEFAULTS_PATH as _CAPABILITY_NAMING_DEFAULTS_PATH,
    LLM_COSTS_PATH as _LLM_COSTS_PATH,
    get_profile_path as _get_profile_path,
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
    LEARNING_SIGNAL_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_SUGGESTED_VALUES_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    PATTERN_SIGNAL_CATEGORIES,
    VALID_SIGNAL_CATEGORIES,
)
# Import at module level to allow monkeypatching in tests
from job_hunter_agent.profile_store import (
    get_candidate_profile_tier_weights,
    get_candidate_profile_tiers,
    load_profile,
)

load_dotenv()

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


def _get_llm_prompt_settings() -> dict[str, Any]:
    prompt_settings = load_global_settings().get(KEY_LLM_SETTINGS, {}).get(KEY_LLM_PROMPT_SETTINGS, {})
    if not isinstance(prompt_settings, dict) or not prompt_settings:
        raise ValueError("No LLM prompt settings are configured in Admin.")
    return prompt_settings


def _log_llm_call(resp: Any, purpose: str, model: str) -> None:
    global _session_cost_usd
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    # Responses API uses input_tokens/output_tokens; Chat uses prompt_tokens/completion_tokens
    tok_in  = getattr(usage, "input_tokens",  None) or getattr(usage, "prompt_tokens",     0) or 0
    tok_out = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens",  0) or 0
    prices  = _get_llm_pricing_per_1m()[model]
    cost    = (tok_in * prices["input"] + tok_out * prices["output"]) / 1_000_000
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


def get_session_cost_usd() -> float:
    return round(_session_cost_usd, 6)


def reset_session_cost() -> None:
    global _session_cost_usd
    _session_cost_usd = 0.0


def _profile_fingerprint() -> str:
    """Cheap fingerprint of the profile file - mtime + size, no read/parse.
    Cached for the lifetime of the process so repeated cache-key lookups in a
    single scraping run are O(1) after the first call.
    """
    global _profile_fingerprint_cache
    if _profile_fingerprint_cache is not None:
        return _profile_fingerprint_cache
    try:
        st = _get_profile_path().stat()
        raw = f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
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
        print(f"[LLM] Model: {model}  (source: user settings)")
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


class _LLMContextualCapabilityMatch(BaseModel):
    capability_name: str
    confidence: str
    matched_text: str
    reason: str


class _LLMJobRequirementsPayload(BaseModel):
    job_requirements: list[str] = Field(default_factory=list)


class _LLMReviewPayload(BaseModel):
    fit_review: _LLMReviewDecision | None = None
    learning_candidates: list[_LLMLearningCandidate] = Field(default_factory=list)


class _LLMFitReviewPayload(BaseModel):
    fit_review: _LLMReviewDecision
    contextual_capability_matches: list[_LLMContextualCapabilityMatch] = Field(default_factory=list)
    job_requirements: list[str] = Field(default_factory=list)


_api_key = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=_api_key) if (_api_key and not _NO_LLM_MODE) else None
ALLOWED_LEARNING_CATEGORIES = frozenset(VALID_SIGNAL_CATEGORIES - {CATEGORY_HARD_BLOCKER_PATTERN})


def _load_managed_prompt_lines(path, filename: str) -> tuple[str, ...]:
    payload = _json_mod.loads(path.read_text(encoding="utf-8"))
    lines = payload.get("lines")
    if not isinstance(lines, list):
        raise ValueError(f"{filename} must contain a lines list")
    cleaned = tuple(str(line).strip() for line in lines if str(line).strip())
    if not cleaned:
        raise ValueError(f"{filename} must define at least one prompt line")
    return cleaned


FIT_REVIEW_DEFAULT_LINES = _load_managed_prompt_lines(_FIT_REVIEW_DEFAULTS_PATH, "llm_fit_review_defaults.json")
CAPABILITY_NAMING_DEFAULT_LINES = _load_managed_prompt_lines(_CAPABILITY_NAMING_DEFAULTS_PATH, "llm_capability_naming_defaults.json")


def llm_is_enabled() -> bool:
    return client is not None


def build_profile_prompt_context() -> str:
    from job_hunter_agent.profile_store import (
        KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
        KEY_CAPABILITY_PROFILE_RULES,
    )
    profile = load_profile()
    llm_profile_brief = str(profile.get("llm_profile_brief") or "").strip()
    star_evidence_text = str(profile.get("star_evidence_text") or "").strip()
    evidence_tiers = get_candidate_profile_tiers(profile)
    evidence_weights = get_candidate_profile_tier_weights(profile)
    prompt_settings = _get_llm_prompt_settings()
    prompt_templates = prompt_settings[KEY_LLM_PROMPT_TEMPLATES]
    prompt_evidence_tiers = prompt_settings[KEY_LLM_PROMPT_EVIDENCE_TIERS]
    capability_rules = profile.get(KEY_CAPABILITY_PROFILE_RULES, [])
    salary_preferences = profile.get("salary_preferences", {})
    match_preferences = profile.get("match_preferences", {}) if isinstance(profile.get("match_preferences", {}), dict) else {}

    parts = []
    if llm_profile_brief:
        parts.append(LLM_PROMPT_CANDIDATE_FIT_BRIEF_HEADER)
        parts.append(llm_profile_brief[:get_llm_profile_brief_max_chars()])

    if isinstance(capability_rules, list) and capability_rules:
        parts.append(LLM_PROMPT_CAPABILITY_LEVELS_HEADER)
        for rule in capability_rules[:get_llm_capability_rules_max_items()]:
            if not isinstance(rule, dict):
                continue
            name = str(rule.get("name") or "").strip()
            level = str(rule.get("level") or "").strip()
            fit = str(rule.get("fit") or "").strip()
            raw_aliases = rule.get("aliases", [])
            aliases_list = raw_aliases if isinstance(raw_aliases, list) else []
            aliases = ", ".join(
                str(alias).strip()
                for alias in aliases_list[:get_llm_capability_rule_aliases_max_items()]
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
            preference_lines.append(prompt_templates["compensation_target_yearly"].format(value=minimum_salary_yearly))
        if minimum_daily_rate > 0:
            preference_lines.append(prompt_templates["compensation_target_daily"].format(value=minimum_daily_rate))
    home_location = str(match_preferences.get("home_location") or "").strip()
    if home_location:
        preference_lines.append(prompt_templates["home_location"].format(home_location=home_location))
    if match_preferences.get("prefer_permanent"):
        preference_lines.append(prompt_templates["prefer_permanent"])
    if preference_lines:
        parts.append(LLM_PROMPT_MATCH_PREFERENCES_HEADER)
        parts.extend(f"- {line}" for line in preference_lines)

    # star_evidence_text intentionally excluded from fit-scoring prompt.
    # Field is preserved in profile.json for future application/CV generation.
    # See docs/ARCHITECTURE.md parked decisions.

    primary_evidence = str(evidence_tiers.get(KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT) or "").strip()
    secondary_evidence = str(evidence_tiers.get(KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT) or "").strip()
    background_evidence = str(evidence_tiers.get(KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT) or "").strip()

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
        parts.append(f"{tier_label} ({weight_label} weight {evidence_weights.get(tier_key, tier_weight):.2f}):")
        parts.append(tier_text[:tier_limit])

    return "\n".join(part for part in parts if part)


def build_fit_review_guidance(profile: dict[str, Any] | None = None) -> str:
    parts = [LLM_PROMPT_DEFAULT_FIT_REVIEW_GUIDANCE_HEADER]
    parts.extend(f"- {line}" for line in FIT_REVIEW_DEFAULT_LINES)
    return "\n".join(parts)


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
    desc_hash = hashlib.sha256(str(job_description_text or "").encode("utf-8", errors="ignore")).hexdigest()
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
            raise ValueError(f"LLM fit review decision must be one of {sorted(LLM_ALLOWED_DECISIONS)}: {decision!r}")
        if grade not in LLM_ALLOWED_GRADES:
            raise ValueError(f"LLM fit review grade must be one of {sorted(LLM_ALLOWED_GRADES)}: {grade!r}")
        return {"decision": decision, "grade": grade}

    if isinstance(value, str):
        text = value.strip().upper()
        if "|" not in text:
            raise ValueError("LLM fit review must be DECISION|GRADE")
        decision, _, grade = text.partition("|")
        return _require_fit_review({"decision": decision, "grade": grade})

    raise ValueError(f"LLM fit review must be a dict or DECISION|GRADE string, got {type(value).__name__}")


def normalize_llm_review(value: Any) -> Dict[str, str]:
    return _require_fit_review(value)


def _clean_learning_candidate_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_llm_learning_candidates(value: Any, max_items: int | None = None) -> list[dict[str, Any]]:
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
        signal = _clean_learning_candidate_text(item.get(LEARNING_SIGNAL_KEY) or item.get("value") or item.get("name"))
        category = re.sub(r"[^a-z0-9_]+", "_", _clean_learning_candidate_text(item.get(LEARNING_SUGGESTED_CATEGORY_KEY))).strip("_").lower()
        suggested_values = []
        raw_suggested_values = item.get(LEARNING_SUGGESTED_VALUES_KEY) or item.get("suggested_values") or []
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
        confidence = re.sub(r"\s+", " ", str(item.get(LEARNING_CONFIDENCE_KEY) or item.get("confidence") or "")).strip().lower()
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


_ALLOWED_CONTEXTUAL_CONFIDENCES = frozenset({"high", "medium", "low"})


def normalize_llm_contextual_capability_matches(
    value: Any,
    valid_capability_names: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    results: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        cap_name = re.sub(r"\s+", " ", str(item.get("capability_name") or "")).strip().lower()
        confidence = re.sub(r"\s+", " ", str(item.get("confidence") or "")).strip().lower()
        matched_text = re.sub(r"\s+", " ", str(item.get("matched_text") or "")).strip()
        reason = re.sub(r"\s+", " ", str(item.get("reason") or "")).strip()
        if not cap_name or confidence not in _ALLOWED_CONTEXTUAL_CONFIDENCES:
            continue
        if valid_capability_names is not None and cap_name not in valid_capability_names:
            print(f"[LLM][CONTEXTUAL_CAPABILITY] Unknown capability name ignored: {cap_name!r}")
            continue
        results.append({
            "capability_name": cap_name,
            "confidence": confidence,
            "matched_text": matched_text,
            "reason": reason,
        })
    return results


def _clean_job_requirement_text(value: Any) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
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


def normalize_llm_review_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        fit_review = value.get("fit_review")
        has_explicit_fit_review = isinstance(fit_review, dict) or "decision" in value or "grade" in value
        if has_explicit_fit_review:
            if fit_review is None:
                fit_review = {
                    "decision": value.get("decision"),
                    "grade": value.get("grade"),
                }
            return {
                "fit_review": _require_fit_review(fit_review),
                "learning_candidates": normalize_llm_learning_candidates(value.get("learning_candidates")),
                "contextual_capability_matches": normalize_llm_contextual_capability_matches(
                    value.get("contextual_capability_matches")
                ),
                "job_requirements": normalize_llm_job_requirements(value.get("job_requirements")),
            }

        if "learning_candidates" in value or value.get("learning_only") or "fit_review" in value:
            return {
                "fit_review": None,
                "learning_candidates": normalize_llm_learning_candidates(value.get("learning_candidates")),
                "contextual_capability_matches": [],
                "job_requirements": [],
            }

        raise ValueError("LLM review payload is missing fit_review")

    if isinstance(value, str):
        text = value.strip()
        if "|" in text and not text.lstrip().startswith("{"):
            decision, _, grade = text.strip().upper().partition("|")
            return {
                "fit_review": _require_fit_review({"decision": decision, "grade": grade}),
                "learning_candidates": [],
                "contextual_capability_matches": [],
                "job_requirements": [],
            }
        try:
            parsed = _json_mod.loads(_strip_json_fence(text))
        except Exception:
            raise ValueError("LLM review payload must be JSON or DECISION|GRADE")
        return normalize_llm_review_payload(parsed)

    raise ValueError(f"LLM review payload must be a dict or string, got {type(value).__name__}")


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
        part for part in [
        "You suggest candidate-controlled blocker terms for a job-search assistant.",
        "The user will explicitly approve any suggestion before it is saved. Do not decide or save anything.",
        "Use the candidate profile context to avoid suggesting requirements already evidenced by the candidate.",
        "Suggest only concise blocker terms that appear to be hard requirements for this specific job and are not clearly evidenced by the candidate profile.",
        "Hard blockers can be from any field: credentials, clearances, licences, work authorization, language, location, regulated/domain experience, industry background, products, platforms, tools, or specialist experience.",
        "Do not suggest desirable, preferred, nice-to-have, generic duties, soft skills, broad transferable capabilities, sentence fragments, or broad work verbs.",
            f"{LLM_PROMPT_JSON_ONLY}, in this exact shape: {LLM_REJECTION_SUGGESTIONS_JSON_SHAPE}. Return an empty array if unsure.",
            build_profile_prompt_context(),
        ]
        if part
    )

    try:
        model = _log_llm_model_once()
        resp = active_client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": LLM_PROMPT_JOB_DESCRIPTION_PREFIX
                    + description[:get_llm_job_description_max_chars()],
                },
            ],
            max_output_tokens=get_llm_rejection_blocker_suggestions_max_output_tokens(),
        )
        _log_llm_call(resp, "rejection_suggestions", model)
    except Exception as exc:
        print(f"[LLM][REJECTION_SUGGESTIONS][ERROR] {exc}")
        return []

    suggestions = normalize_rejection_blocker_suggestions(getattr(resp, "output_text", ""))
    raw_output = str(getattr(resp, "output_text", "") or "").strip()
    if raw_output:
        print(
            f"[LLM][REJECTION_SUGGESTIONS][RAW] {raw_output[:get_llm_raw_output_log_max_chars()]}"
        )
    print(f"[LLM][REJECTION_SUGGESTIONS][NORMALIZED] {suggestions}")
    if not suggestions and str(getattr(resp, "output_text", "") or "").strip():
        print(f"[LLM][REJECTION_SUGGESTIONS][UNEXPECTED] {str(resp.output_text).strip()}")
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
        payload.append({
            "seed": seed,
            "aliases": aliases[:get_llm_capability_naming_aliases_max_items()],
        })
    if not payload:
        return []

    prompt = build_capability_naming_guidance()

    try:
        _model = get_llm_model()
        resp = active_client.responses.create(
            model=_model,
            input=[{"role": "user", "content": prompt + _json_mod.dumps(payload, ensure_ascii=False)}],
            max_output_tokens=get_llm_capability_naming_max_output_tokens(),
        )
        _log_llm_call(resp, "capability_naming", _model)
        raw = (resp.output_text or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        labels = _json_mod.loads(raw)
        if not isinstance(labels, list): # Catches any exception during JSON loading
            print(f"[LLM][CAPABILITY_NAMING][WARN] LLM returned non-list for capability naming: {raw[:200]}")
            return []
        return [str(label).strip().lower() for label in labels[: len(payload)]]
    except Exception as exc:
        print(f"[LLM][CAPABILITY_NAMING][ERROR] Failed to name capability clusters: {exc}")
        return []

def llm_should_consider(job_description_text: str) -> Dict[str, str]:
    return normalize_llm_review(llm_should_consider_with_learning(job_description_text).get("fit_review"))


def _build_learning_prompt(job_description_text: str, *, fit_review: bool) -> str:
    parts = [
        "You help decide whether a candidate should apply for a job and identify only pending learning signals.",
        LLM_PROMPT_JSON_ONLY,
        LLM_PROMPT_DO_NOT_SAVE,
        LLM_PROMPT_DO_NOT_INVENT,
        LLM_PROMPT_USE_VISIBLE_STRINGS,
        LLM_PROMPT_LEARNING_PENDING_ONLY,
        LLM_PROMPT_ROLE_TITLE_PATTERN_GUIDANCE,
    ]
    if fit_review:
        parts.extend([
            f"Return exactly this shape: {LLM_FIT_REVIEW_PROMPT_SHAPE}",
            LLM_PROMPT_CONTEXTUAL_CAPABILITY_INTRO,
            LLM_PROMPT_JOB_REQUIREMENTS_INTRO,
            f"Use at most {get_llm_contextual_matches_max_items()} contextual_capability_matches.",
        ])
    else:
        parts.extend([
            f"Return exactly this shape: {LLM_LEARNING_ONLY_PROMPT_SHAPE}",
            LLM_PROMPT_NO_FIT_DECISION_REQUIRED,
            f"Use at most {get_llm_learning_candidates_max_items()} learning candidates.",
        ])
    parts.append(build_profile_prompt_context())
    return "\n".join(part for part in parts if part)


def _request_learning_payload(job_description_text: str, *, fit_review: bool) -> dict[str, Any]:
    if client is None:
        raise RuntimeError("LLM review requested but LLM is disabled or OPENAI_API_KEY is missing")

    try:
        model = _log_llm_model_once()
        resp = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": _build_learning_prompt(job_description_text, fit_review=fit_review)},
                {"role": "user", "content": LLM_PROMPT_JOB_DESCRIPTION_PREFIX + job_description_text},
            ],
            max_output_tokens=(
                get_llm_fit_decision_max_output_tokens()
                if fit_review
                else get_llm_learning_candidates_max_output_tokens()
            ),
            text_format=_LLMFitReviewPayload if fit_review else _LLMReviewPayload,
        )
        _log_llm_call(resp, "job_review_with_learning" if fit_review else "job_learning_candidates", model)
    except Exception as exc:
        raise RuntimeError(f"LLM review request failed: {exc}") from exc

    parsed = getattr(resp, "output_parsed", None)
    if parsed is None:
        raise ValueError("LLM review payload is missing parsed output")

    payload = normalize_llm_review_payload(parsed.model_dump())
    if fit_review:
        if payload.get("fit_review") is None:
            raise ValueError("LLM fit review payload is missing fit_review")
    return payload


def llm_extract_job_requirements(job_description_text: str, llm_client: Any = None) -> list[str]:
    active_client = llm_client or client
    description = str(job_description_text or "").strip()
    if active_client is None or not description:
        return []

    system_prompt = "\n".join([
        "You extract only the explicit job requirements visible in the ad.",
        LLM_PROMPT_JSON_ONLY,
        LLM_PROMPT_DO_NOT_INVENT,
        LLM_PROMPT_USE_VISIBLE_STRINGS,
        LLM_PROMPT_JOB_REQUIREMENTS_INTRO,
        f"Return exactly this shape: {LLM_JOB_REQUIREMENTS_PROMPT_SHAPE}",
        f"Use at most {get_llm_job_requirements_max_items()} job_requirements.",
    ])

    try:
        model = _log_llm_model_once()
        resp = active_client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": LLM_PROMPT_JOB_DESCRIPTION_PREFIX + description},
            ],
            max_output_tokens=get_llm_learning_candidates_max_output_tokens(),
            text_format=_LLMJobRequirementsPayload,
        )
        _log_llm_call(resp, "job_requirements", model)
    except Exception as exc:
        print(f"[LLM][JOB_REQUIREMENTS][ERROR] {exc}")
        return []

    parsed = getattr(resp, "output_parsed", None)
    if parsed is None:
        return []
    raw_output = str(getattr(resp, "output_text", "") or "").strip()
    if raw_output:
        print(f"[LLM][JOB_REQUIREMENTS][RAW] {raw_output[:get_llm_raw_output_log_max_chars()]}")
    return normalize_llm_job_requirements(parsed.model_dump())


def llm_should_consider_with_learning(job_description_text: str) -> dict[str, Any]:
    return _request_learning_payload(job_description_text, fit_review=True)


def llm_should_consider_learning_candidates(job_description_text: str) -> list[dict[str, Any]]:
    return normalize_llm_review_payload(_request_learning_payload(job_description_text, fit_review=False)).get("learning_candidates", [])


def llm_classify_section_label(label: str, llm_client: Any = None) -> dict[str, Any] | None:
    """Classify an unknown CV section heading into primary/secondary/supplementary.

    Returns {"bucket": str, "confident": bool} or None if LLM unavailable or output unparseable.
    """
    active_client = llm_client or client
    label = str(label or "").strip()
    if active_client is None or not label:
        return None

    system_prompt = "\n".join([
        "You are routing a CV section heading to one of three evidence tiers for a job-match assistant.",
        "primary: current or recent work experience (roles, projects, achievements).",
        "secondary: older or supporting work experience.",
        "supplementary: education, certifications, training, or non-work background sections.",
        f"Return JSON only, shape: {LLM_SECTION_LABEL_CLASSIFICATION_SHAPE}",
        "Set confident=true only if the heading unambiguously maps to one tier.",
        "Set confident=false if the heading is ambiguous (e.g. Overview, Profile, Summary).",
    ])

    try:
        model = _log_llm_model_once()
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
        print(f"[LLM][SECTION_LABEL][ERROR] {exc}")
        return None

    raw = str(getattr(resp, "output_text", "") or "").strip()
    if not raw:
        return None

    try:
        parsed = _json_mod.loads(raw)
    except _json_mod.JSONDecodeError:
        print(f"[LLM][SECTION_LABEL][PARSE_ERROR] {raw[:200]}")
        return None

    bucket = str(parsed.get("bucket") or "").strip().lower()
    confident = bool(parsed.get("confident"))
    if bucket not in {"primary", "secondary", "supplementary"}:
        print(f"[LLM][SECTION_LABEL][INVALID_BUCKET] {bucket!r}")
        return None

    print(f"[LLM][SECTION_LABEL] '{label}' → {bucket} (confident={confident})")
    return {"bucket": bucket, "confident": confident}


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
                totals[p]["calls"]    += 1
                totals[p]["tok_in"]   += entry.get("tok_in", 0)
                totals[p]["tok_out"]  += entry.get("tok_out", 0)
                totals[p]["cost_usd"] += entry.get("cost_usd", 0.0)
    except FileNotFoundError:
        pass
    grand = sum(v["cost_usd"] for v in totals.values())
    return {"by_purpose": totals, "grand_total_usd": round(grand, 6)}
