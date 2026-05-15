"""Profile persistence and defaults.

Main goals:
- define the runtime profile structure used by matching and review flows
- create a safe default profile for first run
- load, merge, patch, and save profile.json consistently

Notes:
- profile.json is the runtime source of truth
- onboarding and imports may generate it, and admin refines it over time
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from datetime import datetime, timezone
from typing import Any

from job_hunter_agent.match_labels import MATCH_LEVELS, normalize_match_levels
from job_hunter_agent.global_settings import (
    CAPABILITY_STRENGTH_PRESETS,
    DEFAULT_EVIDENCE_TIER_WEIGHTS,
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PREFERENCE_WEIGHTS,
    DEFAULT_SEARCH_SETTINGS,
    KEY_CAPABILITY_ALIAS_LIMIT,
    KEY_CAPABILITY_STRENGTH_PRESETS,
    KEY_DATE_RANGE_DAYS,
    KEY_ENFORCE_POSTED_AGE_LIMIT,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_ONBOARDING_SETTINGS as GLOBAL_KEY_ONBOARDING_SETTINGS,
    KEY_LIMITS,
    KEY_SEARCH_LIMITS,
    KEY_SEEK_MAX_PAGES,
    KEY_SORT_NEWEST_FIRST,
    ONBOARDING_SETTING_LIMITS,
    get_salary_limits,
    load_global_settings,
)
from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.parsing_schema import (
    PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_DEFAULT_KEY,
    PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_KEY,
    PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_PRIMARY_KEY,
    PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_SECONDARY_KEY,
    PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_SUPPLEMENTARY_KEY,
)
from job_hunter_agent.paths import (
    DATA_DIR,
    REPO_ROOT,
    SCORING_RULES_PATH,
    get_profile_path,
)


ROOT_DIR = REPO_ROOT 
# Shared Profile and Settings Keys
KEY_KEYWORDS = "keywords"
KEY_LOCATIONS = "locations"
KEY_ENGAGEMENT_TYPE = "engagement_type"
KEY_WORK_MODE_PREFERENCE = "work_mode_preference"
KEY_PREFER_GOVERNMENT = "prefer_government"
KEY_MIN_SALARY_YEARLY = "minimum_salary_yearly"
KEY_MIN_DAILY_RATE = "minimum_daily_rate"

ENGAGEMENT_TYPE_BOTH = "both"
ENGAGEMENT_TYPE_PERMANENT = "permanent"
ENGAGEMENT_TYPE_CONTRACT = "contract"
ENGAGEMENT_TYPE_OPTIONS = (
    {"value": ENGAGEMENT_TYPE_BOTH, "label": "Both permanent and contract"},
    {"value": ENGAGEMENT_TYPE_PERMANENT, "label": "Permanent only"},
    {"value": ENGAGEMENT_TYPE_CONTRACT, "label": "Contract only"},
)

WORK_MODE_PREFERENCE_NONE = ""
WORK_MODE_PREFERENCE_REMOTE = "remote"
WORK_MODE_PREFERENCE_HYBRID = "hybrid"
WORK_MODE_PREFERENCE_ONSITE = "onsite"
WORK_MODE_PREFERENCE_OPTIONS = (
    {"value": WORK_MODE_PREFERENCE_REMOTE, "label": "Remote"},
    {"value": WORK_MODE_PREFERENCE_HYBRID, "label": "Hybrid"},
    {"value": WORK_MODE_PREFERENCE_ONSITE, "label": "On-site"},
)
_VALID_WORK_MODE_PREFERENCES = frozenset({item["value"] for item in WORK_MODE_PREFERENCE_OPTIONS})
WORK_MODE_PREFERENCE_NONE_LABEL = "No preference"
WORK_MODE_PREFERENCE_HELP_TEXT = "Optional. Choose the work arrangements you want to include in search. Leave all unselected to keep every mode."

GOVERNMENT_PREFERENCE_ANY = "any"
GOVERNMENT_PREFERENCE_GOVERNMENT = "government"
GOVERNMENT_PREFERENCE_PRIVATE = "private"
GOVERNMENT_PREFERENCE_OPTIONS = (
    {"value": GOVERNMENT_PREFERENCE_ANY, "label": "No preference"},
    {"value": GOVERNMENT_PREFERENCE_GOVERNMENT, "label": "Government only"},
    {"value": GOVERNMENT_PREFERENCE_PRIVATE, "label": "Private only"},
)
_VALID_GOVERNMENT_PREFERENCES = frozenset({item["value"] for item in GOVERNMENT_PREFERENCE_OPTIONS})
GOVERNMENT_PREFERENCE_HELP_TEXT = "Optional. Choose government only, private only, or no preference."

SALARY_MIN_ANNUAL_LABEL = "Minimum annual base"
SALARY_MIN_DAILY_LABEL = "Minimum daily rate"
SALARY_ANNUAL_HELP_TEXT = "Optional. Excludes super."
SALARY_DAILY_HELP_TEXT = "Optional. Excludes super."
SETTINGS_SALARY_ANNUAL_HELP_TEXT = "Optional. Used when permanent roles list salary. Excludes super."
SETTINGS_SALARY_DAILY_HELP_TEXT = "Optional. Used when contract roles list a day rate. Excludes super."

KEY_LOOKBACK_YEARS = "extraction_lookback_years"
KEY_MIN_MONTHS = "title_extraction_min_months"
KEY_MAX_TARGET = "max_target_patterns"
KEY_MAX_SECONDARY = "max_secondary_patterns"
KEY_CAP_STRENGTH_PRESET = "capability_strength_preset"

KEY_BRIEF_MODE = "llm_profile_brief_mode"
KEY_BRIEF = "llm_profile_brief"
KEY_FIT_GUIDANCE = "llm_fit_review_guidance"
KEY_CAP_GUIDANCE = "llm_capability_naming_guidance"
KEY_STAR_EVIDENCE = "star_candidate_profile_text"
KEY_CV_TEXT = "cv_text"
KEY_CANDIDATE_PROFILE_TIERS = "candidate_profile_tiers"
KEY_EVIDENCE_TIERS = KEY_CANDIDATE_PROFILE_TIERS
KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT = "primary_candidate_profile_context"
KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT = "secondary_candidate_profile_context"
KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT = "supplementary_candidate_profile_context"
KEY_CAPABILITY_PROFILE_RULES = "capability_profile_rules"
KEY_SIGNAL_CLUSTERS = "dominant_signal_clusters"
KEY_REQUIRED_SKILLS = "must_not_require_skills"
KEY_ONBOARDING_SETTINGS = "onboarding_settings"
KEY_MATCH_PREFS = "match_preferences"
KEY_PRIMARY_PATTERNS = "primary_job_title_pattern"
KEY_SECONDARY_PATTERNS = "secondary_title_patterns"
KEY_LLM_GRADE_POINTS = "llm_grade_points"
KEY_CAPABILITY_LEVEL_WEIGHTS = "capability_level_weights"
KEY_CAPABILITY_EVIDENCE = "capability_candidate_profile"
KEY_MAX_SCORE = "max_score"
MATCHING_RULE_PROFILE_KEYS = frozenset({
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_PRIMARY_PATTERNS,
    KEY_SECONDARY_PATTERNS,
    KEY_REQUIRED_SKILLS,
    "reject_title_rules",
    "reject_description_phrase_rules",
})

KEY_NAME = "name"
KEY_LEVEL = "level"
KEY_ALIASES = "aliases"
KEY_NEEDS_REVIEW = "needs_review"
KEY_CONVERGENCE = "convergence"
KEY_CONVERGENCE_ELIGIBLE_GRADES = "eligible_grades"
KEY_CONVERGENCE_MIN_POSITIVE_MATCHES = "min_positive_matches"
KEY_CONVERGENCE_REQUIRED_TITLE_REASON = "required_title_reason"
KEY_CONVERGENCE_REQUIRED_CONTENT_REASON = "required_content_reason"
KEY_CONVERGENCE_REQUIRED_FIT_CONFIDENCE = "required_fit_confidence"
KEY_CONVERGENCE_BONUS_NO_SOFT_RISKS = "bonus_no_soft_risks"
KEY_CONVERGENCE_BONUS_WITH_SOFT_RISKS = "bonus_with_soft_risks"
KEY_CONVERGENCE_LABEL = "label"
KEY_COMPETITIVE_SIGNAL_ALIGNMENT = "competitive_signal_alignment"

LEVEL_STRONG = "strong"
LEVEL_WORKING = "working"
LEVEL_BASIC = "basic"
LEVEL_LOW = "low"
VALID_CAPABILITY_RULE_LEVELS = frozenset({LEVEL_STRONG, LEVEL_WORKING, LEVEL_BASIC, LEVEL_LOW})
VALID_CAPABILITY_MATCH_LEVELS = frozenset({LEVEL_STRONG, LEVEL_WORKING, LEVEL_BASIC})

DEFAULT_CANDIDATE_PROFILE_TIERS  = {
    KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT: "",
    KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT: "",
    KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT: "",
}

DEFAULT_MATCH_LEVELS = normalize_match_levels(list(MATCH_LEVELS))
LLM_PROFILE_BRIEF_MODE_AUTO = "auto"
LLM_PROFILE_BRIEF_MODE_MANUAL = "manual"
DEFAULT_LLM_PROFILE_BRIEF_MODE = LLM_PROFILE_BRIEF_MODE_AUTO


class ProfileLoadError(RuntimeError):
    pass


def _load_default_scoring_rules() -> dict[str, Any]:
    payload = json.loads(SCORING_RULES_PATH.read_text(encoding="utf-8"))
    if str(payload.get("kind") or "").strip() != "system_config" or str(payload.get("name") or "").strip() != "scoring_rules":
        raise ValueError("scoring_rules.json must be managed knowledge")
    return {
        "fit_breakdown": dict(payload.get("fit_breakdown") or {}),
        KEY_LLM_GRADE_POINTS: dict(payload.get(KEY_LLM_GRADE_POINTS) or {}),
        KEY_CAPABILITY_LEVEL_WEIGHTS: dict(payload.get(KEY_CAPABILITY_LEVEL_WEIGHTS) or {}),
        KEY_CAPABILITY_EVIDENCE: dict(payload.get("capability_evidence") or {}),
        KEY_CONVERGENCE: dict(payload.get(KEY_CONVERGENCE) or {}),
        KEY_COMPETITIVE_SIGNAL_ALIGNMENT: dict(payload.get(KEY_COMPETITIVE_SIGNAL_ALIGNMENT) or {}),
        "deterministic_review_thresholds": dict(payload.get("deterministic_review_thresholds") or {}),
        "freshness": dict(payload.get("freshness") or {}),
        "work_mode": dict(payload.get("work_mode") or {}),
        "salary": dict(payload.get("salary") or {}),
        "location": dict(payload.get("location") or {}),
        "contract": dict(payload.get("contract") or {}),
        "government": dict(payload.get("government") or {}),
    }


DEFAULT_SCORING_RULES = _load_default_scoring_rules()

DEFAULT_PROFILE = {
    "enabled_sources": ["seek"], # Default to 'seek' if not explicitly configured
    "search_settings": {
        **DEFAULT_SEARCH_SETTINGS,
    },
    "review_controls": {
        "applied_job_keys": [],
        "hidden_job_keys": [],
    },    
    "salary_preferences": {
        "minimum_salary_yearly": 0,
        "minimum_daily_rate": 0,
    },
    "preference_weights": {
        **DEFAULT_PREFERENCE_WEIGHTS,
    },
    "scoring_rules": copy.deepcopy(DEFAULT_SCORING_RULES),
    "match_levels": [dict(level) for level in DEFAULT_MATCH_LEVELS],
    "match_preferences": {
        "home_location": "",
        "secondary_location": "",
        KEY_WORK_MODE_PREFERENCE: [],
        KEY_PREFER_GOVERNMENT: False,
        "prefer_permanent": False,
        "engagement_type": ENGAGEMENT_TYPE_BOTH,
        "preferred_contract_months": 12,
        "short_contract_months": 6,
    },
    "llm_profile_brief_mode": DEFAULT_LLM_PROFILE_BRIEF_MODE,
    "llm_profile_brief": "",
    "llm_fit_review_guidance": "",
    "llm_capability_naming_guidance": "",
    "star_candidate_profile_text": "",
    "cv_text": "",
    KEY_CANDIDATE_PROFILE_TIERS : {
        **DEFAULT_CANDIDATE_PROFILE_TIERS ,
    },
    "candidate_profile_tier_weights": {
        **DEFAULT_EVIDENCE_TIER_WEIGHTS,
    },
    KEY_CAPABILITY_PROFILE_RULES: [],
    "dominant_signal_clusters": [],
    "primary_job_title_pattern": [],
    "secondary_title_patterns": [],
    "must_not_require_skills": [],  
    "onboarding_settings": {
        **DEFAULT_ONBOARDING_SETTINGS,
    },
}


def _decode_escaped_newlines(value: Any) -> str:
    text = str(value or "")
    return (
        text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
    )


def normalize_multiline_string_list(values: Any) -> list[str]:
    source = values if isinstance(values, list) else [values]
    cleaned: list[str] = []
    seen: set[str] = set()

    for item in source or []:
        for part in _decode_escaped_newlines(item).split("\n"):
            value = part.strip()
            if not value:
                continue
            normalized = re.sub(r"\s+", " ", value).strip().lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(value)

    return cleaned


def normalize_title_pattern_lists(
    primary_values: Any,
    secondary_values: Any,
) -> tuple[list[str], list[str]]:
    primary = normalize_multiline_string_list(primary_values)
    secondary = normalize_multiline_string_list(secondary_values)
    primary_seen = {re.sub(r"\s+", " ", value).strip().lower() for value in primary if value}

    cleaned_secondary: list[str] = []
    seen_secondary: set[str] = set()
    for value in secondary:
        normalized = re.sub(r"\s+", " ", value).strip().lower()
        if not normalized or normalized in primary_seen or normalized in seen_secondary:
            continue
        seen_secondary.add(normalized)
        cleaned_secondary.append(value)

    return primary, cleaned_secondary


def ensure_profile_exists() -> None:
    profile_path = get_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    if profile_path.exists():
        return
    save_profile(DEFAULT_PROFILE)


def _backup_invalid_profile() -> None:
    profile_path = get_profile_path()
    if not profile_path.exists():
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = profile_path.with_name(f"profile.invalid.{timestamp}.json")
    shutil.copy2(profile_path, backup_path)


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        resolved = int(value)
    except Exception:
        resolved = default
    return max(minimum, min(maximum, resolved))


def normalize_onboarding_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}

    # Global policy baseline: user-configured values from global_settings.json.
    # Falls back to code defaults if global settings are not yet initialised.
    try:
        global_onboarding = load_global_settings()[GLOBAL_KEY_ONBOARDING_SETTINGS]
    except Exception:
        global_onboarding = {}
    global_presets = global_onboarding.get(KEY_CAPABILITY_STRENGTH_PRESETS) or CAPABILITY_STRENGTH_PRESETS

    # Preset resolution: source > global > code default.
    raw_preset = str(
        source.get("capability_strength_preset")
        or global_onboarding.get("capability_strength_preset")
        or DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
    ).strip().lower()
    preset_name = raw_preset if raw_preset in global_presets else DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
    preset_values = global_presets[preset_name]

    # Merge layer: code defaults -> global settings -> chosen preset -> all explicit source overrides.
    merged: dict[str, Any] = {**DEFAULT_ONBOARDING_SETTINGS}
    merged.update({k: v for k, v in global_onboarding.items() if k != KEY_CAPABILITY_STRENGTH_PRESETS})
    merged.update(preset_values)
    merged.update({
        k: v for k, v in source.items()
        if k not in (KEY_CAPABILITY_STRENGTH_PRESETS, "capability_strength_preset") and v is not None
    })

    result: dict[str, Any] = {"capability_strength_preset": preset_name}
    onboarding_limits = load_global_settings()[KEY_LIMITS]["onboarding"]
    for key, bounds in onboarding_limits.items():
        result[key] = _coerce_int(merged.get(key), DEFAULT_ONBOARDING_SETTINGS[key], bounds["min"], bounds["max"])
    return result


def normalize_match_preferences(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    merged = dict(DEFAULT_PROFILE["match_preferences"])
    merged.update({k: v for k, v in source.items() if v is not None})

    raw_government = merged.get(KEY_PREFER_GOVERNMENT)
    if isinstance(raw_government, bool):
        merged[KEY_PREFER_GOVERNMENT] = GOVERNMENT_PREFERENCE_GOVERNMENT if raw_government else GOVERNMENT_PREFERENCE_ANY
    else:
        normalized_government = str(raw_government or "").strip().lower()
        if normalized_government not in _VALID_GOVERNMENT_PREFERENCES:
            normalized_government = GOVERNMENT_PREFERENCE_ANY
        merged[KEY_PREFER_GOVERNMENT] = normalized_government

    merged[KEY_WORK_MODE_PREFERENCE] = normalize_work_mode_preferences(merged.get(KEY_WORK_MODE_PREFERENCE))

    merged["prefer_permanent"] = bool(merged.get("prefer_permanent", False))
    merged["engagement_type"] = str(merged.get("engagement_type") or ENGAGEMENT_TYPE_BOTH).strip().lower()
    merged["preferred_contract_months"] = int(merged.get("preferred_contract_months") or 12)
    merged["short_contract_months"] = int(merged.get("short_contract_months") or 6)
    return merged


def normalize_work_mode_preferences(values: Any) -> list[str]:
    if isinstance(values, str):
        source_values = [part.strip().lower() for part in re.split(r"[,\n|/]+", values) if part.strip()]
    elif isinstance(values, (list, tuple, set)):
        source_values = [str(value).strip().lower() for value in values if str(value).strip()]
    else:
        source_values = []
    selected: list[str] = []
    seen: set[str] = set()
    for item in WORK_MODE_PREFERENCE_OPTIONS:
        value = str(item["value"]).strip().lower()
        if value in source_values and value not in seen:
            seen.add(value)
            selected.append(value)
    return selected


def normalize_capability_rules(
    rules: list[dict[str, Any]] | None,
    onboarding_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalise learned capability rules and keep alias growth under onboarding limits."""
    cleaned: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    derive_job_description_aliases = None

    choose_capability_name = None
    try:
        from job_hunter_agent.capability_matrix import derive_job_description_aliases as _derive_job_description_aliases
        from job_hunter_agent.capability_matrix import choose_capability_name as _choose_capability_name

        derive_job_description_aliases = _derive_job_description_aliases
        choose_capability_name = _choose_capability_name
    except Exception:
        pass

    source_onboarding = onboarding_settings if isinstance(onboarding_settings, dict) else {}
    try:
        alias_limit = int(source_onboarding.get(KEY_CAPABILITY_ALIAS_LIMIT) or DEFAULT_ONBOARDING_SETTINGS[KEY_CAPABILITY_ALIAS_LIMIT])
    except Exception:
        alias_limit = int(DEFAULT_ONBOARDING_SETTINGS[KEY_CAPABILITY_ALIAS_LIMIT])

    for rule in rules or []:
        if not isinstance(rule, dict):
            continue

        name = str(rule.get("name") or "").strip()
        if not name:
            continue

        level = str(rule.get("level") or "").strip().lower()
        if level == "none":
            continue
        if level not in VALID_CAPABILITY_RULE_LEVELS:
            level = LEVEL_BASIC

        raw_aliases = rule.get("aliases")
        if isinstance(raw_aliases, str):
            alias_items = [
                part.strip()
                for part in re.split(r"[\n,]", _decode_escaped_newlines(raw_aliases))
                if part.strip()
            ]
        else:
            alias_items = list(raw_aliases or [])

        if derive_job_description_aliases:
            alias_items = derive_job_description_aliases(name, [str(rule.get("name") or "").strip(), *alias_items], max_aliases=alias_limit)

        name_norm = re.sub(r"\s+", " ", name).strip().lower()
        if not name_norm or name_norm in seen_names:
            continue
        seen_names.add(name_norm)

        aliases: list[str] = []
        seen_aliases: set[str] = set()
        for alias in alias_items:
            cleaned_alias = str(alias or "").strip()
            if not cleaned_alias:
                continue
            alias_norm = re.sub(r"\s+", " ", cleaned_alias).strip().lower()
            if alias_norm == name_norm:
                continue
            if alias_norm in seen_aliases:
                continue
            seen_aliases.add(alias_norm)
            aliases.append(cleaned_alias)

        needs_review = bool(rule.get("needs_review"))
        if aliases:
            needs_review = True

        canonical_name = choose_capability_name(name, alias_items) if choose_capability_name else name_norm
        if not canonical_name:
            continue

        cleaned.append({
            "name": canonical_name,
            "level": level,
            "aliases": aliases,
            "needs_review": needs_review,
        })

    return cleaned


def normalize_full_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise TypeError("profile must be a dict")
    merged = _deep_merge(copy.deepcopy(DEFAULT_PROFILE), profile)
    merged["search_settings"] = normalize_search_settings(merged.get("search_settings", {}))
    merged["salary_preferences"] = normalize_salary_preferences(merged.get("salary_preferences", {}))
    merged["preference_weights"] = normalize_preference_weights(merged.get("preference_weights", {}))
    merged["scoring_rules"] = normalize_scoring_rules(merged.get("scoring_rules", {}))
    merged["match_levels"] = normalize_match_levels(merged.get("match_levels", []))
    merged["llm_profile_brief_mode"] = normalize_llm_profile_brief_mode(
        merged.get("llm_profile_brief_mode", DEFAULT_LLM_PROFILE_BRIEF_MODE)
    )
    merged["llm_fit_review_guidance"] = normalize_llm_fit_review_guidance(
        merged.get("llm_fit_review_guidance", "")
    )
    merged["llm_capability_naming_guidance"] = normalize_llm_capability_naming_guidance(
        merged.get("llm_capability_naming_guidance", "")
    )
    merged[KEY_CANDIDATE_PROFILE_TIERS ] = normalize_candidate_profile_tiers(
        merged.get(KEY_CANDIDATE_PROFILE_TIERS , {}),
        merged.get("cv_text", ""),
    )
    merged["candidate_profile_tier_weights"] = normalize_candidate_profile_tier_weights(
        merged.get("candidate_profile_tier_weights", {})
    )
    merged["onboarding_settings"] = normalize_onboarding_settings(
        merged.get("onboarding_settings", {})
    )
    merged["match_preferences"] = normalize_match_preferences(
        merged.get("match_preferences", {})
    )
    merged[KEY_CAPABILITY_PROFILE_RULES] = normalize_capability_rules(
        merged.get(KEY_CAPABILITY_PROFILE_RULES, []),
        merged.get("onboarding_settings", {}),
    )
    primary_titles, secondary_titles = normalize_title_pattern_lists(
        merged.get("primary_job_title_pattern", []),
        merged.get("secondary_title_patterns", []),
    )
    merged["primary_job_title_pattern"] = primary_titles
    merged["secondary_title_patterns"] = secondary_titles
    merged["must_not_require_skills"] = normalize_multiline_string_list(
        merged.get("must_not_require_skills", [])
    )
    return merged


def load_profile() -> dict[str, Any]:
    ensure_profile_exists()
    profile_path = get_profile_path()
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _backup_invalid_profile()
        raise ProfileLoadError(f"Failed to parse profile.json: {exc}") from exc
    if not isinstance(data, dict):
        _backup_invalid_profile()
        raise ProfileLoadError("profile.json must contain a JSON object")
    return normalize_full_profile(data)


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_full_profile(profile)
    persisted = dict(normalized)
    persisted.pop("scoring_rules", None)
    profile_path = get_profile_path()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(
        json.dumps(persisted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(patch)


def patch_profile(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_profile()
    merged = _deep_merge(current, patch)
    return save_profile(merged)


def normalize_search_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    merged = _deep_merge(copy.deepcopy(DEFAULT_SEARCH_SETTINGS), settings or {})
    search_limits = load_global_settings()[KEY_LIMITS]["search"]

    try:
        merged[KEY_DATE_RANGE_DAYS] = max(
            search_limits[KEY_DATE_RANGE_DAYS]["min"],
            min(
                int(merged.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])),
                search_limits[KEY_DATE_RANGE_DAYS]["max"],
            ),
        )
    except Exception:
        merged[KEY_DATE_RANGE_DAYS] = DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]

    try:
        merged[KEY_SEEK_MAX_PAGES] = max(
            search_limits[KEY_SEEK_MAX_PAGES]["min"],
            min(
                int(merged.get(KEY_SEEK_MAX_PAGES, search_limits[KEY_SEEK_MAX_PAGES]["max"])),
                search_limits[KEY_SEEK_MAX_PAGES]["max"],
            ),
        )
    except Exception:
        merged[KEY_SEEK_MAX_PAGES] = DEFAULT_SEARCH_SETTINGS[KEY_SEEK_MAX_PAGES]

    try:
        merged[KEY_LINKEDIN_HOURS_OLD] = max(
            search_limits[KEY_LINKEDIN_HOURS_OLD]["min"],
            min(
                int(merged.get(KEY_LINKEDIN_HOURS_OLD, DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD])),
                search_limits[KEY_LINKEDIN_HOURS_OLD]["max"],
            ),
        )
    except Exception:
        merged[KEY_LINKEDIN_HOURS_OLD] = DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]

    try:
        merged[KEY_LINKEDIN_RESULTS_PER_SEARCH] = max(
            search_limits[KEY_LINKEDIN_RESULTS_PER_SEARCH]["min"],
            min(
                int(
                    merged.get(
                        KEY_LINKEDIN_RESULTS_PER_SEARCH,
                        DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH],
                    )
                ),
                search_limits[KEY_LINKEDIN_RESULTS_PER_SEARCH]["max"],
            ),
        )
    except Exception:
        merged[KEY_LINKEDIN_RESULTS_PER_SEARCH] = DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH]

    merged[KEY_ENFORCE_POSTED_AGE_LIMIT] = bool(merged.get(KEY_ENFORCE_POSTED_AGE_LIMIT, True))
    merged[KEY_SORT_NEWEST_FIRST] = bool(merged.get(KEY_SORT_NEWEST_FIRST, True))
    merged["keywords"] = str(merged.get("keywords") or "").strip()
    merged["locations"] = [str(value).strip() for value in merged.get("locations", []) if str(value).strip()]
    merged["classification_ids"] = [
        str(value).strip() for value in merged.get("classification_ids", []) if str(value).strip()
    ]
    easy_apply_only = merged.get(KEY_LINKEDIN_EASY_APPLY_ONLY)
    if easy_apply_only is None or easy_apply_only == "":
        merged[KEY_LINKEDIN_EASY_APPLY_ONLY] = None
    elif isinstance(easy_apply_only, str):
        normalized_easy_apply_only = easy_apply_only.strip().lower()
        if normalized_easy_apply_only == "true":
            merged[KEY_LINKEDIN_EASY_APPLY_ONLY] = True
        elif normalized_easy_apply_only == "false":
            merged[KEY_LINKEDIN_EASY_APPLY_ONLY] = False
        else:
            merged[KEY_LINKEDIN_EASY_APPLY_ONLY] = None
    else:
        merged[KEY_LINKEDIN_EASY_APPLY_ONLY] = bool(easy_apply_only)
    return merged


def normalize_salary_preferences(payload: dict[str, Any] | None) -> dict[str, int]:
    source = payload if isinstance(payload, dict) else {}
    salary_limits = get_salary_limits()
    yearly_cap = int(salary_limits.get(KEY_MIN_SALARY_YEARLY, {}).get("max", 0) or 0)
    daily_cap = int(salary_limits.get(KEY_MIN_DAILY_RATE, {}).get("max", 0) or 0)
    try:
        minimum_salary_yearly = max(0, int(str(source.get("minimum_salary_yearly", 0)).replace(",", "").strip() or 0))
    except Exception:
        minimum_salary_yearly = 0
    minimum_salary_yearly = min(minimum_salary_yearly, yearly_cap) if yearly_cap > 0 else minimum_salary_yearly
    try:
        minimum_daily_rate = max(0, int(str(source.get("minimum_daily_rate", 0)).replace(",", "").strip() or 0))
    except Exception:
        minimum_daily_rate = 0
    minimum_daily_rate = min(minimum_daily_rate, daily_cap) if daily_cap > 0 else minimum_daily_rate
    return {
        "minimum_salary_yearly": minimum_salary_yearly,
        "minimum_daily_rate": minimum_daily_rate,
    }


def normalize_preference_weights(payload: dict[str, Any] | None) -> dict[str, float]:
    source = payload if isinstance(payload, dict) else {}
    normalized = dict(DEFAULT_PREFERENCE_WEIGHTS)
    for key, default in DEFAULT_PREFERENCE_WEIGHTS.items():
        try:
            value = float(source.get(key, default) or default)
        except Exception:
            value = default
        normalized[key] = max(min(value, 2.0), 0.0)
    return normalized


def normalize_scoring_rules(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    normalized = copy.deepcopy(DEFAULT_SCORING_RULES)

    def _merge(default_value: Any, incoming_value: Any) -> Any:
        if isinstance(default_value, dict):
            incoming = incoming_value if isinstance(incoming_value, dict) else {}
            result: dict[str, Any] = {}
            for key, child_default in default_value.items():
                result[key] = _merge(child_default, incoming.get(key))
            return result
        if isinstance(default_value, list):
            if not isinstance(incoming_value, list):
                return list(default_value)
            return [str(item).strip().upper() for item in incoming_value if str(item).strip()]
        if isinstance(default_value, int) and not isinstance(default_value, bool):
            try:
                return int(incoming_value)
            except Exception:
                return int(default_value)
        if isinstance(default_value, float):
            try:
                return float(incoming_value)
            except Exception:
                return float(default_value)
        return copy.deepcopy(default_value if incoming_value in (None, "") else incoming_value)

    for key, default_value in DEFAULT_SCORING_RULES.items():
        normalized[key] = _merge(default_value, source.get(key))
    return normalized


def normalize_profile_match_levels(payload: list[dict[str, Any]] | None) -> list[dict[str, object]]:
    normalized = normalize_match_levels(payload)
    return normalized or [dict(level) for level in DEFAULT_MATCH_LEVELS]


def normalize_llm_profile_brief_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == LLM_PROFILE_BRIEF_MODE_MANUAL:
        return LLM_PROFILE_BRIEF_MODE_MANUAL
    return DEFAULT_LLM_PROFILE_BRIEF_MODE


def normalize_llm_fit_review_guidance(value: Any) -> str:
    return str(value or "").strip()


def normalize_llm_capability_naming_guidance(value: Any) -> str:
    return str(value or "").strip()


def classify_candidate_profile_section_label(label: str) -> str:
    lowered = str(label or "").strip().lower()
    routing = load_parsing_rules().get(PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_KEY)
    if not isinstance(routing, dict):
        raise ValueError("parsing_rules.json must define candidate_profile_section_routing")
    default_bucket = str(routing.get(PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_DEFAULT_KEY) or "").strip()
    primary_labels = routing.get(PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_PRIMARY_KEY)
    secondary_labels = routing.get(PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_SECONDARY_KEY)
    supplementary_labels = routing.get(PARSING_CANDIDATE_PROFILE_SECTION_ROUTING_SUPPLEMENTARY_KEY)
    if not all(isinstance(items, list) for items in (primary_labels, secondary_labels, supplementary_labels)):
        raise ValueError("candidate_profile_section_routing labels must be lists")
    if default_bucket not in DEFAULT_CANDIDATE_PROFILE_TIERS:
        raise ValueError("candidate_profile_section_routing.default_bucket must be a known profile bucket")
    primary_tokens = [str(token).strip().lower() for token in primary_labels if str(token).strip()]
    secondary_tokens = [str(token).strip().lower() for token in secondary_labels if str(token).strip()]
    supplementary_tokens = [str(token).strip().lower() for token in supplementary_labels if str(token).strip()]
    if not lowered:
        return default_bucket
    if any(token in lowered for token in primary_tokens):
        return KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT
    if any(token in lowered for token in secondary_tokens):
        return KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT
    if any(token in lowered for token in supplementary_tokens):
        return KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT
    return default_bucket


def _combine_unique_sections(parts: list[str]) -> str:
    seen: set[str] = set()
    cleaned_parts: list[str] = []
    for item in parts:
        text = str(item or "").strip()
        if not text:
            continue
        normalized = re.sub(r"\s+", " ", text).strip().lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        cleaned_parts.append(text)
    return "\n\n".join(cleaned_parts).strip()


def build_candidate_profile_tiers_from_sections(sections: list[dict[str, str]] | None) -> dict[str, str]:
    buckets = {key: [] for key in DEFAULT_CANDIDATE_PROFILE_TIERS }
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label") or "").strip()
        text = str(section.get("text") or "").strip()
        if not text:
            continue
        bucket = classify_candidate_profile_section_label(label)
        # Headings only decide the bucket; the text itself is preserved unchanged.
        buckets[bucket].append(text)
    return {
        bucket: _combine_unique_sections(parts)
        for bucket, parts in buckets.items()
    }


def infer_candidate_profile_tiers_from_cv_text(cv_text: str) -> dict[str, str]:
    text = str(cv_text or "").strip()
    if not text:
        return dict(DEFAULT_CANDIDATE_PROFILE_TIERS )

    heading_matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if heading_matches:
        # Headings are the only routing signal here; no score or judgment is applied.
        sections: list[dict[str, str]] = []
        for index, match in enumerate(heading_matches):
            label = match.group(1).strip()
            start = match.end()
            end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(text)
            body = text[start:end].strip()
            if body:
                sections.append({"label": label, "text": body})
        tiers = build_candidate_profile_tiers_from_sections(sections)
        if any(tiers.values()):
            return tiers

    return {
        KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT: text,
        KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT: "",
        KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT: "",
    }


def normalize_candidate_profile_tiers(payload: dict[str, Any] | None, cv_text: str = "") -> dict[str, str]:
    normalized = dict(DEFAULT_CANDIDATE_PROFILE_TIERS )
    source = payload if isinstance(payload, dict) else {}
    inferred = infer_candidate_profile_tiers_from_cv_text(cv_text)
    for key in normalized:
        value = str(source.get(key) or "").strip()
        normalized[key] = value or inferred.get(key, "")
    return normalized


def normalize_candidate_profile_tier_weights(payload: dict[str, Any] | None) -> dict[str, float]:
    source = payload if isinstance(payload, dict) else {}
    normalized = dict(DEFAULT_EVIDENCE_TIER_WEIGHTS)
    for key, default in DEFAULT_EVIDENCE_TIER_WEIGHTS.items():
        try:
            value = float(source.get(key, default) or default)
        except Exception:
            value = default
        normalized[key] = max(min(value, 1.0), 0.0)
    return normalized


def get_candidate_profile_tiers(profile: dict[str, Any]) -> dict[str, str]:
    return normalize_candidate_profile_tiers(
        profile.get(KEY_CANDIDATE_PROFILE_TIERS , {}),
        str(profile.get("cv_text") or ""),
    )


def get_candidate_profile_tier_weights(profile: dict[str, Any]) -> dict[str, float]:
    return normalize_candidate_profile_tier_weights(profile.get("candidate_profile_tier_weights", {}))


def get_search_settings(profile: dict[str, Any]) -> dict[str, Any]:
    return normalize_search_settings(profile.get("search_settings", {}))


def get_preference_weights(profile: dict[str, Any]) -> dict[str, float]:
    return normalize_preference_weights(profile.get("preference_weights", {}))


def get_scoring_rules(profile: dict[str, Any]) -> dict[str, Any]:
    return normalize_scoring_rules(profile.get("scoring_rules", {}))


def get_match_levels(profile: dict[str, Any]) -> list[dict[str, object]]:
    return normalize_profile_match_levels(profile.get("match_levels", []))
