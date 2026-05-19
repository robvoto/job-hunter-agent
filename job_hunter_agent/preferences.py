import re
from typing import Optional, Tuple

from job_hunter_agent.job_types import load_job_type
from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.profile_store import (
    DEFAULT_PROFILE,
    ENGAGEMENT_TYPE_OPTIONS,
    GovPref,
    Engagement,
    KEY_PREFER_SECTOR,
    WorkMode,
    KEY_WORK_MODE_PREFERENCE,
    VALID_WORK_MODE_PREFERENCES,
    get_scoring_rules,
    load_profile,
    normalize_engagement_type_preferences,
    normalize_match_preferences,
    normalize_work_mode_preferences,
)
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.role_analysis import has_government_context
from job_hunter_agent.salary_utils import salary_includes_super_or_package, salary_max_value
from job_hunter_agent.scoring_utils import build_scoring_source_text, extract_contract_months
from job_hunter_agent.text_processing import compact_whitespace

def passes_preference_filters(record: dict, profile: Optional[dict] = None) -> Tuple[bool, str]:
    """Hard eligibility gate: exclude only when a value is explicitly known to be incompatible.
    Unknown / unlisted values always pass through."""
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)

    # Work type — exclude only when type is unambiguously incompatible with the stated preference
    selected_engagement_types = normalize_engagement_type_preferences(preferences.get("engagement_type"))
    selected_engagement_type_set = set(selected_engagement_types)
    if selected_engagement_type_set != {Engagement.PERMANENT, Engagement.CONTRACT}:
        is_perm, is_contract = _parse_work_type_flags(str(record.get("work_type") or ""))
        if is_perm and selected_engagement_type_set == {Engagement.CONTRACT}:
            return False, "PREF_CONTRACT_TYPE"
        if not is_perm and is_contract and selected_engagement_type_set == {Engagement.PERMANENT}:
            return False, "PREF_CONTRACT_TYPE"

    work_mode_prefs = normalize_work_mode_preferences(preferences.get(KEY_WORK_MODE_PREFERENCE))
    if work_mode_prefs:
        work_mode = _normalize_work_mode(record.get("work_mode") or "")
        if work_mode and work_mode not in work_mode_prefs:
            return False, "PREF_WORK_MODE"

    # Sector — exclude only when public-sector context is explicitly detected and user wants private only.
    # Public-sector-only preference does NOT hard-filter: absence of public-sector context ≠ confirmed private.
    sector_pref = str(preferences.get(KEY_PREFER_SECTOR) or GovPref.ANY).strip().lower()
    if sector_pref == GovPref.PRIVATE:
        if has_government_context(_government_combined_text(record)):
            return False, "PREF_SECTOR_OUTSIDE_SELECTED"

    # Min contract length — exclude only when the job is a contract and the stated duration is below the minimum.
    # Unknown contract duration always passes through.
    min_months = preferences.get("min_contract_months")
    if min_months:
        _, is_contract = _parse_work_type_flags(str(record.get("work_type") or ""))
        if is_contract:
            contract_months = extract_contract_months(build_scoring_source_text(record))
            if contract_months is not None and contract_months < int(min_months):
                return False, "CONTRACT_TOO_SHORT"

    # Salary — exclude only when salary is explicitly stated, parseable, and below the minimum.
    # Missing or non-comparable salary (hourly/weekly/package) always passes through.
    comparison = _resolve_salary_comparison(record, active_profile)
    if comparison is not None:
        parsed_value, minimum_target = comparison
        if parsed_value < minimum_target:
            return False, "PREF_SALARY_BELOW_MIN"

    return True, "OK"


def assess_work_mode_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    selected_work_modes = normalize_work_mode_preferences(preferences.get(KEY_WORK_MODE_PREFERENCE))
    selected_mode_set = set(selected_work_modes)
    work_mode = _normalize_work_mode(record.get("work_mode") or "")
    scoring_rules = get_scoring_rules(active_profile)
    work_mode_rules = scoring_rules["work_mode"]
    labels = load_ui_labels().get("work_mode_score_labels", {})
    label_bonus = str(labels.get("selected_bonus") or "").strip()
    label_multiple = str(labels.get("multiple_selected_neutral") or "").strip()
    label_all = str(labels.get("all_selected_neutral") or "").strip()
    label_unknown = str(labels.get("unknown_neutral") or "").strip()
    if not label_bonus or not label_multiple or not label_all or not label_unknown:
        raise ValueError("work_mode_score_labels are required in ui_labels")
    if not selected_mode_set or selected_mode_set == VALID_WORK_MODE_PREFERENCES:
        if work_mode:
            return {"label": label_all, "value": 0}
        return {"label": label_unknown, "value": 0}
    if len(selected_mode_set) > 1:
        if work_mode:
            return {"label": label_multiple, "value": 0}
        return {"label": label_unknown, "value": 0}
    if not work_mode:
        return {"label": label_unknown, "value": 0}
    if work_mode in selected_mode_set:
        return {"label": label_bonus, "value": int(work_mode_rules["selected_mode_match"])}
    return None


def get_match_preferences(profile: Optional[dict] = None) -> dict:
    active_profile = profile or load_profile()
    defaults = dict(DEFAULT_PROFILE["match_preferences"])
    preferences = active_profile.get("match_preferences", {})
    if isinstance(preferences, dict):
        defaults.update(preferences)
    return normalize_match_preferences(defaults)


def assess_location_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    location_rules = scoring_rules["location"]
    source_text = build_scoring_source_text(record).lower()
    location = compact_whitespace(record.get("location") or "").lower()

    if not location or location == "n/a":
        return None

    def _location_variants(value: str) -> list[str]:
        cleaned = compact_whitespace(value).lower()
        if not cleaned:
            return []
        variants = [cleaned]
        no_prefix = re.sub(r"^all\s+", "", cleaned).strip()
        if no_prefix and no_prefix not in variants:
            variants.append(no_prefix)
        no_region = re.sub(r"\s+[a-z]{2,3}$", "", no_prefix).strip()
        if no_region and no_region not in variants:
            variants.append(no_region)
        return variants
    def _matches_location(preference: str) -> bool:
        return any(variant and variant in location for variant in _location_variants(preference))

    home_location = str(preferences.get("home_location") or "")
    secondary_location = str(preferences.get("secondary_location") or "")

    if home_location and _matches_location(home_location):
        label_target = compact_whitespace(home_location)
        return {"label": f"Location matches primary preference: {label_target}", "value": int(location_rules["primary_match"])}

    if secondary_location and _matches_location(secondary_location):
        label_target = compact_whitespace(secondary_location)
        work_mode = compact_whitespace(record.get("work_mode") or "").lower()
        if work_mode == "remote" or "remote position" in source_text or "fully remote" in source_text:
            return {"label": f"Location matches secondary preference with remote setup: {label_target}", "value": int(location_rules["secondary_remote"])}
        if re.search(r"\b(2 days a week|two days a week|3 days a week|three days a week|2-3 days|two to three days)\b", source_text):
            return {"label": f"Secondary location requires regular onsite attendance: {label_target}", "value": int(location_rules["secondary_regular_onsite"])}

        secondary_terms = [re.escape(value) for value in _location_variants(secondary_location) if value]
        if secondary_terms and re.search(
            rf"\b(must be based in|must reside in|onsite in)\s+(?:{'|'.join(secondary_terms)})\b",
            source_text,
        ):
            return {"label": f"Secondary location requires local onsite attendance: {label_target}", "value": int(location_rules["secondary_local_onsite"])}
        return {"label": f"Location matches secondary preference: {label_target}", "value": int(location_rules["secondary_match"])}

    return None

def assess_contract_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    contract_rules = scoring_rules["contract"]
    labels = load_ui_labels().get("work_type_score_labels", {})
    label_bonus = str(labels.get("selected_bonus") or "").strip()
    label_multiple = str(labels.get("multiple_selected_neutral") or "").strip()
    label_all = str(labels.get("all_selected_neutral") or "").strip()
    label_unknown = str(labels.get("unknown_neutral") or "").strip()
    if not label_bonus or not label_multiple or not label_all or not label_unknown:
        raise ValueError("work_type_score_labels are required in ui_labels")
    source_text = build_scoring_source_text(record)
    preferred_contract_months = int(preferences["preferred_contract_months"])
    short_contract_months = int(preferences["short_contract_months"])
    selected_engagement_types = normalize_engagement_type_preferences(preferences["engagement_type"])
    selected_engagement_type_set = set(selected_engagement_types)
    is_perm, is_contract = _parse_work_type_flags(str(record.get("work_type") or ""))

    if not is_perm and not is_contract:
        return {"label": label_unknown, "value": 0}

    if not selected_engagement_type_set or selected_engagement_type_set == {Engagement.PERMANENT, Engagement.CONTRACT}:
        return {"label": label_all, "value": 0}

    if len(selected_engagement_type_set) > 1:
        return {"label": label_multiple, "value": 0}

    if is_perm:
        if selected_engagement_type_set == {Engagement.PERMANENT}:
            return {"label": f"{label_bonus}: Permanent role", "value": int(contract_rules["permanent_match"])}
        return None

    if not is_contract:
        return None

    contract_months = extract_contract_months(source_text)
    if contract_months is None:
        return {"label": label_unknown, "value": 0}
    if contract_months >= preferred_contract_months:
        if "extension" in source_text.lower():
            return {"label": f"{label_bonus}: 12+ month contract with extension potential", "value": int(contract_rules["long_with_extension"])}
        return {"label": f"{label_bonus}: 12+ month contract", "value": int(contract_rules["long_contract"])}
    if contract_months >= short_contract_months:
        return {"label": f"{label_bonus}: 6-12 month contract", "value": int(contract_rules["medium_contract"])}
    return {"label": f"{label_bonus}: Contract is shorter than preferred", "value": int(contract_rules["short_contract"])}


def assess_sector_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    labels = load_ui_labels().get("sector_score_labels", {})
    label_bonus = str(labels.get("selected_bonus") or "").strip()
    label_multiple = str(labels.get("multiple_selected_neutral") or "").strip()
    label_all = str(labels.get("all_selected_neutral") or "").strip()
    label_unknown = str(labels.get("unknown_neutral") or "").strip()
    if not label_bonus or not label_multiple or not label_all or not label_unknown:
        raise ValueError("sector_score_labels are required in ui_labels")
    preference = str(preferences[KEY_PREFER_SECTOR] or GovPref.ANY).strip().lower()
    if preference == GovPref.ANY:
        return {"label": label_all, "value": 0}

    combined = _government_combined_text(record)
    if preference == GovPref.GOVERNMENT:
        if has_government_context(combined):
            return {"label": f"{label_bonus}: Public sector", "value": abs(int(scoring_rules["government"]["match_bonus"]))}
        return {"label": label_unknown, "value": 0}

    if preference == GovPref.PRIVATE:
        if has_government_context(combined):
            return {"label": f"{label_bonus}: Public sector", "value": -abs(int(scoring_rules["government"]["match_bonus"]))}
        return {"label": label_unknown, "value": 0}

    return None


def _canonical_job_type(work_type: str) -> str:
    normalized = compact_whitespace(work_type).lower().replace(" ", "")
    if not normalized:
        return ""
    mapping = load_job_type()
    return compact_whitespace(str(mapping.get(normalized) or "")).lower()


def _engagement_label(value: str) -> str:
    normalized = compact_whitespace(value).lower()
    for item in ENGAGEMENT_TYPE_OPTIONS:
        if str(item.get("value") or "").strip().lower() == normalized:
            return str(item.get("label") or "").strip()
    return ""


def display_work_type_label(record: dict) -> str:
    raw_work_type = compact_whitespace(record.get("work_type") or "")
    if not raw_work_type:
        return ""

    is_perm, is_contract = _parse_work_type_flags(raw_work_type)
    if is_perm and not is_contract:
        return _engagement_label(Engagement.PERMANENT)
    if is_contract and not is_perm:
        return _engagement_label(Engagement.CONTRACT)

    return ""


def _salary_period_hint(salary_text: str) -> str:
    lowered = salary_text.lower()
    daily_match = bool(re.search(r"\b(per\s+day|daily|p\.d\.|day\s+rate)\b|/day", lowered))
    annual_match = bool(re.search(r"\b(p\.a\.|per\s+annum|annually)\b|/yr\b|/year\b|base\s*\+", lowered))
    if daily_match and not annual_match:
        return "daily"
    if annual_match and not daily_match:
        return "annual"
    return ""


def _salary_has_non_comparable_period(salary_text: str) -> bool:
    lowered = salary_text.lower()
    return bool(
        re.search(
            r"\b(per\s+hour|hourly|p/h|ph|per\s+week|weekly|per\s+month|monthly)\b"
            r"|/(?:hr|hour|wk|week|mo|month)",
            lowered,
        )
    )


def _parse_work_type_flags(work_type: str) -> tuple[bool, bool]:
    """Returns (is_perm, is_contract) from a raw work_type string."""
    normalized = re.sub(r"[\s_-]+", " ", compact_whitespace(work_type).lower()).strip()
    kw = load_parsing_rules().get("engagement_keywords", {})
    is_perm = any(k in normalized for k in kw.get("permanent", ["full time", "permanent"]))
    is_contract = any(k in normalized for k in kw.get("contract", ["contract"]))
    return is_perm, is_contract


def _normalize_work_mode(value: str) -> str:
    normalized = re.sub(r"[\s_-]+", " ", compact_whitespace(value).lower()).strip()
    if normalized in {"on site", "onsite"}:
        return WorkMode.ONSITE
    if normalized == WorkMode.REMOTE:
        return WorkMode.REMOTE
    if normalized == WorkMode.HYBRID:
        return WorkMode.HYBRID
    return ""


def _government_combined_text(record: dict) -> str:
    title = compact_whitespace(record.get("title") or "").lower()
    company = compact_whitespace(record.get("company") or "").lower()
    source_text = build_scoring_source_text(record).lower()
    return "\n".join([title, company, source_text])


def _resolve_salary_comparison(record: dict, profile: Optional[dict] = None) -> Optional[tuple[int, int]]:
    """Returns (parsed_value, minimum_target) when salary is stated and comparable, else None."""
    salary_text = str(record.get("salary") or "").strip()
    if not salary_text or salary_text == "N/A":
        return None
    if salary_includes_super_or_package(salary_text):
        return None
    salary_period = _salary_period_hint(salary_text)
    if not salary_period and _salary_has_non_comparable_period(salary_text):
        return None
    work_type_canon = _canonical_job_type(str(record.get("work_type") or ""))
    if salary_period == "daily":
        target_period = "daily"
    elif salary_period == "annual":
        target_period = "annual"
    elif work_type_canon == "contract":
        target_period = "daily"
    else:
        target_period = "annual"
    active_profile = profile or load_profile()
    salary_preferences = active_profile.get("salary_preferences", {})
    minimum_salary_yearly = int(salary_preferences.get("minimum_salary_yearly", 0) or 0)
    minimum_daily_rate = int(salary_preferences.get("minimum_daily_rate", 0) or 0)
    parsed_value = salary_max_value(salary_text)
    minimum_target = minimum_daily_rate if target_period == "daily" else minimum_salary_yearly
    if minimum_target <= 0 or parsed_value <= 0:
        return None
    return parsed_value, minimum_target


def salary_fit_adjustment(record: dict, profile: Optional[dict] = None) -> int:
    comparison = _resolve_salary_comparison(record, profile)
    if comparison is None:
        return 0
    parsed_value, minimum_target = comparison
    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    salary_rules = scoring_rules["salary"]
    if parsed_value >= minimum_target:
        return int(salary_rules["meeting_target"])
    ratio = parsed_value / minimum_target
    if ratio >= float(salary_rules["below_target_near_min_ratio"]):
        return int(salary_rules["below_target_near_adjustment"])
    if ratio >= float(salary_rules["below_target_mid_min_ratio"]):
        return int(salary_rules["below_target_mid_adjustment"])
    return int(salary_rules["below_target_far_adjustment"])
