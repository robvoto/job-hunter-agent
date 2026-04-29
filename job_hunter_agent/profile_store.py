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
from typing import Any

from job_hunter_agent.paths import DATA_DIR, REPO_ROOT


ROOT_DIR = REPO_ROOT
PROFILE_PATH = DATA_DIR / "profile.json"
MIN_DATE_RANGE_DAYS = 1
MAX_DATE_RANGE_DAYS = 30
MIN_PAGES_CAP = 1
MAX_PAGES_CAP_HARD_LIMIT = 25
DEFAULT_EVIDENCE_TIERS = {
    "primary_current_evidence": "",
    "secondary_older_evidence": "",
    "background_optional_evidence": "",
}
DEFAULT_EVIDENCE_TIER_WEIGHTS = {
    "primary_current_evidence": 1.0,
    "secondary_older_evidence": 0.55,
    "background_optional_evidence": 0.25,
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
DEFAULT_LLM_PROFILE_BRIEF_MODE = "auto"

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

DEFAULT_SEARCH_SETTINGS = {
    "keywords": "",
    "locations": [],
    "classification_ids": [],
    "date_range_days": 3,
    "max_pages_cap": 10,
    "enforce_posted_age_limit": True,
    "sort_newest_first": True,
    "linkedin_hours_old": 24,
    "linkedin_results_per_search": 25,
    "linkedin_easy_apply_only": None,
}

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
    "star_evidence_text": "",
    "cv_text": "",
    "evidence_tiers": {
        **DEFAULT_EVIDENCE_TIERS,
    },
    "evidence_tier_weights": {
        **DEFAULT_EVIDENCE_TIER_WEIGHTS,
    },
    "capability_profile_rules": [],
    "cheap_keep_counter_patterns": [],
    "cheap_reject_metadata_rules": [],
    "dominant_signal_clusters": [],
    "target_title_patterns": [],
    "secondary_title_patterns": [],
    "must_not_require_skills": [],
    "reject_title_rules": [],
    "reject_description_phrase_rules": [],
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


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        resolved = int(value)
    except Exception:
        resolved = default
    return max(minimum, min(maximum, resolved))


def normalize_onboarding_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    source = settings if isinstance(settings, dict) else {}
    raw_preset = str(source.get("capability_strength_preset") or DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]).strip().lower()
    capability_strength_preset = raw_preset if raw_preset in CAPABILITY_STRENGTH_PRESETS else DEFAULT_ONBOARDING_SETTINGS["capability_strength_preset"]
    merged = _deep_merge(copy.deepcopy(DEFAULT_ONBOARDING_SETTINGS), CAPABILITY_STRENGTH_PRESETS[capability_strength_preset])
    merged = _deep_merge(
        merged,
        {
            "extraction_lookback_years": source.get("extraction_lookback_years"),
            "title_extraction_min_months": source.get("title_extraction_min_months"),
            "max_target_patterns": source.get("max_target_patterns"),
            "max_secondary_patterns": source.get("max_secondary_patterns"),
            "capability_strength_preset": capability_strength_preset,
        },
    )
    return {
        "capability_strength_preset": capability_strength_preset,
        "extraction_lookback_years": _coerce_int(
            merged.get("extraction_lookback_years"),
            DEFAULT_ONBOARDING_SETTINGS["extraction_lookback_years"],
            1,
            20,
        ),
        "title_extraction_min_months": _coerce_int(
            merged.get("title_extraction_min_months"),
            DEFAULT_ONBOARDING_SETTINGS["title_extraction_min_months"],
            1,
            24,
        ),
        "max_target_patterns": _coerce_int(
            merged.get("max_target_patterns"),
            DEFAULT_ONBOARDING_SETTINGS["max_target_patterns"],
            1,
            20,
        ),
        "max_secondary_patterns": _coerce_int(
            merged.get("max_secondary_patterns"),
            DEFAULT_ONBOARDING_SETTINGS["max_secondary_patterns"],
            1,
            20,
        ),
        "capability_recent_years": _coerce_int(
            merged.get("capability_recent_years"),
            DEFAULT_ONBOARDING_SETTINGS["capability_recent_years"],
            1,
            15,
        ),
        "capability_strong_max_years_since_use": _coerce_int(
            merged.get("capability_strong_max_years_since_use"),
            DEFAULT_ONBOARDING_SETTINGS["capability_strong_max_years_since_use"],
            1,
            20,
        ),
        "capability_strong_min_months": _coerce_int(
            merged.get("capability_strong_min_months"),
            DEFAULT_ONBOARDING_SETTINGS["capability_strong_min_months"],
            1,
            240,
        ),
        "capability_strong_min_roles": _coerce_int(
            merged.get("capability_strong_min_roles"),
            DEFAULT_ONBOARDING_SETTINGS["capability_strong_min_roles"],
            1,
            10,
        ),
        "capability_working_max_years_since_use": _coerce_int(
            merged.get("capability_working_max_years_since_use"),
            DEFAULT_ONBOARDING_SETTINGS["capability_working_max_years_since_use"],
            1,
            25,
        ),
        "capability_working_min_months": _coerce_int(
            merged.get("capability_working_min_months"),
            DEFAULT_ONBOARDING_SETTINGS["capability_working_min_months"],
            1,
            240,
        ),
        "capability_working_long_history_max_years_since_use": _coerce_int(
            merged.get("capability_working_long_history_max_years_since_use"),
            DEFAULT_ONBOARDING_SETTINGS["capability_working_long_history_max_years_since_use"],
            1,
            30,
        ),
        "capability_working_long_history_min_months": _coerce_int(
            merged.get("capability_working_long_history_min_months"),
            DEFAULT_ONBOARDING_SETTINGS["capability_working_long_history_min_months"],
            1,
            360,
        ),
        "capability_single_role_old_max_years_since_use": _coerce_int(
            merged.get("capability_single_role_old_max_years_since_use"),
            DEFAULT_ONBOARDING_SETTINGS["capability_single_role_old_max_years_since_use"],
            1,
            25,
        ),
        "capability_drop_to_basic_after_years": _coerce_int(
            merged.get("capability_drop_to_basic_after_years"),
            DEFAULT_ONBOARDING_SETTINGS["capability_drop_to_basic_after_years"],
            1,
            40,
        ),
        "capability_max_items": _coerce_int(
            merged.get("capability_max_items"),
            DEFAULT_ONBOARDING_SETTINGS["capability_max_items"],
            1,
            50,
        ),
    }


def normalize_capability_rules(rules: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    valid_levels = {"strong", "working", "basic", "low"}
    choose_capability_name = None
    derive_job_description_aliases = None

    try:
        from job_hunter_agent.capability_matrix import choose_capability_name as _choose_capability_name
        from job_hunter_agent.capability_matrix import derive_job_description_aliases as _derive_job_description_aliases

        choose_capability_name = _choose_capability_name
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
        if level not in valid_levels:
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

        if choose_capability_name and derive_job_description_aliases:
            name = choose_capability_name(name, alias_items)
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

        cleaned.append({
            "name": name,
            "level": level,
            "aliases": aliases,
        })

    return cleaned


def load_profile() -> dict[str, Any]:
    ensure_profile_exists()
    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            merged = _deep_merge(copy.deepcopy(DEFAULT_PROFILE), data)
            merged["search_settings"] = normalize_search_settings(merged.get("search_settings", {}))
            merged["salary_preferences"] = normalize_salary_preferences(merged.get("salary_preferences", {}))
            merged["preference_weights"] = normalize_preference_weights(merged.get("preference_weights", {}))
            merged["llm_profile_brief_mode"] = normalize_llm_profile_brief_mode(
                merged.get("llm_profile_brief_mode", DEFAULT_LLM_PROFILE_BRIEF_MODE)
            )
            merged["evidence_tiers"] = normalize_evidence_tiers(
                merged.get("evidence_tiers", {}),
                merged.get("cv_text", ""),
            )
            merged["evidence_tier_weights"] = normalize_evidence_tier_weights(
                merged.get("evidence_tier_weights", {})
            )
            merged["onboarding_settings"] = normalize_onboarding_settings(
                merged.get("onboarding_settings", {})
            )
            merged.pop("strengths", None)
            merged["capability_profile_rules"] = normalize_capability_rules(
                merged.get("capability_profile_rules", [])
            )
            merged["target_title_patterns"] = normalize_multiline_string_list(
                merged.get("target_title_patterns", [])
            )
            merged["secondary_title_patterns"] = normalize_multiline_string_list(
                merged.get("secondary_title_patterns", [])
            )
            merged["must_not_require_skills"] = normalize_multiline_string_list(
                merged.get("must_not_require_skills", [])
            )
            return merged
    except Exception:
        pass
    fallback = copy.deepcopy(DEFAULT_PROFILE)
    fallback["search_settings"] = normalize_search_settings(fallback.get("search_settings", {}))
    fallback["salary_preferences"] = normalize_salary_preferences(fallback.get("salary_preferences", {}))
    fallback["preference_weights"] = normalize_preference_weights(fallback.get("preference_weights", {}))
    fallback["llm_profile_brief_mode"] = normalize_llm_profile_brief_mode(
        fallback.get("llm_profile_brief_mode", DEFAULT_LLM_PROFILE_BRIEF_MODE)
    )
    fallback["evidence_tiers"] = normalize_evidence_tiers(
        fallback.get("evidence_tiers", {}),
        fallback.get("cv_text", ""),
    )
    fallback["evidence_tier_weights"] = normalize_evidence_tier_weights(
        fallback.get("evidence_tier_weights", {})
    )
    fallback["onboarding_settings"] = normalize_onboarding_settings(
        fallback.get("onboarding_settings", {})
    )
    fallback.pop("strengths", None)
    fallback["capability_profile_rules"] = normalize_capability_rules(
        fallback.get("capability_profile_rules", [])
    )
    fallback["target_title_patterns"] = normalize_multiline_string_list(
        fallback.get("target_title_patterns", [])
    )
    fallback["adjacent_title_patterns"] = normalize_multiline_string_list(
        fallback.get("adjacent_title_patterns", [])
    )
    fallback["must_not_require_skills"] = normalize_multiline_string_list(
        fallback.get("must_not_require_skills", [])
    )
    return fallback


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(profile)
    normalized["search_settings"] = normalize_search_settings(normalized.get("search_settings", {}))
    normalized["salary_preferences"] = normalize_salary_preferences(normalized.get("salary_preferences", {}))
    normalized["preference_weights"] = normalize_preference_weights(normalized.get("preference_weights", {}))
    normalized["llm_profile_brief_mode"] = normalize_llm_profile_brief_mode(
        normalized.get("llm_profile_brief_mode", DEFAULT_LLM_PROFILE_BRIEF_MODE)
    )
    normalized["evidence_tiers"] = normalize_evidence_tiers(
        normalized.get("evidence_tiers", {}),
        normalized.get("cv_text", ""),
    )
    normalized["evidence_tier_weights"] = normalize_evidence_tier_weights(
        normalized.get("evidence_tier_weights", {})
    )
    normalized["onboarding_settings"] = normalize_onboarding_settings(
        normalized.get("onboarding_settings", {})
    )
    normalized.pop("strengths", None)
    normalized["capability_profile_rules"] = normalize_capability_rules(
        normalized.get("capability_profile_rules", [])
    )
    normalized["target_title_patterns"] = normalize_multiline_string_list(
        normalized.get("target_title_patterns", [])
    )
    normalized["adjacent_title_patterns"] = normalize_multiline_string_list(
        normalized.get("adjacent_title_patterns", [])
    )
    normalized["must_not_require_skills"] = normalize_multiline_string_list(
        normalized.get("must_not_require_skills", [])
    )
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
            MIN_DATE_RANGE_DAYS,
            min(int(merged.get("date_range_days", DEFAULT_SEARCH_SETTINGS["date_range_days"])), MAX_DATE_RANGE_DAYS),
        )
    except Exception:
        merged["date_range_days"] = DEFAULT_SEARCH_SETTINGS["date_range_days"]

    try:
        merged["max_pages_cap"] = max(
            MIN_PAGES_CAP,
            min(int(merged.get("max_pages_cap", DEFAULT_SEARCH_SETTINGS["max_pages_cap"])), MAX_PAGES_CAP_HARD_LIMIT),
        )
    except Exception:
        merged["max_pages_cap"] = DEFAULT_SEARCH_SETTINGS["max_pages_cap"]

    merged["enforce_posted_age_limit"] = bool(merged.get("enforce_posted_age_limit", True))
    merged["sort_newest_first"] = bool(merged.get("sort_newest_first", True))
    merged["keywords"] = str(merged.get("keywords") or "").strip()
    merged["locations"] = [str(value).strip() for value in merged.get("locations", []) if str(value).strip()]
    merged["classification_ids"] = [
        str(value).strip() for value in merged.get("classification_ids", []) if str(value).strip()
    ]
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


def normalize_llm_profile_brief_mode(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "manual":
        return "manual"
    return DEFAULT_LLM_PROFILE_BRIEF_MODE


def classify_evidence_section_label(label: str) -> str:
    lowered = str(label or "").strip().lower()
    if not lowered:
        return "primary_current_evidence"
    if any(token in lowered for token in ("primary", "detailed", "current", "recent", "main", "core")):
        return "primary_current_evidence"
    if any(token in lowered for token in ("supporting", "older", "secondary", "legacy", "earlier", "previous")):
        return "secondary_older_evidence"
    if any(token in lowered for token in ("background", "optional", "extra", "additional", "note", "notes", "cert", "education")):
        return "background_optional_evidence"
    return "primary_current_evidence"


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


def build_evidence_tiers_from_sections(sections: list[dict[str, str]] | None) -> dict[str, str]:
    buckets = {key: [] for key in DEFAULT_EVIDENCE_TIERS}
    for section in sections or []:
        if not isinstance(section, dict):
            continue
        label = str(section.get("label") or "").strip()
        text = str(section.get("text") or "").strip()
        if not text:
            continue
        bucket = classify_evidence_section_label(label)
        buckets[bucket].append(text)
    return {
        bucket: _combine_unique_sections(parts)
        for bucket, parts in buckets.items()
    }


def infer_evidence_tiers_from_cv_text(cv_text: str) -> dict[str, str]:
    text = str(cv_text or "").strip()
    if not text:
        return dict(DEFAULT_EVIDENCE_TIERS)

    heading_matches = list(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    if heading_matches:
        sections: list[dict[str, str]] = []
        for index, match in enumerate(heading_matches):
            label = match.group(1).strip()
            start = match.end()
            end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(text)
            body = text[start:end].strip()
            if body:
                sections.append({"label": label, "text": body})
        tiers = build_evidence_tiers_from_sections(sections)
        if any(tiers.values()):
            return tiers

    if "supporting background" in text.lower():
        parts = re.split(r"(?im)^##\s+supporting background\s*$", text, maxsplit=1)
        primary = parts[0].strip()
        secondary = parts[1].strip() if len(parts) > 1 else ""
        return {
            "primary_current_evidence": primary,
            "secondary_older_evidence": secondary,
            "background_optional_evidence": "",
        }

    return {
        "primary_current_evidence": text,
        "secondary_older_evidence": "",
        "background_optional_evidence": "",
    }


def normalize_evidence_tiers(payload: dict[str, Any] | None, cv_text: str = "") -> dict[str, str]:
    normalized = dict(DEFAULT_EVIDENCE_TIERS)
    source = payload if isinstance(payload, dict) else {}
    inferred = infer_evidence_tiers_from_cv_text(cv_text)
    for key in normalized:
        value = str(source.get(key) or "").strip()
        normalized[key] = value or inferred.get(key, "")
    return normalized


def normalize_evidence_tier_weights(payload: dict[str, Any] | None) -> dict[str, float]:
    source = payload if isinstance(payload, dict) else {}
    normalized = dict(DEFAULT_EVIDENCE_TIER_WEIGHTS)
    for key, default in DEFAULT_EVIDENCE_TIER_WEIGHTS.items():
        try:
            value = float(source.get(key, default) or default)
        except Exception:
            value = default
        normalized[key] = max(min(value, 1.0), 0.0)
    return normalized


def get_evidence_tiers(profile: dict[str, Any]) -> dict[str, str]:
    return normalize_evidence_tiers(
        profile.get("evidence_tiers", {}),
        str(profile.get("cv_text") or ""),
    )


def get_evidence_tier_weights(profile: dict[str, Any]) -> dict[str, float]:
    return normalize_evidence_tier_weights(profile.get("evidence_tier_weights", {}))


def get_search_settings(profile: dict[str, Any]) -> dict[str, Any]:
    return normalize_search_settings(profile.get("search_settings", {}))


def get_preference_weights(profile: dict[str, Any]) -> dict[str, float]:
    return normalize_preference_weights(profile.get("preference_weights", {}))
