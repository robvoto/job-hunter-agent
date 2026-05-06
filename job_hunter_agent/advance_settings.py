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


KEY_FIT_HIGHLIGHTS = "fit_highlights"
KEY_SEARCH_SETTINGS = "search_settings"
KEY_SEARCH_LIMITS = "search_limits"
KEY_PREFERENCE_WEIGHTS = "preference_weights"
KEY_EVIDENCE_TIER_WEIGHTS = "candidate_profile_tier_weights"
KEY_ONBOARDING_SETTINGS = "onboarding_settings"
KEY_CAPABILITY_STRENGTH_PRESETS = "capability_strength_presets"

KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT = "primary_candidate_profile_context"
KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT = "secondary_candidate_profile_context"
KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT = "supplementary_candidate_profile_context"

KEY_LINKEDIN_EASY_APPLY_ONLY = "linkedin_easy_apply_only"

# Global card highlight controls are shared dashboard presentation settings.
DEFAULT_FIT_HIGHLIGHTS = {
    "strong_capability_count": 3,
    "working_capability_count": 2,
    "basic_capability_count": 1,
    "reviewed_signal_count": 3,
    "max_highlights": 4,
}

# Global search defaults are shared across every profile and keep runtime code data-driven.
DEFAULT_SEARCH_SETTINGS = {
    "keywords": "",
    "locations": [],
    "classification_ids": [],
    "date_range_days": 3,
    "seek_max_pages": 10,
    "enforce_posted_age_limit": True,
    "sort_newest_first": True,
    "linkedin_hours_old": 24,
    "linkedin_results_per_search": 50,
    KEY_LINKEDIN_EASY_APPLY_ONLY: None,
}

# Validation bounds live beside the defaults so profile code does not own hidden limits.
SEARCH_SETTING_LIMITS = {
    "date_range_days": {"min": 1, "max": 30},
    "seek_max_pages": {"min": 1, "max": 10},
    "linkedin_hours_old": {"min": 1, "max": 168},
    "linkedin_results_per_search": {"min": 5, "max": 100},
}

DEFAULT_PREFERENCE_WEIGHTS = {
    "fit": 1.0,
    "salary": 1.0,
    "location": 1.0,
    "work_mode": 1.0,
    "contract": 1.0,
    "government": 1.0,
    "freshness": 1.0,
}

DEFAULT_EVIDENCE_TIER_WEIGHTS = {
    KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT: 1.0,
    KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT: 0.55,
    KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT: 0.25,
}

DEFAULT_ONBOARDING_SETTINGS = {
    "extraction_lookback_years": 8,
    "title_extraction_min_months": 6,
    "max_target_patterns": 8,
    "max_secondary_patterns": 6,
    "capability_strength_preset": "balanced",
    "capability_recent_years": 4,
    "capability_strong_max_years_since_use": 4,
    "capability_strong_min_months": 36,
    "capability_strong_min_roles": 2,
    "capability_working_max_years_since_use": 8,
    "capability_working_min_months": 18,
    "capability_working_long_history_max_years_since_use": 12,
    "capability_working_long_history_min_months": 48,
    "capability_single_role_old_max_years_since_use": 8,
    "capability_drop_to_basic_after_years": 12,
    "capability_max_items": 20,
}

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
    "capability_strong_min_roles":                         (1, 10),
    "capability_working_max_years_since_use":              (1, 25),
    "capability_working_min_months":                       (1, 240),
    "capability_working_long_history_max_years_since_use": (1, 30),
    "capability_working_long_history_min_months":          (1, 360),
    "capability_single_role_old_max_years_since_use":      (1, 25),
    "capability_drop_to_basic_after_years":                (1, 40),
    "capability_max_items":                                (1, 50),
}

CAPABILITY_STRENGTH_PRESETS = {
    "recent_focus": {
        "capability_recent_years": 3,
        "capability_strong_max_years_since_use": 3,
        "capability_strong_min_months": 36,
        "capability_strong_min_roles": 2,
        "capability_working_max_years_since_use": 6,
        "capability_working_min_months": 18,
        "capability_working_long_history_max_years_since_use": 10,
        "capability_working_long_history_min_months": 60,
        "capability_single_role_old_max_years_since_use": 6,
        "capability_drop_to_basic_after_years": 10,
        "capability_max_items": 20,
    },
    "balanced": {
        "capability_recent_years": 4,
        "capability_strong_max_years_since_use": 4,
        "capability_strong_min_months": 36,
        "capability_strong_min_roles": 2,
        "capability_working_max_years_since_use": 8,
        "capability_working_min_months": 18,
        "capability_working_long_history_max_years_since_use": 12,
        "capability_working_long_history_min_months": 48,
        "capability_single_role_old_max_years_since_use": 8,
        "capability_drop_to_basic_after_years": 12,
        "capability_max_items": 20,
    },
    "include_older_experience": {
        "capability_recent_years": 5,
        "capability_strong_max_years_since_use": 5,
        "capability_strong_min_months": 30,
        "capability_strong_min_roles": 2,
        "capability_working_max_years_since_use": 10,
        "capability_working_min_months": 12,
        "capability_working_long_history_max_years_since_use": 15,
        "capability_working_long_history_min_months": 36,
        "capability_single_role_old_max_years_since_use": 10,
        "capability_drop_to_basic_after_years": 15,
        "capability_max_items": 24,
    },
}

# Default advance settings are persisted globally and shared across profiles.
DEFAULT_ADVANCE_SETTINGS: dict[str, Any] = {
    KEY_FIT_HIGHLIGHTS: dict(DEFAULT_FIT_HIGHLIGHTS),
    KEY_SEARCH_SETTINGS: dict(DEFAULT_SEARCH_SETTINGS),
    KEY_SEARCH_LIMITS: copy.deepcopy(SEARCH_SETTING_LIMITS),
    KEY_PREFERENCE_WEIGHTS: dict(DEFAULT_PREFERENCE_WEIGHTS),
    KEY_EVIDENCE_TIER_WEIGHTS: dict(DEFAULT_EVIDENCE_TIER_WEIGHTS),
    KEY_ONBOARDING_SETTINGS: {
        **DEFAULT_ONBOARDING_SETTINGS,
        KEY_CAPABILITY_STRENGTH_PRESETS: copy.deepcopy(CAPABILITY_STRENGTH_PRESETS),
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


def _normalize_bool(source: dict[str, Any], key: str, default: bool) -> bool:
    raw = source.get(key, default)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return bool(raw)


def normalize_advance_settings(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}

    fit_source = source.get(KEY_FIT_HIGHLIGHTS, {})
    search_source = source.get(KEY_SEARCH_SETTINGS, {})
    search_limits_source = source.get(KEY_SEARCH_LIMITS, {})
    preference_source = source.get(KEY_PREFERENCE_WEIGHTS, {})
    evidence_source = source.get(KEY_EVIDENCE_TIER_WEIGHTS, {})
    onboarding_source = source.get(KEY_ONBOARDING_SETTINGS, {})

    if not isinstance(fit_source, dict):
        raise ValueError(f"advance_settings.{KEY_FIT_HIGHLIGHTS} must be a dict, got {type(fit_source).__name__!r}")
    if not isinstance(search_source, dict):
        raise ValueError(f"advance_settings.{KEY_SEARCH_SETTINGS} must be a dict, got {type(search_source).__name__!r}")
    if not isinstance(search_limits_source, dict):
        raise ValueError(f"advance_settings.{KEY_SEARCH_LIMITS} must be a dict, got {type(search_limits_source).__name__!r}")
    if not isinstance(preference_source, dict):
        raise ValueError(f"advance_settings.{KEY_PREFERENCE_WEIGHTS} must be a dict, got {type(preference_source).__name__!r}")
    if not isinstance(evidence_source, dict):
        raise ValueError(f"advance_settings.{KEY_EVIDENCE_TIER_WEIGHTS} must be a dict, got {type(evidence_source).__name__!r}")
    if not isinstance(onboarding_source, dict):
        raise ValueError(f"advance_settings.{KEY_ONBOARDING_SETTINGS} must be a dict, got {type(onboarding_source).__name__!r}")

    preset_name = str(onboarding_source.get("capability_strength_preset") or DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]).strip().lower()
    preset_name = preset_name if preset_name in CAPABILITY_STRENGTH_PRESETS else DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
    preset_defaults = CAPABILITY_STRENGTH_PRESETS[preset_name]
    merged_onboarding = {**DEFAULT_ONBOARDING_SETTINGS, **preset_defaults, **{k: v for k, v in onboarding_source.items() if k != KEY_CAPABILITY_STRENGTH_PRESETS}}

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
            "date_range_days": _require_int(
                search_source,
                "date_range_days",
                DEFAULT_SEARCH_SETTINGS["date_range_days"],
                SEARCH_SETTING_LIMITS["date_range_days"]["min"],
                SEARCH_SETTING_LIMITS["date_range_days"]["max"],
            ),
            "seek_max_pages": _require_int(
                search_source,
                "seek_max_pages",
                DEFAULT_SEARCH_SETTINGS["seek_max_pages"],
                SEARCH_SETTING_LIMITS["seek_max_pages"]["min"],
                SEARCH_SETTING_LIMITS["seek_max_pages"]["max"],
            ),
            "enforce_posted_age_limit": _normalize_bool(search_source, "enforce_posted_age_limit", DEFAULT_SEARCH_SETTINGS["enforce_posted_age_limit"]),
            "sort_newest_first": _normalize_bool(search_source, "sort_newest_first", DEFAULT_SEARCH_SETTINGS["sort_newest_first"]),
            "linkedin_hours_old": _require_int(
                search_source,
                "linkedin_hours_old",
                DEFAULT_SEARCH_SETTINGS["linkedin_hours_old"],
                SEARCH_SETTING_LIMITS["linkedin_hours_old"]["min"],
                SEARCH_SETTING_LIMITS["linkedin_hours_old"]["max"],
            ),
            "linkedin_results_per_search": _require_int(
                search_source,
                "linkedin_results_per_search",
                DEFAULT_SEARCH_SETTINGS["linkedin_results_per_search"],
                SEARCH_SETTING_LIMITS["linkedin_results_per_search"]["min"],
                SEARCH_SETTING_LIMITS["linkedin_results_per_search"]["max"],
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
        },
        KEY_SEARCH_LIMITS: {
            **normalized_search_limits,
        },
        KEY_PREFERENCE_WEIGHTS: _normalize_float_map(preference_source, DEFAULT_PREFERENCE_WEIGHTS, maximum=2.0),
        KEY_EVIDENCE_TIER_WEIGHTS: _normalize_float_map(evidence_source, DEFAULT_EVIDENCE_TIER_WEIGHTS),
        KEY_ONBOARDING_SETTINGS: {
            **{
                key: _require_int(merged_onboarding, key, DEFAULT_ONBOARDING_SETTINGS[key], minimum, maximum)
                for key, (minimum, maximum) in ONBOARDING_SETTING_LIMITS.items()
            },
            "capability_strength_preset": preset_name,
            KEY_CAPABILITY_STRENGTH_PRESETS: normalized_preset_table,
        },
    }


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
