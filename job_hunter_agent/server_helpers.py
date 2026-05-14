import json
import hashlib
import re
import shutil
import threading
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

load_dotenv()

from job_hunter_agent.config import SERVER_HOST as HOST, SERVER_PORT as PORT, DEBUG_MODE, ALLOWED_DOC_REL_PATHS
from job_hunter_agent.agent_settings import (
    DEFAULT_AGENT_SETTINGS, 
    load_agent_state, 
    KEY_DASHBOARD,
    KEY_EMAIL,
    KEY_TELEGRAM,
    KEY_SCHEDULE,
    KEY_LLM,
)
from job_hunter_agent.llm_gate import llm_suggest_rejection_blockers
from job_hunter_agent.notifiers.telegram_notifier import build_telegram_connect_link, send_telegram_notification, sync_telegram_subscribers
from job_hunter_agent.paths import (
    DATA_DIR,
    REPO_ROOT as ROOT_DIR,
    SETTINGS_HTML_PATH,
    SHOWCASE_PATH,
    STATIC_DIR,
    WORKSPACE_HTML_PATH,
    ONBOARDING_HTML_PATH,
    get_audit_records_path,
    get_dashboard_path,
    get_job_history_path,
    get_review_data_path,
    get_run_stats_path,
    get_source_pack_dir,
)
from job_hunter_agent.profile_store import (
    DEFAULT_ONBOARDING_SETTINGS,
    DEFAULT_PROFILE,
    LLM_PROFILE_BRIEF_MODE_AUTO,
    LLM_PROFILE_BRIEF_MODE_MANUAL,
    ENGAGEMENT_TYPE_BOTH,
    ENGAGEMENT_TYPE_CONTRACT,
    ENGAGEMENT_TYPE_PERMANENT,
    build_candidate_profile_tiers_from_sections,
    load_profile, 
    normalize_onboarding_settings,
    normalize_search_settings, 
    save_profile,
    KEY_KEYWORDS,
    KEY_LOCATIONS,
    KEY_ENGAGEMENT_TYPE,
    KEY_PREFER_GOVERNMENT,
    KEY_MIN_SALARY_YEARLY,
    KEY_MIN_DAILY_RATE,
    KEY_LOOKBACK_YEARS,
    KEY_MIN_MONTHS,
    KEY_MAX_TARGET,
    KEY_MAX_SECONDARY,
    KEY_BRIEF_MODE,
    KEY_BRIEF,
    KEY_STAR_EVIDENCE,
    KEY_FIT_GUIDANCE,
    KEY_CAP_GUIDANCE,
    KEY_CV_TEXT,
    KEY_EVIDENCE_TIERS,
    KEY_CAPABILITY_PROFILE_RULES,
    KEY_ONBOARDING_SETTINGS,
    MATCHING_RULE_PROFILE_KEYS,
    patch_profile,
)
from job_hunter_agent.locations import default_location_value, resolve_location
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.review_insights import apply_capability_tuning_decisions, build_suggested_tuning_from_saved_review
from job_hunter_agent.server_review import (
    append_review_key,
    build_description_block_followups,
    build_title_block_followups,
    get_job_description,
    load_job_history,
    persist_review_event,
    rebuild_dashboard_after_rule_change,
    record_job_view,
    remove_review_key,
    save_block_similar_feedback,
    save_description_block_feedback,
    save_job_history,
    save_not_for_me_feedback,
    save_requirement_blockers_feedback,
)
from job_hunter_agent.source_connector import rebuild_html_dashboard, scrape_jobs_direct
from job_hunter_agent.source_documents import (
    DEFAULT_SOURCE_MATERIALS,
    build_llm_profile_brief,
    load_source_materials,
    persist_uploaded_source_pack,
    run_onboarding,
    save_source_materials,
)
from job_hunter_agent.advance_settings import (
    KEY_DATE_RANGE_DAYS,
    KEY_LLM_SETTINGS,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_MODEL_OPTIONS,
    KEY_SEEK_MAX_PAGES,
    load_advance_settings,
    save_advance_settings,
)
_STATIC_MIME_OVERRIDES = {
    ".css": "text/css",
    ".js": "text/javascript",
    ".png": "image/png",
}
_run_in_progress = False
_run_state_lock = threading.Lock()
_rejection_suggestions_cache: dict[str, dict[str, Any]] = {}


def get_docs() -> list[dict[str, str]]:
    """Return allowed markdown docs under the repo root (for /docs API)."""
    docs: list[dict[str, str]] = []
    root = ROOT_DIR.resolve()
    for rel_path in ALLOWED_DOC_REL_PATHS:
        file_path = (root / rel_path).resolve()
        if root not in file_path.parents and file_path != root:
            continue
        if file_path.is_file():
            docs.append({"name": rel_path, "content": file_path.read_text(encoding="utf-8")})
    return docs


def _set_run_in_progress(value: bool) -> None:
    global _run_in_progress
    with _run_state_lock:
        _run_in_progress = bool(value)


def _is_run_in_progress() -> bool:
    with _run_state_lock:
        return _run_in_progress


def _try_mark_run_started() -> bool:
    global _run_in_progress
    with _run_state_lock:
        if _run_in_progress:
            return False
        _run_in_progress = True
        return True


def _normalize_suggestion_phrase(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _render_template(path: Path) -> str:
    return (
        path.read_text(encoding="utf-8", errors="ignore")
        .replace("__JOB_HUNTER_DEBUG_MODE_VALUE__", "true" if DEBUG_MODE else "false")
        .replace("__JOB_HUNTER_ONBOARDING_DEFAULTS_JSON__", json.dumps(DEFAULT_ONBOARDING_SETTINGS, ensure_ascii=True))
    )


def _parse_locations_override(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[\r\n,]+", text) if part.strip()]


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() == "true"


_VALID_ENGAGEMENT_TYPES = frozenset(
    {ENGAGEMENT_TYPE_BOTH, ENGAGEMENT_TYPE_PERMANENT, ENGAGEMENT_TYPE_CONTRACT}
)
_LOCATION_NAME_RE = re.compile(r"^[A-Za-z\s,'()-]+$")


def _normalize_onboarding_search_preferences(payload: dict | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    engagement_type = str(source.get(KEY_ENGAGEMENT_TYPE) or "").strip().lower()
    prefer_government = _parse_bool(source.get(KEY_PREFER_GOVERNMENT))
    keywords = str(source.get(KEY_KEYWORDS) or "").strip()
    locations = _parse_locations_override(source.get(KEY_LOCATIONS))
    normalized = {
        KEY_KEYWORDS: keywords,
        KEY_LOCATIONS: locations[:1] or [default_location_value()],
        KEY_ENGAGEMENT_TYPE: engagement_type,
        KEY_PREFER_GOVERNMENT: prefer_government,
    }
    if KEY_MIN_SALARY_YEARLY in source:
        normalized[KEY_MIN_SALARY_YEARLY] = source.get(KEY_MIN_SALARY_YEARLY)
    if KEY_MIN_DAILY_RATE in source:
        normalized[KEY_MIN_DAILY_RATE] = source.get(KEY_MIN_DAILY_RATE)
    return normalized


def _validate_required_onboarding_inputs(
    search_preferences: dict[str, Any],
    onboarding_settings_payload: dict | None,
) -> None:
    keywords = str(search_preferences.get(KEY_KEYWORDS) or "").strip()
    locations = _parse_locations_override(search_preferences.get(KEY_LOCATIONS))
    engagement_type = str(search_preferences.get(KEY_ENGAGEMENT_TYPE) or "").strip().lower()

    if keywords and (len(keywords) < 2 or len(keywords) > 120):
        raise ValueError("Please keep the primary search title between 2 and 120 characters.")
    if len(locations) != 1:
        raise ValueError("Please choose one search location.")
    location = locations[0]
    if len(location) < 2 or len(location) > 80:
        raise ValueError("Location should be between 2 and 80 characters.")
    if not _LOCATION_NAME_RE.match(location):
        raise ValueError("Location should look like a normal city, state, or region name.")
    resolve_location(location)
    if engagement_type not in _VALID_ENGAGEMENT_TYPES:
        raise ValueError("Please choose what type of work you are open to.")

    raw_yearly = search_preferences.get(KEY_MIN_SALARY_YEARLY)
    if raw_yearly not in (None, ""):
        try:
            yearly = int(raw_yearly)
        except Exception as exc:
            raise ValueError("Minimum permanent salary must be a whole number.") from exc
        if yearly < 0:
            raise ValueError("Minimum permanent salary cannot be negative.")

    raw_daily = search_preferences.get(KEY_MIN_DAILY_RATE)
    if raw_daily not in (None, ""):
        try:
            daily = int(raw_daily)
        except Exception as exc:
            raise ValueError("Minimum contract daily rate must be a whole number.") from exc
        if daily < 0:
            raise ValueError("Minimum contract daily rate cannot be negative.")

    raw_settings = onboarding_settings_payload if isinstance(onboarding_settings_payload, dict) else {}
    if isinstance(raw_settings.get(KEY_ONBOARDING_SETTINGS), dict):
        raw_settings = raw_settings.get(KEY_ONBOARDING_SETTINGS) or {}

    raw_lookback = raw_settings.get(KEY_LOOKBACK_YEARS)
    raw_min_months = raw_settings.get(KEY_MIN_MONTHS)
    if raw_lookback in (None, ""):
        raise ValueError("Please choose how far back we should look.")
    if raw_min_months in (None, ""):
        raise ValueError("Please choose when a role is too short to count as a main signal.")

    try:
        lookback = int(raw_lookback)
    except Exception as exc:
        raise ValueError("Lookback must be a whole number of years.") from exc
    try:
        min_months = int(raw_min_months)
    except Exception as exc:
        raise ValueError("Short-role threshold must be a whole number of months.") from exc

    if lookback < 1 or lookback > 20:
        raise ValueError("Please enter a lookback between 1 and 20 years.")
    if min_months < 1 or min_months > 24:
        raise ValueError("Please enter a short-role threshold between 1 and 24 months.")


def _read_last_run_timestamp() -> str | None:
    try:
        run_stats_path = get_run_stats_path()
        if run_stats_path.exists():
            payload = json.loads(run_stats_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                timestamp = str(
                    payload.get("last_run_attempt_at")
                    or payload.get("run_finished_at")
                    or payload.get("run_started_at")
                    or ""
                ).strip()
                if timestamp:
                    return timestamp
        state = load_agent_state()
        return str(state.get("last_agent_run_at") or "").strip() or None
    except Exception:
        return None


def _normalize_search_settings_payload(payload: dict | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    if isinstance(source.get("search_settings"), dict):
        source = source.get("search_settings") or {}

    overrides: dict[str, Any] = {}
    if KEY_KEYWORDS in source:
        overrides[KEY_KEYWORDS] = str(source.get(KEY_KEYWORDS) or "").strip()
    if KEY_LOCATIONS in source:
        overrides[KEY_LOCATIONS] = _parse_locations_override(source.get(KEY_LOCATIONS))
    if KEY_DATE_RANGE_DAYS in source:
        overrides[KEY_DATE_RANGE_DAYS] = source.get(KEY_DATE_RANGE_DAYS)
    if KEY_SEEK_MAX_PAGES in source:
        overrides[KEY_SEEK_MAX_PAGES] = source.get(KEY_SEEK_MAX_PAGES)
    if KEY_LINKEDIN_HOURS_OLD in source:
        overrides[KEY_LINKEDIN_HOURS_OLD] = source.get(KEY_LINKEDIN_HOURS_OLD)
    if KEY_LINKEDIN_RESULTS_PER_SEARCH in source:
        overrides[KEY_LINKEDIN_RESULTS_PER_SEARCH] = source.get(KEY_LINKEDIN_RESULTS_PER_SEARCH)

    if not overrides:
        return {}

    current_search_settings = normalize_search_settings(load_profile().get("search_settings", {}))
    current_search_settings.update(overrides)
    return normalize_search_settings(current_search_settings)


def _normalize_onboarding_settings_payload(payload: dict | None) -> dict[str, int]:
    allowed_keys = (
            KEY_LOOKBACK_YEARS,
            KEY_MIN_MONTHS,
            KEY_MAX_TARGET,
            KEY_MAX_SECONDARY,
    )
    source = payload if isinstance(payload, dict) else {}
    if isinstance(source.get(KEY_ONBOARDING_SETTINGS), dict):
        source = source.get(KEY_ONBOARDING_SETTINGS) or {}

    if not source:
        current = load_profile().get(KEY_ONBOARDING_SETTINGS)
        if isinstance(current, dict) and current:
            source = current
        else:
            source = dict(DEFAULT_ONBOARDING_SETTINGS)

    normalized = normalize_onboarding_settings(source)
    return {key: int(normalized[key]) for key in allowed_keys if key in normalized}


def _onboarding_complete(profile: dict[str, Any] | None = None) -> bool:
    current = profile if isinstance(profile, dict) else load_profile()
    target_titles = [str(value).strip() for value in current.get("primary_job_title_pattern", []) if str(value).strip()]
    search_settings = normalize_search_settings(current.get("search_settings", {}))
    locations = [str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()]
    keywords = str(search_settings.get("keywords") or "").strip()
    return bool(target_titles and locations[:1] and keywords)


def _run_scrape_job() -> None:
    try:
        scrape_jobs_direct()
    except Exception as exc:
        print(f"[RUN][ERROR] {type(exc).__name__}: {exc}")
    finally:
        _set_run_in_progress(False)


def _rebuild_dashboard_on_startup() -> None:
    if not get_dashboard_path().exists() and not get_run_stats_path().exists() and not get_audit_records_path().exists():
        return
    try:
        rebuild_html_dashboard(reason="server startup rebuild")
    except Exception as exc:
        print(f"[DASHBOARD][WARN] Could not rebuild on startup: {type(exc).__name__}: {exc}")


class SettingsHandler:
    @staticmethod
    def _patch_affects_matching_rules(patch: dict) -> bool:
        return any(key in (patch or {}) for key in MATCHING_RULE_PROFILE_KEYS)

    @staticmethod
    def _normalize_profile_patch_for_save(current: dict, patch: dict) -> dict:
        normalized = dict(patch or {})
        current = current or load_profile()
        brief_mode = str(
            normalized.get(KEY_BRIEF_MODE, current.get(KEY_BRIEF_MODE, LLM_PROFILE_BRIEF_MODE_AUTO))
            or LLM_PROFILE_BRIEF_MODE_AUTO
        ).strip().lower()
        if brief_mode != LLM_PROFILE_BRIEF_MODE_MANUAL:
            brief_mode = LLM_PROFILE_BRIEF_MODE_AUTO
        normalized[KEY_BRIEF_MODE] = brief_mode

        if brief_mode == LLM_PROFILE_BRIEF_MODE_MANUAL:
            normalized[KEY_BRIEF] = str(normalized.get(KEY_BRIEF) or "").strip()
        else:
            auto_brief = build_llm_profile_brief(
                capability_rules=normalized.get(
                    KEY_CAPABILITY_PROFILE_RULES,
                    current.get(KEY_CAPABILITY_PROFILE_RULES, []),
                ),
            )
            normalized[KEY_BRIEF] = auto_brief

        if KEY_STAR_EVIDENCE in normalized:
            normalized[KEY_STAR_EVIDENCE] = str(normalized.get(KEY_STAR_EVIDENCE) or "").strip()
        if KEY_FIT_GUIDANCE in normalized:
            normalized[KEY_FIT_GUIDANCE] = str(normalized.get(KEY_FIT_GUIDANCE) or "").strip()
        if KEY_CAP_GUIDANCE in normalized:
            normalized[KEY_CAP_GUIDANCE] = str(normalized.get(KEY_CAP_GUIDANCE) or "").strip()
        if KEY_CV_TEXT in normalized:
            new_cv = str(normalized.get(KEY_CV_TEXT) or "").strip()
            current_cv = str(current.get(KEY_CV_TEXT) or "").strip()
            cv_changed = new_cv != current_cv
            if cv_changed and KEY_EVIDENCE_TIERS not in normalized:
                inferred_tiers = build_candidate_profile_tiers_from_sections([{
                    "label": "Primary CV",
                    "text": new_cv,
                }])
                if any(inferred_tiers.values()):
                    normalized[KEY_EVIDENCE_TIERS] = inferred_tiers
        return normalized

    @staticmethod
    def _write_json_file(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def _reset_current_user_state(cls) -> dict[str, Any]:
        save_profile(DEFAULT_PROFILE)
        save_source_materials(DEFAULT_SOURCE_MATERIALS)

        source_pack_dir = get_source_pack_dir()
        if source_pack_dir.exists():
            shutil.rmtree(source_pack_dir)

        cls._write_json_file(get_job_history_path(), {})
        cls._write_json_file(get_review_data_path(), {})
        cls._write_json_file(get_run_stats_path(), {})
        cls._write_json_file(get_audit_records_path(), [])

        try:
            get_dashboard_path().unlink(missing_ok=True)
        except Exception:
            pass

        return {
            "ok": True,
            "message": "Current user state reset. Shared learning was preserved.",
            "redirect_to": "/start",
        }

    @staticmethod
    def _reset_global_learning() -> dict[str, Any]:
        from job_hunter_agent.signal_registry import clear_signal_learning_state

        clear_signal_learning_state()
        return {
            "ok": True,
            "message": "Global learning reset. Shared learned signals were cleared.",
        }

    @staticmethod
    def _sanitize_agent_settings_payload(payload: dict) -> dict:
        dashboard = payload.get(KEY_DASHBOARD, {}) if isinstance(payload, dict) else {}
        telegram = payload.get(KEY_TELEGRAM, {}) if isinstance(payload, dict) else {}
        llm = payload.get(KEY_LLM, {}) if isinstance(payload, dict) else {}
        schedule_payload = payload.get(KEY_SCHEDULE) if isinstance(payload, dict) else None
        sanitized = {
            KEY_DASHBOARD: {
                "minimum_score": max(0, min(int(dashboard.get("minimum_score", 55) or 55), 100)),
            },
            KEY_TELEGRAM: {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token": str(telegram.get("bot_token") or "").strip(),
                "bot_username": str(telegram.get("bot_username") or "").strip().lstrip("@"),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
            },
        }
        model = str(llm.get("model") or "").strip()
        if "model" in llm or model:
            allowed_models = [
                str(value).strip()
                for value in (
                    load_advance_settings()
                    .get(KEY_LLM_SETTINGS, {})
                    .get(KEY_MODEL_OPTIONS, [])
                )
                if str(value).strip()
            ]
            if not allowed_models:
                raise ValueError("No LLM models are configured in Admin.")
            if not model:
                raise ValueError("Please choose an LLM model.")
            if model not in allowed_models:
                raise ValueError("Please choose a model configured in Admin.")
            sanitized[KEY_LLM] = {
                "model": model,
            }
        if isinstance(schedule_payload, dict):
            daily_time_local = str(
                schedule_payload.get("daily_time_local")
                or DEFAULT_AGENT_SETTINGS[KEY_SCHEDULE]["daily_time_local"]
            ).strip()
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_time_local):
                raise ValueError("Schedule time must be in HH:MM 24-hour format.")
            try:
                loop_sleep_seconds = int(
                    schedule_payload.get(
                        "loop_sleep_seconds",
                        DEFAULT_AGENT_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"],
                    )
                    or DEFAULT_AGENT_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"]
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("Schedule polling interval must be a whole number of seconds.") from exc
            sanitized[KEY_SCHEDULE] = {
                "daily_time_local": daily_time_local,
                "loop_sleep_seconds": max(60, loop_sleep_seconds),
            }
        return sanitized

    @staticmethod
    def _public_agent_settings_payload(settings: dict) -> dict:
        dashboard = settings.get(KEY_DASHBOARD, {}) if isinstance(settings, dict) else {}
        telegram = settings.get(KEY_TELEGRAM, {}) if isinstance(settings, dict) else {}
        llm_settings = settings.get(KEY_LLM, {}) if isinstance(settings, dict) else {}
        schedule = settings.get(KEY_SCHEDULE, {}) if isinstance(settings, dict) else {}
        subscribers = telegram.get("subscribers", []) if isinstance(telegram, dict) else []
        return {
            KEY_DASHBOARD: {
                "minimum_score": max(0, min(int(dashboard.get("minimum_score", DEFAULT_AGENT_SETTINGS[KEY_DASHBOARD]["minimum_score"]) or DEFAULT_AGENT_SETTINGS[KEY_DASHBOARD]["minimum_score"]), 100)),
            },
            KEY_SCHEDULE: {
                "daily_time_local": str(schedule.get("daily_time_local") or DEFAULT_AGENT_SETTINGS[KEY_SCHEDULE]["daily_time_local"]).strip(),
                "loop_sleep_seconds": max(60, int(schedule.get("loop_sleep_seconds", DEFAULT_AGENT_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"]) or DEFAULT_AGENT_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"])),
            },
            KEY_TELEGRAM: {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token_present": bool(str(telegram.get("bot_token") or "").strip()),
                "bot_username": str(telegram.get("bot_username") or "").strip(),
                "chat_id_present": bool(str(telegram.get("chat_id") or "").strip()),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
                "subscriber_count": len(subscribers),
                "subscribers": subscribers,
            },
            KEY_LLM: { # Use llm_settings here to avoid shadowing the imported KEY_LLM
                "model": str(llm_settings.get("model") or "").strip(),
            },
        }

    @staticmethod
    def _issue_rejection_suggestion_approval_tokens(job_id: str, suggestions: list[str]) -> dict[str, str]:
        normalized_job_id = normalize_job_key(job_id) or str(job_id or "").strip()
        tokens: dict[str, str] = {}
        for suggestion in suggestions:
            phrase = _normalize_suggestion_phrase(suggestion)
            if not phrase:
                continue
            token = hashlib.sha1(f"{normalized_job_id}|{phrase}".encode("utf-8")).hexdigest()[:16]
            tokens[phrase] = token
        return tokens

    @staticmethod
    def _validate_llm_suggestion_approvals(
        job_id: str,
        blockers: list[str],
        approved_suggestion_tokens: dict[str, str] | None = None,
    ) -> None:
        normalized_job_id = normalize_job_key(job_id) or str(job_id or "").strip()
        cached = _rejection_suggestions_cache.get(normalized_job_id)
        if not isinstance(cached, dict):
            return

        suggested_terms = {
            _normalize_suggestion_phrase(item)
            for item in (cached.get("suggestions") or [])
            if _normalize_suggestion_phrase(item)
        }
        if not suggested_terms:
            return

        provided = approved_suggestion_tokens if isinstance(approved_suggestion_tokens, dict) else {}
        expected_tokens = SettingsHandler._issue_rejection_suggestion_approval_tokens(
            normalized_job_id,
            list(suggested_terms),
        )
        for blocker in blockers:
            phrase = _normalize_suggestion_phrase(blocker)
            if not phrase or phrase not in suggested_terms:
                continue
            expected = expected_tokens.get(phrase, "")
            if not expected or str(provided.get(phrase) or "").strip() != expected:
                raise ValueError(f"Missing explicit approval for suggested blocker: {phrase}")


AdminHandler = SettingsHandler
