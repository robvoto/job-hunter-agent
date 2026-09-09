"""Helpers for preferences."""

import logging
import re
from typing import Optional, Tuple

from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.job_types import load_job_type
from job_hunter_agent.paths import UNCERTAINTY_LOG_PATH
from job_hunter_agent.profile_store import (
    DEFAULT_PROFILE,
    ENGAGEMENT_TYPE_OPTIONS,
    KEY_WORK_MODE_PREFERENCE,
    VALID_ENGAGEMENT_TYPES,
    Engagement,
    WorkMode,
    get_scoring_rules,
    load_profile,
    normalize_engagement_type_preferences,
    normalize_match_preferences,
    normalize_work_mode_preferences,
)
from job_hunter_agent.runtime_helpers import append_uncertainty_log, build_uncertainty_entry
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)
from job_hunter_agent.salary_utils import (
    salary_is_total_package,
    salary_max_value,
    salary_period_classification,
)
from job_hunter_agent.scoring_utils import build_scoring_source_text, extract_contract_months
from job_hunter_agent.text_processing import compact_whitespace

logger = logging.getLogger(__name__)


def passes_preference_filters(record: dict, profile: Optional[dict] = None) -> Tuple[bool, str]:
    """Hard eligibility gate: exclude only when a value is explicitly known to be incompatible.

    Unknown / unlisted values always pass through."""

    active_profile = profile or load_profile()

    preferences = get_match_preferences(active_profile)

    # Work type — exclude only when type is unambiguously incompatible with the stated preference

    selected_engagement_types = normalize_engagement_type_preferences(
        preferences.get("engagement_type")
    )

    selected_engagement_type_set = set(selected_engagement_types)

    raw_work_type = str(record.get("work_type") or "")

    is_perm, is_contract = _parse_work_type_flags(raw_work_type)

    is_full_time_contract = _is_full_time_contract(raw_work_type)

    if not is_perm and not is_contract:
        work_type = str(record.get("work_type") or "").strip()

        entry = build_uncertainty_entry(
            reason_code="WORK_TYPE_UNCLEAR",
            stage="preference_filter",
            field="work_type",
            raw_value=work_type or "<empty>",
            normalized_value="unknown",
            detail="Unable to determine whether the job is contract or permanent from work_type.",
            source="passes_preference_filters",
            job_key=str(record.get("job_key") or ""),
        )

        append_uncertainty_log(UNCERTAINTY_LOG_PATH, entry)
        record_system_warning(
            severity="warning",
            category="preference_uncertainty",
            source="passes_preference_filters",
            message=str(entry.get("detail") or "Preference could not be resolved."),
            fingerprint=make_system_warning_fingerprint(
                "preference_filter",
                "WORK_TYPE_UNCLEAR",
                str(record.get("job_key") or ""),
                str(record.get("work_type") or ""),
            ),
            job_key=str(record.get("job_key") or ""),
            context=entry,
        )

        logger.info(
            "[PREFERENCE][WORK_TYPE_UNKNOWN] job_key=%s — no hard rejection; continuing by design (detail in %s)",
            entry.get("job_key", "<unknown>"),
            UNCERTAINTY_LOG_PATH,
        )

    if selected_engagement_type_set != VALID_ENGAGEMENT_TYPES:
        if is_perm and Engagement.PERMANENT not in selected_engagement_type_set:
            return False, "PREF_CONTRACT_TYPE"

        if (
            is_full_time_contract
            and Engagement.FULL_TIME_CONTRACT not in selected_engagement_type_set
        ):
            return False, "PREF_CONTRACT_TYPE"

        if (
            is_contract
            and not is_full_time_contract
            and Engagement.CONTRACT not in selected_engagement_type_set
        ):
            return False, "PREF_CONTRACT_TYPE"

    work_mode_prefs = normalize_work_mode_preferences(preferences.get(KEY_WORK_MODE_PREFERENCE))

    if work_mode_prefs:
        work_mode = _normalize_work_mode(record.get("work_mode") or "")

        if not work_mode:
            entry = build_uncertainty_entry(
                reason_code="WORK_MODE_UNCLEAR",
                stage="preference_filter",
                field="work_mode",
                raw_value=str(record.get("work_mode") or "<empty>"),
                normalized_value="unknown",
                detail="Could not determine work mode from job ad — letting through.",
                source="passes_preference_filters",
                job_key=str(record.get("job_key") or ""),
            )

            append_uncertainty_log(UNCERTAINTY_LOG_PATH, entry)
            record_system_warning(
                severity="warning",
                category="preference_uncertainty",
                source="passes_preference_filters",
                message=str(entry.get("detail") or "Preference could not be resolved."),
                fingerprint=make_system_warning_fingerprint(
                    "preference_filter",
                    "WORK_MODE_UNCLEAR",
                    str(record.get("job_key") or ""),
                    str(record.get("work_mode") or ""),
                ),
                job_key=str(record.get("job_key") or ""),
                context=entry,
            )

            logger.info(
                "[PREFERENCE][WORK_MODE_UNKNOWN] job_key=%s — no hard rejection; continuing by design (detail in %s)",
                entry.get("job_key", "<unknown>"),
                UNCERTAINTY_LOG_PATH,
            )

        elif work_mode not in work_mode_prefs:
            return False, "PREF_WORK_MODE"

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


def get_match_preferences(profile: Optional[dict] = None) -> dict:

    active_profile = profile or load_profile()

    defaults = dict(DEFAULT_PROFILE["match_preferences"])

    preferences = active_profile.get("match_preferences", {})

    if isinstance(preferences, dict):
        defaults.update(preferences)

    return normalize_match_preferences(defaults)


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

    normalized = re.sub(r"[\s_-]+", " ", raw_work_type.lower()).strip()

    if normalized in {
        "ftc",
        "full time contract",
        "fulltime contract",
        "full time/contract",
        "full-time contract",
    }:
        return "FTC"

    is_perm, is_contract = _parse_work_type_flags(raw_work_type)

    if is_perm and not is_contract:
        return _engagement_label(Engagement.PERMANENT)

    if is_contract and not is_perm:
        return _engagement_label(Engagement.CONTRACT)

    return ""


def display_contract_duration_label(record: dict) -> str:
    raw_work_type = compact_whitespace(record.get("work_type") or "")

    if not raw_work_type:
        return ""

    _, is_contract = _parse_work_type_flags(raw_work_type)

    if not is_contract:
        return ""

    contract_months = extract_contract_months(build_scoring_source_text(record))

    if contract_months is None or contract_months <= 0:
        return ""

    unit = "month" if contract_months == 1 else "months"
    return f"{contract_months} {unit}"


def _is_full_time_contract(work_type: str) -> bool:

    normalized = re.sub(r"[\s_-]+", " ", compact_whitespace(work_type).lower()).strip()

    return normalized in {
        "ftc",
        "full time contract",
        "fulltime contract",
        "full time/contract",
        "full-time contract",
    }


def _parse_work_type_flags(work_type: str) -> tuple[bool, bool]:
    """Returns (is_perm, is_contract) from a raw work_type string."""

    normalized = re.sub(r"[\s_-]+", " ", compact_whitespace(work_type).lower()).strip()

    if _is_full_time_contract(work_type):
        return False, True

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


def _resolve_salary_comparison(
    record: dict, profile: Optional[dict] = None
) -> Optional[tuple[int, int]]:
    """Returns (parsed_value, minimum_target) when salary is stated and comparable, else None."""

    salary_text = str(record.get("salary") or "").strip()

    if not salary_text or salary_text == "N/A":
        return None

    # Total-package / inclusive-super figures are not the same basis as the
    # user's base-salary floor. A clear "+ super" amount is different: the
    # advertised number is the base salary and remains comparable.
    if salary_is_total_package(salary_text):
        return None

    salary_period, _period_confidence = salary_period_classification(salary_text)
    if not salary_period:
        return None

    if salary_period == "daily":
        target_period = "daily"
    elif salary_period == "annual":
        target_period = "annual"
    else:
        return None

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
