"""Profile persistence and defaults.

Main goals:
- define the runtime profile structure used by matching and review flows
- create a safe default profile for first run
- load, merge, patch, and save profile.json consistently

Notes:
- profile.json is the runtime source of truth
- onboarding and imports may generate it, and admin refines it over time
"""

import copy
import json
import re
import shutil
from datetime import datetime, timezone
from typing import Any

from job_hunter_agent.match_labels import MATCH_LEVELS, normalize_match_levels
from job_hunter_agent.advance_settings import (
    CAPABILITY_STRENGTH_PRESETS,
    DEFAULT_EVIDENCE_TIER_WEIGHTS,
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PREFERENCE_WEIGHTS,
    DEFAULT_SEARCH_SETTINGS,
    KEY_CAPABILITY_STRENGTH_PRESETS,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_ONBOARDING_SETTINGS as ADVANCE_KEY_ONBOARDING_SETTINGS,
    ONBOARDING_SETTING_LIMITS,
    SEARCH_SETTING_LIMITS,
    load_advance_settings,
)
from job_hunter_agent.paths import (
    DATA_DIR, 
    PROFILE_PATH,
    REPO_ROOT,
    SCORING_RULES_PATH,
)


ROOT_DIR = REPO_ROOT 
# Shared Profile and Settings Keys
KEY_KEYWORDS = "keywords"
KEY_LOCATIONS = "locations"
KEY_ENGAGEMENT_TYPE = "engagement_type"
KEY_MIN_SALARY_YEARLY = "minimum_salary_yearly"
KEY_MIN_DAILY_RATE = "minimum_daily_rate"

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

KEY_NAME = "name"
KEY_LEVEL = "level"
KEY_ALIASES = "aliases"
KEY_NEEDS_REVIEW = "needs_review"
KEY_CONVERGENCE = "convergence"
KEY_CONVERGENCE_ELIGIBLE_GRADES = "eligible_grades"
KEY_CONVERGENCE_MIN_POSITIVE_MATCHES = "min_positive_matches"
KEY_CONVERGENCE_BONUS_NO_SOFT_RISKS = "bonus_no_soft_risks"
KEY_CONVERGENCE_BONUS_WITH_SOFT_RISKS = "bonus_with_soft_risks"
KEY_CONVERGENCE_LABEL = "label"

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
DEFAULT_LLM_PROFILE_BRIEF_MODE = "auto"


class ProfileLoadError(RuntimeError):
    pass


def _load_default_scoring_rules() -> dict[str, Any]:
    payload = json.loads(SCORING_RULES_PATH.read_text(encoding="utf-8"))
    if str(payload.get("kind") or "").strip() != "managed_knowledge":
        raise ValueError("scoring_rules.json must be managed knowledge")
    return {
        "fit_breakdown": dict(payload.get("fit_breakdown") or {}),
        KEY_LLM_GRADE_POINTS: dict(payload.get(KEY_LLM_GRADE_POINTS) or {}),
        KEY_CAPABILITY_LEVEL_WEIGHTS: dict(payload.get(KEY_CAPABILITY_LEVEL_WEIGHTS) or {}),
        KEY_CAPABILITY_EVIDENCE: dict(payload.get(KEY_CAPABILITY_EVIDENCE) or {}),
        KEY_CONVERGENCE: dict(payload.get(KEY_CONVERGENCE) or {}),
        "freshness": dict(payload.get("freshness") or {}),
        "work_mode": dict(payload.get("work_mode") or {}),
        "salary": dict(payload.get("salary") or {}),
        "location": dict(payload.get("location") or {}),
        "contract": dict(payload.get("contract") or {}),
        "government": dict(payload.get("government") or {}),
    }


DEFAULT_SCORING_RULES = _load_default_scoring_rules()

DEFAULT_PROFILE = {
    "enabled_sources": ["seek", "linkedin"],
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
        "prefer_government": False,
        "prefer_permanent": False,
        "engagement_type": "both",
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


def ensure_profile_exists() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if PROFILE_PATH.exists():
        return
    save_profile(DEFAULT_PROFILE)


def _backup_invalid_profile() -> None:
    if not PROFILE_PATH.exists():
        return
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = PROFILE_PATH.with_name(f"profile.invalid.{timestamp}.json")
    shutil.copy2(PROFILE_PATH, backup_path)


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        resolved = int(value)
    except Exception:
        resolved = default
    return max(minimum, min(maximum, resolved))


def normalize_onboarding_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}

    # Global policy baseline: user-configured values from advance_settings.json.
    # Falls back to code defaults if advance_settings is not yet initialised.
    try:
        global_onboarding = load_advance_settings()[ADVANCE_KEY_ONBOARDING_SETTINGS]
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

    # Merge layer: code defaults → global settings → chosen preset → all explicit source overrides.
    merged: dict[str, Any] = {**DEFAULT_ONBOARDING_SETTINGS}
    merged.update({k: v for k, v in global_onboarding.items() if k != KEY_CAPABILITY_STRENGTH_PRESETS})
    merged.update(preset_values)
    merged.update({
        k: v for k, v in source.items()
        if k not in (KEY_CAPABILITY_STRENGTH_PRESETS, "capability_strength_preset") and v is not None
    })

    result: dict[str, Any] = {"capability_strength_preset": preset_name}
    for key, (minimum, maximum) in ONBOARDING_SETTING_LIMITS.items():
        result[key] = _coerce_int(merged.get(key), DEFAULT_ONBOARDING_SETTINGS[key], minimum, maximum)
    return result


def normalize_capability_rules(rules: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    derive_job_description_aliases = None

    try:
        from job_hunter_agent.capability_matrix import derive_job_description_aliases as _derive_job_description_aliases

        derive_job_description_aliases = _derive_job_description_aliases
    except Exception:
        pass

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
            level = "basic"

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
            alias_items = derive_job_description_aliases(name, [str(rule.get("name") or "").strip(), *alias_items], max_aliases=8)

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

        cleaned.append({
            "name": name,
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
    merged[KEY_CAPABILITY_PROFILE_RULES] = normalize_capability_rules(
        merged.get(KEY_CAPABILITY_PROFILE_RULES, [])
    )
    merged["primary_job_title_pattern"] = normalize_multiline_string_list(
        merged.get("primary_job_title_pattern", [])
    )
    merged["secondary_title_patterns"] = normalize_multiline_string_list(
        merged.get("secondary_title_patterns", [])
    )
    merged["must_not_require_skills"] = normalize_multiline_string_list(
        merged.get("must_not_require_skills", [])
    )
    return merged


def load_profile() -> dict[str, Any]:
    ensure_profile_exists()
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _backup_invalid_profile()
        raise ProfileLoadError(f"Failed to parse profile.json: {exc}") from exc
    if not isinstance(data, dict):
        _backup_invalid_profile()
        raise ProfileLoadError("profile.json must contain a JSON object")
    return normalize_full_profile(data)


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_full_profile(profile)
    PROFILE_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
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

    try:
        merged["date_range_days"] = max(
            SEARCH_SETTING_LIMITS["date_range_days"]["min"],
            min(
                int(merged.get("date_range_days", DEFAULT_SEARCH_SETTINGS["date_range_days"])),
                SEARCH_SETTING_LIMITS["date_range_days"]["max"],
            ),
        )
    except Exception:
        merged["date_range_days"] = DEFAULT_SEARCH_SETTINGS["date_range_days"]

    try:
        merged["seek_max_pages"] = max(
            SEARCH_SETTING_LIMITS["seek_max_pages"]["min"],
            min(
                int(merged.get("seek_max_pages", DEFAULT_SEARCH_SETTINGS["seek_max_pages"])),
                SEARCH_SETTING_LIMITS["seek_max_pages"]["max"],
            ),
        )
    except Exception:
        merged["seek_max_pages"] = DEFAULT_SEARCH_SETTINGS["seek_max_pages"]

    try:
        merged["linkedin_hours_old"] = max(
            SEARCH_SETTING_LIMITS["linkedin_hours_old"]["min"],
            min(
                int(merged.get("linkedin_hours_old", DEFAULT_SEARCH_SETTINGS["linkedin_hours_old"])),
                SEARCH_SETTING_LIMITS["linkedin_hours_old"]["max"],
            ),
        )
    except Exception:
        merged["linkedin_hours_old"] = DEFAULT_SEARCH_SETTINGS["linkedin_hours_old"]

    try:
        merged["linkedin_results_per_search"] = max(
            SEARCH_SETTING_LIMITS["linkedin_results_per_search"]["min"],
            min(
                int(
                    merged.get(
                        "linkedin_results_per_search",
                        DEFAULT_SEARCH_SETTINGS["linkedin_results_per_search"],
                    )
                ),
                SEARCH_SETTING_LIMITS["linkedin_results_per_search"]["max"],
            ),
        )
    except Exception:
        merged["linkedin_results_per_search"] = DEFAULT_SEARCH_SETTINGS["linkedin_results_per_search"]

    merged["enforce_posted_age_limit"] = bool(merged.get("enforce_posted_age_limit", True))
    merged["sort_newest_first"] = bool(merged.get("sort_newest_first", True))
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
    try:
        minimum_salary_yearly = max(0, int(source.get("minimum_salary_yearly", 0) or 0))
    except Exception:
        minimum_salary_yearly = 0
    try:
        minimum_daily_rate = max(0, int(source.get("minimum_daily_rate", 0) or 0))
    except Exception:
        minimum_daily_rate = 0
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
    if normalized == "manual":
        return "manual"
    return DEFAULT_LLM_PROFILE_BRIEF_MODE


def normalize_llm_fit_review_guidance(value: Any) -> str:
    return str(value or "").strip()


def normalize_llm_capability_naming_guidance(value: Any) -> str:
    return str(value or "").strip()


def classify_candidate_profile_section_label(label: str) -> str:
    lowered = str(label or "").strip().lower()
    # Route section headings into the three profile-context buckets.
    if not lowered:
        return KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT
    if any(token in lowered for token in ("primary", "detailed", "current", "recent", "main", "core")):
        return KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT
    if any(token in lowered for token in ("supporting", "older", "secondary", "legacy", "earlier", "previous")):
        return KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT
    if any(token in lowered for token in ("background", "optional", "extra", "additional", "note", "notes", "cert", "education")):
        return KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT
    return KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT


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

    if "supporting background" in text.lower():
        parts = re.split(r"(?im)^##\s+supporting background\s*$", text, maxsplit=1)
        primary = parts[0].strip()
        secondary = parts[1].strip() if len(parts) > 1 else ""
        return {
            KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT: primary,
            KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT: secondary,
            KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT: "",
        }

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
