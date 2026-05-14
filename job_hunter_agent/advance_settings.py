"""Global advance settings.

These settings are system-wide, not candidate-specific. They control dashboard
presentation and other optimiser-style behaviour shared across profiles.
"""

import copy
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from job_hunter_agent.paths import ADVANCE_SETTINGS_PATH, DATA_DIR


def _load_managed_advance_settings_seed() -> dict[str, Any]:
    payload = json.loads(ADVANCE_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("advance_settings.json must contain a JSON object")
    return payload


_MANAGED_ADVANCE_SETTINGS_SEED = _load_managed_advance_settings_seed()


KEY_FIT_HIGHLIGHTS = "fit_highlights"
KEY_SEARCH_SETTINGS = "search_settings"
KEY_SEARCH_LIMITS = "search_limits"
KEY_SALARY_LIMITS = "salary_limits"
KEY_PREFERENCE_WEIGHTS = "preference_weights"
KEY_EVIDENCE_TIER_WEIGHTS = "candidate_profile_tier_weights"
KEY_HISTORY_SETTINGS = "history_settings"
KEY_DESCRIPTION_TRUST_SETTINGS = "description_trust_settings"
KEY_SOURCE_DOCUMENT_SETTINGS = "source_document_settings"
KEY_ONBOARDING_SETTINGS = "onboarding_settings"
KEY_LLM_SETTINGS = "llm_settings"
KEY_LLM_PROMPT_SETTINGS = "llm_prompt_settings"
KEY_LLM_MAX_CHARS = "max_llm_chars"
KEY_CAPABILITY_STRENGTH_PRESETS = "capability_strength_presets"
# These onboarding controls shape how much learned capability structure we keep
# and when a signal cluster is promoted into persisted profile data.
KEY_CAPABILITY_ALIAS_LIMIT = "capability_alias_limit"
KEY_SIGNAL_CLUSTER_MIN_ALIAS_HITS = "signal_cluster_min_alias_hits"
KEY_SIGNAL_CLUSTER_MIN_SNIPPET_HITS = "signal_cluster_min_snippet_hits"
KEY_SIGNAL_CLUSTER_DENSE_SNIPPET_ALIAS_HITS = "signal_cluster_dense_snippet_alias_hits"
KEY_MODEL_OPTIONS = "model_options"
KEY_LLM_PRICING_PER_1M = "pricing_per_1m"
KEY_LLM_PROMPT_TEMPLATES = "match_preference_templates"
KEY_LLM_PROMPT_EVIDENCE_TIERS = "evidence_tiers"
KEY_LLM_PROMPT_LEARNING_MAX_ITEMS = "learning_candidates_max_items"
KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS = "rejection_blocker_suggestions_max_items"
KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS = "rejection_blocker_suggestions_max_words"

KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT = "primary_candidate_profile_context"
KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT = "secondary_candidate_profile_context"
KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT = "supplementary_candidate_profile_context"

KEY_LINKEDIN_EASY_APPLY_ONLY = "linkedin_easy_apply_only"
KEY_SOURCE_DOCUMENT_SUFFIXES = "allowed_suffixes"

KEY_DATE_RANGE_DAYS = "date_range_days"
KEY_SEEK_MAX_PAGES = "seek_max_pages"
KEY_LINKEDIN_HOURS_OLD = "linkedin_hours_old"
KEY_LINKEDIN_RESULTS_PER_SEARCH = "linkedin_results_per_search"
KEY_PLAYWRIGHT_VIEWPORT_WIDTH = "playwright_viewport_width"
KEY_PLAYWRIGHT_VIEWPORT_HEIGHT = "playwright_viewport_height"
KEY_PLAYWRIGHT_SELECTOR_TIMEOUT = "playwright_selector_timeout"
KEY_PLAYWRIGHT_BROWSER_MODE = "playwright_browser_mode"
KEY_DEFAULT_COUNTRY_SUFFIX = "default_country_suffix"
KEY_ARCHIVE_STALE_AFTER_DAYS = "archive_stale_after_days"
KEY_HIDDEN_REVIEW_DAYS = "hidden_review_days"
KEY_MIN_TRUSTED_DESCRIPTION_LENGTH = "min_trusted_description_length"

# Global card highlight controls are shared dashboard presentation settings.
DEFAULT_FIT_HIGHLIGHTS = dict(_MANAGED_ADVANCE_SETTINGS_SEED[KEY_FIT_HIGHLIGHTS])

# Global search defaults are shared across every profile and keep runtime code data-driven.
DEFAULT_SEARCH_SETTINGS = dict(_MANAGED_ADVANCE_SETTINGS_SEED[KEY_SEARCH_SETTINGS])

# Validation bounds live beside the defaults so profile code does not own hidden limits.
SEARCH_SETTING_LIMITS = copy.deepcopy(_MANAGED_ADVANCE_SETTINGS_SEED[KEY_SEARCH_LIMITS])

DEFAULT_SALARY_LIMITS = copy.deepcopy(_MANAGED_ADVANCE_SETTINGS_SEED[KEY_SALARY_LIMITS])

DEFAULT_PREFERENCE_WEIGHTS = dict(_MANAGED_ADVANCE_SETTINGS_SEED[KEY_PREFERENCE_WEIGHTS])

DEFAULT_EVIDENCE_TIER_WEIGHTS = dict(_MANAGED_ADVANCE_SETTINGS_SEED[KEY_EVIDENCE_TIER_WEIGHTS])

DEFAULT_HISTORY_SETTINGS = dict(_MANAGED_ADVANCE_SETTINGS_SEED.get(KEY_HISTORY_SETTINGS, {}))

DEFAULT_DESCRIPTION_TRUST_SETTINGS = dict(_MANAGED_ADVANCE_SETTINGS_SEED.get(KEY_DESCRIPTION_TRUST_SETTINGS, {}))

DEFAULT_SOURCE_DOCUMENT_SETTINGS = {
    KEY_SOURCE_DOCUMENT_SUFFIXES: [
        str(value).strip().lower()
        for value in _MANAGED_ADVANCE_SETTINGS_SEED[KEY_SOURCE_DOCUMENT_SETTINGS][KEY_SOURCE_DOCUMENT_SUFFIXES]
        if str(value).strip()
    ],
}

DEFAULT_ONBOARDING_SETTINGS = {
    k: copy.deepcopy(v)
    for k, v in _MANAGED_ADVANCE_SETTINGS_SEED[KEY_ONBOARDING_SETTINGS].items()
    if k != KEY_CAPABILITY_STRENGTH_PRESETS
}

DEFAULT_LLM_SETTINGS = copy.deepcopy(_MANAGED_ADVANCE_SETTINGS_SEED[KEY_LLM_SETTINGS])

DEFAULT_LLM_PROMPT_SETTINGS = dict(DEFAULT_LLM_SETTINGS[KEY_LLM_PROMPT_SETTINGS])

DEFAULT_PLAYWRIGHT_SETTINGS = dict(_MANAGED_ADVANCE_SETTINGS_SEED.get("playwright_settings", {}))
DEFAULT_PLAYWRIGHT_BROWSER_MODE = str(
    DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_PLAYWRIGHT_BROWSER_MODE, "ephemeral")
).strip().lower()

DEFAULT_COUNTRY_SUFFIX = str(_MANAGED_ADVANCE_SETTINGS_SEED.get(KEY_DEFAULT_COUNTRY_SUFFIX, "Australia")).strip()

# Validation bounds for every onboarding setting. Centralised here so profile_store
# and normalize_advance_settings both use the same limits without duplication.
ONBOARDING_SETTING_LIMITS: dict[str, tuple[int, int]] = {
    "extraction_lookback_years":                           (1, 20),
    "title_extraction_min_months":                         (1, 24),
    "max_target_patterns":                                 (1, 20),
    "max_secondary_patterns":                              (1, 20),
    "capability_recent_years":                             (1, 15),
    "capability_strong_max_years_since_use":               (1, 20),
    "capability_strong_min_months":                        (1, 240),
    "capability_working_max_years_since_use":              (1, 25),
    "capability_working_min_months":                       (1, 240),
    "capability_working_long_history_max_years_since_use": (1, 30),
    "capability_working_long_history_min_months":          (1, 360),
    "capability_drop_to_basic_after_years":                (1, 40),
    "capability_max_items":                                (1, 50),
    "capability_alias_limit":                              (1, 20),
    "signal_cluster_min_alias_hits":                       (1, 10),
    "signal_cluster_min_snippet_hits":                     (1, 10),
    "signal_cluster_dense_snippet_alias_hits":             (1, 20),
}

CAPABILITY_STRENGTH_PRESETS = copy.deepcopy(_MANAGED_ADVANCE_SETTINGS_SEED[KEY_ONBOARDING_SETTINGS][KEY_CAPABILITY_STRENGTH_PRESETS])

# Default advance settings are persisted globally and shared across profiles.
DEFAULT_ADVANCE_SETTINGS: dict[str, Any] = {
    KEY_FIT_HIGHLIGHTS: copy.deepcopy(DEFAULT_FIT_HIGHLIGHTS),
    KEY_SEARCH_SETTINGS: copy.deepcopy(DEFAULT_SEARCH_SETTINGS),
    KEY_SEARCH_LIMITS: copy.deepcopy(SEARCH_SETTING_LIMITS),
    KEY_SALARY_LIMITS: copy.deepcopy(DEFAULT_SALARY_LIMITS),
    KEY_PREFERENCE_WEIGHTS: copy.deepcopy(DEFAULT_PREFERENCE_WEIGHTS),
    KEY_EVIDENCE_TIER_WEIGHTS: copy.deepcopy(DEFAULT_EVIDENCE_TIER_WEIGHTS),
    KEY_HISTORY_SETTINGS: copy.deepcopy(DEFAULT_HISTORY_SETTINGS),
    KEY_DESCRIPTION_TRUST_SETTINGS: copy.deepcopy(DEFAULT_DESCRIPTION_TRUST_SETTINGS),
    KEY_SOURCE_DOCUMENT_SETTINGS: copy.deepcopy(DEFAULT_SOURCE_DOCUMENT_SETTINGS),
    KEY_ONBOARDING_SETTINGS: {
        **copy.deepcopy(DEFAULT_ONBOARDING_SETTINGS),
        KEY_CAPABILITY_STRENGTH_PRESETS: copy.deepcopy(CAPABILITY_STRENGTH_PRESETS),
    },
    KEY_LLM_SETTINGS: copy.deepcopy(DEFAULT_LLM_SETTINGS),
    "playwright_settings": {
        KEY_PLAYWRIGHT_VIEWPORT_WIDTH: DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_PLAYWRIGHT_VIEWPORT_WIDTH, 1400),
        KEY_PLAYWRIGHT_VIEWPORT_HEIGHT: DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_PLAYWRIGHT_VIEWPORT_HEIGHT, 900),
        KEY_PLAYWRIGHT_SELECTOR_TIMEOUT: DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_PLAYWRIGHT_SELECTOR_TIMEOUT, 8000),
        KEY_PLAYWRIGHT_BROWSER_MODE: DEFAULT_PLAYWRIGHT_BROWSER_MODE,
    },
}


class AdvanceSettingsLoadError(RuntimeError):
    pass


def ensure_advance_settings_exists() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if ADVANCE_SETTINGS_PATH.exists():
        return
    save_advance_settings(DEFAULT_ADVANCE_SETTINGS)


def _backup_invalid_advance_settings() -> None:
    if not ADVANCE_SETTINGS_PATH.exists():
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = ADVANCE_SETTINGS_PATH.with_name(f"advance_settings.invalid.{timestamp}.json")
    backup_path.write_bytes(ADVANCE_SETTINGS_PATH.read_bytes())


def _require_int(source: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    raw = source.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"advance_settings.{key} must be an integer, got {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"advance_settings.{key} must be between {minimum} and {maximum}, got {value}")
    return value


def _require_float(source: dict[str, Any], key: str, default: float, minimum: float, maximum: float) -> float:
    raw = source.get(key, default)
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"advance_settings.{key} must be a number, got {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"advance_settings.{key} must be between {minimum} and {maximum}, got {value}")
    return value


def _normalize_int_map(source: dict[str, Any], defaults: dict[str, int], *, minimum: int = 0) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, default in defaults.items():
        normalized[key] = _require_int(source, key, int(default), minimum, 10_000)
    return normalized


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


def _normalize_llm_pricing_map(source: dict[str, Any], defaults: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    normalized: dict[str, dict[str, float]] = {}
    for model, raw_prices in source.items():
        if not isinstance(raw_prices, dict):
            raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PRICING_PER_1M}.{model} must be a dict")
        default_prices = defaults.get(model, {"input": 0.0, "output": 0.0})
        normalized[model] = {
            "input": _require_float(raw_prices, "input", float(default_prices["input"]), 0.0, 10_000.0),
            "output": _require_float(raw_prices, "output", float(default_prices["output"]), 0.0, 10_000.0),
        }
    if not normalized:
        normalized = copy.deepcopy(defaults)
    return normalized


def _normalize_llm_prompt_settings(source: dict[str, Any]) -> dict[str, Any]:
    templates_source = source.get(KEY_LLM_PROMPT_TEMPLATES, {})
    if not isinstance(templates_source, dict):
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_TEMPLATES} must be a dict")
    evidence_tiers_source = source.get(KEY_LLM_PROMPT_EVIDENCE_TIERS, [])
    if not isinstance(evidence_tiers_source, list):
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_EVIDENCE_TIERS} must be a list")

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
            raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_EVIDENCE_TIERS}[{index}].profile_key is required")
        evidence_tiers.append(
            {
                "profile_key": profile_key,
                "label": str(tier_source.get("label") or default_tier["label"]).strip(),
                "weight_label": str(tier_source.get("weight_label") or default_tier["weight_label"]).strip(),
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

    try:
        learning_max_items = int(source.get(KEY_LLM_PROMPT_LEARNING_MAX_ITEMS, DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_LEARNING_MAX_ITEMS]) or DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_LEARNING_MAX_ITEMS])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_LEARNING_MAX_ITEMS} must be an integer") from exc
    if learning_max_items < 1 or learning_max_items > 20:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_LEARNING_MAX_ITEMS} must be between 1 and 20")
    try:
        rejection_blocker_max_items = int(source.get(KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS, DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS]) or DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS} must be an integer") from exc
    if rejection_blocker_max_items < 1 or rejection_blocker_max_items > 20:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS} must be between 1 and 20")
    try:
        rejection_blocker_max_words = int(source.get(KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS, DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS]) or DEFAULT_LLM_PROMPT_SETTINGS[KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS} must be an integer") from exc
    if rejection_blocker_max_words < 1 or rejection_blocker_max_words > 20:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS}.{KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS} must be between 1 and 20")

    return {
        KEY_LLM_PROMPT_TEMPLATES: templates,
        KEY_LLM_PROMPT_EVIDENCE_TIERS: evidence_tiers,
        KEY_LLM_PROMPT_LEARNING_MAX_ITEMS: learning_max_items,
        KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS: rejection_blocker_max_items,
        KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS: rejection_blocker_max_words,
    }


def _normalize_bool(source: dict[str, Any], key: str, default: bool) -> bool:
    raw = source.get(key, default)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(raw)


def _normalize_source_document_suffixes(source: dict[str, Any], defaults: list[str]) -> list[str]:
    raw_suffixes = source.get(KEY_SOURCE_DOCUMENT_SUFFIXES, defaults)
    if not isinstance(raw_suffixes, list):
        raise ValueError(f"advance_settings.{KEY_SOURCE_DOCUMENT_SETTINGS}.{KEY_SOURCE_DOCUMENT_SUFFIXES} must be a list")

    normalized: list[str] = []
    for value in raw_suffixes:
        suffix = str(value or "").strip().lower()
        if not suffix:
            continue
        if not suffix.startswith("."):
            raise ValueError(f"advance_settings.{KEY_SOURCE_DOCUMENT_SETTINGS}.{KEY_SOURCE_DOCUMENT_SUFFIXES} entries must start with '.'")
        if " " in suffix:
            raise ValueError(f"advance_settings.{KEY_SOURCE_DOCUMENT_SETTINGS}.{KEY_SOURCE_DOCUMENT_SUFFIXES} entries must not contain spaces")
        if suffix not in normalized:
            normalized.append(suffix)
    if not normalized:
        raise ValueError(f"advance_settings.{KEY_SOURCE_DOCUMENT_SETTINGS}.{KEY_SOURCE_DOCUMENT_SUFFIXES} must contain at least one suffix")
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
            "min": _require_int(raw_bounds, "min", int(default.get("min", minimum)), minimum, maximum),
            "max": _require_int(raw_bounds, "max", int(default.get("max", maximum)), minimum, maximum),
        }
        if normalized[key]["min"] > normalized[key]["max"]:
            raise ValueError(f"advance_settings.{key}.min must be <= max")
    return normalized


def normalize_advance_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}

    fit_source = source.get(KEY_FIT_HIGHLIGHTS, {})
    search_source = source.get(KEY_SEARCH_SETTINGS, {})
    search_limits_source = source.get(KEY_SEARCH_LIMITS, {})
    salary_limits_source = source.get(KEY_SALARY_LIMITS, {})
    preference_source = source.get(KEY_PREFERENCE_WEIGHTS, {})
    evidence_source = source.get(KEY_EVIDENCE_TIER_WEIGHTS, {})
    history_source = source.get(KEY_HISTORY_SETTINGS, {})
    description_trust_source = source.get(KEY_DESCRIPTION_TRUST_SETTINGS, {})
    source_document_source = source.get(KEY_SOURCE_DOCUMENT_SETTINGS, {})
    onboarding_source = source.get(KEY_ONBOARDING_SETTINGS, {})
    llm_source = source.get(KEY_LLM_SETTINGS, {})
    playwright_source = source.get("playwright_settings", {})

    if not isinstance(fit_source, dict):
        raise ValueError(f"advance_settings.{KEY_FIT_HIGHLIGHTS} must be a dict, got {type(fit_source).__name__!r}")
    if not isinstance(search_source, dict):
        raise ValueError(f"advance_settings.{KEY_SEARCH_SETTINGS} must be a dict, got {type(search_source).__name__!r}")
    if not isinstance(search_limits_source, dict):
        raise ValueError(f"advance_settings.{KEY_SEARCH_LIMITS} must be a dict, got {type(search_limits_source).__name__!r}")
    if not isinstance(salary_limits_source, dict):
        raise ValueError(f"advance_settings.{KEY_SALARY_LIMITS} must be a dict, got {type(salary_limits_source).__name__!r}")
    if not isinstance(preference_source, dict):
        raise ValueError(f"advance_settings.{KEY_PREFERENCE_WEIGHTS} must be a dict, got {type(preference_source).__name__!r}")
    if not isinstance(evidence_source, dict):
        raise ValueError(f"advance_settings.{KEY_EVIDENCE_TIER_WEIGHTS} must be a dict, got {type(evidence_source).__name__!r}")
    if not isinstance(history_source, dict):
        raise ValueError(f"advance_settings.{KEY_HISTORY_SETTINGS} must be a dict, got {type(history_source).__name__!r}")
    if not isinstance(description_trust_source, dict):
        raise ValueError(f"advance_settings.{KEY_DESCRIPTION_TRUST_SETTINGS} must be a dict, got {type(description_trust_source).__name__!r}")
    if not isinstance(source_document_source, dict):
        raise ValueError(f"advance_settings.{KEY_SOURCE_DOCUMENT_SETTINGS} must be a dict, got {type(source_document_source).__name__!r}")
    if not isinstance(playwright_source, dict):
        raise ValueError(f"advance_settings.playwright_settings must be a dict, got {type(playwright_source).__name__!r}")
    if not isinstance(onboarding_source, dict):
        raise ValueError(f"advance_settings.{KEY_ONBOARDING_SETTINGS} must be a dict, got {type(onboarding_source).__name__!r}")
    if not isinstance(llm_source, dict):
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS} must be a dict, got {type(llm_source).__name__!r}")

    preset_name = str(onboarding_source.get("capability_strength_preset") or DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]).strip().lower()
    preset_name = preset_name if preset_name in CAPABILITY_STRENGTH_PRESETS else DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
    preset_defaults = CAPABILITY_STRENGTH_PRESETS[preset_name]
    merged_onboarding = {**DEFAULT_ONBOARDING_SETTINGS, **preset_defaults, **{k: v for k, v in onboarding_source.items() if k != KEY_CAPABILITY_STRENGTH_PRESETS}}

    model_options_source = llm_source.get(KEY_MODEL_OPTIONS, DEFAULT_LLM_SETTINGS[KEY_MODEL_OPTIONS])
    if not isinstance(model_options_source, list):
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_MODEL_OPTIONS} must be a list")
    normalized_model_options: list[str] = []
    for value in model_options_source:
        model = str(value or "").strip()
        if model and model not in normalized_model_options:
            normalized_model_options.append(model)
    if not normalized_model_options:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_MODEL_OPTIONS} must contain at least one model")
    pricing_source = llm_source.get(KEY_LLM_PRICING_PER_1M, {})
    if not isinstance(pricing_source, dict):
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PRICING_PER_1M} must be a dict")
    normalized_llm_pricing = _normalize_llm_pricing_map(pricing_source, DEFAULT_LLM_SETTINGS[KEY_LLM_PRICING_PER_1M])
    prompt_source = llm_source.get(KEY_LLM_PROMPT_SETTINGS, {})
    if not isinstance(prompt_source, dict):
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_PROMPT_SETTINGS} must be a dict")
    normalized_llm_prompt_settings = _normalize_llm_prompt_settings(prompt_source)

    try:
        max_llm_chars = int(llm_source.get(KEY_LLM_MAX_CHARS, DEFAULT_LLM_SETTINGS[KEY_LLM_MAX_CHARS]) or DEFAULT_LLM_SETTINGS[KEY_LLM_MAX_CHARS])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_MAX_CHARS} must be an integer") from exc
    if max_llm_chars < 1 or max_llm_chars > 20_000:
        raise ValueError(f"advance_settings.{KEY_LLM_SETTINGS}.{KEY_LLM_MAX_CHARS} must be between 1 and 20000")

    # Keep the configured preset table in the persisted settings file, not in feature code.
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

    # Search guardrails are stored as nested bounds so the UI can show them without guessing.
    normalized_search_limits: dict[str, dict[str, int]] = {}
    for limit_key, default_bounds in SEARCH_SETTING_LIMITS.items():
        bounds_source = search_limits_source.get(limit_key, {})
        if not isinstance(bounds_source, dict):
            bounds_source = {}
        min_value = _require_int(bounds_source, "min", int(default_bounds["min"]), 0, 10_000)
        max_value = _require_int(bounds_source, "max", int(default_bounds["max"]), 1, 10_000)
        if min_value > max_value:
            raise ValueError(f"advance_settings.search_limits.{limit_key}.min must be <= max")
        normalized_search_limits[limit_key] = {"min": min_value, "max": max_value}

    normalized_salary_limits = _normalize_limit_map(salary_limits_source, DEFAULT_SALARY_LIMITS, maximum=10_000_000)

    normalized_history_settings = {
        KEY_ARCHIVE_STALE_AFTER_DAYS: _require_int(
            history_source,
            KEY_ARCHIVE_STALE_AFTER_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_ARCHIVE_STALE_AFTER_DAYS],
            1,
            365,
        ),
        KEY_HIDDEN_REVIEW_DAYS: _require_int(
            history_source,
            KEY_HIDDEN_REVIEW_DAYS,
            DEFAULT_HISTORY_SETTINGS[KEY_HIDDEN_REVIEW_DAYS],
            1,
            365,
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
    normalized_source_document_settings = {
        KEY_SOURCE_DOCUMENT_SUFFIXES: _normalize_source_document_suffixes(
            source_document_source,
            DEFAULT_SOURCE_DOCUMENT_SETTINGS[KEY_SOURCE_DOCUMENT_SUFFIXES],
        ),
    }

    browser_mode = str(
        playwright_source.get(KEY_PLAYWRIGHT_BROWSER_MODE, DEFAULT_PLAYWRIGHT_BROWSER_MODE)
        or DEFAULT_PLAYWRIGHT_BROWSER_MODE
    ).strip().lower()
    if browser_mode not in {"ephemeral", "persistent"}:
        raise ValueError("advance_settings.playwright_browser_mode must be either 'ephemeral' or 'persistent'")

    return {
        KEY_FIT_HIGHLIGHTS: {
            "strong_capability_count": _require_int(fit_source, "strong_capability_count", DEFAULT_FIT_HIGHLIGHTS["strong_capability_count"], 0, 10),
            "working_capability_count": _require_int(fit_source, "working_capability_count", DEFAULT_FIT_HIGHLIGHTS["working_capability_count"], 0, 10),
            "basic_capability_count": _require_int(fit_source, "basic_capability_count", DEFAULT_FIT_HIGHLIGHTS["basic_capability_count"], 0, 10),
            "reviewed_signal_count": _require_int(fit_source, "reviewed_signal_count", DEFAULT_FIT_HIGHLIGHTS["reviewed_signal_count"], 0, 10),
            "max_highlights": _require_int(fit_source, "max_highlights", DEFAULT_FIT_HIGHLIGHTS["max_highlights"], 1, 20),
        },
        KEY_SEARCH_SETTINGS: {
            "keywords": str(search_source.get("keywords") or "").strip(),
            "locations": [str(value).strip() for value in search_source.get("locations", []) if str(value).strip()],
            "classification_ids": [str(value).strip() for value in search_source.get("classification_ids", []) if str(value).strip()],
            KEY_DATE_RANGE_DAYS: _require_int(
                search_source,
                KEY_DATE_RANGE_DAYS,
                DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS],
                normalized_search_limits[KEY_DATE_RANGE_DAYS]["min"],
                normalized_search_limits[KEY_DATE_RANGE_DAYS]["max"],
            ),
            KEY_SEEK_MAX_PAGES: _require_int(
                search_source,
                KEY_SEEK_MAX_PAGES,
                normalized_search_limits[KEY_SEEK_MAX_PAGES]["max"],
                normalized_search_limits[KEY_SEEK_MAX_PAGES]["min"],
                normalized_search_limits[KEY_SEEK_MAX_PAGES]["max"],
            ),
            "enforce_posted_age_limit": _normalize_bool(search_source, "enforce_posted_age_limit", DEFAULT_SEARCH_SETTINGS["enforce_posted_age_limit"]),
            "sort_newest_first": _normalize_bool(search_source, "sort_newest_first", DEFAULT_SEARCH_SETTINGS["sort_newest_first"]),
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
            KEY_LINKEDIN_EASY_APPLY_ONLY: (
                None
                if search_source.get(KEY_LINKEDIN_EASY_APPLY_ONLY) in (None, "")
                else (
                    True
                    if str(search_source.get(KEY_LINKEDIN_EASY_APPLY_ONLY)).strip().lower() == "true"
                    else False
                    if str(search_source.get(KEY_LINKEDIN_EASY_APPLY_ONLY)).strip().lower() == "false"
                    else None
                )
            ),
            KEY_PLAYWRIGHT_VIEWPORT_WIDTH: _require_int(
                search_source,
                KEY_PLAYWRIGHT_VIEWPORT_WIDTH,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH],
                100, 4000
            ),
            KEY_PLAYWRIGHT_VIEWPORT_HEIGHT: _require_int(
                search_source,
                KEY_PLAYWRIGHT_VIEWPORT_HEIGHT,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT],
                100, 4000
            ),
            KEY_PLAYWRIGHT_SELECTOR_TIMEOUT: _require_int(
                search_source,
                KEY_PLAYWRIGHT_SELECTOR_TIMEOUT,
                DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT],
                1000, 60000
            ),
        },
        KEY_SEARCH_LIMITS: {
            **normalized_search_limits,
        },
        KEY_SALARY_LIMITS: normalized_salary_limits,
        KEY_PREFERENCE_WEIGHTS: _normalize_float_map(preference_source, DEFAULT_PREFERENCE_WEIGHTS, maximum=2.0),
        KEY_EVIDENCE_TIER_WEIGHTS: _normalize_float_map(evidence_source, DEFAULT_EVIDENCE_TIER_WEIGHTS),
        KEY_HISTORY_SETTINGS: normalized_history_settings,
        KEY_DESCRIPTION_TRUST_SETTINGS: normalized_description_trust_settings,
        KEY_SOURCE_DOCUMENT_SETTINGS: normalized_source_document_settings,
        KEY_ONBOARDING_SETTINGS: {
            **{
                key: _require_int(merged_onboarding, key, DEFAULT_ONBOARDING_SETTINGS[key], minimum, maximum)
                for key, (minimum, maximum) in ONBOARDING_SETTING_LIMITS.items()
            },
            "capability_strength_preset": preset_name,
            KEY_CAPABILITY_STRENGTH_PRESETS: normalized_preset_table,
        },
        KEY_LLM_SETTINGS: {
            "model": str(llm_source.get("model") or DEFAULT_LLM_SETTINGS.get("model")).strip(),
            KEY_MODEL_OPTIONS: normalized_model_options,
            KEY_LLM_PRICING_PER_1M: normalized_llm_pricing,
            KEY_LLM_PROMPT_SETTINGS: normalized_llm_prompt_settings,
            KEY_LLM_MAX_CHARS: max_llm_chars,
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
            KEY_PLAYWRIGHT_BROWSER_MODE: browser_mode,
        },
    }


def get_default_country_suffix() -> str:
    return load_advance_settings().get(KEY_DEFAULT_COUNTRY_SUFFIX, DEFAULT_COUNTRY_SUFFIX)


def get_llm_max_chars() -> int:
    return int(load_advance_settings()[KEY_LLM_SETTINGS][KEY_LLM_MAX_CHARS])


def get_archive_stale_after_days() -> int:
    return int(load_advance_settings()[KEY_HISTORY_SETTINGS][KEY_ARCHIVE_STALE_AFTER_DAYS])


def get_hidden_review_days() -> int:
    return int(load_advance_settings()[KEY_HISTORY_SETTINGS][KEY_HIDDEN_REVIEW_DAYS])


def get_min_trusted_description_length() -> int:
    return int(load_advance_settings()[KEY_DESCRIPTION_TRUST_SETTINGS][KEY_MIN_TRUSTED_DESCRIPTION_LENGTH])


def get_playwright_browser_mode() -> str:
    settings = load_advance_settings().get("playwright_settings", {})
    return str(settings.get(KEY_PLAYWRIGHT_BROWSER_MODE, DEFAULT_PLAYWRIGHT_BROWSER_MODE)).strip().lower()


def get_salary_limits() -> dict[str, dict[str, int]]:
    settings = load_advance_settings().get(KEY_SALARY_LIMITS, {})
    return settings if isinstance(settings, dict) else copy.deepcopy(DEFAULT_SALARY_LIMITS)


def get_allowed_source_document_suffixes() -> frozenset[str]:
    settings = load_advance_settings().get(KEY_SOURCE_DOCUMENT_SETTINGS, {})
    suffixes = settings.get(KEY_SOURCE_DOCUMENT_SUFFIXES, []) if isinstance(settings, dict) else []
    return frozenset(
        str(value).strip().lower()
        for value in suffixes
        if str(value).strip()
    )


def get_allowed_source_document_suffixes_label() -> str:
    return ", ".join(sorted(get_allowed_source_document_suffixes()))

@lru_cache(maxsize=1)
def load_advance_settings() -> dict[str, Any]:
    ensure_advance_settings_exists()
    try:
        data = json.loads(ADVANCE_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _backup_invalid_advance_settings()
        raise AdvanceSettingsLoadError(f"Failed to parse advance_settings.json: {exc}") from exc
    if not isinstance(data, dict):
        _backup_invalid_advance_settings()
        raise AdvanceSettingsLoadError("advance_settings.json must contain a JSON object")
    return normalize_advance_settings(data)


def save_advance_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_advance_settings(settings)
    ADVANCE_SETTINGS_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    load_advance_settings.cache_clear()
    return normalized
