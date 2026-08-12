"""Profile persistence and defaults.

Purpose: load, save, and normalise the SQLite-backed runtime profile used by
matching, review, and scoring flows.
"""

from __future__ import annotations

import copy
import json
import logging
import re
from typing import Any

from job_hunter_agent.capability_matrix import (
    choose_capability_name,
    derive_job_description_aliases,
)
from job_hunter_agent.eligibility_profile import normalize_eligibility_facts
from job_hunter_agent.qualification_profile import normalize_qualifications
from job_hunter_agent.global_settings import (
    CAPABILITY_STRENGTH_PRESETS,
    DEFAULT_EVIDENCE_TIER_WEIGHTS,
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PREFERENCE_WEIGHTS,
    DEFAULT_SEARCH_SETTINGS,
    KEY_APSJOBS_RESULTS_PER_SEARCH,
    KEY_CAPABILITY_ALIAS_LIMIT,
    KEY_CAPABILITY_STRENGTH_PRESETS,
    KEY_DATE_RANGE_DAYS,
    KEY_LIMITS,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_LOCATIONS_MAX_SELECTED,
    KEY_SEEK_MAX_PAGES,
    KEY_SEEK_QUICK_APPLY_ONLY,
    KEY_SORT_NEWEST_FIRST,
    get_salary_limits,
    load_global_settings,
)
from job_hunter_agent.global_settings import (
    KEY_ONBOARDING_SETTINGS as GLOBAL_KEY_ONBOARDING_SETTINGS,
)
from job_hunter_agent.io_utils import load_parsing_rules, load_ui_labels
from job_hunter_agent.match_labels import MATCH_LEVELS, normalize_match_levels
from job_hunter_agent.parsing_schema import (
    KEY_P_ROUTING,
    KEY_P_ROUTING_DEFAULT,
    KEY_P_ROUTING_PRIMARY,
    KEY_P_ROUTING_SECONDARY,
    KEY_P_ROUTING_SUPPLEMENTARY,
)
from job_hunter_agent.runtime_helpers import is_desktop_runtime, log_settings_change
from job_hunter_agent.title_normalization_rules import normalize_title_text
from job_hunter_agent.utils import coerce_int, deep_merge

# Shared Profile and Settings Keys
KEY_KEYWORDS = "keywords"
KEY_LOCATIONS = "locations"
KEY_ENGAGEMENT_TYPE = "engagement_type"
KEY_WORK_MODE_PREFERENCE = "work_mode_preference"
KEY_PREFER_SECTOR = "prefer_sector"
KEY_EXPLORE_ADJACENT_ROLES = "explore_adjacent_roles"
KEY_MIN_SALARY_YEARLY = "minimum_salary_yearly"
KEY_MIN_DAILY_RATE = "minimum_daily_rate"


def _profile_ui_labels() -> dict[str, Any]:
    return load_ui_labels()


def _profile_label(group: str, key: str) -> str:
    group_labels = _profile_ui_labels().get(group)
    if not isinstance(group_labels, dict) or not str(group_labels.get(key, "")).strip():
        raise ValueError(f"Missing required ui_labels.json entry: {group}.{key}")
    return str(group_labels[key])


class Engagement:
    PERMANENT = "permanent"
    CONTRACT = "contract"
    FULL_TIME_CONTRACT = "full_time_contract"


ENGAGEMENT_TYPE_OPTIONS = (
    {"value": Engagement.PERMANENT, "label": _profile_label("profile_field_labels", "engagement_option_permanent")},
    {"value": Engagement.CONTRACT, "label": _profile_label("profile_field_labels", "engagement_option_contract")},
    {
        "value": Engagement.FULL_TIME_CONTRACT,
        "label": _profile_label("profile_field_labels", "engagement_option_full_time_contract"),
    },
)
VALID_ENGAGEMENT_TYPES = frozenset({item["value"] for item in ENGAGEMENT_TYPE_OPTIONS})
ENGAGEMENT_TYPE_DEFAULT_VALUES = [item["value"] for item in ENGAGEMENT_TYPE_OPTIONS]
MIN_CONTRACT_MONTH_OPTIONS = (
    {"value": "3", "label": _profile_label("profile_field_labels", "min_contract_month_option_3")},
    {"value": "6", "label": _profile_label("profile_field_labels", "min_contract_month_option_6")},
    {"value": "12", "label": _profile_label("profile_field_labels", "min_contract_month_option_12")},
)
MIN_CONTRACT_MONTH_LABEL = _profile_label("profile_field_labels", "min_contract_month_label")
MIN_CONTRACT_MONTH_NONE_LABEL = _profile_label("profile_field_labels", "min_contract_month_none_label")
MIN_CONTRACT_MONTH_HELP_TEXT = _profile_label("profile_field_labels", "min_contract_month_help_text")


class WorkMode:
    NONE = ""
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


WORK_MODE_PREFERENCE_OPTIONS = (
    {"value": WorkMode.REMOTE, "label": _profile_label("work_mode_labels", "remote_label")},
    {"value": WorkMode.HYBRID, "label": _profile_label("work_mode_labels", "hybrid_label")},
    {"value": WorkMode.ONSITE, "label": _profile_label("work_mode_labels", "onsite_label")},
)
VALID_WORK_MODE_PREFERENCES = frozenset({item["value"] for item in WORK_MODE_PREFERENCE_OPTIONS})
WORK_MODE_PREFERENCE_DEFAULT_VALUES = tuple(item["value"] for item in WORK_MODE_PREFERENCE_OPTIONS)
WORK_MODE_PREFERENCE_HELP_TEXT = _profile_label("profile_field_labels", "work_mode_preference_help_text")
WORK_MODE_PREFERENCE_NONE_LABEL = _profile_label("workspace_page_labels", "work_mode_option_any")
WORK_TYPE_PREFERENCE_HELP_TEXT = _profile_label("profile_field_labels", "work_type_preference_help_text")


class GovPref:
    ANY = "any"
    GOVERNMENT = "government"
    PRIVATE = "private"


SECTOR_PREFERENCE_OPTIONS = (
    {"value": GovPref.ANY, "label": _profile_label("profile_field_labels", "sector_option_no_preference")},
    {"value": GovPref.GOVERNMENT, "label": _profile_label("workspace_page_labels", "sector_option_public")},
    {"value": GovPref.PRIVATE, "label": _profile_label("workspace_page_labels", "sector_option_private")},
)
SECTOR_PREFERENCE_CHOICE_OPTIONS = (
    {"value": GovPref.GOVERNMENT, "label": _profile_label("workspace_page_labels", "sector_option_public")},
    {"value": GovPref.PRIVATE, "label": _profile_label("workspace_page_labels", "sector_option_private")},
)
VALID_SECTOR_PREFERENCE_VALUES = frozenset(
    {item["value"] for item in SECTOR_PREFERENCE_CHOICE_OPTIONS}
)
SECTOR_PREFERENCE_DEFAULT_LABEL = next(
    (item["label"] for item in SECTOR_PREFERENCE_OPTIONS if item["value"] == GovPref.ANY), ""
)
SECTOR_PREFERENCE_HELP_TEXT = _profile_label("profile_field_labels", "sector_preference_help_text")

SALARY_MIN_ANNUAL_LABEL = _profile_label("profile_field_labels", "salary_min_annual_label")
SALARY_MIN_DAILY_LABEL = _profile_label("profile_field_labels", "salary_min_daily_label")
SALARY_MIN_COMPENSATION_HELP_TEXT = _profile_label("profile_field_labels", "salary_min_compensation_help_text")
SETTINGS_SALARY_ANNUAL_HELP_TEXT = _profile_label("profile_field_labels", "settings_salary_annual_help_text")
SETTINGS_SALARY_DAILY_HELP_TEXT = _profile_label("profile_field_labels", "settings_salary_daily_help_text")

KEY_LOOKBACK_YEARS = "extraction_lookback_years"
KEY_MIN_MONTHS = "title_extraction_min_months"
KEY_MAX_TARGET = "max_target_patterns"
KEY_MAX_SECONDARY = "max_secondary_patterns"
KEY_CV_MAX_PAGES = "cv_max_pages"

KEY_STAR_EVIDENCE = "star_candidate_profile_text"
KEY_EVIDENCE_TIERS = "candidate_profile_tiers"
KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT = "primary_candidate_profile_context"
KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT = "secondary_candidate_profile_context"
KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT = "supplementary_candidate_profile_context"
KEY_CANDIDATE_CAPABILITIES = "candidate_capabilities"
KEY_CANDIDATE_ELIGIBILITY = "candidate_eligibility"
KEY_CANDIDATE_ELIGIBILITY_FACTS = "candidate_eligibility_facts"
KEY_CANDIDATE_QUALIFICATIONS = "candidate_qualifications"
KEY_ROLE_EXPERIENCE = "role_experience"
KEY_SIGNAL_CLUSTERS = "dominant_signal_clusters"
KEY_MUST_NOT_REQUIRED_SKILLS = "must_not_require_skills"
KEY_ONBOARDING_SETTINGS = "onboarding_settings"
KEY_ONBOARDING_COMPLETE = "onboarding_complete"
KEY_MATCH_PREFS = "match_preferences"
KEY_PRIMARY_PATTERNS = "target_roles"
KEY_SECONDARY_PATTERNS = "also_consider_roles"
KEY_TARGET_OCCUPATION_QUERIES = "target_occupation_queries"
KEY_CAPABILITY_LEVEL_WEIGHTS = "capability_level_weights"
KEY_REQUIREMENT_IMPORTANCE_WEIGHTS = "requirement_importance_weights"
KEY_REQUIREMENT_STATUS_WEIGHTS = "requirement_status_weights"
KEY_OCCUPATION_ALIGNMENT = "occupation_alignment"
KEY_CAPABILITY_EVIDENCE = "capability_candidate_profile"
MATCHING_RULE_PROFILE_KEYS = frozenset(
    {
        KEY_CANDIDATE_CAPABILITIES,
        KEY_CANDIDATE_ELIGIBILITY,
        KEY_CANDIDATE_ELIGIBILITY_FACTS,
        KEY_CANDIDATE_QUALIFICATIONS,
        KEY_PRIMARY_PATTERNS,
        KEY_SECONDARY_PATTERNS,
        KEY_EXPLORE_ADJACENT_ROLES,
        KEY_MUST_NOT_REQUIRED_SKILLS,
        "reject_title_rules",
        "reject_description_phrase_rules",
    }
)

KEY_NAME = "name"
KEY_LEVEL = "level"
KEY_ALIASES = "aliases"
KEY_ICON_KEY = "icon_key"
CAPABILITY_ICON_GENERIC = "generic_capability"
VALID_CAPABILITY_ICON_KEYS = frozenset(
    {
        "people_support",
        "communication_stakeholders",
        "analysis_requirements",
        "operations_process",
        "delivery_project",
        "technical_build",
        "systems_platforms",
        "data_reporting",
        "finance_commercial",
        "risk_compliance_security",
        "creative_marketing_content",
        CAPABILITY_ICON_GENERIC,
    }
)
KEY_CONVERGENCE = "convergence"
KEY_COMPETITIVE_SIGNAL_ALIGNMENT = "competitive_signal_alignment"
PROFILE_REVIEW_BLOCKING_REASON_NO_PROFILE = _profile_label(
    "profile_field_labels", "profile_review_blocking_reason_no_profile"
)
PROFILE_REVIEW_BLOCKING_REASON_NO_CAPABILITIES = _profile_label(
    "profile_field_labels", "profile_review_blocking_reason_no_capabilities"
)

logger = logging.getLogger(__name__)


class CapabilityLevel:
    STRONG = "strong"
    WORKING = "working"
    BASIC = "basic"


VALID_CAPABILITY_RULE_LEVELS = frozenset(
    {CapabilityLevel.STRONG, CapabilityLevel.WORKING, CapabilityLevel.BASIC}
)

LEVEL_STRONG = CapabilityLevel.STRONG
LEVEL_WORKING = CapabilityLevel.WORKING
LEVEL_BASIC = CapabilityLevel.BASIC

DEFAULT_CANDIDATE_PROFILE_TIERS = {
    KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT: "",
    KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT: "",
    KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT: "",
}

DEFAULT_MATCH_LEVELS = normalize_match_levels(list(MATCH_LEVELS))
_OBSOLETE_PROFILE_KEYS = (
    "".join(["llm_profile", "_brief_mode"]),
    "".join(["llm_profile", "_brief"]),
    "star_" + "evidence_text",
)


class ProfileLoadError(RuntimeError):
    pass


def _load_default_scoring_rules() -> dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge

    payload = get_knowledge("scoring_rules")
    if payload is None:
        raise RuntimeError("scoring_rules not found in knowledge table — seed the DB first")
    if (
        str(payload.get("kind") or "").strip() != "system_config"
        or str(payload.get("name") or "").strip() != "scoring_rules"
    ):
        raise ValueError("scoring_rules must be managed knowledge")
    return {
        "fit_breakdown": dict(payload.get("fit_breakdown") or {}),
        KEY_CAPABILITY_LEVEL_WEIGHTS: dict(payload.get(KEY_CAPABILITY_LEVEL_WEIGHTS) or {}),
        KEY_REQUIREMENT_IMPORTANCE_WEIGHTS: dict(
            payload.get(KEY_REQUIREMENT_IMPORTANCE_WEIGHTS) or {}
        ),
        KEY_REQUIREMENT_STATUS_WEIGHTS: dict(payload.get(KEY_REQUIREMENT_STATUS_WEIGHTS) or {}),
        KEY_OCCUPATION_ALIGNMENT: dict(payload.get(KEY_OCCUPATION_ALIGNMENT) or {}),
        KEY_CAPABILITY_EVIDENCE: dict(payload.get("capability_evidence") or {}),
        KEY_CONVERGENCE: dict(payload.get(KEY_CONVERGENCE) or {}),
        KEY_COMPETITIVE_SIGNAL_ALIGNMENT: dict(payload.get(KEY_COMPETITIVE_SIGNAL_ALIGNMENT) or {}),
        "deterministic_review_thresholds": dict(
            payload.get("deterministic_review_thresholds") or {}
        ),
        "work_mode": dict(payload.get("work_mode") or {}),
        "salary": dict(payload.get("salary") or {}),
        "location": dict(payload.get("location") or {}),
        "contract": dict(payload.get("contract") or {}),
        "government": dict(payload.get("government") or {}),
    }


DEFAULT_SCORING_RULES = _load_default_scoring_rules()

# Candidate facts live here; the other keys are generated helpers or review state.
DEFAULT_PROFILE = {
    "enabled_sources": ["seek", "linkedin"],
    "search_settings": {
        **DEFAULT_SEARCH_SETTINGS,
    },
    "review_controls": {
        "applied_job_keys": [],
        "hidden_job_keys": [],
    },
    KEY_ONBOARDING_COMPLETE: False,
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
        KEY_WORK_MODE_PREFERENCE: list(WORK_MODE_PREFERENCE_DEFAULT_VALUES),
        KEY_PREFER_SECTOR: [],
        "prefer_permanent": False,
        "engagement_type": list(ENGAGEMENT_TYPE_DEFAULT_VALUES),
        "preferred_contract_months": 12,
        "short_contract_months": 6,
        "min_contract_months": None,
    },
    "star_candidate_profile_text": "",
    KEY_EVIDENCE_TIERS: {
        **DEFAULT_CANDIDATE_PROFILE_TIERS,
    },
    "candidate_profile_tier_weights": {
        **DEFAULT_EVIDENCE_TIER_WEIGHTS,
    },
    KEY_CANDIDATE_CAPABILITIES: [],
    KEY_CANDIDATE_ELIGIBILITY: [],
    KEY_CANDIDATE_ELIGIBILITY_FACTS: [],
    KEY_CANDIDATE_QUALIFICATIONS: [],
    KEY_ROLE_EXPERIENCE: [],
    "dominant_signal_clusters": [],
    "target_roles": [],
    "also_consider_roles": [],
    KEY_EXPLORE_ADJACENT_ROLES: False,
    KEY_TARGET_OCCUPATION_QUERIES: [],
    "must_not_require_skills": [],
    "onboarding_settings": {
        **DEFAULT_ONBOARDING_SETTINGS,
    },
}


def _decode_escaped_newlines(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("\r\n", "\n")
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


def normalize_onboarding_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}

    # Global policy baseline: user-configured values from global_settings.json.
    # Falls back to code defaults if global settings are not yet initialised.
    try:
        global_onboarding = load_global_settings()[GLOBAL_KEY_ONBOARDING_SETTINGS]
    except Exception as exc:
        global_onboarding = {}
        logger.warning("Failed to load global onboarding settings: %s", exc)
    global_presets = (
        global_onboarding.get(KEY_CAPABILITY_STRENGTH_PRESETS) or CAPABILITY_STRENGTH_PRESETS
    )

    # Preset resolution: source > global > code default.
    raw_preset = (
        str(
            source.get("capability_strength_preset")
            or global_onboarding.get("capability_strength_preset")
            or DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
        )
        .strip()
        .lower()
    )
    preset_name = (
        raw_preset
        if raw_preset in global_presets
        else DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
    )
    preset_values = global_presets[preset_name]

    # Merge layer: code defaults -> global settings -> chosen preset -> all explicit source overrides.
    merged: dict[str, Any] = {**DEFAULT_ONBOARDING_SETTINGS}
    merged.update(
        {k: v for k, v in global_onboarding.items() if k != KEY_CAPABILITY_STRENGTH_PRESETS}
    )
    merged.update(preset_values)
    merged.update(
        {
            k: v
            for k, v in source.items()
            if k not in (KEY_CAPABILITY_STRENGTH_PRESETS, "capability_strength_preset")
            and v is not None
        }
    )

    result: dict[str, Any] = {"capability_strength_preset": preset_name}
    onboarding_limits = load_global_settings()[KEY_LIMITS]["onboarding"]
    for key, bounds in onboarding_limits.items():
        result[key] = coerce_int(
            merged.get(key), DEFAULT_ONBOARDING_SETTINGS[key], bounds["min"], bounds["max"]
        )
    return result


def normalize_match_preferences(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    merged = dict(DEFAULT_PROFILE["match_preferences"])
    merged.update({k: v for k, v in source.items() if v is not None})

    merged[KEY_PREFER_SECTOR] = normalize_sector_preference_values(merged.get(KEY_PREFER_SECTOR))

    merged[KEY_WORK_MODE_PREFERENCE] = normalize_work_mode_preferences(
        merged.get(KEY_WORK_MODE_PREFERENCE)
    )

    merged["home_location"] = str(merged.get("home_location") or "").strip()
    merged["secondary_location"] = str(merged.get("secondary_location") or "").strip()
    merged["prefer_permanent"] = bool(merged.get("prefer_permanent", False))
    merged["engagement_type"] = normalize_engagement_type_preferences(merged.get("engagement_type"))
    merged["preferred_contract_months"] = int(merged.get("preferred_contract_months") or 12)
    merged["short_contract_months"] = int(merged.get("short_contract_months") or 6)
    raw_min = merged.get("min_contract_months")
    merged["min_contract_months"] = int(raw_min) if raw_min else None
    return merged


def normalize_work_mode_preferences(values: Any) -> list[str]:
    if isinstance(values, str):
        source_values = [
            part.strip().lower() for part in re.split(r"[,\n|/]+", values) if part.strip()
        ]
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


def normalize_sector_preference_values(values: Any) -> list[str]:
    if isinstance(values, bool):
        return [GovPref.GOVERNMENT] if values else []
    if isinstance(values, str):
        source_values = [
            part.strip().lower() for part in re.split(r"[,\n|/]+", values) if part.strip()
        ]
    elif isinstance(values, (list, tuple, set)):
        source_values = [str(value).strip().lower() for value in values if str(value).strip()]
    else:
        source_values = []
    selected: list[str] = []
    seen: set[str] = set()
    for item in SECTOR_PREFERENCE_CHOICE_OPTIONS:
        value = str(item["value"]).strip().lower()
        if value in source_values and value not in seen:
            seen.add(value)
            selected.append(value)
    return selected


def normalize_engagement_type_preferences(values: Any, *, default_to_all: bool = True) -> list[str]:
    if isinstance(values, str):
        source_values = [
            part.strip().lower() for part in re.split(r"[,\n|/]+", values) if part.strip()
        ]
    elif isinstance(values, (list, tuple, set)):
        source_values = [str(value).strip().lower() for value in values if str(value).strip()]
    else:
        source_values = []
    selected: list[str] = []
    seen: set[str] = set()
    for item in ENGAGEMENT_TYPE_OPTIONS:
        value = str(item["value"]).strip().lower()
        if value in source_values and value not in seen:
            seen.add(value)
            selected.append(value)
    if selected:
        return selected
    return list(ENGAGEMENT_TYPE_DEFAULT_VALUES) if default_to_all else []


def normalize_capability_rules(
    rules: list[dict[str, Any]] | None,
    onboarding_settings: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalise learned capability rules and keep alias growth under onboarding limits."""
    cleaned: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    source_onboarding = onboarding_settings if isinstance(onboarding_settings, dict) else {}
    try:
        alias_limit = int(
            source_onboarding.get(KEY_CAPABILITY_ALIAS_LIMIT)
            or DEFAULT_ONBOARDING_SETTINGS[KEY_CAPABILITY_ALIAS_LIMIT]
        )
    except Exception as exc:
        alias_limit = int(DEFAULT_ONBOARDING_SETTINGS[KEY_CAPABILITY_ALIAS_LIMIT])
        logger.warning("Failed to normalise capability alias limit: %s", exc)

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
            level = CapabilityLevel.BASIC

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
            alias_items = derive_job_description_aliases(
                name, [str(rule.get("name") or "").strip(), *alias_items], max_aliases=alias_limit
            )

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

        canonical_name = (
            choose_capability_name(name, alias_items) if choose_capability_name else name_norm
        )
        if not canonical_name:
            continue

        cleaned.append(
            {
                "name": canonical_name,
                "level": level,
                "aliases": aliases,
                "needs_review": needs_review,
                KEY_ICON_KEY: str(rule.get(KEY_ICON_KEY) or CAPABILITY_ICON_GENERIC)
                .strip()
                .lower(),
            }
        )

    return cleaned


def _normalize_eligibility_value(value: Any, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1", "have", "has", "held", "present"}:
            return True
        if lowered in {"false", "no", "n", "0", "absent", "missing", "none", "not"}:
            return False
    return bool(value)


def load_clearance_ui_options() -> list[dict[str, Any]]:
    rules = load_parsing_rules()
    config = rules.get("government_discovery_config")
    if not isinstance(config, dict):
        raise ValueError("parsing_rules.json must define government_discovery_config")
    options = config.get("clearance_ui_options")
    if not isinstance(options, list) or not options:
        raise ValueError("parsing_rules.json must define government_discovery_config.clearance_ui_options")

    cleaned: list[dict[str, Any]] = []
    seen_values: set[str] = set()
    seen_ranks: set[int] = set()
    for option in options:
        if not isinstance(option, dict):
            raise ValueError("clearance_ui_options entries must be objects")
        value = re.sub(r"\s+", " ", str(option.get("value") or "")).strip()
        label = re.sub(r"\s+", " ", str(option.get("label") or "")).strip()
        aliases = option.get("aliases") or []
        if not value or not label:
            raise ValueError("clearance_ui_options entries must define non-empty value and label")
        key = value.casefold()
        if key in seen_values:
            raise ValueError(f"Duplicate clearance_ui_options value: {value}")
        if not isinstance(aliases, list):
            raise ValueError(f"clearance_ui_options aliases for {value} must be a list")
        rank = option.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank <= 0:
            raise ValueError(
                f"clearance_ui_options entry {value} must define a positive integer rank"
            )
        if rank in seen_ranks:
            raise ValueError(f"Duplicate clearance_ui_options rank: {rank}")
        seen_values.add(key)
        seen_ranks.add(rank)
        cleaned.append(
            {
                "value": value,
                "label": label,
                "rank": rank,
                "aliases": [
                    re.sub(r"\s+", " ", str(alias or "")).strip()
                    for alias in aliases
                    if str(alias or "").strip()
                ],
            }
        )
    return sorted(cleaned, key=lambda item: item["rank"])


def apply_clearance_hierarchy(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Enforce that holding a higher managed clearance implies holding every lower one.

    This is a one-directional (upward) invariant: holding NV2 implies Baseline and
    NV1 are also held, using `rank` from the managed clearance catalogue as the
    single source of truth for ordering (see docs backlog JH-260 for why TS-PA is
    intentionally not modelled here yet). It never turns an explicitly-submitted
    True value to False, so it never silently discards a submitted signal. Turning
    a lower clearance off and cascading that downward to higher ones is a
    deliberate user action handled interactively in settings-clearance-editor.js,
    which knows which toggle the user just changed; a stateless pass over the
    final rule list cannot recover that intent.
    """
    options = load_clearance_ui_options()
    rank_by_key: dict[str, int] = {}
    for option in options:
        for key in (option["value"], option["label"], *option["aliases"]):
            normalized_key = re.sub(r"\s+", " ", str(key or "")).strip().casefold()
            if normalized_key:
                rank_by_key[normalized_key] = option["rank"]

    max_held_rank = 0
    for rule in rules:
        rank = rank_by_key.get(str(rule.get("name") or "").strip().casefold())
        if rank is not None and rule.get("value"):
            max_held_rank = max(max_held_rank, rank)

    if not max_held_rank:
        return rules

    for rule in rules:
        rank = rank_by_key.get(str(rule.get("name") or "").strip().casefold())
        if rank is not None and rank <= max_held_rank:
            rule["value"] = True

    return rules


def normalize_eligibility_rules(rules: list[dict[str, Any]] | list[str] | None) -> list[dict[str, Any]]:
    """Normalise explicit eligibility facts while preserving original fact casing."""
    cleaned: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for rule in rules or []:
        if isinstance(rule, str):
            name = str(rule or "").strip()
            value = True
            evidence: list[str] = []
            needs_review = False
        elif isinstance(rule, dict):
            name = str(rule.get("name") or rule.get("label") or "").strip()
            value = _normalize_eligibility_value(
                rule.get("value") if "value" in rule else rule.get("has"),
                default=True,
            )
            raw_evidence = rule.get("evidence") or rule.get("sources") or []
            if isinstance(raw_evidence, str):
                raw_evidence = [raw_evidence]
            evidence = normalize_multiline_string_list(raw_evidence)
            needs_review = bool(rule.get("needs_review"))
        else:
            continue

        name_norm = re.sub(r"\s+", " ", name).strip().casefold()
        if not name_norm or name_norm in seen_names:
            continue
        seen_names.add(name_norm)

        cleaned.append(
            {
                "name": name,
                "value": value,
                "evidence": evidence,
                "needs_review": needs_review,
            }
        )

    return apply_clearance_hierarchy(cleaned)


def normalize_role_experience(items: Any) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}

    for item in items or []:
        if not isinstance(item, dict):
            continue

        normalized_title = normalize_title_text(item.get("normalized_title"))
        if not normalized_title:
            continue

        total_duration_months = coerce_int(
            item.get("total_duration_months"),
            default=0,
            minimum=0,
            maximum=12_000,
        )
        most_recent_end_year = coerce_int(
            item.get("most_recent_end_year"),
            default=0,
            minimum=0,
            maximum=9_999,
        )

        existing = aggregated.setdefault(
            normalized_title,
            {
                "normalized_title": normalized_title,
                "total_duration_months": 0,
                "most_recent_end_year": 0,
                "title_variants": {},
            },
        )
        existing["total_duration_months"] = int(existing["total_duration_months"]) + int(
            total_duration_months
        )
        existing["most_recent_end_year"] = max(
            int(existing["most_recent_end_year"]),
            int(most_recent_end_year),
        )

        raw_variants = item.get("title_variants") or []
        if not isinstance(raw_variants, list):
            raw_variants = []
        variant_items = raw_variants or [
            {
                "normalized_title": normalized_title,
                "total_duration_months": total_duration_months,
                "most_recent_end_year": most_recent_end_year,
            }
        ]
        for raw_variant in variant_items:
            if not isinstance(raw_variant, dict):
                continue
            variant_title = normalize_title_text(raw_variant.get("normalized_title"))
            if not variant_title:
                continue
            variant_duration_months = coerce_int(
                raw_variant.get("total_duration_months"),
                default=0,
                minimum=0,
                maximum=12_000,
            )
            variant_end_year = coerce_int(
                raw_variant.get("most_recent_end_year"),
                default=0,
                minimum=0,
                maximum=9_999,
            )
            variants = existing["title_variants"]
            variant = variants.setdefault(
                variant_title,
                {
                    "normalized_title": variant_title,
                    "total_duration_months": 0,
                    "most_recent_end_year": 0,
                },
            )
            variant["total_duration_months"] = int(variant["total_duration_months"]) + int(
                variant_duration_months
            )
            variant["most_recent_end_year"] = max(
                int(variant["most_recent_end_year"]),
                int(variant_end_year),
            )

    result: list[dict[str, Any]] = []
    for key in sorted(aggregated):
        row = aggregated[key]
        variants = row.pop("title_variants", {})
        row["title_variants"] = [variants[name] for name in sorted(variants)]
        result.append(row)
    return result


def normalize_full_profile(profile: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise TypeError("profile must be a dict")
    merged = deep_merge(copy.deepcopy(DEFAULT_PROFILE), profile)
    merged.pop("".join(["llm", "_capability_naming_guidance"]), None)
    for key in _OBSOLETE_PROFILE_KEYS:
        merged.pop(key, None)
    merged["search_settings"] = normalize_search_settings(merged.get("search_settings", {}))
    merged["salary_preferences"] = normalize_salary_preferences(
        merged.get("salary_preferences", {})
    )
    merged["preference_weights"] = normalize_preference_weights(
        merged.get("preference_weights", {})
    )
    merged["scoring_rules"] = normalize_scoring_rules(merged.get("scoring_rules", {}))
    merged["match_levels"] = normalize_match_levels(merged.get("match_levels", []))
    merged[KEY_EVIDENCE_TIERS] = normalize_candidate_profile_tiers(
        merged.get(KEY_EVIDENCE_TIERS, {}),
    )
    merged["candidate_profile_tier_weights"] = normalize_candidate_profile_tier_weights(
        merged.get("candidate_profile_tier_weights", {})
    )
    merged["onboarding_settings"] = normalize_onboarding_settings(
        merged.get("onboarding_settings", {})
    )
    merged[KEY_ONBOARDING_COMPLETE] = bool(merged.get(KEY_ONBOARDING_COMPLETE, False))
    merged["match_preferences"] = normalize_match_preferences(merged.get("match_preferences", {}))
    primary_search_location = next(
        (
            str(value).strip()
            for value in merged["search_settings"].get("locations", [])
            if str(value).strip()
        ),
        "",
    )
    if primary_search_location and not merged["match_preferences"].get("home_location"):
        merged["match_preferences"]["home_location"] = primary_search_location
    merged[KEY_CANDIDATE_CAPABILITIES] = normalize_capability_rules(
        merged.get(KEY_CANDIDATE_CAPABILITIES, []),
        merged.get("onboarding_settings", {}),
    )
    merged[KEY_CANDIDATE_ELIGIBILITY] = normalize_eligibility_rules(
        merged.get(KEY_CANDIDATE_ELIGIBILITY, [])
    )
    merged[KEY_CANDIDATE_ELIGIBILITY_FACTS] = normalize_eligibility_facts(
        merged.get(KEY_CANDIDATE_ELIGIBILITY_FACTS, [])
    )
    merged[KEY_CANDIDATE_QUALIFICATIONS] = normalize_qualifications(
        merged.get(KEY_CANDIDATE_QUALIFICATIONS, [])
    )
    merged[KEY_ROLE_EXPERIENCE] = normalize_role_experience(merged.get(KEY_ROLE_EXPERIENCE, []))
    primary_titles, secondary_titles = normalize_title_pattern_lists(
        merged.get(KEY_PRIMARY_PATTERNS, []),
        merged.get(KEY_SECONDARY_PATTERNS, []),
    )
    merged[KEY_PRIMARY_PATTERNS] = primary_titles
    merged[KEY_SECONDARY_PATTERNS] = secondary_titles
    merged[KEY_TARGET_OCCUPATION_QUERIES] = normalize_multiline_string_list(
        merged.get(KEY_TARGET_OCCUPATION_QUERIES, [])
    )
    merged["must_not_require_skills"] = normalize_multiline_string_list(
        merged.get("must_not_require_skills", [])
    )
    return merged


def load_profile() -> dict[str, Any]:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        row = conn.execute("SELECT data FROM user_profile WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return normalize_full_profile(copy.deepcopy(DEFAULT_PROFILE))
    data = json.loads(row["data"])
    if not isinstance(data, dict):
        raise ProfileLoadError("user_profile in DB must contain a JSON object")
    return normalize_full_profile(data)


def profile_exists() -> bool:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_profile WHERE user_id = ? LIMIT 1", (user_id,)
        ).fetchone()
    return row is not None


def profile_review_status(
    profile: dict[str, Any] | None = None,
    has_profile: bool | None = None,
) -> dict[str, Any]:
    current = profile if isinstance(profile, dict) else load_profile()
    current_has_profile = profile_exists() if has_profile is None else bool(has_profile)
    capability_rules = current.get(KEY_CANDIDATE_CAPABILITIES, [])
    if not isinstance(capability_rules, list):
        capability_rules = []
    usable_capabilities = [
        rule
        for rule in capability_rules
        if isinstance(rule, dict) and str(rule.get(KEY_NAME) or "").strip()
    ]
    candidate_capability_count = len(usable_capabilities)
    has_candidate_capabilities = candidate_capability_count > 0
    profile_ready_for_review = current_has_profile and has_candidate_capabilities
    blocking_reason = ""
    if not current_has_profile:
        blocking_reason = PROFILE_REVIEW_BLOCKING_REASON_NO_PROFILE
    elif not has_candidate_capabilities:
        blocking_reason = PROFILE_REVIEW_BLOCKING_REASON_NO_CAPABILITIES
    return {
        "has_profile": current_has_profile,
        "has_candidate_capabilities": has_candidate_capabilities,
        "candidate_capability_count": candidate_capability_count,
        "profile_ready_for_review": profile_ready_for_review,
        "blocking_reason": blocking_reason,
    }


def require_profile_ready_for_review(
    profile: dict[str, Any] | None = None,
    has_profile: bool | None = None,
) -> dict[str, Any]:
    status = profile_review_status(profile=profile, has_profile=has_profile)
    if not status["profile_ready_for_review"]:
        raise ValueError(
            str(status.get("blocking_reason") or PROFILE_REVIEW_BLOCKING_REASON_NO_PROFILE)
        )
    return status


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    try:
        current = load_profile()
    except Exception:
        current = None
    validate_search_keywords(
        (profile or {}).get("search_settings", {}).get("keywords"),
        require_phrase=True,
    )
    normalized = normalize_full_profile(profile)
    persisted = dict(normalized)
    persisted.pop("scoring_rules", None)
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO user_profile (user_id, data, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at""",
            (user_id, json.dumps(persisted, ensure_ascii=False)),
        )
    log_settings_change(
        logger,
        scope="PROFILE_SETTINGS",
        before=current,
        after=normalized,
    )
    return normalized


def patch_profile(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_profile()
    merged = deep_merge(current, patch)
    return save_profile(merged)


def normalize_search_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    merged = deep_merge(copy.deepcopy(DEFAULT_SEARCH_SETTINGS), settings or {})
    search_limits = load_global_settings()[KEY_LIMITS]["search"]

    try:
        merged[KEY_DATE_RANGE_DAYS] = max(
            search_limits[KEY_DATE_RANGE_DAYS]["min"],
            min(
                int(merged.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])),
                search_limits[KEY_DATE_RANGE_DAYS]["max"],
            ),
        )
    except Exception as exc:
        merged[KEY_DATE_RANGE_DAYS] = DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]
        logger.warning("Failed to normalise date_range_days: %s", exc)

    try:
        merged[KEY_SEEK_MAX_PAGES] = max(
            search_limits[KEY_SEEK_MAX_PAGES]["min"],
            min(
                int(merged.get(KEY_SEEK_MAX_PAGES, search_limits[KEY_SEEK_MAX_PAGES]["max"])),
                search_limits[KEY_SEEK_MAX_PAGES]["max"],
            ),
        )
    except Exception as exc:
        merged[KEY_SEEK_MAX_PAGES] = DEFAULT_SEARCH_SETTINGS[KEY_SEEK_MAX_PAGES]
        logger.warning("Failed to normalise seek_max_pages: %s", exc)

    try:
        merged[KEY_LINKEDIN_HOURS_OLD] = max(
            search_limits[KEY_LINKEDIN_HOURS_OLD]["min"],
            min(
                int(
                    merged.get(
                        KEY_LINKEDIN_HOURS_OLD, DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
                    )
                ),
                search_limits[KEY_LINKEDIN_HOURS_OLD]["max"],
            ),
        )
    except Exception as exc:
        merged[KEY_LINKEDIN_HOURS_OLD] = DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
        logger.warning("Failed to normalise linkedin_hours_old: %s", exc)

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
    except Exception as exc:
        merged[KEY_LINKEDIN_RESULTS_PER_SEARCH] = DEFAULT_SEARCH_SETTINGS[
            KEY_LINKEDIN_RESULTS_PER_SEARCH
        ]
        logger.warning("Failed to normalise linkedin_results_per_search: %s", exc)

    try:
        merged[KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS] = max(
            search_limits[KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS]["min"],
            min(
                int(
                    merged.get(
                        KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS,
                        DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS],
                    )
                ),
                search_limits[KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS]["max"],
            ),
        )
    except Exception as exc:
        merged[KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS] = DEFAULT_SEARCH_SETTINGS[
            KEY_LINKEDIN_FETCH_TIMEOUT_SECONDS
        ]
        logger.warning("Failed to normalise linkedin_fetch_timeout_seconds: %s", exc)

    try:
        merged[KEY_APSJOBS_RESULTS_PER_SEARCH] = max(
            search_limits[KEY_APSJOBS_RESULTS_PER_SEARCH]["min"],
            min(
                int(
                    merged.get(
                        KEY_APSJOBS_RESULTS_PER_SEARCH,
                        DEFAULT_SEARCH_SETTINGS[KEY_APSJOBS_RESULTS_PER_SEARCH],
                    )
                ),
                search_limits[KEY_APSJOBS_RESULTS_PER_SEARCH]["max"],
            ),
        )
    except Exception as exc:
        merged[KEY_APSJOBS_RESULTS_PER_SEARCH] = DEFAULT_SEARCH_SETTINGS[
            KEY_APSJOBS_RESULTS_PER_SEARCH
        ]
        logger.warning("Failed to normalise apsjobs_results_per_search: %s", exc)

    merged[KEY_SORT_NEWEST_FIRST] = bool(merged.get(KEY_SORT_NEWEST_FIRST, True))
    merged["keywords"] = str(merged.get("keywords") or "").strip()
    raw_locations = merged.get("locations", [])
    if isinstance(raw_locations, str):
        raw_locations = [raw_locations]
    normalized_locations: list[str] = []
    seen_locations: set[str] = set()
    max_locations = int(search_limits.get(KEY_LOCATIONS_MAX_SELECTED, {}).get("max", 3) or 3)
    for value in raw_locations if isinstance(raw_locations, (list, tuple, set)) else []:
        cleaned = str(value).strip()
        normalized = cleaned.lower()
        if not cleaned or normalized in seen_locations:
            continue
        seen_locations.add(normalized)
        normalized_locations.append(cleaned)
        if len(normalized_locations) >= max_locations:
            break
    merged["locations"] = normalized_locations
    quick_apply_only = merged.get(KEY_SEEK_QUICK_APPLY_ONLY)
    if quick_apply_only is None or quick_apply_only == "":
        merged[KEY_SEEK_QUICK_APPLY_ONLY] = None
    elif isinstance(quick_apply_only, str):
        normalized_quick_apply_only = quick_apply_only.strip().lower()
        if normalized_quick_apply_only == "true":
            merged[KEY_SEEK_QUICK_APPLY_ONLY] = True
        elif normalized_quick_apply_only == "false":
            merged[KEY_SEEK_QUICK_APPLY_ONLY] = False
        else:
            merged[KEY_SEEK_QUICK_APPLY_ONLY] = None
    else:
        merged[KEY_SEEK_QUICK_APPLY_ONLY] = bool(quick_apply_only)
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


def validate_search_keywords(value: object, *, require_phrase: bool = False) -> str:
    keywords = str(value or "").strip()
    if not keywords:
        return ""
    if len(keywords) < 2 or len(keywords) > 120:
        raise ValueError(_profile_label("profile_field_labels", "search_keywords_length_error"))
    if require_phrase and len(keywords.split()) < 2:
        raise ValueError(_profile_label("profile_field_labels", "search_keywords_phrase_error"))
    return keywords


def normalize_salary_preferences(payload: dict[str, Any] | None) -> dict[str, int]:
    source = payload if isinstance(payload, dict) else {}
    salary_limits = get_salary_limits()
    yearly_cap = int(salary_limits.get(KEY_MIN_SALARY_YEARLY, {}).get("max", 0) or 0)
    daily_cap = int(salary_limits.get(KEY_MIN_DAILY_RATE, {}).get("max", 0) or 0)
    try:
        minimum_salary_yearly = max(
            0, int(str(source.get("minimum_salary_yearly", 0)).replace(",", "").strip() or 0)
        )
    except Exception as exc:
        minimum_salary_yearly = 0
        logger.warning("Failed to parse minimum_salary_yearly: %s", exc)
    minimum_salary_yearly = (
        min(minimum_salary_yearly, yearly_cap) if yearly_cap > 0 else minimum_salary_yearly
    )
    try:
        minimum_daily_rate = max(
            0, int(str(source.get("minimum_daily_rate", 0)).replace(",", "").strip() or 0)
        )
    except Exception as exc:
        minimum_daily_rate = 0
        logger.warning("Failed to parse minimum_daily_rate: %s", exc)
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
        except Exception as exc:
            value = default
            logger.warning("Failed to normalise weight for %s: %s", key, exc)
        normalized[key] = max(min(value, 2.0), 0.0)
    return normalized


def normalize_scoring_rules(payload: dict[str, Any] | None) -> dict[str, Any]:
    # Always load fresh from the DB so schema additions in scoring_rules.json take effect
    # on the next request after db_seed --upgrade, without requiring a process restart.
    # (DEFAULT_SCORING_RULES is frozen at import time; that is too early for sections
    # added after the first DB upgrade runs.)
    live_default = _load_default_scoring_rules()
    source = payload if isinstance(payload, dict) else {}
    normalized = copy.deepcopy(live_default)

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
            if incoming_value is None or incoming_value == "":
                return int(default_value)
            try:
                return int(incoming_value)
            except Exception as exc:
                logger.warning("Failed to merge int value: %s", exc)
                return int(default_value)
        if isinstance(default_value, float):
            if incoming_value is None or incoming_value == "":
                return float(default_value)
            try:
                return float(incoming_value)
            except Exception as exc:
                logger.warning("Failed to merge float value: %s", exc)
                return float(default_value)
        return copy.deepcopy(default_value if incoming_value in (None, "") else incoming_value)

    for key, default_value in live_default.items():
        normalized[key] = _merge(default_value, source.get(key))
    # Preserve dict sections from source that the live default does not yet know about.
    # This ensures new sections (e.g. llm_grade_bands) from scoring_rules.json are available
    # to feature code even if the DB version lags behind the file (e.g. between restarts).
    _METADATA_KEYS = frozenset(
        {"kind", "name", "version", "updated_at", "description", "calibration_notes"}
    )
    for key, value in source.items():
        if key not in normalized and key not in _METADATA_KEYS and isinstance(value, dict):
            normalized[key] = copy.deepcopy(value)
    return normalized


def normalize_profile_match_levels(payload: list[dict[str, Any]] | None) -> list[dict[str, object]]:
    normalized = normalize_match_levels(payload)
    return normalized or [dict(level) for level in DEFAULT_MATCH_LEVELS]


_SECTION_BUCKET_TO_TIER = {
    "primary": KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
    "secondary": KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
    "supplementary": KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
}


def classify_candidate_profile_section_label(label: str) -> str:
    lowered = str(label or "").strip().lower()
    routing = load_parsing_rules().get(KEY_P_ROUTING)
    if not isinstance(routing, dict):
        raise ValueError("parsing_rules.json must define candidate_profile_section_routing")
    default_bucket = str(routing.get(KEY_P_ROUTING_DEFAULT) or "").strip()
    primary_labels = routing.get(KEY_P_ROUTING_PRIMARY)
    secondary_labels = routing.get(KEY_P_ROUTING_SECONDARY)
    supplementary_labels = routing.get(KEY_P_ROUTING_SUPPLEMENTARY)
    if not all(
        isinstance(items, list)
        for items in (primary_labels, secondary_labels, supplementary_labels)
    ):
        raise ValueError("candidate_profile_section_routing labels must be lists")
    if default_bucket not in DEFAULT_CANDIDATE_PROFILE_TIERS:
        raise ValueError(f"{KEY_P_ROUTING}.{KEY_P_ROUTING_DEFAULT} must be a known profile bucket")
    primary_tokens = [str(token).strip().lower() for token in primary_labels if str(token).strip()]
    secondary_tokens = [
        str(token).strip().lower() for token in secondary_labels if str(token).strip()
    ]
    supplementary_tokens = [
        str(token).strip().lower() for token in supplementary_labels if str(token).strip()
    ]
    if not lowered:
        return default_bucket
    if any(token in lowered for token in primary_tokens):
        return KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT
    if any(token in lowered for token in secondary_tokens):
        return KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT
    if any(token in lowered for token in supplementary_tokens):
        return KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT
    return _classify_unknown_section_label(lowered, default_bucket)


def _classify_unknown_section_label(lowered: str, default_bucket: str) -> str:
    if is_desktop_runtime():
        return default_bucket
    from job_hunter_agent import llm_gate  # lazy import — llm_gate imports profile_store
    from job_hunter_agent.signal_registry import register_signals, upsert_profile_section_label
    from job_hunter_agent.signal_schema import (
        CATEGORY_PROFILE_SECTION_LABEL,
        LEARNING_SUGGESTED_VALUES_KEY,
    )

    result = llm_gate.llm_classify_section_label(lowered)
    if result is None:
        return default_bucket

    bucket = result["bucket"]
    tier = _SECTION_BUCKET_TO_TIER.get(bucket, default_bucket)

    if result["confident"]:
        upsert_profile_section_label(lowered, bucket)
    else:
        register_signals(
            [
                {
                    "signal": lowered,
                    "category": CATEGORY_PROFILE_SECTION_LABEL,
                    LEARNING_SUGGESTED_VALUES_KEY: [bucket],
                    "evidence": [
                        f"## {lowered} (profile section — LLM classified as {bucket}, confidence uncertain)"
                    ],
                }
            ]
        )

    return tier


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


def build_candidate_profile_tiers_from_sections(
    sections: list[dict[str, str]] | None,
) -> dict[str, str]:
    buckets = {key: [] for key in DEFAULT_CANDIDATE_PROFILE_TIERS}
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
    return {bucket: _combine_unique_sections(parts) for bucket, parts in buckets.items()}


def normalize_candidate_profile_tiers(payload: dict[str, Any] | None) -> dict[str, str]:
    normalized = dict(DEFAULT_CANDIDATE_PROFILE_TIERS)
    source = payload if isinstance(payload, dict) else {}
    for key in normalized:
        normalized[key] = str(source.get(key) or "").strip()
    return normalized


def normalize_candidate_profile_tier_weights(payload: dict[str, Any] | None) -> dict[str, float]:
    source = payload if isinstance(payload, dict) else {}
    normalized = dict(DEFAULT_EVIDENCE_TIER_WEIGHTS)
    for key, default in DEFAULT_EVIDENCE_TIER_WEIGHTS.items():
        try:
            value = float(source.get(key, default) or default)
        except Exception as exc:
            value = default
            logger.warning("Failed to normalise tier weight for %s: %s", key, exc)
        normalized[key] = max(min(value, 1.0), 0.0)
    return normalized


def get_candidate_profile_tiers(profile: dict[str, Any]) -> dict[str, str]:
    return normalize_candidate_profile_tiers(profile.get(KEY_EVIDENCE_TIERS, {}))


def get_candidate_profile_tier_weights(profile: dict[str, Any]) -> dict[str, float]:
    return normalize_candidate_profile_tier_weights(
        profile.get("candidate_profile_tier_weights", {})
    )


def get_search_settings(profile: dict[str, Any]) -> dict[str, Any]:
    return normalize_search_settings(profile.get("search_settings", {}))


def get_scoring_rules(profile: dict[str, Any]) -> dict[str, Any]:
    return normalize_scoring_rules(profile.get("scoring_rules", {}))


def get_match_levels(profile: dict[str, Any]) -> list[dict[str, object]]:
    return normalize_profile_match_levels(profile.get("match_levels", []))
