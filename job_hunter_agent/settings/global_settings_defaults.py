"""Static global settings constants and managed defaults."""

from __future__ import annotations

import copy
import json
from typing import Any

from job_hunter_agent.paths import GLOBAL_SETTINGS_PATH


def _load_managed_global_settings_seed() -> dict[str, Any]:
    payload = json.loads(GLOBAL_SETTINGS_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("global_settings.json must contain a JSON object")
    return payload


_MANAGED_GLOBAL_SETTINGS_SEED = _load_managed_global_settings_seed()


KEY_FIT_HIGHLIGHTS = "fit_highlights"
KEY_LIMITS = "limits"
KEY_SEARCH_SETTINGS = "search_settings"
KEY_SEARCH_LIMITS = "search_limits"
KEY_SALARY_LIMITS = "salary_limits"
KEY_PREFERENCE_WEIGHTS = "preference_weights"
KEY_EVIDENCE_TIER_WEIGHTS = "candidate_profile_tier_weights"
KEY_HISTORY_SETTINGS = "history_settings"
KEY_MAX_HISTORY_SIGHTINGS = "max_history_sightings"
KEY_REPEATED_LISTING_MIN_TIMES_SEEN = "repeated_listing_min_times_seen"
KEY_REPEATED_LISTING_MIN_SPAN_DAYS = "repeated_listing_min_span_days"
KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS = "multi_listing_red_flag_min_listings"
KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS = "multi_listing_red_flag_min_span_days"
KEY_DESCRIPTION_TRUST_SETTINGS = "description_trust_settings"
KEY_SOURCE_DOCUMENT_SETTINGS = "source_document_settings"
KEY_ONBOARDING_SETTINGS = "onboarding_settings"
KEY_LLM_SETTINGS = "llm_settings"
KEY_LLM_PROMPT_SETTINGS = "llm_prompt_settings"
KEY_LLM_MAX_CHARS = "max_llm_chars"
KEY_CAPABILITY_STRENGTH_PRESETS = "capability_strength_presets"
KEY_CAPABILITY_ALIAS_LIMIT = "capability_alias_limit"
KEY_CV_MAX_PAGES = "cv_max_pages"
KEY_SIGNAL_CLUSTER_MIN_ALIAS_HITS = "signal_cluster_min_alias_hits"
KEY_SIGNAL_CLUSTER_MIN_SNIPPET_HITS = "signal_cluster_min_snippet_hits"
KEY_SIGNAL_CLUSTER_DENSE_SNIPPET_ALIAS_HITS = "signal_cluster_dense_snippet_alias_hits"
KEY_MODEL_OPTIONS = "model_options"
KEY_LLM_MAX_CHARS_LIMITS = "max_llm_chars_limits"
KEY_LLM_PRICING_PER_1M = "pricing_per_1m"
KEY_LLM_PROMPT_TEMPLATES = "match_preference_templates"
KEY_LLM_PROMPT_EVIDENCE_TIERS = "evidence_tiers"
KEY_LLM_PROMPT_FIT_DECISION_MAX_OUTPUT_TOKENS = "fit_decision_max_output_tokens"
KEY_LLM_PROMPT_LEARNING_CANDIDATES_MAX_OUTPUT_TOKENS = "learning_candidates_max_output_tokens"
KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_OUTPUT_TOKENS = "rejection_blocker_suggestions_max_output_tokens"
KEY_LLM_PROMPT_CAPABILITY_NAMING_MAX_OUTPUT_TOKENS = "capability_naming_max_output_tokens"
KEY_LLM_PROMPT_PROFILE_EXTRACTION_MAX_OUTPUT_TOKENS = "profile_extraction_max_output_tokens"
KEY_LLM_PROMPT_JOB_DESCRIPTION_MAX_CHARS = "job_description_max_chars"
KEY_LLM_PROMPT_CV_EVIDENCE_JSON_CHARS = "cv_evidence_json_chars"
KEY_LLM_PROMPT_CV_FALLBACK_CHARS = "cv_fallback_chars"
KEY_LLM_PROMPT_PROFILE_BRIEF_MAX_CHARS = "profile_brief_max_chars"
KEY_LLM_PROMPT_CAPABILITY_RULES_MAX_ITEMS = "capability_rules_max_items"
KEY_LLM_PROMPT_CAPABILITY_RULE_ALIASES_MAX_ITEMS = "capability_rule_aliases_max_items"
KEY_LLM_PROMPT_FIT_GUIDANCE_MAX_CHARS = "fit_guidance_max_chars"
KEY_LLM_PROMPT_CAPABILITY_NAMING_ALIASES_MAX_ITEMS = "capability_naming_aliases_max_items"
KEY_LLM_PROMPT_RAW_OUTPUT_LOG_MAX_CHARS = "raw_output_log_max_chars"
KEY_LLM_PROMPT_LEARNING_MAX_ITEMS = "learning_candidates_max_items"
KEY_LLM_PROMPT_CONTEXTUAL_MATCHES_MAX_ITEMS = "contextual_matches_max_items"
KEY_LLM_PROMPT_JOB_REQUIREMENTS_MAX_ITEMS = "job_requirements_max_items"
KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_ITEMS = "rejection_blocker_suggestions_max_items"
KEY_LLM_PROMPT_REJECTION_BLOCKER_MAX_WORDS = "rejection_blocker_suggestions_max_words"

KEY_REVIEW_SETTINGS = "review_settings"
KEY_REVIEW_MAX_EXAMPLES_PER_SKILL = "max_examples_per_skill"
KEY_REVIEW_MAX_SAMPLES_PER_REJECTION = "max_samples_per_rejection"
KEY_REVIEW_CAPABILITY_SUGGESTION_MIN_COUNT = "capability_suggestion_min_count"
KEY_REVIEW_CAPABILITY_WORKING_MIN_COUNT = "capability_working_min_count"
KEY_REVIEW_TITLE_NOT_TARGET_MIN_COUNT = "title_not_target_min_count"
KEY_REVIEW_RULE_SUGGESTION_MIN_COUNT = "rule_suggestion_min_count"

KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT = "primary_candidate_profile_context"
KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT = "secondary_candidate_profile_context"
KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT = "supplementary_candidate_profile_context"

KEY_LINKEDIN_EASY_APPLY_ONLY = "linkedin_easy_apply_only"
KEY_SOURCE_DOCUMENT_SUFFIXES = "allowed_suffixes"

KEY_DATE_RANGE_DAYS = "date_range_days"
KEY_SEEK_MAX_PAGES = "seek_max_pages"
KEY_LINKEDIN_HOURS_OLD = "linkedin_hours_old"
KEY_LINKEDIN_RESULTS_PER_SEARCH = "linkedin_results_per_search"
KEY_SORT_NEWEST_FIRST = "sort_newest_first"
KEY_PLAYWRIGHT_VIEWPORT_WIDTH = "playwright_viewport_width"
KEY_PLAYWRIGHT_VIEWPORT_HEIGHT = "playwright_viewport_height"
KEY_PLAYWRIGHT_SELECTOR_TIMEOUT = "playwright_selector_timeout"
KEY_PLAYWRIGHT_BROWSER_MODE = "playwright_browser_mode"
KEY_DEFAULT_COUNTRY_SUFFIX = "default_country_suffix"
KEY_ARCHIVE_STALE_AFTER_DAYS = "archive_stale_after_days"
KEY_HIDDEN_REVIEW_DAYS = "hidden_review_days"
KEY_MIN_TRUSTED_DESCRIPTION_LENGTH = "min_trusted_description_length"


DEFAULT_FIT_HIGHLIGHTS = dict(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_FIT_HIGHLIGHTS])
DEFAULT_SEARCH_SETTINGS = dict(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_SEARCH_SETTINGS])
SEARCH_SETTING_LIMITS = copy.deepcopy(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_LIMITS]["search"])
DEFAULT_SALARY_LIMITS = copy.deepcopy(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_LIMITS]["salary"])
DEFAULT_PREFERENCE_WEIGHTS = dict(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_PREFERENCE_WEIGHTS])
DEFAULT_EVIDENCE_TIER_WEIGHTS = dict(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_EVIDENCE_TIER_WEIGHTS])
DEFAULT_HISTORY_SETTINGS = dict(_MANAGED_GLOBAL_SETTINGS_SEED.get(KEY_HISTORY_SETTINGS, {}))
HISTORY_SETTING_LIMITS: dict[str, tuple[int, int]] = {
    KEY_MAX_HISTORY_SIGHTINGS: (1, 100),
    KEY_REPEATED_LISTING_MIN_TIMES_SEEN: (1, 100),
    KEY_REPEATED_LISTING_MIN_SPAN_DAYS: (1, 365),
    KEY_MULTI_LISTING_RED_FLAG_MIN_LISTINGS: (1, 100),
    KEY_MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS: (1, 365),
}
DEFAULT_DESCRIPTION_TRUST_SETTINGS = dict(_MANAGED_GLOBAL_SETTINGS_SEED.get(KEY_DESCRIPTION_TRUST_SETTINGS, {}))
DEFAULT_SOURCE_DOCUMENT_SETTINGS = {
    KEY_SOURCE_DOCUMENT_SUFFIXES: [
        str(value).strip().lower()
        for value in _MANAGED_GLOBAL_SETTINGS_SEED[KEY_SOURCE_DOCUMENT_SETTINGS][KEY_SOURCE_DOCUMENT_SUFFIXES]
        if str(value).strip()
    ],
}
DEFAULT_ONBOARDING_SETTINGS = {
    k: copy.deepcopy(v)
    for k, v in _MANAGED_GLOBAL_SETTINGS_SEED[KEY_ONBOARDING_SETTINGS].items()
    if k != KEY_CAPABILITY_STRENGTH_PRESETS
}
DEFAULT_LLM_SETTINGS = copy.deepcopy(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_LLM_SETTINGS])
DEFAULT_REVIEW_SETTINGS = copy.deepcopy(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_REVIEW_SETTINGS])
DEFAULT_LLM_PROMPT_SETTINGS = dict(DEFAULT_LLM_SETTINGS[KEY_LLM_PROMPT_SETTINGS])
DEFAULT_PLAYWRIGHT_SETTINGS = dict(_MANAGED_GLOBAL_SETTINGS_SEED.get("playwright_settings", {}))
DEFAULT_PLAYWRIGHT_BROWSER_MODE = str(
    DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_PLAYWRIGHT_BROWSER_MODE, "ephemeral")
).strip().lower()
DEFAULT_COUNTRY_SUFFIX = str(_MANAGED_GLOBAL_SETTINGS_SEED[KEY_DEFAULT_COUNTRY_SUFFIX]).strip()
if not DEFAULT_COUNTRY_SUFFIX:
    raise ValueError("global_settings.default_country_suffix must not be empty")


def _to_min_max_dict(limits: dict[str, tuple[int, int]]) -> dict[str, dict[str, int]]:
    return {k: {"min": v[0], "max": v[1]} for k, v in limits.items()}


# Validation bounds for every onboarding setting. Centralised here so profile_store
# and normalize_global_settings both use the same limits without duplication.
ONBOARDING_SETTING_LIMITS: dict[str, tuple[int, int]] = {
    "extraction_lookback_years": (1, 20),
    "title_extraction_min_months": (1, 24),
    "max_target_patterns": (1, 20),
    "max_secondary_patterns": (1, 20),
    "capability_recent_years": (1, 15),
    "capability_strong_max_years_since_use": (1, 20),
    "capability_strong_min_months": (1, 240),
    "capability_working_max_years_since_use": (1, 25),
    "capability_working_min_months": (1, 240),
    "capability_working_long_history_max_years_since_use": (1, 30),
    "capability_working_long_history_min_months": (1, 360),
    "capability_drop_to_basic_after_years": (1, 40),
    "capability_max_items": (1, 50),
    "capability_alias_limit": (1, 20),
    "cv_max_pages": (1, 100),
    "signal_cluster_min_alias_hits": (1, 10),
    "signal_cluster_min_snippet_hits": (1, 10),
    "signal_cluster_dense_snippet_alias_hits": (1, 20),
}

CAPABILITY_STRENGTH_PRESETS = copy.deepcopy(
    _MANAGED_GLOBAL_SETTINGS_SEED[KEY_ONBOARDING_SETTINGS][KEY_CAPABILITY_STRENGTH_PRESETS]
)

DEFAULT_GLOBAL_SETTINGS: dict[str, Any] = {
    KEY_FIT_HIGHLIGHTS: copy.deepcopy(DEFAULT_FIT_HIGHLIGHTS),
    KEY_SEARCH_SETTINGS: copy.deepcopy(DEFAULT_SEARCH_SETTINGS),
    KEY_LIMITS: {
        "search": copy.deepcopy(SEARCH_SETTING_LIMITS),
        "salary": copy.deepcopy(DEFAULT_SALARY_LIMITS),
        "onboarding": _to_min_max_dict(ONBOARDING_SETTING_LIMITS),
        "history": _to_min_max_dict(HISTORY_SETTING_LIMITS),
    },
    KEY_PREFERENCE_WEIGHTS: copy.deepcopy(DEFAULT_PREFERENCE_WEIGHTS),
    KEY_EVIDENCE_TIER_WEIGHTS: copy.deepcopy(DEFAULT_EVIDENCE_TIER_WEIGHTS),
    KEY_HISTORY_SETTINGS: copy.deepcopy(DEFAULT_HISTORY_SETTINGS),
    KEY_DESCRIPTION_TRUST_SETTINGS: copy.deepcopy(DEFAULT_DESCRIPTION_TRUST_SETTINGS),
    KEY_SOURCE_DOCUMENT_SETTINGS: copy.deepcopy(DEFAULT_SOURCE_DOCUMENT_SETTINGS),
    KEY_DEFAULT_COUNTRY_SUFFIX: DEFAULT_COUNTRY_SUFFIX,
    KEY_ONBOARDING_SETTINGS: {
        **copy.deepcopy(DEFAULT_ONBOARDING_SETTINGS),
        KEY_CAPABILITY_STRENGTH_PRESETS: copy.deepcopy(CAPABILITY_STRENGTH_PRESETS),
    },
    KEY_LLM_SETTINGS: copy.deepcopy(DEFAULT_LLM_SETTINGS),
    KEY_REVIEW_SETTINGS: copy.deepcopy(DEFAULT_REVIEW_SETTINGS),
    "playwright_settings": {
        KEY_PLAYWRIGHT_VIEWPORT_WIDTH: DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_PLAYWRIGHT_VIEWPORT_WIDTH, 1400),
        KEY_PLAYWRIGHT_VIEWPORT_HEIGHT: DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_PLAYWRIGHT_VIEWPORT_HEIGHT, 900),
        KEY_PLAYWRIGHT_SELECTOR_TIMEOUT: DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_PLAYWRIGHT_SELECTOR_TIMEOUT, 8000),
        KEY_PLAYWRIGHT_BROWSER_MODE: DEFAULT_PLAYWRIGHT_BROWSER_MODE,
    },
}
