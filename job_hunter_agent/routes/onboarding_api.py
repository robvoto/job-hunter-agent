from pathlib import Path

from fastapi import APIRouter, Body

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.profile_store import (
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_ENGAGEMENT_TYPE,
    KEY_KEYWORDS,
    KEY_LOCATIONS,
    KEY_MATCH_PREFS,
    KEY_MIN_DAILY_RATE,
    KEY_MIN_SALARY_YEARLY,
    KEY_PRIMARY_PATTERNS,
    KEY_SECONDARY_PATTERNS,
)
from job_hunter_agent.routes.responses import json_response

router = APIRouter()

REQUEST_FILES_KEY = "files"
REQUEST_SEARCH_PREFERENCES_KEY = "search_preferences"
REQUEST_ONBOARDING_SETTINGS_KEY = "onboarding_settings"
REQUEST_SEARCH_KEYWORD_KEY = "search_keyword"
REQUEST_SEARCH_LOCATIONS_KEY = "search_locations"
PROFILE_SEARCH_SETTINGS_KEY = "search_settings"
PROFILE_SALARY_PREFS_KEY = "salary_preferences"
#hardcoded
ALLOWED_IMPORT_SUFFIXES = frozenset({".docx", ".md", ".txt"})


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
            if suffix not in ALLOWED_IMPORT_SUFFIXES:
                raise ValueError("Please upload CV files as .docx, .md, or .txt.")
        materials = srv.persist_uploaded_source_pack(files) if files else srv.load_source_materials(create_if_missing=True)
        srv.patch_profile({REQUEST_ONBOARDING_SETTINGS_KEY: onboarding_settings})
        result = srv.run_onboarding(materials, search_preferences=search_prefs, onboarding_settings=onboarding_settings)
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
        engagement_type = str(body.get(KEY_ENGAGEMENT_TYPE) or "").strip().lower()
        raw_minimum_salary_yearly = body.get(KEY_MIN_SALARY_YEARLY)
        raw_minimum_daily_rate = body.get(KEY_MIN_DAILY_RATE)
        capability_rules = srv.normalize_capability_rules(body.get(KEY_CAPABILITY_PROFILE_RULES) or [])
        if not target:
            raise ValueError("Primary job title must not be empty")
        if keyword and (len(keyword) < 2 or len(keyword) > 120):
            raise ValueError("Please keep the primary search title between 2 and 120 characters.")
        if not locations:
            raise ValueError("Please add at least one search location.")
        if len(locations) > 8:
            raise ValueError("Please keep your location list to 8 places or fewer.")
        for location in locations:
            if len(location) < 2 or len(location) > 80:
                raise ValueError("Each search location must be between 2 and 80 characters.")
            if not srv._LOCATION_NAME_RE.fullmatch(location):
                raise ValueError("Search locations should look like normal city, state, or region names.")
        if engagement_type not in srv._VALID_ENGAGEMENT_TYPES:
            raise ValueError("Please choose what type of work you are open to.")
        try:
            minimum_salary_yearly = max(0, int(raw_minimum_salary_yearly or 0))
        except Exception as exc:
            raise ValueError("Minimum permanent salary must be a whole number.") from exc
        try:
            minimum_daily_rate = max(0, int(raw_minimum_daily_rate or 0))
        except Exception as exc:
            raise ValueError("Minimum contract daily rate must be a whole number.") from exc
        profile_patch: dict = {
            KEY_PRIMARY_PATTERNS: target,
            KEY_SECONDARY_PATTERNS: secondary,
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
        profile_patch[KEY_MATCH_PREFS] = match_preferences
        profile_patch[PROFILE_SALARY_PREFS_KEY] = {
            KEY_MIN_SALARY_YEARLY: minimum_salary_yearly,
            KEY_MIN_DAILY_RATE: minimum_daily_rate,
        }
        updated = srv.patch_profile(profile_patch)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"ok": True, "message": "Onboarding profile saved.", "profile": updated})
