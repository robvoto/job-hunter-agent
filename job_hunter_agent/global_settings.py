"""Global settings."""

from __future__ import annotations

import json
import logging
import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

from job_hunter_agent.paths import GLOBAL_SETTINGS_PATH, RUNTIME_DIR
from job_hunter_agent.settings.global_settings_defaults import *  # noqa: F401,F403
from job_hunter_agent.settings.global_settings_normalization import normalize_global_settings
from job_hunter_agent.runtime_helpers import log_settings_change

logger = logging.getLogger(__name__)

_GLOBAL_SETTINGS_DOCUMENT_KEY = "global_settings"
# Rob-only local integration override. The file lives under data/runtime,
# which is ignored by git and must not be shipped in desktop builds.
_LOCAL_CANDIDATE_APPLICATION_HISTORY_OVERRIDE_PATH = (
    RUNTIME_DIR / "rob_candidate_application_history_import.local.json"
)


class GlobalSettingsLoadError(RuntimeError):
    pass


def _deep_merge_settings(base: Any, overlay: Any) -> Any:
    if isinstance(base, dict) and isinstance(overlay, dict):
        merged = copy.deepcopy(base)
        for key, value in overlay.items():
            merged[key] = _deep_merge_settings(merged.get(key), value)
        return merged
    return copy.deepcopy(overlay)


def _load_managed_global_settings() -> dict[str, Any]:
    data = json.loads(GLOBAL_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise GlobalSettingsLoadError("global_settings.json must contain a JSON object")
    return data


def _db_load(db_path: Path | None = None) -> dict[str, Any] | None:
    from job_hunter_agent.database import db_conn

    with db_conn(db_path) as conn:
        row = conn.execute("SELECT value FROM global_settings WHERE key = ?", (_GLOBAL_SETTINGS_DOCUMENT_KEY,)).fetchone()
    return json.loads(row["value"]) if row else None


def _db_save(settings: dict[str, Any], db_path: Path | None = None) -> None:
    from job_hunter_agent.database import db_conn

    with db_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO global_settings (key, value, updated_at)
            VALUES ( ?, ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (_GLOBAL_SETTINGS_DOCUMENT_KEY, json.dumps(settings, ensure_ascii=False)),
        )


def get_default_country_suffix() -> str:
    return str(load_global_settings()[KEY_DEFAULT_COUNTRY_SUFFIX]).strip()


def get_llm_max_chars() -> int:
    """Max chars for the combined (title + description) input to fit-review and learning-candidates calls.

    Truncation is applied in source_learning.resolve_llm_review_payload before the LLM gate is called.
    Lower than job_description_max_chars because the fit-review system prompt carries the full candidate
    profile, capability rules, and guidance — leaving less room for the job text.
    """
    return int(load_global_settings()[KEY_LLM_SETTINGS][KEY_LLM_MAX_CHARS])


def get_llm_prompt_setting_int(key: str) -> int:
    return int(load_global_settings()[KEY_LLM_SETTINGS][KEY_LLM_PROMPT_SETTINGS][key])


def get_llm_fit_decision_max_output_tokens() -> int:
    """Max tokens for the fit decision response."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_FIT_DECISION_MAX_OUTPUT_TOKENS)


def get_llm_learning_candidates_max_output_tokens() -> int:
    """Max tokens for the learning-candidate response."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_LEARNING_CANDIDATES_MAX_OUTPUT_TOKENS)


def get_llm_job_requirements_max_output_tokens() -> int:
    """Max tokens for the job-requirements response."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_JOB_REQUIREMENTS_MAX_OUTPUT_TOKENS)


def get_llm_rejection_blocker_suggestions_max_output_tokens() -> int:
    """Max tokens for blocker-term suggestions."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_OUTPUT_TOKENS)


def get_llm_capability_naming_max_output_tokens() -> int:
    """Max tokens for capability-cluster naming."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_NAMING_MAX_OUTPUT_TOKENS)


def get_llm_title_judgment_max_output_tokens() -> int:
    """Max tokens for the title-only target-role judgment response."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_TITLE_JUDGMENT_MAX_OUTPUT_TOKENS)


def get_llm_profile_extraction_max_output_tokens() -> int:
    """Max tokens for CV/profile extraction."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_PROFILE_EXTRACTION_MAX_OUTPUT_TOKENS)


def get_llm_job_description_max_chars() -> int:
    """Max description-only chars for secondary sidebar calls: rejection-blocker suggestions and
    job-requirements extraction. Higher than get_llm_max_chars() because these calls have
    lightweight system prompts (no candidate profile context).
    """
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_JOB_DESCRIPTION_MAX_CHARS)


def get_llm_capability_rules_max_items() -> int:
    """Max capability rules included in the prompt."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_RULES_MAX_ITEMS)


def get_llm_capability_rule_aliases_max_items() -> int:
    """Max aliases kept per capability rule."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_RULE_ALIASES_MAX_ITEMS)


def get_llm_fit_guidance_max_chars() -> int:
    """Max fit-guidance characters included in the prompt."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_FIT_GUIDANCE_MAX_CHARS)


def get_llm_capability_naming_aliases_max_items() -> int:
    """Max aliases used when naming capability clusters."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_CAPABILITY_NAMING_ALIASES_MAX_ITEMS)


def get_llm_raw_output_log_max_chars() -> int:
    """Max raw-output characters kept in logs."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_RAW_OUTPUT_LOG_MAX_CHARS)


def get_llm_fit_review_debug_match_diagnostics_enabled() -> bool:
    """Whether fit review uses the temporary debug-only match diagnostics schema."""
    return bool(
        load_global_settings()[KEY_LLM_SETTINGS][KEY_LLM_PROMPT_SETTINGS][
            KEY_LLM_PROMPT_FIT_REVIEW_DEBUG_MATCH_DIAGNOSTICS_ENABLED
        ]
    )


def get_llm_learning_candidates_max_items() -> int:
    """Max learning candidates returned by the LLM."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_LEARNING_MAX_ITEMS)


def get_llm_job_requirements_max_items() -> int:
    """Max job_requirements returned by the LLM."""
    return get_llm_prompt_setting_int(KEY_LLM_PROMPT_JOB_REQUIREMENTS_MAX_ITEMS)


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


def get_job_history_max_entries() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_JOB_HISTORY_MAX_ENTRIES])


def get_job_history_max_age_days() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_JOB_HISTORY_MAX_AGE_DAYS])


def get_repeated_listing_min_times_seen() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_REPEATED_LISTING_MIN_TIMES_SEEN])


def get_repeated_listing_min_span_days() -> int:
    return int(load_global_settings()[KEY_HISTORY_SETTINGS][KEY_REPEATED_LISTING_MIN_SPAN_DAYS])


def get_multi_listing_red_flag_min_listings() -> int:
    return int(
        load_global_settings()[KEY_HISTORY_SETTINGS][KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS]
    )


def get_multi_listing_red_flag_min_span_days() -> int:
    return int(
        load_global_settings()[KEY_HISTORY_SETTINGS][KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS]
    )


def get_llm_cache_max_entries() -> int:
    return int(load_global_settings()[KEY_CACHE_SETTINGS][KEY_LLM_CACHE_MAX_ENTRIES])


def get_llm_cache_max_age_days() -> int:
    return int(load_global_settings()[KEY_CACHE_SETTINGS][KEY_LLM_CACHE_MAX_AGE_DAYS])


def get_cv_extraction_cache_max_entries() -> int:
    return int(load_global_settings()[KEY_CACHE_SETTINGS][KEY_CV_EXTRACTION_CACHE_MAX_ENTRIES])


def get_cv_extraction_cache_max_age_days() -> int:
    return int(load_global_settings()[KEY_CACHE_SETTINGS][KEY_CV_EXTRACTION_CACHE_MAX_AGE_DAYS])


def get_candidate_application_history_cache_max_entries() -> int:
    return int(
        load_global_settings()[KEY_CACHE_SETTINGS][
            KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_ENTRIES
        ]
    )


def get_candidate_application_history_cache_max_age_days() -> int:
    return int(
        load_global_settings()[KEY_CACHE_SETTINGS][
            KEY_CANDIDATE_APPLICATION_HISTORY_CACHE_MAX_AGE_DAYS
        ]
    )


def get_occupation_title_cache_max_entries() -> int:
    return int(load_global_settings()[KEY_CACHE_SETTINGS][KEY_OCCUPATION_TITLE_CACHE_MAX_ENTRIES])


def get_occupation_title_cache_max_age_days() -> int:
    return int(
        load_global_settings()[KEY_CACHE_SETTINGS][KEY_OCCUPATION_TITLE_CACHE_MAX_AGE_DAYS]
    )


def get_min_trusted_description_length() -> int:
    return int(
        load_global_settings()[KEY_DESCRIPTION_TRUST_SETTINGS][KEY_MIN_TRUSTED_DESCRIPTION_LENGTH]
    )


def get_description_compaction_enabled() -> bool:
    return bool(load_global_settings()[KEY_DESCRIPTION_COMPACTION_SETTINGS][KEY_COMPACTION_ENABLED])


def get_description_compaction_min_chars() -> int:
    return int(
        load_global_settings()[KEY_DESCRIPTION_COMPACTION_SETTINGS][KEY_COMPACTION_MIN_CHARS]
    )


def get_description_compaction_min_retention() -> float:
    return float(
        load_global_settings()[KEY_DESCRIPTION_COMPACTION_SETTINGS][KEY_COMPACTION_MIN_RETENTION]
    )


def get_playwright_headless() -> bool:
    return bool(load_global_settings()["playwright_settings"][KEY_PLAYWRIGHT_HEADLESS])


def get_playwright_browser_mode() -> str:
    return (
        str(load_global_settings()["playwright_settings"][KEY_PLAYWRIGHT_BROWSER_MODE])
        .strip()
        .lower()
    )


def get_seek_assisted_verification_enabled() -> bool:
    return bool(
        load_global_settings()["playwright_settings"].get(
            KEY_SEEK_ASSISTED_VERIFICATION_ENABLED, False
        )
    )


def get_salary_limits() -> dict[str, dict[str, int]]:
    return load_global_settings()[KEY_LIMITS]["salary"]


def get_allowed_source_document_suffixes() -> frozenset[str]:
    suffixes = load_global_settings()[KEY_SOURCE_DOCUMENT_SETTINGS][KEY_SOURCE_DOCUMENT_SUFFIXES]
    return frozenset(str(value).strip().lower() for value in suffixes if str(value).strip())


def get_allowed_source_document_suffixes_label() -> str:
    return ", ".join(sorted(get_allowed_source_document_suffixes()))


def get_cv_chars_per_page() -> int:
    return int(load_global_settings()[KEY_SOURCE_DOCUMENT_SETTINGS][KEY_CV_CHARS_PER_PAGE])


def _load_local_candidate_application_history_override() -> dict[str, Any]:
    """Load local-only ignored runtime settings when present."""
    if not _LOCAL_CANDIDATE_APPLICATION_HISTORY_OVERRIDE_PATH.exists():
        return {}

    data = json.loads(
        _LOCAL_CANDIDATE_APPLICATION_HISTORY_OVERRIDE_PATH.read_text(encoding="utf-8-sig")
    )
    if not isinstance(data, dict):
        raise GlobalSettingsLoadError("Local override must contain a JSON object")

    section = data.get(KEY_CANDIDATE_APPLICATION_HISTORY, data)
    if not isinstance(section, dict):
        raise GlobalSettingsLoadError("Local override section must contain a JSON object")
    return section


def get_candidate_application_history_settings() -> dict[str, Any]:
    """Return settings with ignored local runtime override applied."""
    settings = dict(load_global_settings()[KEY_CANDIDATE_APPLICATION_HISTORY])
    settings.update(_load_local_candidate_application_history_override())
    return settings


def is_candidate_application_history_enabled() -> bool:
    return bool(get_candidate_application_history_settings()["enabled"])


def get_candidate_application_history_spreadsheet_id() -> str:
    return str(get_candidate_application_history_settings()["spreadsheet_id"])


def get_candidate_application_history_tab_name() -> str:
    return str(get_candidate_application_history_settings()["tab_name"])


def get_candidate_application_history_required_headers() -> list[str]:
    return list(get_candidate_application_history_settings()["required_headers"])


def get_candidate_application_history_sync_before_run() -> bool:
    return bool(
        get_candidate_application_history_settings().get(
            KEY_CANDIDATE_APPLICATION_HISTORY_SYNC_BEFORE_RUN, False
        )
    )


@lru_cache(maxsize=1)
def load_global_settings() -> dict[str, Any]:
    data = _db_load()
    if data is None:
        raise GlobalSettingsLoadError(
            "global_settings table is empty; seed the database from data/config/global_settings.json"
        )
    if not isinstance(data, dict):
        raise GlobalSettingsLoadError("global_settings in DB must contain a JSON object")
    merged = _deep_merge_settings(_load_managed_global_settings(), data)
    normalized = normalize_global_settings(merged, strict_managed=True)
    if normalized != data:
        logger.warning(
            "Global settings DB row was missing or stale versus managed defaults; repairing in place."
        )
        _db_save(normalized)
    return normalized


def seed_global_settings_from_file(db_path: Path | None = None, *, overwrite: bool = False) -> bool:
    if not overwrite and _db_load(db_path) is not None:
        return False
    normalized = normalize_global_settings(_load_managed_global_settings(), strict_managed=True)
    _db_save(normalized, db_path)
    load_global_settings.cache_clear()
    return True


def get_review_settings() -> dict[str, Any]:
    return load_global_settings()[KEY_REVIEW_SETTINGS]


def save_global_settings(settings: dict[str, Any]) -> dict[str, Any]:
    try:
        current = _db_load()
        current_normalized = (
            normalize_global_settings(current) if isinstance(current, dict) else current
        )
    except Exception:
        current_normalized = None
    # The admin UI PATCHes only the sections it renders. Preserve the hidden
    # runtime-owned candidate history section when the request omits it, so the
    # browser settings form does not collapse it to an empty dict.
    merged_settings = dict(settings) if isinstance(settings, dict) else {}
    if (
        isinstance(current_normalized, dict)
        and KEY_CANDIDATE_APPLICATION_HISTORY not in merged_settings
        and KEY_CANDIDATE_APPLICATION_HISTORY in current_normalized
    ):
        merged_settings[KEY_CANDIDATE_APPLICATION_HISTORY] = current_normalized[
            KEY_CANDIDATE_APPLICATION_HISTORY
        ]
    normalized = normalize_global_settings(merged_settings)
    _db_save(normalized)
    load_global_settings.cache_clear()
    log_settings_change(
        logger,
        scope="GLOBAL_SETTINGS",
        before=current_normalized,
        after=normalized,
    )
    return normalized
