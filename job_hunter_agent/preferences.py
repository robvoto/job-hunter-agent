import re
from typing import Optional

from job_hunter_agent.profile_store import get_scoring_rules, load_profile
from job_hunter_agent.role_analysis import has_government_context, text_contains_term
from job_hunter_agent.salary_utils import _salary_includes_super_or_package, _salary_max_value
from job_hunter_agent.scoring_utils import build_scoring_source_text, extract_contract_months
from job_hunter_agent.text_processing import compact_whitespace


def get_match_preferences(profile: Optional[dict] = None) -> dict:
    active_profile = profile or load_profile()
    defaults = {
        "home_location": "",
        "secondary_location": "",
        "prefer_government": False,
        "prefer_permanent": False,
        "preferred_contract_months": 12,
        "short_contract_months": 6,
    }
    preferences = active_profile.get("match_preferences", {})
    if isinstance(preferences, dict):
        defaults.update(preferences)
    return defaults


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
        if re.search(r"\b(1 day a week|one day a week|1 day per week|fortnight|2 days a month|two days a month)\b", source_text):
            return {"label": f"Secondary location has limited onsite attendance: {label_target}", "value": int(location_rules["secondary_limited_onsite"])}
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
    source_text = build_scoring_source_text(record)
    work_type = compact_whitespace(record.get("work_type") or "").lower()
    preferred_contract_months = int(preferences.get("preferred_contract_months", 12) or 12)
    short_contract_months = int(preferences.get("short_contract_months", 6) or 6)
    eng_pref = preferences.get("engagement_type", "both")

    normalized_work_type = re.sub(r"[\s_-]+", " ", work_type).strip()
    is_perm = "full time" in normalized_work_type or "permanent" in normalized_work_type
    is_contract = "contract" in normalized_work_type

    if is_perm:
        if eng_pref == "contract":
            return {"label": "Permanent role (preference is Contract)", "value": int(contract_rules["permanent_when_contract_preferred"])}
        return {"label": "Permanent role", "value": int(contract_rules["permanent_match"])}

    if not is_contract:
        return None

    if eng_pref == "permanent":
        return {"label": "Contract role (preference is Permanent)", "value": int(contract_rules["contract_when_permanent_preferred"])}

    contract_months = extract_contract_months(source_text)
    if contract_months is None:
        return None
    if contract_months >= preferred_contract_months:
        if "extension" in source_text.lower():
            return {"label": "12+ month contract with extension potential", "value": int(contract_rules["long_with_extension"])}
        return {"label": "12+ month contract", "value": int(contract_rules["long_contract"])}
    if contract_months >= short_contract_months:
        return {"label": "6-12 month contract", "value": int(contract_rules["medium_contract"])}
    return {"label": "Contract is shorter than preferred", "value": int(contract_rules["short_contract"])}


def assess_government_preference(record: dict, profile: Optional[dict] = None) -> Optional[dict]:
    active_profile = profile or load_profile()
    preferences = get_match_preferences(active_profile)
    scoring_rules = get_scoring_rules(active_profile)
    if not preferences.get("prefer_government", True):
        return None

    title = compact_whitespace(record.get("title") or "").lower()
    company = compact_whitespace(record.get("company") or "").lower()
    source_text = build_scoring_source_text(record).lower()
    combined = "\n".join([title, company, source_text])
    if has_government_context(combined) or text_contains_term(combined, "ministerial"):
        return {"label": "Government context", "value": int(scoring_rules["government"]["match_bonus"])}
    return None


def salary_fit_adjustment(record: dict, profile: Optional[dict] = None) -> int:
    salary_text = str(record.get("salary") or "").strip()
    if not salary_text or salary_text == "N/A":
        return 0
    if _salary_includes_super_or_package(salary_text):
        return 0

    active_profile = profile or load_profile()
    scoring_rules = get_scoring_rules(active_profile)
    salary_rules = scoring_rules["salary"]
    salary_preferences = active_profile.get("salary_preferences", {})
    minimum_salary_yearly = int(salary_preferences.get("minimum_salary_yearly", 0) or 0)
    minimum_daily_rate = int(salary_preferences.get("minimum_daily_rate", 0) or 0)
    parsed_value = _salary_max_value(salary_text)
    lowered = salary_text.lower()
    is_daily = bool(re.search(r"\b(per\s+day|daily\s+rate|day\s+rate|p/d|pd)\b|/day", lowered))
    is_non_comparable_period = bool(
        re.search(
            r"\b(per\s+hour|hourly|p/h|ph|per\s+week|weekly|per\s+month|monthly)\b"
            r"|/(?:hr|hour|wk|week|mo|month)",
            lowered,
        )
    )

    if is_daily:
        if minimum_daily_rate <= 0 or parsed_value <= 0:
            return 0
        if parsed_value >= minimum_daily_rate:
            return int(salary_rules["meeting_target"])
        ratio = parsed_value / minimum_daily_rate
        if ratio >= float(salary_rules["below_target_near_min_ratio"]):
            return int(salary_rules["below_target_near_adjustment"])
        if ratio >= float(salary_rules["below_target_mid_min_ratio"]):
            return int(salary_rules["below_target_mid_adjustment"])
        return int(salary_rules["below_target_far_adjustment"])

    if is_non_comparable_period:
        return 0

    if minimum_salary_yearly <= 0 or parsed_value <= 0:
        return 0
    if parsed_value >= minimum_salary_yearly:
        return int(salary_rules["meeting_target"])
    ratio = parsed_value / minimum_salary_yearly
    if ratio >= float(salary_rules["below_target_near_min_ratio"]):
        return int(salary_rules["below_target_near_adjustment"])
    if ratio >= float(salary_rules["below_target_mid_min_ratio"]):
        return int(salary_rules["below_target_mid_adjustment"])
    return int(salary_rules["below_target_far_adjustment"])
