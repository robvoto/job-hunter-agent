"""Normalization logic for global settings."""

from __future__ import annotations

import copy
from typing import Any

from job_hunter_agent.settings.global_settings_defaults import (
    CACHE_SETTING_LIMITS,
    CAPABILITY_STRENGTH_PRESETS,
    DEFAULT_ACCESS_SETTINGS,
    DEFAULT_CACHE_SETTINGS,
    DEFAULT_COUNTRY_SUFFIX,
    DEFAULT_DESCRIPTION_COMPACTION_SETTINGS,
    DEFAULT_DESCRIPTION_TRUST_SETTINGS,
    DEFAULT_EVIDENCE_TIER_WEIGHTS,
    DEFAULT_FIT_HIGHLIGHTS,
    DEFAULT_HISTORY_SETTINGS,
    DEFAULT_LLM_PROMPT_SETTINGS,
    DEFAULT_LLM_SETTINGS,
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PLAYWRIGHT_BROWSER_MODE,
    DEFAULT_PLAYWRIGHT_SETTINGS,
    DEFAULT_PREFERENCE_WEIGHTS,
    DEFAULT_REVIEW_SETTINGS,
    DEFAULT_SALARY_LIMITS,
    DEFAULT_SEARCH_SETTINGS,
    DEFAULT_SOURCE_DOCUMENT_SETTINGS,
    DEFAULT_UI_SETTINGS,
    HISTORY_SETTING_LIMITS,
    KEY_ACCESS_SETTINGS,
    KEY_APPLIED_RETENTION_DAYS,
    KEY_APSJOBS_ENABLED,
    KEY_CACHE_SETTINGS,
    KEY_CANDIDATE_APPLICATION_HISTORY,
    KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_AGE_DAYS,
    KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_ENTRIES,
    KEY_CAPABILITY_STRENGTH_PRESETS,
    KEY_COMPACTION_ENABLED,
    KEY_COMPACTION_MIN_CHARS,
    KEY_COMPACTION_MIN_RETENTION,
    KEY_CV_CHARS_PER_PAGE,
    KEY_CV_EXTRACTION_CACHE_MAX_AGE_DAYS,
    KEY_CV_EXTRACTION_CACHE_MAX_ENTRIES,
    KEY_DATE_RANGE_DAYS,
    KEY_DEFAULT_COUNTRY_SUFFIX,
    KEY_DEFAULT_THEME,
    KEY_DESCRIPTION_COMPACTION_SETTINGS,
    KEY_DESCRIPTION_TRUST_SETTINGS,
    KEY_EVIDENCE_TIER_WEIGHTS,
    KEY_FIT_HIGHLIGHTS,
    KEY_HIDDEN_RETENTION_DAYS,
    KEY_HISTORICAL_APPLICATION_EVIDENCE_MAX_ENTRIES,
    KEY_HISTORY_SETTINGS,
    KEY_INCREMENTAL_SEARCH_CATCH_UP_INTERVAL_DAYS,
    KEY_INCREMENTAL_SEARCH_LATE_DISCOVERY_THRESHOLD_DAYS,
    KEY_INCREMENTAL_SEARCH_OVERLAP_DAYS,
    KEY_JOB_HISTORY_MAX_AGE_DAYS,
    KEY_JOB_HISTORY_MAX_ENTRIES,
    KEY_JOB_MARKET_MAP_PARALLEL_WORKERS,
    KEY_MARKET_SOURCE_MODE,
    KEY_LIMITS,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_ENABLED,
    KEY_LINKEDIN_FAILURE_BACKOFF_MINUTES,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS,
    KEY_LINKEDIN_MAX_CONSECUTIVE_TARGET_FAILURES,
    KEY_LINKEDIN_PARALLEL_REVIEW_WORKERS,
    KEY_LINKEDIN_PARALLEL_SEARCH_WORKERS,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_LINKEDIN_STALE_FALLBACK_MAX_AGE_MINUTES,
    KEY_LLM_CACHE_MAX_AGE_DAYS,
    KEY_LLM_CACHE_MAX_ENTRIES,
    KEY_LLM_MAX_CHARS,
    KEY_LLM_MAX_CHARS_LIMITS,
    KEY_LLM_MAX_RETRIES,
    KEY_LLM_MODEL_OVERRIDES_BY_PURPOSE,
    KEY_LLM_PRICING_PER_1M,
    KEY_LLM_PROMPT_CAPABILITY_NAMING_ALIASES_MAX_ITEMS,
    KEY_LLM_PROMPT_CAPABILITY_NAMING_MAX_OUTPUT_TOKENS,
    KEY_LLM_PROMPT_CAPABILITY_RULE_ALIASES_MAX_ITEMS,
    KEY_LLM_PROMPT_CAPABILITY_RULES_MAX_ITEMS,
    KEY_LLM_PROMPT_CV_EVIDENCE_JSON_CHARS,
    KEY_LLM_PROMPT_CV_FALLBACK_CHARS,
    KEY_LLM_PROMPT_EVIDENCE_TIERS,
    KEY_LLM_PROMPT_FIT_DECISION_MAX_OUTPUT_TOKENS,
    KEY_LLM_PROMPT_FIT_GUIDANCE_MAX_CHARS,
    KEY_LLM_PROMPT_FIT_REVIEW_DEBUG_MATCH_DIAGNOSTICS_ENABLED,
    KEY_LLM_PROMPT_JOB_DESCRIPTION_MAX_CHARS,
    KEY_LLM_PROMPT_LEARNING_CANDIDATES_MAX_OUTPUT_TOKENS,
    KEY_LLM_PROMPT_LEARNING_MAX_ITEMS,
    KEY_LLM_PROMPT_PROFILE_EXTRACTION_MAX_OUTPUT_TOKENS,
    KEY_LLM_PROMPT_RAW_OUTPUT_LOG_MAX_CHARS,
    KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS,
    KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_OUTPUT_TOKENS,
    KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS,
    KEY_LLM_PROMPT_REQUIREMENT_COVERAGE_MAX_ITEMS,
    KEY_LLM_PROMPT_SETTINGS,
    KEY_LLM_PROMPT_TEMPLATES,
    KEY_LLM_PROMPT_TITLE_JUDGMENT_MAX_OUTPUT_TOKENS,
    KEY_LLM_REASONING_EFFORT_BY_MODEL,
    KEY_LLM_REQUEST_TIMEOUT_SECONDS,
    KEY_LLM_SETTINGS,
    KEY_LLM_TEMPERATURE,
    KEY_MIN_TRUSTED_DESCRIPTION_LENGTH,
    KEY_MODEL_OPTIONS,
    KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS,
    KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS,
    KEY_OCCUPATION_TITLE_CACHE_MAX_AGE_DAYS,
    KEY_OCCUPATION_TITLE_CACHE_MAX_ENTRIES,
    KEY_ONBOARDING_SETTINGS,
    KEY_PLAYWRIGHT_BROWSER_MODE,
    KEY_PLAYWRIGHT_HEADLESS,
    KEY_PLAYWRIGHT_SELECTOR_TIMEOUT,
    KEY_PLAYWRIGHT_VIEWPORT_HEIGHT,
    KEY_PLAYWRIGHT_VIEWPORT_WIDTH,
    KEY_POSTED_AGE_BADGE_THRESHOLD_DAYS,
    KEY_POTENTIAL_POSTED_AGE_LIMIT_DAYS,
    KEY_POTENTIAL_RETENTION_DAYS,
    KEY_PREFERENCE_WEIGHTS,
    KEY_REPEATED_LISTING_MIN_SPAN_DAYS,
    KEY_REPEATED_LISTING_MIN_TIMES_SEEN,
    KEY_REQUIRE_APPROVAL_FOR_NEW_USERS,
    KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT,
    KEY_REVIEW_MAX_EXAMPLES_PER_SKILL,
    KEY_REVIEW_MAX_SAMPLES_PER_REJECTION,
    KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT,
    KEY_REVIEW_SETTINGS,
    KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT,
    KEY_SALARY_LIMITS,
    KEY_SEARCH_LIMITS,
    KEY_SEARCH_PLAN_MAX_AGE_MINUTES,
    KEY_SEARCH_PLAN_MIN_CORROBORATION_SAMPLES,
    KEY_SEARCH_SETTINGS,
    KEY_SEEK_ASSISTED_VERIFICATION_ENABLED,
    KEY_SEEK_ENABLED,
    KEY_SEEK_MANUAL_VERIFICATION_TIMEOUT_MS,
    KEY_SEEK_MAX_PAGES,
    KEY_SEEK_QUICK_APPLY_ONLY,
    KEY_SESSION_MAX_AGE_DAYS,
    KEY_SORT_NEWEST_FIRST,
    KEY_SOURCE_DISCOVERY_CACHE_MAX_AGE_MINUTES,
    KEY_SOURCE_DISCOVERY_CACHE_MAX_ENTRIES,
    KEY_SOURCE_DOCUMENT_SETTINGS,
    KEY_SOURCE_DOCUMENT_SUFFIXES,
    KEY_UI_SETTINGS,
    MARKET_SOURCE_MODES,
    ONBOARDING_SETTING_LIMITS,
    SEARCH_SETTING_LIMITS,
)


def _require_int(source: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    raw = source.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"global_settings.{key} must be an integer, got {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ValueError(
            f"global_settings.{key} must be between {minimum} and {maximum}, got {value}"
        )
    return value


def _require_float(
    source: dict[str, Any], key: str, default: float, minimum: float, maximum: float
) -> float:
    raw = source.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"global_settings.{key} must be a number, got {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ValueError(
            f"global_settings.{key} must be between {minimum} and {maximum}, got {value}"
        )
    return value


def _normalize_float_map(
    source: dict[str, Any],
    defaults: dict[str, float],
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key, default in defaults.items():
        normalized[key] = _require_float(source, key, float(default), minimum, maximum)
    return normalized


def _require_int_list(
    source: dict[str, Any],
    key: str,
    default: list[int],
    *,
    minimum: int,
    maximum: int,
    min_items: int = 1,
    max_items: int = 10,
) -> list[int]:
    raw = source.get(key, default)
    if not isinstance(raw, list):
        raise ValueError(f"global_settings.{key} must be a list, got {type(raw).__name__!r}")
    if len(raw) < min_items or len(raw) > max_items:
        raise ValueError(
            f"global_settings.{key} must contain between {min_items} and {max_items} items"
        )
    values: list[int] = []
    for index, item in enumerate(raw):
        try:
            value = int(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"global_settings.{key}[{index}] must be an integer, got {item!r}"
            ) from exc
        if value < minimum or value > maximum:
            raise ValueError(
                f"global_settings.{key}[{index}] must be between {minimum} and {maximum}, got {value}"
            )
        values.append(value)
    if values != sorted(values):
        raise ValueError(f"global_settings.{key} must be sorted ascending")
    if len(set(values)) != len(values):
        raise ValueError(f"global_settings.{key} must not contain duplicates")
    return values


def _normalize_int_bounds(source: dict[str, Any], defaults: dict[str, int]) -> dict[str, int]:
    min_value = _require_int(source, "min", int(defaults["min"]), 1, 10_000_000)
    max_value = _require_int(source, "max", int(defaults["max"]), min_value, 10_000_000)
    return {"min": min_value, "max": max_value}


def _normalize_llm_pricing_map(
    source: dict[str, Any], defaults: dict[str, dict[str, float]]
) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    for model, raw_prices in source.items():
        if not isinstance(raw_prices, dict):
            raise ValueError(
                f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PRICING_PER_1M}.{model} must be a dict"
            )
        default_prices = defaults.get(model, {"input": 0.0, "output": 0.0})
        normalized[model] = {
            "input": _require_float(
                raw_prices, "input", float(default_prices["input"]), 0.0, 10_000.0
            ),
            "output": _require_float(
                raw_prices, "output", float(default_prices["output"]), 0.0, 10_000.0
            ),
        }
    if not normalized:
        normalized = copy.deepcopy(defaults)
    return normalized


# Values accepted by the OpenAI Responses API `reasoning.effort` parameter.
_ALLOWED_LLM_REASONING_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh"})


def _normalize_llm_reasoning_effort_map(
    source: dict[str, Any], defaults: dict[str, str]
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for model, raw_effort in source.items():
        effort = str(raw_effort or "").strip().lower()
        if effort not in _ALLOWED_LLM_REASONING_EFFORTS:
            raise ValueError(
                f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_REASONING_EFFORT_BY_MODEL}.{model} "
                f"must be one of {sorted(_ALLOWED_LLM_REASONING_EFFORTS)}, got {raw_effort!r}"
            )
        normalized[model] = effort
    if not normalized:
        normalized = copy.deepcopy(defaults)
    return normalized


def _normalize_llm_model_overrides_by_purpose_map(
    source: dict[str, Any], defaults: dict[str, str]
) -> dict[str, str]:
    """Validate purpose -> model overrides.

    Deliberately not cross-checked against model_options: like pricing_per_1m and
    reasoning_effort_by_model, these reference specific model ids that may not (yet)
    be in the account-wide selectable model_options dropdown, so the two lists are
    allowed to evolve independently rather than needing to be seeded in lockstep.
    """
    normalized: dict[str, str] = {}
    for purpose, raw_model in source.items():
        model = str(raw_model or "").strip()
        if not model:
            raise ValueError(
                f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_MODEL_OVERRIDES_BY_PURPOSE}.{purpose} "
                f"must be a non-empty model id, got {raw_model!r}"
            )
        normalized[purpose] = model
    if not normalized:
        normalized = copy.deepcopy(defaults)
    return normalized


def _normalize_llm_prompt_settings(
    source: dict[str, Any], *, strict_managed: bool = False
) -> dict[str, Any]:
    templates_source = source.get(KEY_LLM_PROMPT_TEMPLATES, {})
    if not isinstance(templates_source, dict):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_TEMPLATES} must be a dict"
        )
    evidence_tiers_source = source.get(KEY_LLM_PROMPT_EVIDENCE_TIERS, [])
    if not isinstance(evidence_tiers_source, list):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_EVIDENCE_TIERS} must be a list"
        )

    templates = {
        name: str(templates_source.get(name) or default).strip()
        for name, default in DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_TEMPLATES].items()
    }
    evidence_tiers: list[dict[str, Any]] = []
    default_tiers = DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_EVIDENCE_TIERS]
    for index, default_tier in enumerate(default_tiers):
        tier_source = evidence_tiers_source[index] if index < len(evidence_tiers_source) else {}
        if not isinstance(tier_source, dict):
            tier_source = {}
        profile_key = str(tier_source.get("profile_key") or default_tier["profile_key"]).strip()
        if not profile_key:
            raise ValueError(
                f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_EVIDENCE_TIERS}[{index}].profile_key is required"
            )
        evidence_tiers.append(
            {
                "profile_key": profile_key,
                "label": str(tier_source.get("label") or default_tier["label"]).strip(),
                "weight_label": str(
                    tier_source.get("weight_label") or default_tier["weight_label"]
                ).strip(),
                "default_weight": _require_float(
                    tier_source,
                    "default_weight",
                    float(default_tier["default_weight"]),
                    0.0,
                    10.0,
                ),
                "limit": _require_int(
                    tier_source,
                    "limit",
                    int(default_tier["limit"]),
                    1,
                    10_000,
                ),
            }
        )

    def _prompt_int(key: str, default_key: str, *, minimum: int, maximum: int) -> int:
        if strict_managed and key not in source:
            raise ValueError(
                f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{key} is required"
            )
        raw = source.get(key, DEFAULT_LLM_PROMPT_SETTINGS[default_key])
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{key} must be an integer"
            ) from exc
        if value < minimum or value > maximum:
            raise ValueError(
                f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{key} must be between {minimum} and {maximum}"
            )
        return value

    # Output token limits: too low → truncated JSON → CARD_EXCEPTION; too high → runaway API cost.
    # Char limits: cap prompt context sent to the model; inflating them wastes tokens but doesn't cause errors.
    fit_decision_max_output_tokens = _prompt_int(
        KEY_LLM_PROMPT_FIT_DECISION_MAX_OUTPUT_TOKENS,
        KEY_LLM_PROMPT_FIT_DECISION_MAX_OUTPUT_TOKENS,
        minimum=100,  # min needed for a valid fit_review + a few contextual matches
        maximum=4_000,
    )
    learning_candidates_max_output_tokens = _prompt_int(
        KEY_LLM_PROMPT_LEARNING_CANDIDATES_MAX_OUTPUT_TOKENS,
        KEY_LLM_PROMPT_LEARNING_CANDIDATES_MAX_OUTPUT_TOKENS,
        minimum=100,
        maximum=2_000,
    )
    rejection_blocker_max_output_tokens = _prompt_int(
        KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_OUTPUT_TOKENS,
        KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_OUTPUT_TOKENS,
        minimum=50,
        maximum=1_000,
    )
    capability_naming_max_output_tokens = _prompt_int(
        KEY_LLM_PROMPT_CAPABILITY_NAMING_MAX_OUTPUT_TOKENS,
        KEY_LLM_PROMPT_CAPABILITY_NAMING_MAX_OUTPUT_TOKENS,
        minimum=50,
        maximum=1_500,
    )
    title_judgment_max_output_tokens = _prompt_int(
        KEY_LLM_PROMPT_TITLE_JUDGMENT_MAX_OUTPUT_TOKENS,
        KEY_LLM_PROMPT_TITLE_JUDGMENT_MAX_OUTPUT_TOKENS,
        minimum=160,  # Luna structured title JSON can exceed 80 tokens, including reasoning.
        maximum=500,
    )
    profile_extraction_max_output_tokens = _prompt_int(
        KEY_LLM_PROMPT_PROFILE_EXTRACTION_MAX_OUTPUT_TOKENS,
        KEY_LLM_PROMPT_PROFILE_EXTRACTION_MAX_OUTPUT_TOKENS,
        minimum=200,
        maximum=4_000,
    )
    job_description_max_chars = _prompt_int(
        KEY_LLM_PROMPT_JOB_DESCRIPTION_MAX_CHARS,
        KEY_LLM_PROMPT_JOB_DESCRIPTION_MAX_CHARS,
        minimum=500,
        maximum=20_000,
    )
    cv_evidence_json_chars = _prompt_int(
        KEY_LLM_PROMPT_CV_EVIDENCE_JSON_CHARS,
        KEY_LLM_PROMPT_CV_EVIDENCE_JSON_CHARS,
        minimum=500,
        maximum=30_000,
    )
    cv_fallback_chars = _prompt_int(
        KEY_LLM_PROMPT_CV_FALLBACK_CHARS,
        KEY_LLM_PROMPT_CV_FALLBACK_CHARS,
        minimum=200,
        maximum=10_000,
    )
    capability_rules_max_items = _prompt_int(
        KEY_LLM_PROMPT_CAPABILITY_RULES_MAX_ITEMS,
        KEY_LLM_PROMPT_CAPABILITY_RULES_MAX_ITEMS,
        minimum=1,
        maximum=50,
    )
    capability_rule_aliases_max_items = _prompt_int(
        KEY_LLM_PROMPT_CAPABILITY_RULE_ALIASES_MAX_ITEMS,
        KEY_LLM_PROMPT_CAPABILITY_RULE_ALIASES_MAX_ITEMS,
        minimum=1,
        maximum=20,
    )
    fit_guidance_max_chars = _prompt_int(
        KEY_LLM_PROMPT_FIT_GUIDANCE_MAX_CHARS,
        KEY_LLM_PROMPT_FIT_GUIDANCE_MAX_CHARS,
        minimum=100,
        maximum=5_000,
    )
    capability_naming_aliases_max_items = _prompt_int(
        KEY_LLM_PROMPT_CAPABILITY_NAMING_ALIASES_MAX_ITEMS,
        KEY_LLM_PROMPT_CAPABILITY_NAMING_ALIASES_MAX_ITEMS,
        minimum=1,
        maximum=20,
    )
    raw_output_log_max_chars = _prompt_int(
        KEY_LLM_PROMPT_RAW_OUTPUT_LOG_MAX_CHARS,
        KEY_LLM_PROMPT_RAW_OUTPUT_LOG_MAX_CHARS,
        minimum=100,
        maximum=5_000,
    )
    requirement_coverage_max_items = _prompt_int(
        KEY_LLM_PROMPT_REQUIREMENT_COVERAGE_MAX_ITEMS,
        KEY_LLM_PROMPT_REQUIREMENT_COVERAGE_MAX_ITEMS,
        minimum=1,
        maximum=20,
    )

    try:
        learning_max_items = int(
            source.get(
                KEY_LLM_PROMPT_LEARNING_MAX_ITEMS,
                DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_LEARNING_MAX_ITEMS],
            )
            or DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_LEARNING_MAX_ITEMS]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_LEARNING_MAX_ITEMS} must be an integer"
        ) from exc
    if learning_max_items < 1 or learning_max_items > 20:
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_LEARNING_MAX_ITEMS} must be between 1 and 20"
        )
    try:
        rejection_blocker_max_items = int(
            source.get(
                KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS,
                DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS],
            )
            or DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS} must be an integer"
        ) from exc
    if rejection_blocker_max_items < 1 or rejection_blocker_max_items > 20:
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS} must be between 1 and 20"
        )
    try:
        rejection_blocker_max_words = int(
            source.get(
                KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS,
                DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS],
            )
            or DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS} must be an integer"
        ) from exc
    if rejection_blocker_max_words < 1 or rejection_blocker_max_words > 20:
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS} must be between 1 and 20"
        )

    return {
        KEY_LLM_PROMPT_TEMPLATES: templates,
        KEY_LLM_PROMPT_EVIDENCE_TIERS: evidence_tiers,
        KEY_LLM_PROMPT_FIT_DECISION_MAX_OUTPUT_TOKENS: fit_decision_max_output_tokens,
        KEY_LLM_PROMPT_LEARNING_CANDIDATES_MAX_OUTPUT_TOKENS: learning_candidates_max_output_tokens,
        KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_OUTPUT_TOKENS: rejection_blocker_max_output_tokens,
        KEY_LLM_PROMPT_CAPABILITY_NAMING_MAX_OUTPUT_TOKENS: capability_naming_max_output_tokens,
        KEY_LLM_PROMPT_TITLE_JUDGMENT_MAX_OUTPUT_TOKENS: title_judgment_max_output_tokens,
        KEY_LLM_PROMPT_PROFILE_EXTRACTION_MAX_OUTPUT_TOKENS: profile_extraction_max_output_tokens,
        KEY_LLM_PROMPT_JOB_DESCRIPTION_MAX_CHARS: job_description_max_chars,
        KEY_LLM_PROMPT_CV_EVIDENCE_JSON_CHARS: cv_evidence_json_chars,
        KEY_LLM_PROMPT_CV_FALLBACK_CHARS: cv_fallback_chars,
        KEY_LLM_PROMPT_CAPABILITY_RULES_MAX_ITEMS: capability_rules_max_items,
        KEY_LLM_PROMPT_CAPABILITY_RULE_ALIASES_MAX_ITEMS: capability_rule_aliases_max_items,
        KEY_LLM_PROMPT_FIT_GUIDANCE_MAX_CHARS: fit_guidance_max_chars,
        KEY_LLM_PROMPT_CAPABILITY_NAMING_ALIASES_MAX_ITEMS: capability_naming_aliases_max_items,
        KEY_LLM_PROMPT_RAW_OUTPUT_LOG_MAX_CHARS: raw_output_log_max_chars,
        KEY_LLM_PROMPT_FIT_REVIEW_DEBUG_MATCH_DIAGNOSTICS_ENABLED: _normalize_bool(
            source,
            KEY_LLM_PROMPT_FIT_REVIEW_DEBUG_MATCH_DIAGNOSTICS_ENABLED,
            bool(
                DEFAULT_LLM_PROMPT_SETTINGS[
                    KEY_LLM_PROMPT_FIT_REVIEW_DEBUG_MATCH_DIAGNOSTICS_ENABLED
                ]
            ),
        ),
        KEY_LLM_PROMPT_REQUIREMENT_COVERAGE_MAX_ITEMS: requirement_coverage_max_items,
        KEY_LLM_PROMPT_LEARNING_MAX_ITEMS: learning_max_items,
        KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS: rejection_blocker_max_items,
        KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS: rejection_blocker_max_words,
    }


def _normalize_market_source_mode(source: dict[str, Any]) -> str:
    mode = str(source.get(KEY_MARKET_SOURCE_MODE, DEFAULT_SEARCH_SETTINGS.get(KEY_MARKET_SOURCE_MODE, "auto"))).strip().lower()
    if mode not in MARKET_SOURCE_MODES:
        raise ValueError(
            f"global_settings.{KEY_SEARCH_SETTINGS}.{KEY_MARKET_SOURCE_MODE} "
            f"must be one of {sorted(MARKET_SOURCE_MODES)}, got {mode!r}"
        )
    return mode


def _normalize_bool(source: dict[str, Any], key: str, default: bool) -> bool:
    raw = source.get(key, default)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(raw)


def _search_setting_default_bool(key: str, default: bool) -> bool:
    return bool(DEFAULT_SEARCH_SETTINGS.get(key, default))


def _search_setting_default_int(key: str, default: int) -> int:
    raw = DEFAULT_SEARCH_SETTINGS.get(key, default)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return int(default)


def _normalize_source_document_suffixes(source: dict[str, Any], defaults: list[str]) -> list[str]:
    raw_suffixes = source.get(KEY_SOURCE_DOCUMENT_SUFFIXES, defaults)
    if not isinstance(raw_suffixes, list):
        raise ValueError(
            f"global_settings.{KEY_SOURCE_DOCUMENT_SETTINGS}.{KEY_SOURCE_DOCUMENT_SUFFIXES} must be a list"
        )

    normalized: list[str] = []
    for value in raw_suffixes:
        suffix = str(value or "").strip().lower()
        if not suffix:
            continue
        if not suffix.startswith("."):
            raise ValueError(
                f"global_settings.{KEY_SOURCE_DOCUMENT_SETTINGS}.{KEY_SOURCE_DOCUMENT_SUFFIXES} entries must start with '.'"
            )
        if " " in suffix:
            raise ValueError(
                f"global_settings.{KEY_SOURCE_DOCUMENT_SETTINGS}.{KEY_SOURCE_DOCUMENT_SUFFIXES} entries must not contain spaces"
            )
        if suffix not in normalized:
            normalized.append(suffix)
    if not normalized:
        raise ValueError(
            f"global_settings.{KEY_SOURCE_DOCUMENT_SETTINGS}.{KEY_SOURCE_DOCUMENT_SUFFIXES} must contain at least one suffix"
        )
    return normalized


def _normalize_limit_map(
    source: dict[str, Any],
    defaults: dict[str, dict[str, int]],
    *,
    minimum: int = 0,
    maximum: int = 10_000_000,
) -> dict[str, dict[str, int]]:
    normalized: dict[str, dict[str, int]] = {}
    for key, default in defaults.items():
        raw_bounds = source.get(key, {})
        if not isinstance(raw_bounds, dict):
            raw_bounds = {}
        normalized[key] = {
            "min": _require_int(
                raw_bounds, "min", int(default.get("min", minimum)), minimum, maximum
            ),
            "max": _require_int(
                raw_bounds, "max", int(default.get("max", maximum)), minimum, maximum
            ),
        }
        if normalized[key]["min"] > normalized[key]["max"]:
            raise ValueError(f"global_settings.{key}.min must be <= max")
    return normalized


def normalize_global_settings(
    payload: dict[str, Any] | None, *, strict_managed: bool = False
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}

    fit_source = source.get(KEY_FIT_HIGHLIGHTS, {})
    access_source = source.get(KEY_ACCESS_SETTINGS, {})
    ui_source = source.get(KEY_UI_SETTINGS, {})
    search_source = source.get(KEY_SEARCH_SETTINGS, {})

    limits_source = source.get(KEY_LIMITS, {})
    search_limits_source = limits_source.get("search") or source.get(KEY_SEARCH_LIMITS, {})
    salary_limits_source = limits_source.get("salary") or source.get(KEY_SALARY_LIMITS, {})
    onboarding_limits_source = limits_source.get("onboarding", {})
    history_limits_source = limits_source.get("history", {})
    cache_limits_source = limits_source.get("cache", {})

    preference_source = source.get(KEY_PREFERENCE_WEIGHTS, {})
    evidence_source = source.get(KEY_EVIDENCE_TIER_WEIGHTS, {})
    history_source = source.get(KEY_HISTORY_SETTINGS, {})
    cache_source = source.get(KEY_CACHE_SETTINGS, {})
    description_trust_source = source.get(KEY_DESCRIPTION_TRUST_SETTINGS, {})
    description_compaction_source = source.get(KEY_DESCRIPTION_COMPACTION_SETTINGS, {})
    source_document_source = source.get(KEY_SOURCE_DOCUMENT_SETTINGS, {})
    default_country_suffix = str(
        source.get(KEY_DEFAULT_COUNTRY_SUFFIX, DEFAULT_COUNTRY_SUFFIX)
    ).strip()
    onboarding_source = source.get(KEY_ONBOARDING_SETTINGS, {})
    llm_source = source.get(KEY_LLM_SETTINGS, {})
    playwright_source = source.get("playwright_settings", {})
    review_source = source.get(KEY_REVIEW_SETTINGS, {})
    candidate_application_history_source = source.get(KEY_CANDIDATE_APPLICATION_HISTORY, {})

    if not isinstance(fit_source, dict):
        raise ValueError(
            f"global_settings.{KEY_FIT_HIGHLIGHTS} must be a dict, got {type(fit_source).__name__!r}"
        )
    if not isinstance(access_source, dict):
        raise ValueError(
            f"global_settings.{KEY_ACCESS_SETTINGS} must be a dict, got {type(access_source).__name__!r}"
        )
    if not isinstance(ui_source, dict):
        raise ValueError(
            f"global_settings.{KEY_UI_SETTINGS} must be a dict, got {type(ui_source).__name__!r}"
        )
    if not isinstance(search_source, dict):
        raise ValueError(
            f"global_settings.{KEY_SEARCH_SETTINGS} must be a dict, got {type(search_source).__name__!r}"
        )
    if not isinstance(limits_source, dict):
        raise ValueError(
            f"global_settings.{KEY_LIMITS} must be a dict, got {type(limits_source).__name__!r}"
        )
    if not isinstance(preference_source, dict):
        raise ValueError(
            f"global_settings.{KEY_PREFERENCE_WEIGHTS} must be a dict, got {type(preference_source).__name__!r}"
        )
    if not isinstance(evidence_source, dict):
        raise ValueError(
            f"global_settings.{KEY_EVIDENCE_TIER_WEIGHTS} must be a dict, got {type(evidence_source).__name__!r}"
        )
    if not isinstance(history_source, dict):
        raise ValueError(
            f"global_settings.{KEY_HISTORY_SETTINGS} must be a dict, got {type(history_source).__name__!r}"
        )
    if not isinstance(cache_source, dict):
        raise ValueError(
            f"global_settings.{KEY_CACHE_SETTINGS} must be a dict, got {type(cache_source).__name__!r}"
        )
    if not isinstance(description_trust_source, dict):
        raise ValueError(
            f"global_settings.{KEY_DESCRIPTION_TRUST_SETTINGS} must be a dict, got {type(description_trust_source).__name__!r}"
        )
    if not isinstance(description_compaction_source, dict):
        raise ValueError(
            f"global_settings.{KEY_DESCRIPTION_COMPACTION_SETTINGS} must be a dict, got {type(description_compaction_source).__name__!r}"
        )
    if not isinstance(source_document_source, dict):
        raise ValueError(
            f"global_settings.{KEY_SOURCE_DOCUMENT_SETTINGS} must be a dict, got {type(source_document_source).__name__!r}"
        )
    if not default_country_suffix:
        raise ValueError("global_settings.default_country_suffix must not be empty")
    if not isinstance(playwright_source, dict):
        raise ValueError(
            f"global_settings.playwright_settings must be a dict, got {type(playwright_source).__name__!r}"
        )
    if not isinstance(onboarding_source, dict):
        raise ValueError(
            f"global_settings.{KEY_ONBOARDING_SETTINGS} must be a dict, got {type(onboarding_source).__name__!r}"
        )
    if not isinstance(llm_source, dict):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS} must be a dict, got {type(llm_source).__name__!r}"
        )
    if not isinstance(review_source, dict):
        raise ValueError(
            f"global_settings.{KEY_REVIEW_SETTINGS} must be a dict, got {type(review_source).__name__!r}"
        )

    preset_name = (
        str(
            onboarding_source.get("capability_strength_preset")
            or DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
        )
        .strip()
        .lower()
    )
    preset_name = (
        preset_name
        if preset_name in CAPABILITY_STRENGTH_PRESETS
        else DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
    )
    preset_defaults = CAPABILITY_STRENGTH_PRESETS[preset_name]
    merged_onboarding = {
        **DEFAULT_ONBOARDING_SETTINGS,
        **preset_defaults,
        **{k: v for k, v in onboarding_source.items() if k != KEY_CAPABILITY_STRENGTH_PRESETS},
    }

    model_options_source = llm_source.get(
        KEY_MODEL_OPTIONS, DEFAULT_LLM_SETTINGS[KEY_MODEL_OPTIONS]
    )
    if not isinstance(model_options_source, list):
        raise ValueError(f"global_settings.{KEY_LLM_SETTINGS}.{KEY_MODEL_OPTIONS} must be a list")
    normalized_model_options: list[str] = []
    for value in model_options_source:
        model = str(value or "").strip()
        if model and model not in normalized_model_options:
            normalized_model_options.append(model)
    if not normalized_model_options:
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_MODEL_OPTIONS} must contain at least one model"
        )
    pricing_source = llm_source.get(KEY_LLM_PRICING_PER_1M, {})
    if not isinstance(pricing_source, dict):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PRICING_PER_1M} must be a dict"
        )
    normalized_llm_pricing = _normalize_llm_pricing_map(
        pricing_source, DEFAULT_LLM_SETTINGS[KEY_LLM_PRICING_PER_1M]
    )
    reasoning_effort_source = llm_source.get(KEY_LLM_REASONING_EFFORT_BY_MODEL, {})
    if not isinstance(reasoning_effort_source, dict):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_REASONING_EFFORT_BY_MODEL} must be a dict"
        )
    normalized_llm_reasoning_effort = _normalize_llm_reasoning_effort_map(
        reasoning_effort_source,
        DEFAULT_LLM_SETTINGS.get(KEY_LLM_REASONING_EFFORT_BY_MODEL, {}),
    )
    model_overrides_source = llm_source.get(KEY_LLM_MODEL_OVERRIDES_BY_PURPOSE, {})
    if not isinstance(model_overrides_source, dict):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_MODEL_OVERRIDES_BY_PURPOSE} must be a dict"
        )
    normalized_llm_model_overrides_by_purpose = _normalize_llm_model_overrides_by_purpose_map(
        model_overrides_source,
        DEFAULT_LLM_SETTINGS.get(KEY_LLM_MODEL_OVERRIDES_BY_PURPOSE, {}),
    )
    pricing_metadata_source = llm_source.get(
        "pricing_metadata", DEFAULT_LLM_SETTINGS.get("pricing_metadata", {})
    )
    if not isinstance(pricing_metadata_source, dict):
        raise ValueError(f"global_settings.{KEY_LLM_SETTINGS}.pricing_metadata must be a dict")
    pricing_unit = str(pricing_metadata_source.get("unit") or "").strip().lower()
    if pricing_unit not in {
        "per_1m_tokens",
        "per_million_tokens",
        "per_1000000_tokens",
        "per_1k_tokens",
        "per_thousand_tokens",
        "per_1000_tokens",
    }:
        raise ValueError(
            "global_settings.llm_settings.pricing_metadata.unit must be per_1m_tokens or per_1k_tokens"
        )
    normalized_pricing_metadata = copy.deepcopy(pricing_metadata_source)
    normalized_pricing_metadata["unit"] = pricing_unit
    max_chars_limits_source = llm_source.get(KEY_LLM_MAX_CHARS_LIMITS, {})
    if not isinstance(max_chars_limits_source, dict):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_MAX_CHARS_LIMITS} must be a dict"
        )
    normalized_max_chars_limits = _normalize_int_bounds(
        max_chars_limits_source,
        DEFAULT_LLM_SETTINGS[KEY_LLM_MAX_CHARS_LIMITS],
    )
    prompt_source = llm_source.get(KEY_LLM_PROMPT_SETTINGS, {})
    if not isinstance(prompt_source, dict):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS} must be a dict"
        )
    normalized_llm_prompt_settings = _normalize_llm_prompt_settings(
        prompt_source, strict_managed=strict_managed
    )

    try:
        max_llm_chars = int(
            llm_source.get(KEY_LLM_MAX_CHARS, DEFAULT_LLM_SETTINGS[KEY_LLM_MAX_CHARS])
            or DEFAULT_LLM_SETTINGS[KEY_LLM_MAX_CHARS]
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_MAX_CHARS} must be an integer"
        ) from exc
    if (
        max_llm_chars < normalized_max_chars_limits["min"]
        or max_llm_chars > normalized_max_chars_limits["max"]
    ):
        raise ValueError(
            f"global_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_MAX_CHARS} must be between "
            f"{normalized_max_chars_limits['min']} and {normalized_max_chars_limits['max']}"
        )

    llm_request_timeout_seconds = _require_float(
        llm_source,
        KEY_LLM_REQUEST_TIMEOUT_SECONDS,
        DEFAULT_LLM_SETTINGS[KEY_LLM_REQUEST_TIMEOUT_SECONDS],
        5.0,
        120.0,
    )
    llm_max_retries = _require_int(
        llm_source,
        KEY_LLM_MAX_RETRIES,
        DEFAULT_LLM_SETTINGS[KEY_LLM_MAX_RETRIES],
        0,
        5,
    )
    llm_temperature = _require_float(
        llm_source,
        KEY_LLM_TEMPERATURE,
        DEFAULT_LLM_SETTINGS[KEY_LLM_TEMPERATURE],
        0.0,
        2.0,
    )

    preset_table_source = onboarding_source.get(KEY_CAPABILITY_STRENGTH_PRESETS, {})
    if not isinstance(preset_table_source, dict):
        preset_table_source = {}
    normalized_preset_table: dict[str, dict[str, int]] = {}
    for preset_key, preset_defaults_source in CAPABILITY_STRENGTH_PRESETS.items():
        preset_payload = preset_table_source.get(preset_key, {})
        if not isinstance(preset_payload, dict):
            preset_payload = {}
        normalized_preset_table[preset_key] = {
            field: _require_int(preset_payload, field, int(default_value), 1, 360)
            for field, default_value in preset_defaults_source.items()
        }

    normalized_search_limits: dict[str, dict[str, int]] = {}
    for limit_key, default_bounds in SEARCH_SETTING_LIMITS.items():
        bounds_source = search_limits_source.get(limit_key, {})
        if not isinstance(bounds_source, dict):
            bounds_source = {}
        min_value = _require_int(bounds_source, "min", int(default_bounds["min"]), 0, 10_000)
        max_value = _require_int(bounds_source, "max", int(default_bounds["max"]), 1, 10_000)
        if min_value > max_value:
            raise ValueError(f"global_settings.search_limits.{limit_key}.min must be <= max")
        normalized_search_limits[limit_key] = {"min": min_value, "max": max_value}

    normalized_salary_limits = _normalize_limit_map(
        salary_limits_source, DEFAULT_SALARY_LIMITS, maximum=10_000_000
    )
    normalized_onboarding_limits = _normalize_limit_map(
        onboarding_limits_source,
        {k: {"min": v[0], "max": v[1]} for k, v in ONBOARDING_SETTING_LIMITS.items()},
        minimum=1,
        maximum=1000,
    )
    normalized_history_limits = _normalize_limit_map(
        history_limits_source,
        {k: {"min": v[0], "max": v[1]} for k, v in HISTORY_SETTING_LIMITS.items()},
        minimum=1,
        maximum=100_000,
    )
    normalized_cache_limits = _normalize_limit_map(
        cache_limits_source,
        {k: {"min": v[0], "max": v[1]} for k, v in CACHE_SETTING_LIMITS.items()},
        minimum=1,
        maximum=100_000,
    )

    normalized_history_settings = {
        KEY_POTENTIAL_RETENTION_DAYS: _require_int(
            history_source,
            KEY_POTENTIAL_RETENTION_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_POTENTIAL_RETENTION_DAYS],
            1,
            365,
        ),
        KEY_POTENTIAL_POSTED_AGE_LIMIT_DAYS: _require_int(
            history_source,
            KEY_POTENTIAL_POSTED_AGE_LIMIT_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_POTENTIAL_POSTED_AGE_LIMIT_DAYS],
            1,
            14,
        ),
        KEY_POSTED_AGE_BADGE_THRESHOLD_DAYS: _require_int_list(
            history_source,
            KEY_POSTED_AGE_BADGE_THRESHOLD_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_POSTED_AGE_BADGE_THRESHOLD_DAYS],
            minimum=1,
            maximum=365,
            min_items=1,
            max_items=6,
        ),
        KEY_HIDDEN_RETENTION_DAYS: _require_int(
            history_source,
            KEY_HIDDEN_RETENTION_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_HIDDEN_RETENTION_DAYS],
            1,
            365,
        ),
        KEY_APPLIED_RETENTION_DAYS: _require_int(
            history_source,
            KEY_APPLIED_RETENTION_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_APPLIED_RETENTION_DAYS],
            0,
            3650,
        ),
        KEY_JOB_HISTORY_MAX_ENTRIES: _require_int(
            history_source,
            KEY_JOB_HISTORY_MAX_ENTRIES,
            DEFAULT_HISTORY_SETTINGS[KEY_JOB_HISTORY_MAX_ENTRIES],
            normalized_history_limits[KEY_JOB_HISTORY_MAX_ENTRIES]["min"],
            normalized_history_limits[KEY_JOB_HISTORY_MAX_ENTRIES]["max"],
        ),
        KEY_JOB_HISTORY_MAX_AGE_DAYS: _require_int(
            history_source,
            KEY_JOB_HISTORY_MAX_AGE_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_JOB_HISTORY_MAX_AGE_DAYS],
            normalized_history_limits[KEY_JOB_HISTORY_MAX_AGE_DAYS]["min"],
            normalized_history_limits[KEY_JOB_HISTORY_MAX_AGE_DAYS]["max"],
        ),
        KEY_HISTORICAL_APPLICATION_EVIDENCE_MAX_ENTRIES: _require_int(
            history_source,
            KEY_HISTORICAL_APPLICATION_EVIDENCE_MAX_ENTRIES,
            DEFAULT_HISTORY_SETTINGS[KEY_HISTORICAL_APPLICATION_EVIDENCE_MAX_ENTRIES],
            normalized_history_limits[KEY_HISTORICAL_APPLICATION_EVIDENCE_MAX_ENTRIES]["min"],
            normalized_history_limits[KEY_HISTORICAL_APPLICATION_EVIDENCE_MAX_ENTRIES]["max"],
        ),
        KEY_REPEATED_LISTING_MIN_TIMES_SEEN: _require_int(
            history_source,
            KEY_REPEATED_LISTING_MIN_TIMES_SEEN,
            DEFAULT_HISTORY_SETTINGS[KEY_REPEATED_LISTING_MIN_TIMES_SEEN],
            normalized_history_limits[KEY_REPEATED_LISTING_MIN_TIMES_SEEN]["min"],
            normalized_history_limits[KEY_REPEATED_LISTING_MIN_TIMES_SEEN]["max"],
        ),
        KEY_REPEATED_LISTING_MIN_SPAN_DAYS: _require_int(
            history_source,
            KEY_REPEATED_LISTING_MIN_SPAN_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_REPEATED_LISTING_MIN_SPAN_DAYS],
            normalized_history_limits[KEY_REPEATED_LISTING_MIN_SPAN_DAYS]["min"],
            normalized_history_limits[KEY_REPEATED_LISTING_MIN_SPAN_DAYS]["max"],
        ),
        KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS: _require_int(
            history_source,
            KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS,
            DEFAULT_HISTORY_SETTINGS[KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS],
            normalized_history_limits[KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS]["min"],
            normalized_history_limits[KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS]["max"],
        ),
        KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS: _require_int(
            history_source,
            KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS],
            normalized_history_limits[KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS]["min"],
            normalized_history_limits[KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS]["max"],
        ),
    }
    normalized_cache_settings = {
        KEY_LLM_CACHE_MAX_ENTRIES: _require_int(
            cache_source,
            KEY_LLM_CACHE_MAX_ENTRIES,
            DEFAULT_CACHE_SETTINGS[KEY_LLM_CACHE_MAX_ENTRIES],
            normalized_cache_limits[KEY_LLM_CACHE_MAX_ENTRIES]["min"],
            normalized_cache_limits[KEY_LLM_CACHE_MAX_ENTRIES]["max"],
        ),
        KEY_LLM_CACHE_MAX_AGE_DAYS: _require_int(
            cache_source,
            KEY_LLM_CACHE_MAX_AGE_DAYS,
            DEFAULT_CACHE_SETTINGS[KEY_LLM_CACHE_MAX_AGE_DAYS],
            normalized_cache_limits[KEY_LLM_CACHE_MAX_AGE_DAYS]["min"],
            normalized_cache_limits[KEY_LLM_CACHE_MAX_AGE_DAYS]["max"],
        ),
        KEY_CV_EXTRACTION_CACHE_MAX_ENTRIES: _require_int(
            cache_source,
            KEY_CV_EXTRACTION_CACHE_MAX_ENTRIES,
            DEFAULT_CACHE_SETTINGS[KEY_CV_EXTRACTION_CACHE_MAX_ENTRIES],
            normalized_cache_limits[KEY_CV_EXTRACTION_CACHE_MAX_ENTRIES]["min"],
            normalized_cache_limits[KEY_CV_EXTRACTION_CACHE_MAX_ENTRIES]["max"],
        ),
        KEY_CV_EXTRACTION_CACHE_MAX_AGE_DAYS: _require_int(
            cache_source,
            KEY_CV_EXTRACTION_CACHE_MAX_AGE_DAYS,
            DEFAULT_CACHE_SETTINGS[KEY_CV_EXTRACTION_CACHE_MAX_AGE_DAYS],
            normalized_cache_limits[KEY_CV_EXTRACTION_CACHE_MAX_AGE_DAYS]["min"],
            normalized_cache_limits[KEY_CV_EXTRACTION_CACHE_MAX_AGE_DAYS]["max"],
        ),
        KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_ENTRIES: _require_int(
            cache_source,
            KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_ENTRIES,
            DEFAULT_CACHE_SETTINGS[KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_ENTRIES],
            normalized_cache_limits[KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_ENTRIES]["min"],
            normalized_cache_limits[KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_ENTRIES]["max"],
        ),
        KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_AGE_DAYS: _require_int(
            cache_source,
            KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_AGE_DAYS,
            DEFAULT_CACHE_SETTINGS[KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_AGE_DAYS],
            normalized_cache_limits[KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_AGE_DAYS]["min"],
            normalized_cache_limits[KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_AGE_DAYS]["max"],
        ),
        KEY_OCCUPATION_TITLE_CACHE_MAX_ENTRIES: _require_int(
            cache_source,
            KEY_OCCUPATION_TITLE_CACHE_MAX_ENTRIES,
            DEFAULT_CACHE_SETTINGS[KEY_OCCUPATION_TITLE_CACHE_MAX_ENTRIES],
            normalized_cache_limits[KEY_OCCUPATION_TITLE_CACHE_MAX_ENTRIES]["min"],
            normalized_cache_limits[KEY_OCCUPATION_TITLE_CACHE_MAX_ENTRIES]["max"],
        ),
        KEY_OCCUPATION_TITLE_CACHE_MAX_AGE_DAYS: _require_int(
            cache_source,
            KEY_OCCUPATION_TITLE_CACHE_MAX_AGE_DAYS,
            DEFAULT_CACHE_SETTINGS[KEY_OCCUPATION_TITLE_CACHE_MAX_AGE_DAYS],
            normalized_cache_limits[KEY_OCCUPATION_TITLE_CACHE_MAX_AGE_DAYS]["min"],
            normalized_cache_limits[KEY_OCCUPATION_TITLE_CACHE_MAX_AGE_DAYS]["max"],
        ),
        KEY_SOURCE_DISCOVERY_CACHE_MAX_ENTRIES: _require_int(
            cache_source,
            KEY_SOURCE_DISCOVERY_CACHE_MAX_ENTRIES,
            DEFAULT_CACHE_SETTINGS[KEY_SOURCE_DISCOVERY_CACHE_MAX_ENTRIES],
            normalized_cache_limits[KEY_SOURCE_DISCOVERY_CACHE_MAX_ENTRIES]["min"],
            normalized_cache_limits[KEY_SOURCE_DISCOVERY_CACHE_MAX_ENTRIES]["max"],
        ),
        KEY_SOURCE_DISCOVERY_CACHE_MAX_AGE_MINUTES: _require_int(
            cache_source,
            KEY_SOURCE_DISCOVERY_CACHE_MAX_AGE_MINUTES,
            DEFAULT_CACHE_SETTINGS[KEY_SOURCE_DISCOVERY_CACHE_MAX_AGE_MINUTES],
            normalized_cache_limits[KEY_SOURCE_DISCOVERY_CACHE_MAX_AGE_MINUTES]["min"],
            normalized_cache_limits[KEY_SOURCE_DISCOVERY_CACHE_MAX_AGE_MINUTES]["max"],
        ),
        KEY_SEARCH_PLAN_MAX_AGE_MINUTES: _require_int(
            cache_source,
            KEY_SEARCH_PLAN_MAX_AGE_MINUTES,
            DEFAULT_CACHE_SETTINGS[KEY_SEARCH_PLAN_MAX_AGE_MINUTES],
            normalized_cache_limits[KEY_SEARCH_PLAN_MAX_AGE_MINUTES]["min"],
            normalized_cache_limits[KEY_SEARCH_PLAN_MAX_AGE_MINUTES]["max"],
        ),
        KEY_LINKEDIN_FAILURE_BACKOFF_MINUTES: _require_int(
            cache_source,
            KEY_LINKEDIN_FAILURE_BACKOFF_MINUTES,
            DEFAULT_CACHE_SETTINGS[KEY_LINKEDIN_FAILURE_BACKOFF_MINUTES],
            normalized_cache_limits[KEY_LINKEDIN_FAILURE_BACKOFF_MINUTES]["min"],
            normalized_cache_limits[KEY_LINKEDIN_FAILURE_BACKOFF_MINUTES]["max"],
        ),
        KEY_SEARCH_PLAN_MIN_CORROBORATION_SAMPLES: _require_int(
            cache_source,
            KEY_SEARCH_PLAN_MIN_CORROBORATION_SAMPLES,
            DEFAULT_CACHE_SETTINGS[KEY_SEARCH_PLAN_MIN_CORROBORATION_SAMPLES],
            normalized_cache_limits[KEY_SEARCH_PLAN_MIN_CORROBORATION_SAMPLES]["min"],
            normalized_cache_limits[KEY_SEARCH_PLAN_MIN_CORROBORATION_SAMPLES]["max"],
        ),
        KEY_LINKEDIN_STALE_FALLBACK_MAX_AGE_MINUTES: _require_int(
            cache_source,
            KEY_LINKEDIN_STALE_FALLBACK_MAX_AGE_MINUTES,
            DEFAULT_CACHE_SETTINGS[KEY_LINKEDIN_STALE_FALLBACK_MAX_AGE_MINUTES],
            normalized_cache_limits[KEY_LINKEDIN_STALE_FALLBACK_MAX_AGE_MINUTES]["min"],
            normalized_cache_limits[KEY_LINKEDIN_STALE_FALLBACK_MAX_AGE_MINUTES]["max"],
        ),
        KEY_LINKEDIN_MAX_CONSECUTIVE_TARGET_FAILURES: _require_int(
            cache_source,
            KEY_LINKEDIN_MAX_CONSECUTIVE_TARGET_FAILURES,
            DEFAULT_CACHE_SETTINGS[KEY_LINKEDIN_MAX_CONSECUTIVE_TARGET_FAILURES],
            normalized_cache_limits[KEY_LINKEDIN_MAX_CONSECUTIVE_TARGET_FAILURES]["min"],
            normalized_cache_limits[KEY_LINKEDIN_MAX_CONSECUTIVE_TARGET_FAILURES]["max"],
        ),
        KEY_INCREMENTAL_SEARCH_OVERLAP_DAYS: _require_int(
            cache_source,
            KEY_INCREMENTAL_SEARCH_OVERLAP_DAYS,
            DEFAULT_CACHE_SETTINGS[KEY_INCREMENTAL_SEARCH_OVERLAP_DAYS],
            normalized_cache_limits[KEY_INCREMENTAL_SEARCH_OVERLAP_DAYS]["min"],
            normalized_cache_limits[KEY_INCREMENTAL_SEARCH_OVERLAP_DAYS]["max"],
        ),
        KEY_INCREMENTAL_SEARCH_CATCH_UP_INTERVAL_DAYS: _require_int(
            cache_source,
            KEY_INCREMENTAL_SEARCH_CATCH_UP_INTERVAL_DAYS,
            DEFAULT_CACHE_SETTINGS[KEY_INCREMENTAL_SEARCH_CATCH_UP_INTERVAL_DAYS],
            normalized_cache_limits[KEY_INCREMENTAL_SEARCH_CATCH_UP_INTERVAL_DAYS]["min"],
            normalized_cache_limits[KEY_INCREMENTAL_SEARCH_CATCH_UP_INTERVAL_DAYS]["max"],
        ),
        KEY_INCREMENTAL_SEARCH_LATE_DISCOVERY_THRESHOLD_DAYS: _require_int(
            cache_source,
            KEY_INCREMENTAL_SEARCH_LATE_DISCOVERY_THRESHOLD_DAYS,
            DEFAULT_CACHE_SETTINGS[KEY_INCREMENTAL_SEARCH_LATE_DISCOVERY_THRESHOLD_DAYS],
            normalized_cache_limits[KEY_INCREMENTAL_SEARCH_LATE_DISCOVERY_THRESHOLD_DAYS]["min"],
            normalized_cache_limits[KEY_INCREMENTAL_SEARCH_LATE_DISCOVERY_THRESHOLD_DAYS]["max"],
        ),
    }

    normalized_description_trust_settings = {
        KEY_MIN_TRUSTED_DESCRIPTION_LENGTH: _require_int(
            description_trust_source,
            KEY_MIN_TRUSTED_DESCRIPTION_LENGTH,
            DEFAULT_DESCRIPTION_TRUST_SETTINGS[KEY_MIN_TRUSTED_DESCRIPTION_LENGTH],
            1,
            100_000,
        ),
    }
    normalized_description_compaction_settings = {
        KEY_COMPACTION_ENABLED: bool(
            description_compaction_source.get(
                KEY_COMPACTION_ENABLED,
                DEFAULT_DESCRIPTION_COMPACTION_SETTINGS[KEY_COMPACTION_ENABLED],
            )
        ),
        KEY_COMPACTION_MIN_CHARS: _require_int(
            description_compaction_source,
            KEY_COMPACTION_MIN_CHARS,
            int(DEFAULT_DESCRIPTION_COMPACTION_SETTINGS[KEY_COMPACTION_MIN_CHARS]),
            100,
            10_000,
        ),
        KEY_COMPACTION_MIN_RETENTION: _require_float(
            description_compaction_source,
            KEY_COMPACTION_MIN_RETENTION,
            float(DEFAULT_DESCRIPTION_COMPACTION_SETTINGS[KEY_COMPACTION_MIN_RETENTION]),
            0.0,
            1.0,
        ),
    }
    normalized_source_document_settings = {
        KEY_CV_CHARS_PER_PAGE: _require_int(
            source_document_source,
            KEY_CV_CHARS_PER_PAGE,
            DEFAULT_SOURCE_DOCUMENT_SETTINGS[KEY_CV_CHARS_PER_PAGE],
            1,
            100_000,
        ),
        KEY_SOURCE_DOCUMENT_SUFFIXES: _normalize_source_document_suffixes(
            source_document_source,
            DEFAULT_SOURCE_DOCUMENT_SETTINGS[KEY_SOURCE_DOCUMENT_SUFFIXES],
        ),
    }

    browser_mode = (
        str(
            playwright_source.get(KEY_PLAYWRIGHT_BROWSER_MODE, DEFAULT_PLAYWRIGHT_BROWSER_MODE)
            or DEFAULT_PLAYWRIGHT_BROWSER_MODE
        )
        .strip()
        .lower()
    )
    if browser_mode not in {"ephemeral", "persistent"}:
        raise ValueError(
            "global_settings.playwright_browser_mode must be either 'ephemeral' or 'persistent'"
        )

    default_theme = str(
        ui_source.get(KEY_DEFAULT_THEME, DEFAULT_UI_SETTINGS[KEY_DEFAULT_THEME])
    ).strip().lower()
    if default_theme not in {"soft-professional", "bold-aggressive", "dark-professional"}:
        raise ValueError(
            "global_settings.ui_settings.default_theme must be soft-professional, "
            "bold-aggressive, or dark-professional"
        )

    return {
        KEY_ACCESS_SETTINGS: {
            KEY_REQUIRE_APPROVAL_FOR_NEW_USERS: bool(
                access_source.get(
                    KEY_REQUIRE_APPROVAL_FOR_NEW_USERS,
                    DEFAULT_ACCESS_SETTINGS[KEY_REQUIRE_APPROVAL_FOR_NEW_USERS],
                )
            ),
        },
        KEY_UI_SETTINGS: {
            KEY_DEFAULT_THEME: default_theme,
        },
        KEY_FIT_HIGHLIGHTS: {
            "strong_capability_count": _require_int(
                fit_source,
                "strong_capability_count",
                DEFAULT_FIT_HIGHLIGHTS["strong_capability_count"],
                0,
                10,
            ),
            "working_capability_count": _require_int(
                fit_source,
                "working_capability_count",
                DEFAULT_FIT_HIGHLIGHTS["working_capability_count"],
                0,
                10,
            ),
            "basic_capability_count": _require_int(
                fit_source,
                "basic_capability_count",
                DEFAULT_FIT_HIGHLIGHTS["basic_capability_count"],
                0,
                10,
            ),
            "reviewed_signal_count": _require_int(
                fit_source,
                "reviewed_signal_count",
                DEFAULT_FIT_HIGHLIGHTS["reviewed_signal_count"],
                0,
                10,
            ),
            "max_highlights": _require_int(
                fit_source, "max_highlights", DEFAULT_FIT_HIGHLIGHTS["max_highlights"], 1, 20
            ),
        },
        KEY_SEARCH_SETTINGS: {
            "keywords": str(search_source.get("keywords") or "").strip(),
            "locations": [
                str(value).strip()
                for value in search_source.get("locations", [])
                if str(value).strip()
            ],
            "classification_ids": [
                str(value).strip()
                for value in search_source.get("classification_ids", [])
                if str(value).strip()
            ],
            "classifications": [
                str(value).strip()
                for value in search_source.get("classifications", [])
                if str(value).strip()
            ],
            "subclassifications": [
                str(value).strip()
                for value in search_source.get("subclassifications", [])
                if str(value).strip()
            ],
            "companies": [
                str(value).strip()
                for value in search_source.get("companies", [])
                if str(value).strip()
            ],
            KEY_DATE_RANGE_DAYS: _require_int(
                search_source,
                KEY_DATE_RANGE_DAYS,
                DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS],
                normalized_search_limits[KEY_DATE_RANGE_DAYS]["min"],
                normalized_search_limits[KEY_DATE_RANGE_DAYS]["max"],
            ),
            KEY_SEEK_ENABLED: _normalize_bool(
                search_source, KEY_SEEK_ENABLED, _search_setting_default_bool(KEY_SEEK_ENABLED, True)
            ),
            KEY_LINKEDIN_ENABLED: _normalize_bool(
                search_source,
                KEY_LINKEDIN_ENABLED,
                _search_setting_default_bool(KEY_LINKEDIN_ENABLED, True),
            ),
            KEY_APSJOBS_ENABLED: _normalize_bool(
                search_source,
                KEY_APSJOBS_ENABLED,
                _search_setting_default_bool(KEY_APSJOBS_ENABLED, True),
            ),
            KEY_MARKET_SOURCE_MODE: _normalize_market_source_mode(search_source),
            KEY_SEEK_MAX_PAGES: _require_int(
                search_source,
                KEY_SEEK_MAX_PAGES,
                normalized_search_limits[KEY_SEEK_MAX_PAGES]["max"],
                normalized_search_limits[KEY_SEEK_MAX_PAGES]["min"],
                normalized_search_limits[KEY_SEEK_MAX_PAGES]["max"],
            ),
            KEY_SORT_NEWEST_FIRST: _normalize_bool(
                search_source, KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST]
            ),
            KEY_LINKEDIN_HOURS_OLD: _require_int(
                search_source,
                KEY_LINKEDIN_HOURS_OLD,
                DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD],
                normalized_search_limits[KEY_LINKEDIN_HOURS_OLD]["min"],
                normalized_search_limits[KEY_LINKEDIN_HOURS_OLD]["max"],
            ),
            KEY_LINKEDIN_RESULTS_PER_SEARCH: _require_int(
                search_source,
                KEY_LINKEDIN_RESULTS_PER_SEARCH,
                DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH],
                normalized_search_limits[KEY_LINKEDIN_RESULTS_PER_SEARCH]["min"],
                normalized_search_limits[KEY_LINKEDIN_RESULTS_PER_SEARCH]["max"],
            ),
            KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS: _require_int(
                search_source,
                KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS,
                DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS],
                normalized_search_limits[KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS]["min"],
                normalized_search_limits[KEY_LINKEDIN_JOBSPY_STALL_TIMEOUT_SECONDS]["max"],
            ),
            KEY_LINKEDIN_PARALLEL_SEARCH_WORKERS: _require_int(
                search_source,
                KEY_LINKEDIN_PARALLEL_SEARCH_WORKERS,
                _search_setting_default_int(KEY_LINKEDIN_PARALLEL_SEARCH_WORKERS, 3),
                normalized_search_limits[KEY_LINKEDIN_PARALLEL_SEARCH_WORKERS]["min"],
                normalized_search_limits[KEY_LINKEDIN_PARALLEL_SEARCH_WORKERS]["max"],
            ),
            KEY_LINKEDIN_PARALLEL_REVIEW_WORKERS: _require_int(
                search_source,
                KEY_LINKEDIN_PARALLEL_REVIEW_WORKERS,
                _search_setting_default_int(KEY_LINKEDIN_PARALLEL_REVIEW_WORKERS, 3),
                normalized_search_limits[KEY_LINKEDIN_PARALLEL_REVIEW_WORKERS]["min"],
                normalized_search_limits[KEY_LINKEDIN_PARALLEL_REVIEW_WORKERS]["max"],
            ),
            KEY_JOB_MARKET_MAP_PARALLEL_WORKERS: _require_int(
                search_source,
                KEY_JOB_MARKET_MAP_PARALLEL_WORKERS,
                _search_setting_default_int(KEY_JOB_MARKET_MAP_PARALLEL_WORKERS, 3),
                normalized_search_limits[KEY_JOB_MARKET_MAP_PARALLEL_WORKERS]["min"],
                normalized_search_limits[KEY_JOB_MARKET_MAP_PARALLEL_WORKERS]["max"],
            ),
            KEY_SEEK_QUICK_APPLY_ONLY: (
                None
                if search_source.get(KEY_SEEK_QUICK_APPLY_ONLY) in (None, "")
                else (
                    True
                    if str(search_source.get(KEY_SEEK_QUICK_APPLY_ONLY)).strip().lower() == "true"
                    else False
                    if str(search_source.get(KEY_SEEK_QUICK_APPLY_ONLY)).strip().lower() == "false"
                    else None
                )
            ),
            KEY_LINKEDIN_EASY_APPLY_ONLY: (
                None
                if search_source.get(KEY_LINKEDIN_EASY_APPLY_ONLY) in (None, "")
                else (
                    True
                    if str(search_source.get(KEY_LINKEDIN_EASY_APPLY_ONLY)).strip().lower()
                    == "true"
                    else False
                    if str(search_source.get(KEY_LINKEDIN_EASY_APPLY_ONLY)).strip().lower()
                    == "false"
                    else None
                )
            ),
            KEY_PLAYWRIGHT_VIEWPORT_WIDTH: _require_int(
                search_source,
                KEY_PLAYWRIGHT_VIEWPORT_WIDTH,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH],
                100,
                4000,
            ),
            KEY_PLAYWRIGHT_VIEWPORT_HEIGHT: _require_int(
                search_source,
                KEY_PLAYWRIGHT_VIEWPORT_HEIGHT,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT],
                100,
                4000,
            ),
            KEY_PLAYWRIGHT_SELECTOR_TIMEOUT: _require_int(
                search_source,
                KEY_PLAYWRIGHT_SELECTOR_TIMEOUT,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT],
                1000,
                60000,
            ),
        },
        KEY_LIMITS: {
            "search": normalized_search_limits,
            "salary": normalized_salary_limits,
            "onboarding": normalized_onboarding_limits,
            "history": normalized_history_limits,
            "cache": normalized_cache_limits,
        },
        KEY_PREFERENCE_WEIGHTS: _normalize_float_map(
            preference_source, DEFAULT_PREFERENCE_WEIGHTS, maximum=2.0
        ),
        KEY_EVIDENCE_TIER_WEIGHTS: _normalize_float_map(
            evidence_source, DEFAULT_EVIDENCE_TIER_WEIGHTS
        ),
        KEY_HISTORY_SETTINGS: normalized_history_settings,
        KEY_CACHE_SETTINGS: normalized_cache_settings,
        KEY_DESCRIPTION_TRUST_SETTINGS: normalized_description_trust_settings,
        KEY_DESCRIPTION_COMPACTION_SETTINGS: normalized_description_compaction_settings,
        KEY_SOURCE_DOCUMENT_SETTINGS: normalized_source_document_settings,
        KEY_DEFAULT_COUNTRY_SUFFIX: default_country_suffix,
        KEY_ONBOARDING_SETTINGS: {
            **{
                key: _require_int(
                    merged_onboarding,
                    key,
                    DEFAULT_ONBOARDING_SETTINGS[key],
                    normalized_onboarding_limits[key]["min"],
                    normalized_onboarding_limits[key]["max"],
                )
                for key in ONBOARDING_SETTING_LIMITS
            },
            "capability_strength_preset": preset_name,
            KEY_CAPABILITY_STRENGTH_PRESETS: normalized_preset_table,
        },
        KEY_LLM_SETTINGS: {
            "model": str(llm_source.get("model") or DEFAULT_LLM_SETTINGS.get("model")).strip(),
            KEY_MODEL_OPTIONS: normalized_model_options,
            KEY_LLM_PRICING_PER_1M: normalized_llm_pricing,
            KEY_LLM_REASONING_EFFORT_BY_MODEL: normalized_llm_reasoning_effort,
            KEY_LLM_MODEL_OVERRIDES_BY_PURPOSE: normalized_llm_model_overrides_by_purpose,
            "pricing_metadata": normalized_pricing_metadata,
            KEY_LLM_MAX_CHARS_LIMITS: normalized_max_chars_limits,
            KEY_LLM_PROMPT_SETTINGS: normalized_llm_prompt_settings,
            KEY_LLM_MAX_CHARS: max_llm_chars,
            KEY_LLM_REQUEST_TIMEOUT_SECONDS: llm_request_timeout_seconds,
            KEY_LLM_MAX_RETRIES: llm_max_retries,
            KEY_LLM_TEMPERATURE: llm_temperature,
        },
        KEY_REVIEW_SETTINGS: {
            KEY_REVIEW_MAX_EXAMPLES_PER_SKILL: _require_int(
                review_source,
                KEY_REVIEW_MAX_EXAMPLES_PER_SKILL,
                DEFAULT_REVIEW_SETTINGS[KEY_REVIEW_MAX_EXAMPLES_PER_SKILL],
                1,
                50,
            ),
            KEY_REVIEW_MAX_SAMPLES_PER_REJECTION: _require_int(
                review_source,
                KEY_REVIEW_MAX_SAMPLES_PER_REJECTION,
                DEFAULT_REVIEW_SETTINGS[KEY_REVIEW_MAX_SAMPLES_PER_REJECTION],
                1,
                50,
            ),
            KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT: _require_int(
                review_source,
                KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT,
                DEFAULT_REVIEW_SETTINGS[KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT],
                1,
                100,
            ),
            KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT: _require_int(
                review_source,
                KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT,
                DEFAULT_REVIEW_SETTINGS[KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT],
                1,
                100,
            ),
            KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT: _require_int(
                review_source,
                KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT,
                DEFAULT_REVIEW_SETTINGS[KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT],
                1,
                1000,
            ),
            KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT: _require_int(
                review_source,
                KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT,
                DEFAULT_REVIEW_SETTINGS[KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT],
                1,
                100,
            ),
        },
        "playwright_settings": {
            KEY_PLAYWRIGHT_VIEWPORT_WIDTH: _require_int(
                playwright_source,
                KEY_PLAYWRIGHT_VIEWPORT_WIDTH,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH],
                100,
                4000,
            ),
            KEY_PLAYWRIGHT_VIEWPORT_HEIGHT: _require_int(
                playwright_source,
                KEY_PLAYWRIGHT_VIEWPORT_HEIGHT,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT],
                100,
                4000,
            ),
            KEY_PLAYWRIGHT_SELECTOR_TIMEOUT: _require_int(
                playwright_source,
                KEY_PLAYWRIGHT_SELECTOR_TIMEOUT,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT],
                1000,
                60000,
            ),
            KEY_PLAYWRIGHT_HEADLESS: bool(playwright_source.get(KEY_PLAYWRIGHT_HEADLESS, True)),
            KEY_PLAYWRIGHT_BROWSER_MODE: browser_mode,
            KEY_SEEK_ASSISTED_VERIFICATION_ENABLED: bool(
                playwright_source.get(KEY_SEEK_ASSISTED_VERIFICATION_ENABLED, False)
            ),
            KEY_SEEK_MANUAL_VERIFICATION_TIMEOUT_MS: _require_int(
                playwright_source,
                KEY_SEEK_MANUAL_VERIFICATION_TIMEOUT_MS,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_SEEK_MANUAL_VERIFICATION_TIMEOUT_MS],
                30000,
                300000,
            ),
            KEY_SESSION_MAX_AGE_DAYS: _require_int(
                playwright_source, KEY_SESSION_MAX_AGE_DAYS, 7, 1, 365
            ),
        },
        KEY_CANDIDATE_APPLICATION_HISTORY: candidate_application_history_source
        if isinstance(candidate_application_history_source, dict)
        else {},
    }
