"""Global settings."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from job_hunter_agent.paths import CONFIG_DIR, GLOBAL_SETTINGS_PATH
from job_hunter_agent.settings.global_settings_defaults import *  # noqa: F401,F403
from job_hunter_agent.settings.global_settings_normalization import normalize_global_settings


class GlobalSettingsLoadError(RuntimeError):
    pass


def ensure_global_settings_exists() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if GLOBAL_SETTINGS_PATH.exists():
        return
    save_global_settings(DEFAULT_GLOBAL_SETTINGS)


def _backup_invalid_global_settings() -> None:
    if not GLOBAL_SETTINGS_PATH.exists():
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = GLOBAL_SETTINGS_PATH.with_name(f"global_settings.invalid.{timestamp}.json")
    backup_path.write_bytes(GLOBAL_SETTINGS_PATH.read_bytes())


def get_default_country_suffix() -> str:
    return str(load_global_settings()[KEY_DEFAULT_COUNTRY_SUFFIX]).strip()


def get_llm_max_chars() -> int:
    return int(load_global_settings()[KEY_LLM_SETTINGS][KEY_LLM_MAX_CHARS])


def get_llm_prompt_setting_int(key: str) -> int:
    return int(load_global_settings()[KEY_LLM_SETTINGS][KEY_LLM_PROMPT_SETTINGS][key])


def get_llm_fit_decision_max_output_tokens() -> int:
    """Max tokens for the fit decision response."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_FIT_DECISION_MAX_OUTPUT_TOKENS)


def get_llm_learning_candidates_max_output_tokens() -> int:
    """Max tokens for the learning-candidate response."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_LEARNING_CANDIDATES_MAX_OUTPUT_TOKENS)


def get_llm_rejection_blocker_suggestions_max_output_tokens() -> int:
    """Max tokens for blocker-term suggestions."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_OUTPUT_TOKENS)


def get_llm_capability_naming_max_output_tokens() -> int:
    """Max tokens for capability-cluster naming."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_NAMING_MAX_OUTPUT_TOKENS)


def get_llm_profile_extraction_max_output_tokens() -> int:
    """Max tokens for CV/profile extraction."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_PROFILE_EXTRACTION_MAX_OUTPUT_TOKENS)


def get_llm_job_description_max_chars() -> int:
    """Max job-description characters sent to the LLM."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_JOB_DESCRIPTION_MAX_CHARS)


def get_llm_profile_brief_max_chars() -> int:
    """Max profile-brief characters sent to the LLM."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_PROFILE_BRIEF_MAX_CHARS)


def get_llm_capability_rules_max_items() -> int:
    """Max capability rules included in the prompt."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_RULES_MAX_ITEMS)


def get_llm_capability_rule_aliases_max_items() -> int:
    """Max aliases kept per capability rule."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_RULE_ALIASES_MAX_ITEMS)


def get_llm_fit_guidance_max_chars() -> int:
    """Max fit-guidance characters included in the prompt."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_FIT_GUIDANCE_MAX_CHARS)


def get_llm_capability_naming_guidance_max_chars() -> int:
    """Max naming-guidance characters included in the prompt."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_NAMING_GUIDANCE_MAX_CHARS)


def get_llm_capability_naming_aliases_max_items() -> int:
    """Max aliases used when naming capability clusters."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_NAMING_ALIASES_MAX_ITEMS)


def get_llm_raw_output_log_max_chars() -> int:
    """Max raw-output characters kept in logs."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_RAW_OUTPUT_LOG_MAX_CHARS)


def get_llm_learning_candidates_max_items() -> int:
    """Max learning candidates returned by the LLM."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_LEARNING_MAX_ITEMS)


def get_llm_rejection_blocker_suggestions_max_items() -> int:
    """Max blocker suggestions returned by the LLM."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS)


def get_llm_rejection_blocker_suggestions_max_words() -> int:
    """Max words allowed per blocker suggestion."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS)


def get_llm_cv_evidence_json_chars() -> int:
    """Max JSON evidence characters included in profile extraction."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CV_EVIDENCE_JSON_CHARS)


def get_llm_cv_fallback_chars() -> int:
    """Max fallback CV text characters included in profile extraction."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CV_FALLBACK_CHARS)


def get_archive_stale_after_days() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_ARCHIVE_STALE_AFTER_DAYS])


def get_hidden_review_days() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_HIDDEN_REVIEW_DAYS])


def get_max_history_sightings() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_MAX_HISTORY_SIGHTINGS])


def get_repeated_listing_min_times_seen() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_REPEATED_LISTING_MIN_TIMES_SEEN])


def get_repeated_listing_min_span_days() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_REPEATED_LISTING_MIN_SPAN_DAYS])


def get_multi_listing_red_flag_min_listings() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS])


def get_multi_listing_red_flag_min_span_days() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS])


def get_min_trusted_description_length() -> int:
    return int(load_global_settings()[KEY_DESCRIPTION_TRUST_SETTINGS][KEY_MIN_TRUSTED_DESCRIPTION_LENGTH])


def get_playwright_browser_mode() -> str:
    settings = load_global_settings().get("playwright_settings", {})
    return str(settings.get(KEY_PLAYWRIGHT_BROWSER_MODE, DEFAULT_PLAYWRIGHT_BROWSER_MODE)).strip().lower()


def get_salary_limits() -> dict[str, dict[str, int]]:
    settings = load_global_settings().get(KEY_LIMITS, {}).get("salary", {})
    return settings if isinstance(settings, dict) else copy.deepcopy(DEFAULT_SALARY_LIMITS)


def get_allowed_source_document_suffixes() -> frozenset[str]:
    settings = load_global_settings().get(KEY_SOURCE_DOCUMENT_SETTINGS, {})
    suffixes = settings.get(KEY_SOURCE_DOCUMENT_SUFFIXES, []) if isinstance(settings, dict) else []
    return frozenset(
        str(value).strip().lower()
        for value in suffixes
        if str(value).strip()
    )


def get_allowed_source_document_suffixes_label() -> str:
    return ", ".join(sorted(get_allowed_source_document_suffixes()))

@lru_cache(maxsize=1)
def load_global_settings() -> dict[str, Any]:
    ensure_global_settings_exists()
    try:
        data = json.loads(GLOBAL_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _backup_invalid_global_settings()
        raise GlobalSettingsLoadError(f"Failed to parse global_settings.json: {exc}") from exc
    if not isinstance(data, dict):
        _backup_invalid_global_settings()
        raise GlobalSettingsLoadError("global_settings.json must contain a JSON object")
    return normalize_global_settings(data)


def get_review_settings() -> dict[str, Any]:
    return load_global_settings()[KEY_REVIEW_SETTINGS]


def save_global_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_global_settings(settings)
    GLOBAL_SETTINGS_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    load_global_settings.cache_clear()
    return normalized
