from pathlib import Path
import logging

from fastapi import APIRouter, Body

from job_hunter_agent.locations import resolve_location, find_nearest_location
from job_hunter_agent.global_settings import get_allowed_source_document_suffixes, get_allowed_source_document_suffixes_label
from job_hunter_agent import server_helpers as srv
from job_hunter_agent.source_documents import persist_uploaded_source_pack, run_onboarding, load_source_materials
from job_hunter_agent.profile_store import (
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_ENGAGEMENT_TYPE,
    KEY_KEYWORDS,
    KEY_LOCATIONS,
    KEY_MATCH_PREFS,
    KEY_MIN_DAILY_RATE,
    KEY_MIN_SALARY_YEARLY,
    KEY_ONBOARDING_COMPLETE,
    KEY_PREFER_SECTOR,
    KEY_WORK_MODE_PREFERENCE,
    KEY_ONBOARDING_SETTINGS,
    KEY_PRIMARY_PATTERNS,
    KEY_SECONDARY_PATTERNS,
    MIN_CONTRACT_MONTH_OPTIONS,
    VALID_ENGAGEMENT_TYPES,
    VALID_SECTOR_PREFERENCES,
    VALID_WORK_MODE_PREFERENCES,
    normalize_capability_rules,
    normalize_engagement_type_preferences,
    normalize_work_mode_preferences,
)
from job_hunter_agent.global_settings import get_salary_limits
from job_hunter_agent.logging_utils import format_log_block
from job_hunter_agent.routes.responses import json_response

router = APIRouter()
logger = logging.getLogger(__name__)

REQUEST_FILES_KEY = "files"
REQUEST_SEARCH_PREFERENCES_KEY = "search_preferences"
REQUEST_ONBOARDING_SETTINGS_KEY = "onboarding_settings"
REQUEST_SEARCH_KEYWORD_KEY = "search_keyword"
REQUEST_SEARCH_LOCATIONS_KEY = "search_locations"
PROFILE_SEARCH_SETTINGS_KEY = "search_settings"
PROFILE_SALARY_PREFS_KEY = "salary_preferences"


@router.post("/api/onboarding/lookup-location-by-geolocation")
def api_lookup_location_by_geolocation(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    """Find nearest location given browser geolocation coordinates."""
    try:
        latitude = float(body.get("latitude"))
        longitude = float(body.get("longitude"))
        if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
            raise ValueError("Invalid coordinates")
        nearest_location = find_nearest_location(latitude, longitude)
        return json_response({"location": nearest_location, "ok": True})
    except Exception as exc:
        return json_response({"error": str(exc), "ok": False}, 400)


@router.post("/api/onboarding/import")
def api_onboarding_import(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        files = body.get(REQUEST_FILES_KEY, [])
        search_prefs = srv._normalize_onboarding_search_preferences(body.get(REQUEST_SEARCH_PREFERENCES_KEY))
        onboarding_settings = srv._normalize_onboarding_settings_payload(body.get(REQUEST_ONBOARDING_SETTINGS_KEY))
        if not isinstance(files, list):
            raise ValueError("files must be a list")
        if not files:
            raise ValueError("Please upload your detailed CV before continuing.")
        for item in files:
            if not isinstance(item, dict):
                raise ValueError("Each uploaded file must include a filename and content.")
            filename = str(item.get("filename") or "").strip()
            if not filename:
                raise ValueError("Each uploaded file needs a filename.")
            suffix = Path(filename).suffix.lower()
            if suffix not in get_allowed_source_document_suffixes():
                raise ValueError(f"Please upload CV files as {get_allowed_source_document_suffixes_label()}.")
        srv._validate_onboarding_settings_inputs(onboarding_settings)
        materials = persist_uploaded_source_pack(files) if files else load_source_materials(create_if_missing=True)
        requested_preset = str(onboarding_settings.get("capability_strength_preset") or "").strip()
        preset_info = srv.describe_capability_strength_preset(requested_preset)
        resolved_preset = str(preset_info["capability_strength_preset"]).strip()
        logger.info(
            format_log_block(
                "ONBOARDING_IMPORT",
                {
                    "requested_preset": requested_preset or "(empty)",
                    "resolved": resolved_preset,
                    "values": preset_info["values"],
                    "files": len(files),
                },
            )
        )
        srv.patch_profile({REQUEST_ONBOARDING_SETTINGS_KEY: onboarding_settings})
        result = run_onboarding(materials, search_preferences=search_prefs, onboarding_settings=onboarding_settings)
        result["materials"] = materials
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(result)


@router.post("/api/onboarding/confirm-profile-signals")
def api_onboarding_confirm(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        target = [str(p).strip() for p in body.get(KEY_PRIMARY_PATTERNS, []) if str(p).strip()]
        secondary = [str(p).strip() for p in body.get(KEY_SECONDARY_PATTERNS, []) if str(p).strip()]
        keyword = str(body.get(REQUEST_SEARCH_KEYWORD_KEY) or "").strip()
        locations = [str(value).strip() for value in body.get(REQUEST_SEARCH_LOCATIONS_KEY, []) if str(value).strip()]
        engagement_type = normalize_engagement_type_preferences(body.get(KEY_ENGAGEMENT_TYPE), default_to_all=False)
        work_mode_preference = normalize_work_mode_preferences(body.get(KEY_WORK_MODE_PREFERENCE))
        prefer_sector = str(body.get(KEY_PREFER_SECTOR) or "").strip().lower()
        raw_min_contract_months = body.get("min_contract_months")
        raw_minimum_salary_yearly = body.get(KEY_MIN_SALARY_YEARLY)
        raw_minimum_daily_rate = body.get(KEY_MIN_DAILY_RATE)
        current_onboarding = srv.load_profile().get(KEY_ONBOARDING_SETTINGS)
        # Keep the current onboarding limits in the learning path so profile saves do not drop them.
        capability_rules = normalize_capability_rules(body.get(KEY_CAPABILITY_PROFILE_RULES) or [], current_onboarding)
        if not target:
            raise ValueError("Primary job title must not be empty")
        if keyword and (len(keyword) < 2 or len(keyword) > 120):
            raise ValueError("Please keep the primary search title between 2 and 120 characters.")
        if len(locations) != 1:
            raise ValueError("Please choose one search location.")
        location = locations[0]
        if len(location) < 2 or len(location) > 80:
            raise ValueError("Location should be between 2 and 80 characters.")
        if not srv.LOCATION_NAME_RE.fullmatch(location):
            raise ValueError("Location should look like a normal city, state, or region name.")
        locations = [resolve_location(location)["name"]]
        if not engagement_type or any(value not in VALID_ENGAGEMENT_TYPES for value in engagement_type):
            raise ValueError("Please choose what type of work you are open to.")
        if any(value not in VALID_WORK_MODE_PREFERENCES for value in work_mode_preference):
            raise ValueError("Please choose only remote, hybrid, or on-site.")
        if prefer_sector not in VALID_SECTOR_PREFERENCES:
            prefer_sector = srv.GovPref.ANY
        min_contract_months = None
        if raw_min_contract_months not in (None, ""):
            try:
                min_contract_months = int(str(raw_min_contract_months).strip())
            except Exception as exc:
                raise ValueError("Minimum contract length must be a whole number.") from exc
            if min_contract_months not in {int(item["value"]) for item in MIN_CONTRACT_MONTH_OPTIONS}:
                raise ValueError("Please choose a valid minimum contract length.")
        if "contract" not in engagement_type:
            min_contract_months = None
        try:
            minimum_salary_yearly = int(str(raw_minimum_salary_yearly).replace(",", "").strip() or 0)
        except Exception as exc:
            raise ValueError("Minimum permanent salary must be a whole number.") from exc
        if minimum_salary_yearly < 0:
            raise ValueError("Minimum permanent salary cannot be negative.")
        try:
            minimum_daily_rate = int(str(raw_minimum_daily_rate).replace(",", "").strip() or 0)
        except Exception as exc:
            raise ValueError("Minimum contract daily rate must be a whole number.") from exc
        if minimum_daily_rate < 0:
            raise ValueError("Minimum contract daily rate cannot be negative.")
        salary_limits = get_salary_limits()
        yearly_cap = int(salary_limits.get(KEY_MIN_SALARY_YEARLY, {}).get("max", minimum_salary_yearly))
        daily_cap = int(salary_limits.get(KEY_MIN_DAILY_RATE, {}).get("max", minimum_daily_rate))
        if minimum_salary_yearly > yearly_cap:
            raise ValueError(f"Minimum permanent salary cannot exceed {yearly_cap:,}.")
        if minimum_daily_rate > daily_cap:
            raise ValueError(f"Minimum contract daily rate cannot exceed {daily_cap:,}.")
        profile_patch: dict = {
            KEY_PRIMARY_PATTERNS: target,
            KEY_SECONDARY_PATTERNS: secondary,
            KEY_ONBOARDING_COMPLETE: True,
        }
        if capability_rules:
            profile_patch[KEY_CAPABILITY_PROFILE_RULES] = capability_rules
        current = srv.load_profile()
        search_settings = dict(current.get(PROFILE_SEARCH_SETTINGS_KEY, {}))
        if keyword:
            search_settings[KEY_KEYWORDS] = keyword
        elif not str(search_settings.get(KEY_KEYWORDS) or "").strip():
            search_settings[KEY_KEYWORDS] = target[0]
        search_settings[KEY_LOCATIONS] = locations
        profile_patch[PROFILE_SEARCH_SETTINGS_KEY] = search_settings
        match_preferences = dict(current.get(KEY_MATCH_PREFS, {}))
        match_preferences[KEY_ENGAGEMENT_TYPE] = engagement_type
        match_preferences["min_contract_months"] = min_contract_months
        match_preferences[KEY_WORK_MODE_PREFERENCE] = work_mode_preference
        match_preferences[KEY_PREFER_SECTOR] = prefer_sector
        profile_patch[KEY_MATCH_PREFS] = match_preferences
        profile_patch[PROFILE_SALARY_PREFS_KEY] = {
            KEY_MIN_SALARY_YEARLY: minimum_salary_yearly,
            KEY_MIN_DAILY_RATE: minimum_daily_rate,
        }
        updated = srv.patch_profile(profile_patch)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"ok": True, "message": "Onboarding profile saved.", "profile": updated})

