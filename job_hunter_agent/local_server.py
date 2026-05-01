import json
import hashlib
import mimetypes
import re
import shutil
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

load_dotenv()

from job_hunter_agent.agent_settings import DEFAULT_AGENT_SETTINGS, load_agent_settings, save_agent_settings
from job_hunter_agent.config import SERVER_HOST as HOST, SERVER_PORT as PORT
from job_hunter_agent.filters import build_title_block_rule, normalize_title_block_phrase, passes_saved_rejection_rules, suggest_title_block_phrase
from job_hunter_agent.llm_gate import llm_suggest_rejection_blockers
from job_hunter_agent.notifiers.telegram_notifier import build_telegram_connect_link, send_telegram_notification, sync_telegram_subscribers
from job_hunter_agent.paths import (
    AUDIT_RECORDS_PATH,
    DASHBOARD_PATH,
    DATA_DIR,
    JOB_HISTORY_PATH,
    OUTPUT_DIR,
    REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH,
    REJECTION_RULES_PATH,
    REPO_ROOT as ROOT_DIR,
    REVIEW_DATA_PATH,
    RUN_STATS_PATH,
    SETTINGS_HTML_PATH,
    SHOWCASE_PATH,
    STATIC_DIR,
    WORKSPACE_HTML_PATH,
    ONBOARDING_HTML_PATH,
)
from job_hunter_agent.profile_store import DEFAULT_ONBOARDING_SETTINGS, DEFAULT_PROFILE, load_profile, normalize_capability_rules, normalize_onboarding_settings, normalize_search_settings, patch_profile, save_profile
from job_hunter_agent.profile_store import build_evidence_tiers_from_sections, get_evidence_tiers
from job_hunter_agent.review_insights import apply_capability_tuning_decisions, build_suggested_tuning_from_saved_review
from job_hunter_agent.source_connector import rebuild_html_dashboard, scrape_jobs_direct
from job_hunter_agent.source_documents import (
    DEFAULT_SOURCE_MATERIALS,
    SOURCE_PACK_DIR,
    build_llm_profile_brief,
    load_source_materials,
    persist_uploaded_source_pack,
    run_onboarding,
    save_source_materials,
)

_STATIC_MIME_OVERRIDES = {
    ".css": "text/css",
    ".js": "text/javascript",
    ".png": "image/png",
}
TEST_MODE = "--test-mode" in set(sys.argv[1:])
_run_in_progress = False
_run_state_lock = threading.Lock()
_rejection_suggestions_cache: dict[str, dict[str, Any]] = {}


def _load_rejection_rule_categories() -> frozenset[str]:
    payload = json.loads(REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("rejection_rule_categories.json must contain an entries list")

    categories: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("enabled", True) is False:
            continue
        value = str(entry.get("value") or "").strip()
        if value:
            categories.append(value)
    if not categories:
        raise ValueError("rejection_rule_categories.json must define at least one enabled category")
    return frozenset(categories)


_VALID_REJECTION_RULE_CATEGORIES = _load_rejection_rule_categories()


def _load_rejection_rule_junk_values() -> frozenset[str]:
    payload = json.loads(REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    entries = payload.get("junk_values")
    if not isinstance(entries, list):
        raise ValueError("rejection_rule_categories.json must contain a junk_values list")

    junk_values = [
        str(value).strip().lower()
        for value in entries
        if str(value).strip()
    ]
    if not junk_values:
        raise ValueError("rejection_rule_categories.json must define at least one junk value")
    return frozenset(junk_values)


_REJECTION_RULE_JUNK_VALUES = _load_rejection_rule_junk_values()


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
    return path.read_text(encoding="utf-8", errors="ignore").replace(
        "__JOB_HUNTER_TEST_MODE__",
        "true" if TEST_MODE else "false",
    )


def _parse_locations_override(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    return [part.strip() for part in re.split(r"[\r\n,]+", text) if part.strip()]


_VALID_ENGAGEMENT_TYPES = {"both", "permanent", "contract"}
_LOCATION_NAME_RE = re.compile(r"^[A-Za-z\s,'()-]+$")


def _normalize_onboarding_search_preferences(payload: dict | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    engagement_type = str(source.get("engagement_type") or "").strip().lower()
    keywords = str(source.get("keywords") or "").strip()
    locations = _parse_locations_override(source.get("locations"))
    normalized = {
        "keywords": keywords,
        "locations": locations,
        "engagement_type": engagement_type,
    }
    if "minimum_salary_yearly" in source:
        normalized["minimum_salary_yearly"] = source.get("minimum_salary_yearly")
    if "minimum_daily_rate" in source:
        normalized["minimum_daily_rate"] = source.get("minimum_daily_rate")
    return normalized


def _validate_required_onboarding_inputs(
    search_preferences: dict[str, Any],
    onboarding_settings_payload: dict | None,
) -> None:
    keywords = str(search_preferences.get("keywords") or "").strip()
    locations = _parse_locations_override(search_preferences.get("locations"))
    engagement_type = str(search_preferences.get("engagement_type") or "").strip().lower()

    if keywords and (len(keywords) < 2 or len(keywords) > 120):
        raise ValueError("Please keep the primary search title between 2 and 120 characters.")
    if not locations:
        raise ValueError("Please add at least one search location.")
    if len(locations) > 8:
        raise ValueError("Please keep your location list to 8 places or fewer.")
    for location in locations:
        if len(location) < 2 or len(location) > 80:
            raise ValueError("Each location should be between 2 and 80 characters.")
        if not _LOCATION_NAME_RE.match(location):
            raise ValueError("Locations should look like normal city, state, or region names.")
    if engagement_type not in _VALID_ENGAGEMENT_TYPES:
        raise ValueError("Please choose what type of work you are open to.")

    raw_yearly = search_preferences.get("minimum_salary_yearly")
    if raw_yearly not in (None, ""):
        try:
            yearly = int(raw_yearly)
        except Exception as exc:
            raise ValueError("Minimum permanent salary must be a whole number.") from exc
        if yearly < 0:
            raise ValueError("Minimum permanent salary cannot be negative.")

    raw_daily = search_preferences.get("minimum_daily_rate")
    if raw_daily not in (None, ""):
        try:
            daily = int(raw_daily)
        except Exception as exc:
            raise ValueError("Minimum contract daily rate must be a whole number.") from exc
        if daily < 0:
            raise ValueError("Minimum contract daily rate cannot be negative.")

    raw_settings = onboarding_settings_payload if isinstance(onboarding_settings_payload, dict) else {}
    if isinstance(raw_settings.get("onboarding_settings"), dict):
        raw_settings = raw_settings.get("onboarding_settings") or {}

    raw_lookback = raw_settings.get("extraction_lookback_years")
    raw_min_months = raw_settings.get("title_extraction_min_months")
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
    if not RUN_STATS_PATH.exists():
        return None
    try:
        payload = json.loads(RUN_STATS_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return str(payload.get("run_finished_at") or payload.get("run_started_at") or "").strip() or None
    except Exception:
        return None


def _normalize_search_settings_payload(payload: dict | None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    if isinstance(source.get("search_settings"), dict):
        source = source.get("search_settings") or {}

    overrides: dict[str, Any] = {}
    if "keywords" in source:
        overrides["keywords"] = str(source.get("keywords") or "").strip()
    if "locations" in source:
        overrides["locations"] = _parse_locations_override(source.get("locations"))
    if "date_range_days" in source:
        overrides["date_range_days"] = source.get("date_range_days")
    if "max_pages_cap" in source:
        overrides["max_pages_cap"] = source.get("max_pages_cap")
    if "linkedin_hours_old" in source:
        overrides["linkedin_hours_old"] = source.get("linkedin_hours_old")
    if "linkedin_results_per_search" in source:
        overrides["linkedin_results_per_search"] = source.get("linkedin_results_per_search")

    if not overrides:
        return {}

    current_search_settings = normalize_search_settings(load_profile().get("search_settings", {}))
    current_search_settings.update(overrides)
    return normalize_search_settings(current_search_settings)


def _normalize_onboarding_settings_payload(payload: dict | None) -> dict[str, int]:
    allowed_keys = (
        "extraction_lookback_years",
        "title_extraction_min_months",
        "max_target_patterns",
        "max_secondary_patterns",
    )
    source = payload if isinstance(payload, dict) else {}
    if isinstance(source.get("onboarding_settings"), dict):
        source = source.get("onboarding_settings") or {}

    if not source:
        current = load_profile().get("onboarding_settings")
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
    return bool(target_titles and locations and keywords)


def _run_scrape_job() -> None:
    try:
        scrape_jobs_direct()
    except Exception as exc:
        print(f"[RUN][ERROR] {type(exc).__name__}: {exc}")
    finally:
        _set_run_in_progress(False)



class SettingsHandler(BaseHTTPRequestHandler):
    MATCHING_RULE_PROFILE_KEYS = {
        "capability_profile_rules",
        "primary_job_title_pattern",
        "secondary_title_patterns",
        "must_not_require_skills",
        "reject_title_rules",
        "reject_description_phrase_rules",
    }

    @staticmethod
    def _patch_affects_matching_rules(patch: dict) -> bool:
        return any(key in (patch or {}) for key in SettingsHandler.MATCHING_RULE_PROFILE_KEYS)

    @staticmethod
    def _rebuild_dashboard_after_rule_change(reason: str = "matching rule change") -> None:
        if not DASHBOARD_PATH.exists() and not RUN_STATS_PATH.exists() and not AUDIT_RECORDS_PATH.exists():
            return
        def _rebuild() -> None:
            try:
                rebuild_html_dashboard(reason=f"{reason}; applying saved filters to current dashboard")
            except Exception as exc:
                print(f"[DASHBOARD][WARN] Could not rebuild after rule change: {type(exc).__name__}: {exc}")

        threading.Thread(
            target=_rebuild,
            daemon=True,
            name="job-hunter-dashboard-rebuild",
        ).start()

    @staticmethod
    def _normalize_profile_patch_for_save(current: dict, patch: dict) -> dict:
        normalized = dict(patch or {})
        current = current or load_profile()
        brief_mode = str(
            normalized.get("llm_profile_brief_mode", current.get("llm_profile_brief_mode", "auto")) or "auto"
        ).strip().lower()
        if brief_mode != "manual":
            brief_mode = "auto"
        normalized["llm_profile_brief_mode"] = brief_mode

        if brief_mode == "manual":
            normalized["llm_profile_brief"] = str(normalized.get("llm_profile_brief") or "").strip()
        else:
            auto_brief = build_llm_profile_brief(
                capability_rules=normalized.get(
                    "capability_profile_rules",
                    current.get("capability_profile_rules", []),
                ),
            )
            normalized["llm_profile_brief"] = auto_brief

        if "star_evidence_text" in normalized:
            normalized["star_evidence_text"] = str(normalized.get("star_evidence_text") or "").strip()
        if "llm_fit_review_guidance" in normalized:
            normalized["llm_fit_review_guidance"] = str(normalized.get("llm_fit_review_guidance") or "").strip()
        if "llm_capability_naming_guidance" in normalized:
            normalized["llm_capability_naming_guidance"] = str(normalized.get("llm_capability_naming_guidance") or "").strip()
        if "cv_text" in normalized:
          new_cv = str(normalized.get("cv_text") or "").strip()
          current_cv = str(current.get("cv_text") or "").strip()
          cv_changed = new_cv != current_cv

          if cv_changed and "evidence_tiers" not in normalized:
              inferred_tiers = build_evidence_tiers_from_sections([{
                  "label": "Primary CV",
                  "text": new_cv,
              }])
              if any(inferred_tiers.values()):
                  normalized["evidence_tiers"] = inferred_tiers
        return normalized

    @staticmethod
    def _load_job_history() -> dict:
        if not JOB_HISTORY_PATH.exists():
            return {}
        try:
            payload = json.loads(JOB_HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    @staticmethod
    def _save_job_history(history: dict) -> None:
        JOB_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        JOB_HISTORY_PATH.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

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

        if SOURCE_PACK_DIR.exists():
            shutil.rmtree(SOURCE_PACK_DIR)

        cls._write_json_file(JOB_HISTORY_PATH, {})
        cls._write_json_file(REVIEW_DATA_PATH, {})
        cls._write_json_file(RUN_STATS_PATH, {})
        cls._write_json_file(AUDIT_RECORDS_PATH, [])
        cls._write_json_file(REJECTION_RULES_PATH, [])

        try:
            DASHBOARD_PATH.unlink(missing_ok=True)
        except Exception:
            pass

        return {
            "ok": True,
            "message": "Current user state reset. Shared learning was preserved.",
            "redirect_to": "/start",
        }

    @staticmethod
    def _reset_global_learning() -> dict[str, Any]:
        from job_hunter_agent.signal_registry import save_registry

        save_registry({})
        return {
            "ok": True,
            "message": "Global learning reset. Shared learned signals were cleared.",
        }

    @staticmethod
    def _sanitize_agent_settings_payload(payload: dict) -> dict:
        telegram = payload.get("telegram", {}) if isinstance(payload, dict) else {}
        llm = payload.get("llm", {}) if isinstance(payload, dict) else {}
        schedule_payload = payload.get("schedule") if isinstance(payload, dict) else None
        _allowed_models = {"gpt-4o-mini", "gpt-4.1-mini", "gpt-4.1", "gpt-4o"}
        model = str(llm.get("model") or "").strip()
        sanitized = {
            "telegram": {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token": str(telegram.get("bot_token") or "").strip(),
                "bot_username": str(telegram.get("bot_username") or "").strip().lstrip("@"),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
            },
            "llm": {
                "model": model if model in _allowed_models else "gpt-4o-mini",
            },
        }
        if isinstance(schedule_payload, dict):
            daily_time_local = str(
                schedule_payload.get("daily_time_local")
                or DEFAULT_AGENT_SETTINGS["schedule"]["daily_time_local"]
            ).strip()
            if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", daily_time_local):
                raise ValueError("Schedule time must be in HH:MM 24-hour format.")
            try:
                loop_sleep_seconds = int(
                    schedule_payload.get(
                        "loop_sleep_seconds",
                        DEFAULT_AGENT_SETTINGS["schedule"]["loop_sleep_seconds"],
                    )
                    or DEFAULT_AGENT_SETTINGS["schedule"]["loop_sleep_seconds"]
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("Schedule polling interval must be a whole number of seconds.") from exc
            sanitized["schedule"] = {
                "daily_time_local": daily_time_local,
                "loop_sleep_seconds": max(60, loop_sleep_seconds),
            }
        return sanitized

    @staticmethod
    def _public_agent_settings_payload(settings: dict) -> dict:
        telegram = settings.get("telegram", {}) if isinstance(settings, dict) else {}
        llm = settings.get("llm", {}) if isinstance(settings, dict) else {}
        schedule = settings.get("schedule", {}) if isinstance(settings, dict) else {}
        subscribers = telegram.get("subscribers", []) if isinstance(telegram, dict) else []
        return {
            "schedule": {
                "daily_time_local": str(
                    schedule.get("daily_time_local")
                    or DEFAULT_AGENT_SETTINGS["schedule"]["daily_time_local"]
                ).strip(),
                "loop_sleep_seconds": max(
                    60,
                    int(
                        schedule.get(
                            "loop_sleep_seconds",
                            DEFAULT_AGENT_SETTINGS["schedule"]["loop_sleep_seconds"],
                        )
                        or DEFAULT_AGENT_SETTINGS["schedule"]["loop_sleep_seconds"]
                    ),
                ),
            },
            "telegram": {
                "enabled": bool(telegram.get("enabled", False)),
                "bot_token_present": bool(str(telegram.get("bot_token") or "").strip()),
                "bot_username": str(telegram.get("bot_username") or "").strip(),
                "chat_id_present": bool(str(telegram.get("chat_id") or "").strip()),
                "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
                "subscriber_count": len(subscribers) if isinstance(subscribers, list) else 0,
                "subscribers": subscribers if isinstance(subscribers, list) else [],
            },
            "llm": {
                "model": str(llm.get("model") or "gpt-4o-mini").strip(),
            },
        }

    @staticmethod
    def _normalize_job_key(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            return ""
        import re

        # Pass through pre-namespaced keys (e.g. 'linkedin:4056789012')
        if re.match(r"^(seek|linkedin|indeed|glassdoor):[^\s]+$", raw):
            return raw
        match = re.search(r"/job/(\d+)", raw)
        if match:
            return match.group(1)
        if re.fullmatch(r"\d+", raw):
            return raw
        return raw.split("#", 1)[0]

    @classmethod
    def _append_review_event(
        cls,
        entry: dict,
        action: str,
        job_key: str,
        occurred_at: str,
        title: str = "",
        company: str = "",
        url: str = "",
        teaser: str = "",
        extra: dict | None = None,
    ) -> None:
        snapshot = entry.get("last_kept_snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}

        event = {
            "action": action,
            "job_key": job_key,
            "timestamp": occurred_at,
        }
        resolved_title = title or entry.get("title") or snapshot.get("title") or ""
        resolved_company = company or entry.get("company") or snapshot.get("company") or ""
        resolved_url = url or entry.get("url") or snapshot.get("url") or ""
        resolved_teaser = teaser or snapshot.get("teaser") or entry.get("teaser") or ""

        if resolved_title:
            event["title"] = resolved_title
        if resolved_company:
            event["company"] = resolved_company
        if resolved_url:
            event["url"] = resolved_url
        if resolved_teaser:
            event["teaser"] = resolved_teaser

        if isinstance(extra, dict):
            for key, value in extra.items():
                if value in (None, "", [], {}):
                    continue
                event[key] = value

        events = entry.get("review_events")
        if not isinstance(events, list):
            events = []
        events.append(event)
        entry["review_events"] = events[-50:]

    @classmethod
    def _persist_review_event(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
        extra: dict | None = None,
    ) -> None:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            return

        history = cls._load_job_history()
        entry = history.get(normalized, {})
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

        entry["job_key"] = normalized
        if title:
            entry["title"] = title
        if company:
            entry["company"] = company
        if url:
            entry["url"] = url

        if action == "hidden":
            entry["is_hidden"] = True
            if not entry.get("first_hidden_at"):
                entry["first_hidden_at"] = now_iso
            entry["last_hidden_at"] = now_iso
        elif action == "unhide":
            entry["is_hidden"] = False
            entry["last_unhidden_at"] = now_iso
        elif action == "applied":
            if not entry.get("first_applied_at"):
                entry["first_applied_at"] = now_iso
            entry["last_applied_at"] = now_iso
        elif action == "unapply":
            entry["last_unapplied_at"] = now_iso
        elif action == "not_for_me":
            entry["last_not_for_me_at"] = now_iso
            entry["times_not_for_me"] = int(entry.get("times_not_for_me", 0) or 0) + 1
        elif action in ("block_similar", "block_title"):
            entry["last_block_title_at"] = now_iso
            entry["times_block_title"] = int(entry.get("times_block_title", 0) or 0) + 1

        cls._append_review_event(
            entry,
            action,
            normalized,
            now_iso,
            title=title,
            company=company,
            url=url,
            teaser=teaser,
            extra=extra,
        )

        history[normalized] = entry
        cls._save_job_history(history)

    @classmethod
    def _append_review_key(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key)
        if not normalized:
            raise ValueError("Missing job key")

        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})

        list_name = {
            "applied": "applied_job_keys",
            "hidden": "hidden_job_keys",
        }.get(action)
        if not list_name:
            raise ValueError("Unsupported review action")

        existing = [
            cls._normalize_job_key(value)
            for value in review_controls.get(list_name, [])
            if cls._normalize_job_key(value)
        ]
        if normalized not in existing:
            existing.append(normalized)
        review_controls[list_name] = existing
        save_profile(profile)
        cls._persist_review_event(
            action,
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        cls._rebuild_dashboard_after_rule_change(f"review action saved: {action}")
        return {
            "ok": True,
            "action": action,
            "job_key": normalized,
            "saved_count": len(existing),
            "reload_dashboard": True,
        }

    @classmethod
    def _remove_review_key(
        cls,
        action: str,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key)
        if not normalized:
            raise ValueError("Missing job key")

        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})

        list_name = {
            "unapply": "applied_job_keys",
            "unhide": "hidden_job_keys",
        }.get(action)
        if not list_name:
            raise ValueError("Unsupported review action")

        existing = [
            cls._normalize_job_key(value)
            for value in review_controls.get(list_name, [])
            if cls._normalize_job_key(value)
        ]
        updated = [value for value in existing if value != normalized]
        review_controls[list_name] = updated
        save_profile(profile)
        cls._persist_review_event(
            action,
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        cls._rebuild_dashboard_after_rule_change(f"review action saved: {action}")
        return {
            "ok": True,
            "action": action,
            "job_key": normalized,
            "saved_count": len(updated),
            "reload_dashboard": True,
        }


    # ------------------------------------------------------------------
    # Rejection-learning helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_audit_rows() -> list[dict[str, Any]]:
        if not AUDIT_RECORDS_PATH.exists():
            return []
        try:
            data = json.loads(AUDIT_RECORDS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _normalize_requirement_blocker(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "").strip())
        return cleaned[:80]

    @staticmethod
    def _normalize_description_block_phrase(value: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(value or "").strip().lower())
        return cleaned[:120]

    @staticmethod
    def _load_rejection_rules() -> list:
        if not REJECTION_RULES_PATH.exists():
            return []
        try:
            data = json.loads(REJECTION_RULES_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _save_rejection_rules_list(rules: list) -> None:
        REJECTION_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        REJECTION_RULES_PATH.write_text(
            json.dumps(rules, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _issue_rejection_suggestion_approval_tokens(job_id: str, suggestions: list[str]) -> dict[str, str]:
        normalized_job_id = str(job_id or "").strip()
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
        normalized_job_id = str(job_id or "").strip()
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

    @classmethod
    def _get_job_description(cls, job_id: str) -> str:
        """Return the full description text for a job_id, or empty string."""
        history = cls._load_job_history()
        for key in [job_id, f"linkedin:{job_id}"]:
            entry = history.get(key) if isinstance(history, dict) else None
            if not isinstance(entry, dict):
                continue
            snap = entry.get("last_kept_snapshot") or {}
            if isinstance(snap, dict):
                desc = snap.get("full_description") or snap.get("fit_source_text") or ""
                if desc:
                    return desc
        seek_path = OUTPUT_DIR / "seek_results.json"
        if seek_path.exists():
            try:
                rows = json.loads(seek_path.read_text(encoding="utf-8"))
                if isinstance(rows, list):
                    for row in rows:
                        if str(row.get("job_key") or "") == str(job_id):
                            return row.get("full_description") or row.get("fit_source_text") or ""
            except Exception:
                pass
        return ""

    @classmethod
    def _build_title_block_followups(cls, blockers: list[str]) -> list[dict[str, Any]]:
        profile = load_profile()
        existing_patterns = {
            str(rule.get("pattern") or "").strip()
            for rule in profile.get("reject_title_rules", [])
            if isinstance(rule, dict)
        }
        audit_rows = cls._load_audit_rows()
        history = cls._load_job_history()
        suggestions: list[dict[str, Any]] = []
        seen_phrases: set[str] = set()

        for blocker in blockers:
            phrase = normalize_title_block_phrase(blocker)
            if not phrase or phrase in seen_phrases:
                continue
            seen_phrases.add(phrase)
            rule = build_title_block_rule(phrase)
            if rule["pattern"] in existing_patterns:
                continue

            matcher = re.compile(rule["pattern"], re.IGNORECASE)
            rejected_keys: set[str] = set()
            kept_keys: set[str] = set()
            rejected_examples: list[dict[str, str]] = []
            kept_examples: list[dict[str, str]] = []

            for row in audit_rows:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").strip()
                if not title or not matcher.search(title.lower()):
                    continue
                job_key = cls._normalize_job_key(str(row.get("job_key") or row.get("url") or title))
                item = {
                    "title": title,
                    "company": str(row.get("company") or "").strip(),
                }
                if str(row.get("decision") or "").strip().upper() == "KEEP":
                    if job_key and job_key in kept_keys:
                        continue
                    if job_key:
                        kept_keys.add(job_key)
                    if len(kept_examples) < 3:
                        kept_examples.append(item)
                    continue
                if job_key and job_key in rejected_keys:
                    continue
                if job_key:
                    rejected_keys.add(job_key)
                if len(rejected_examples) < 3:
                    rejected_examples.append(item)

            for raw_key, entry in history.items():
                if not isinstance(entry, dict):
                    continue
                if int(entry.get("times_kept", 0) or 0) <= 0:
                    continue
                job_key = cls._normalize_job_key(str(raw_key))
                if job_key and job_key in kept_keys:
                    continue
                snapshot = entry.get("last_kept_snapshot") if isinstance(entry.get("last_kept_snapshot"), dict) else {}
                title = str(snapshot.get("title") or entry.get("title") or "").strip()
                if not title or not matcher.search(title.lower()):
                    continue
                if job_key:
                    kept_keys.add(job_key)
                if len(kept_examples) < 3:
                    kept_examples.append({
                        "title": title,
                        "company": str(snapshot.get("company") or entry.get("company") or "").strip(),
                    })

            rejected_count = len(rejected_keys) or len(rejected_examples)
            kept_count = len(kept_keys) or len(kept_examples)
            if rejected_count < 2 or kept_count > 0:
                continue

            suggestions.append(
                {
                    "phrase": phrase,
                    "matched_rejected_count": rejected_count,
                    "matched_kept_count": kept_count,
                    "sample_rejected_titles": rejected_examples,
                    "sample_kept_titles": kept_examples,
                }
            )

        suggestions.sort(
            key=lambda item: (
                -int(item.get("matched_rejected_count", 0) or 0),
                str(item.get("phrase") or ""),
            )
        )
        return suggestions[:4]

    @classmethod
    def _build_description_block_followups(cls, blockers: list[str]) -> list[dict[str, Any]]:
        profile = load_profile()
        existing_phrases = {
            cls._normalize_description_block_phrase(str(rule.get("phrase") or ""))
            for rule in profile.get("reject_description_phrase_rules", [])
            if isinstance(rule, dict)
        }
        audit_rows = cls._load_audit_rows()
        history = cls._load_job_history()
        suggestions: list[dict[str, Any]] = []
        seen_phrases: set[str] = set()

        for blocker in blockers:
            phrase = cls._normalize_description_block_phrase(blocker)
            if len(phrase) < 3 or phrase in seen_phrases or phrase in existing_phrases:
                continue
            seen_phrases.add(phrase)

            rejected_keys: set[str] = set()
            kept_keys: set[str] = set()
            rejected_examples: list[dict[str, str]] = []
            kept_examples: list[dict[str, str]] = []

            for row in audit_rows:
                if not isinstance(row, dict):
                    continue
                details_text = str(row.get("full_description") or row.get("fit_source_text") or "").strip().lower()
                if not details_text or phrase not in details_text:
                    continue
                job_key = cls._normalize_job_key(str(row.get("job_key") or row.get("url") or row.get("title") or phrase))
                item = {
                    "title": str(row.get("title") or "").strip(),
                    "company": str(row.get("company") or "").strip(),
                }
                if str(row.get("decision") or "").strip().upper() == "KEEP":
                    if job_key and job_key in kept_keys:
                        continue
                    if job_key:
                        kept_keys.add(job_key)
                    if len(kept_examples) < 3:
                        kept_examples.append(item)
                    continue
                if job_key and job_key in rejected_keys:
                    continue
                if job_key:
                    rejected_keys.add(job_key)
                if len(rejected_examples) < 3:
                    rejected_examples.append(item)

            for raw_key, entry in history.items():
                if not isinstance(entry, dict):
                    continue
                if int(entry.get("times_kept", 0) or 0) <= 0:
                    continue
                snapshot = entry.get("last_kept_snapshot") if isinstance(entry.get("last_kept_snapshot"), dict) else {}
                details_text = str(snapshot.get("full_description") or snapshot.get("fit_source_text") or "").strip().lower()
                if not details_text or phrase not in details_text:
                    continue
                job_key = cls._normalize_job_key(str(raw_key))
                if job_key and job_key in kept_keys:
                    continue
                if job_key:
                    kept_keys.add(job_key)
                if len(kept_examples) < 3:
                    kept_examples.append({
                        "title": str(snapshot.get("title") or entry.get("title") or "").strip(),
                        "company": str(snapshot.get("company") or entry.get("company") or "").strip(),
                    })

            rejected_count = len(rejected_keys) or len(rejected_examples)
            kept_count = len(kept_keys) or len(kept_examples)
            if rejected_count < 2 or kept_count > 0:
                continue

            suggestions.append(
                {
                    "phrase": phrase,
                    "matched_rejected_count": rejected_count,
                    "matched_kept_count": kept_count,
                    "sample_rejected_titles": rejected_examples,
                    "sample_kept_titles": kept_examples,
                }
            )

        suggestions.sort(
            key=lambda item: (
                -int(item.get("matched_rejected_count", 0) or 0),
                str(item.get("phrase") or ""),
            )
        )
        return suggestions[:4]

    @classmethod
    def _save_description_block_feedback(
        cls,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
        block_phrases: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        resolved: list[str] = []
        seen_phrases: set[str] = set()
        for raw in block_phrases or []:
            phrase = cls._normalize_description_block_phrase(raw)
            if len(phrase) < 3 or phrase in seen_phrases:
                continue
            seen_phrases.add(phrase)
            resolved.append(phrase)
        if not resolved:
            raise ValueError("At least one description block phrase is required")

        profile = load_profile()
        existing = list(profile.get("reject_description_phrase_rules", []))
        existing_phrases = {
            cls._normalize_description_block_phrase(str(item.get("phrase") or ""))
            for item in existing
            if isinstance(item, dict)
        }

        added_rules: list[dict[str, str]] = []
        skipped_phrases: list[str] = []
        for phrase in resolved:
            if phrase in existing_phrases:
                skipped_phrases.append(phrase)
                continue
            existing_phrases.add(phrase)
            added_rules.append({
                "phrase": phrase,
                "reason": f"DESC_REJECT:{phrase}",
            })

        if added_rules:
            profile["reject_description_phrase_rules"] = existing + added_rules
            save_profile(profile)
            cls._rebuild_dashboard_after_rule_change(
                f"description phrase rule added for {', '.join(resolved)}"
            )

        cls._persist_review_event(
            "block_description",
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
            extra={
                "description_phrases_added": [rule["phrase"] for rule in added_rules],
                "description_phrases_skipped": skipped_phrases,
            },
        )

        if added_rules and skipped_phrases:
            message = f"Added {len(added_rules)} description block phrase(s). {len(skipped_phrases)} already existed."
        elif added_rules:
            message = f"Added {len(added_rules)} description block phrase(s)."
        else:
            message = "All selected description block phrases already existed."

        return {
            "ok": True,
            "action": "block_description",
            "job_key": normalized,
            "block_phrases": resolved,
            "rules_added": added_rules,
            "message": message,
        }

    @classmethod
    def _save_requirement_blockers_feedback(
        cls,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
        blockers: list[str] | None = None,
        title_block_phrases: list[str] | None = None,
        description_block_phrases: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        cleaned_blockers: list[str] = []
        seen_blockers: set[str] = set()
        for raw in blockers or []:
            cleaned = cls._normalize_requirement_blocker(str(raw or ""))
            normalized_blocker = cleaned.lower()
            if len(cleaned) < 2 or normalized_blocker in seen_blockers:
                continue
            seen_blockers.add(normalized_blocker)
            cleaned_blockers.append(cleaned)

        if not cleaned_blockers:
            raise ValueError("At least one blocker is required")

        profile = load_profile()
        existing_blockers = list(profile.get("must_not_require_skills", []))
        existing_lookup = {
            cls._normalize_requirement_blocker(str(item or "")).lower()
            for item in existing_blockers
            if cls._normalize_requirement_blocker(str(item or ""))
        }
        added_blockers: list[str] = []
        skipped_blockers: list[str] = []
        for blocker in cleaned_blockers:
            blocker_key = blocker.lower()
            if blocker_key in existing_lookup:
                skipped_blockers.append(blocker)
                continue
            existing_lookup.add(blocker_key)
            existing_blockers.append(blocker)
            added_blockers.append(blocker)

        if added_blockers:
            profile["must_not_require_skills"] = existing_blockers
            save_profile(profile)

        title_result: dict[str, Any] | None = None
        description_result: dict[str, Any] | None = None
        applied_title_block_phrases: list[str] = []
        applied_description_block_phrases: list[str] = []
        if title_block_phrases:
            title_result = cls._save_block_similar_feedback(
                normalized,
                url=url,
                title=title,
                company=company,
                teaser=teaser,
                block_phrases=title_block_phrases,
            )
            applied_title_block_phrases = list(title_result.get("block_phrases") or [])
        if description_block_phrases:
            description_result = cls._save_description_block_feedback(
                normalized,
                url=url,
                title=title,
                company=company,
                teaser=teaser,
                block_phrases=description_block_phrases,
            )
            applied_description_block_phrases = list(description_result.get("block_phrases") or [])

        if added_blockers:
            cls._persist_review_event(
                "block_requirement",
                normalized,
                url=url,
                title=title,
                company=company,
                teaser=teaser,
                extra={
                    "blockers_added": added_blockers,
                    "title_block_phrases": applied_title_block_phrases,
                    "description_block_phrases": applied_description_block_phrases,
                },
            )
        elif skipped_blockers:
            cls._persist_review_event(
                "block_requirement",
                normalized,
                url=url,
                title=title,
                company=company,
                teaser=teaser,
                extra={
                    "blockers_skipped": skipped_blockers,
                    "title_block_phrases": applied_title_block_phrases,
                    "description_block_phrases": applied_description_block_phrases,
                },
            )

        title_block_suggestions = (
            []
            if applied_title_block_phrases
            else cls._build_title_block_followups(cleaned_blockers)
        )
        description_block_suggestions = (
            []
            if applied_description_block_phrases
            else cls._build_description_block_followups(cleaned_blockers)
        )

        message_bits: list[str] = []
        if added_blockers:
            noun = "blocker" if len(added_blockers) == 1 else "blockers"
            message_bits.append(
                f"Added {len(added_blockers)} mandatory requirement {noun}. Future runs will only reject when those terms look required."
            )
        elif skipped_blockers:
            noun = "blocker" if len(skipped_blockers) == 1 else "blockers"
            message_bits.append(f"{len(skipped_blockers)} mandatory requirement {noun} already existed.")

        if applied_title_block_phrases:
            noun = "title block" if len(applied_title_block_phrases) == 1 else "title blocks"
            message_bits.append(
                f"Added {len(applied_title_block_phrases)} {noun} for stronger early filtering."
            )
        if applied_description_block_phrases:
            noun = "description block" if len(applied_description_block_phrases) == 1 else "description blocks"
            message_bits.append(
                f"Added {len(applied_description_block_phrases)} hard {noun} for future runs."
            )
        followup_suggestion_count = len(title_block_suggestions) + len(description_block_suggestions)
        if followup_suggestion_count:
            noun = "extra block" if followup_suggestion_count == 1 else "extra blocks"
            message_bits.append(
                f"{followup_suggestion_count} optional {noun} also has strong evidence from past rejections."
            )

        return {
            "ok": True,
            "job_key": normalized,
            "added_blockers": added_blockers,
            "skipped_blockers": skipped_blockers,
            "title_block_suggestions": title_block_suggestions,
            "description_block_suggestions": description_block_suggestions,
            "applied_title_block_phrases": applied_title_block_phrases,
            "applied_description_block_phrases": applied_description_block_phrases,
            "message": " ".join(message_bits).strip() or "Requirement blockers saved.",
        }

    @classmethod
    def _save_not_for_me_feedback(
        cls,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
    ) -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        cls._persist_review_event(
            "not_for_me",
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
        )
        return {
            "ok": True,
            "action": "not_for_me",
            "job_key": normalized,
            "message": "Saved as Not For Me. This is stored as learning feedback, not a permanent title block.",
        }

    @classmethod
    def _save_block_similar_feedback(
        cls,
        job_key: str,
        url: str = "",
        title: str = "",
        company: str = "",
        teaser: str = "",
        block_phrases: list[str] | None = None,
    ) -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        # Resolve phrases: normalise each candidate, fall back to title suggestion
        raw_phrases = [p for p in (block_phrases or []) if str(p).strip()]
        resolved: list[str] = [normalize_title_block_phrase(p) for p in raw_phrases]
        resolved = [p for p in resolved if p]
        if not resolved:
            fallback = suggest_title_block_phrase(title)
            if not fallback:
                raise ValueError("Could not suggest a title keyword to block from this title yet")
            resolved = [fallback]

        profile = load_profile()
        existing = list(profile.get("reject_title_rules", []))
        existing_patterns = {str(item.get("pattern") or "").strip() for item in existing}

        added_rules: list[dict] = []
        skipped_phrases: list[str] = []
        for phrase in resolved:
            rule = build_title_block_rule(phrase)
            if rule["pattern"] not in existing_patterns:
                existing.append(rule)
                existing_patterns.add(rule["pattern"])
                added_rules.append(rule)
            else:
                skipped_phrases.append(phrase)

        if added_rules:
            profile["reject_title_rules"] = existing
            save_profile(profile)
            cls._rebuild_dashboard_after_rule_change(
                f"title block added for {', '.join(resolved)}"
            )

        cls._persist_review_event(
            "block_title",
            normalized,
            url=url,
            title=title,
            company=company,
            teaser=teaser,
            extra={
                "extracted_phrases": resolved,
                "rules_added": [r["pattern"] for r in added_rules],
                "rules_skipped": skipped_phrases,
            },
        )

        added_labels = "', '".join(r["reason"].split("'")[1] if "'" in r["reason"] else r["pattern"] for r in added_rules)
        if added_rules and skipped_phrases:
            message = f"Blocked '{added_labels}'. {len(skipped_phrases)} pattern(s) already existed."
        elif added_rules:
            message = f"Blocked {len(added_rules)} pattern(s). Similar jobs will be filtered in future runs."
        else:
            message = "All selected patterns already existed as title block rules."

        return {
            "ok": True,
            "action": "block_similar",
            "job_key": normalized,
            "block_phrase": resolved[0],
            "block_phrases": resolved,
            "rules_added": added_rules,
            "message": message,
        }

    @classmethod
    def _record_job_view(cls, job_key: str, url: str = "", title: str = "") -> dict:
        normalized = cls._normalize_job_key(job_key or url)
        if not normalized:
            raise ValueError("Missing job key")

        history = cls._load_job_history()
        entry = history.get(normalized, {})
        now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

        entry["job_key"] = normalized
        if title and not entry.get("title"):
            entry["title"] = title
        if url:
            entry["url"] = url
        entry["times_viewed"] = int(entry.get("times_viewed", 0) or 0) + 1
        if not entry.get("first_viewed_at"):
            entry["first_viewed_at"] = now_iso
        entry["last_viewed_at"] = now_iso

        history[normalized] = entry
        cls._save_job_history(history)
        return {
            "ok": True,
            "action": "viewed",
            "job_key": normalized,
            "times_viewed": entry["times_viewed"],
            "last_viewed_at": entry["last_viewed_at"],
        }

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, PATCH, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_static_file(self, file_path: Path) -> None:
        body = file_path.read_bytes()
        mime_type = _STATIC_MIME_OVERRIDES.get(file_path.suffix.lower())
        if not mime_type:
            mime_type, _ = mimetypes.guess_type(str(file_path))
        self.send_response(200)
        content_type = mime_type or "application/octet-stream"
        if content_type.startswith("text/") or content_type == "application/javascript":
            content_type = f"{content_type}; charset=utf-8"
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b"{}"
        payload = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload

    def do_OPTIONS(self) -> None:
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:
        from urllib.parse import urlparse as _urlparse
        _path = _urlparse(self.path).path
        if _path.startswith("/static/"):
            relative = _path.removeprefix("/static/").strip("/")
            candidate = (STATIC_DIR / relative).resolve()
            static_root = STATIC_DIR.resolve()
            if static_root in candidate.parents and candidate.is_file():
                self._send_static_file(candidate)
                return
            self._send_json(404, {"error": "Static asset not found"})
            return
        if _path.startswith("/data/"):
            relative = _path.removeprefix("/data/").strip("/")
            candidate = (DATA_DIR / relative).resolve()
            data_root = DATA_DIR.resolve()
            if data_root in candidate.parents and candidate.is_file():
                self._send_static_file(candidate)
                return
            self._send_json(404, {"error": "Data asset not found"})
            return
        if _path in {"/", "/workspace", "/admin", "/profile", "/demo", "/start", "/onboarding", "/dashboard", "/settings"}:
            if _path in {"/", "/workspace", "/admin", "/profile", "/dashboard"} and not _onboarding_complete():
                self._redirect("/start")
                return
            if _path in {"/admin", "/profile"}:
                self._redirect("/settings")
                return
            if _path == "/dashboard":
                self._redirect("/")
                return
            if _path == "/settings":
                if not TEST_MODE and not _onboarding_complete():
                    self._redirect("/start")
                    return
                if SETTINGS_HTML_PATH.exists():
                    self._send_html(_render_template(SETTINGS_HTML_PATH))
                else:
                    self._send_html("<h1>Template missing</h1><p>Missing templates/settings.html</p>")
                return
            if _path in {"/start", "/onboarding"}:
                if ONBOARDING_HTML_PATH.exists():
                    self._send_html(_render_template(ONBOARDING_HTML_PATH))
                else:
                    self._send_html("<h1>Template missing</h1><p>Missing templates/onboarding.html</p>")
                return
            if _path == "/demo":
                if SHOWCASE_PATH.exists():
                    self._send_html(SHOWCASE_PATH.read_text(encoding="utf-8", errors="ignore"))
                    return
                self._send_html("<h1>Demo page not found</h1>")
                return
            if WORKSPACE_HTML_PATH.exists():
                self._send_html(_render_template(WORKSPACE_HTML_PATH))
            else:
                self._send_html("<h1>Template missing</h1><p>Missing templates/workspace.html</p>")
            return
        if _path == "/api/results-html":
            if not DASHBOARD_PATH.exists():
                body = '<div style="padding:64px 24px;color:#667085;text-align:center;font-family:sans-serif;">No results yet - run a search first.</div>'.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            try:
                fragment = DASHBOARD_PATH.read_bytes()
            except Exception as exc:
                self._send_json(500, {"error": str(exc)})
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(fragment)))
            self.end_headers()
            self.wfile.write(fragment)
            return
        if _path == "/api/health":
            self._send_json(200, {"ok": True})
            return
        if _path == "/api/run-stats":
            if RUN_STATS_PATH.exists():
                try:
                    payload = json.loads(RUN_STATS_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        self._send_json(200, payload)
                        return
                except Exception:
                    pass
            self._send_json(200, {})
            return
        if _path == "/api/review-data":
            if REVIEW_DATA_PATH.exists():
                try:
                    payload = json.loads(REVIEW_DATA_PATH.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        payload["suggested_tuning"] = build_suggested_tuning_from_saved_review(
                            payload,
                            load_profile(),
                        )
                        self._send_json(200, payload)
                        return
                except Exception:
                    pass
            self._send_json(200, {})
            return
        if _path == "/api/job-history":
            history = self._load_job_history()
            slim_history: dict[str, dict] = {}
            for job_key, entry in history.items():
                if not isinstance(entry, dict):
                    continue
                slim_history[str(job_key)] = {
                    "times_viewed": int(entry.get("times_viewed", 0) or 0),
                    "first_viewed_at": entry.get("first_viewed_at"),
                    "last_viewed_at": entry.get("last_viewed_at"),
                }
            self._send_json(200, {"jobs": slim_history})
            return
        if _path == "/api/profile":
            self._send_json(200, load_profile())
            return
        if _path == "/api/llm-costs":
            from job_hunter_agent.llm_gate import get_cost_summary
            self._send_json(200, get_cost_summary())
            return
        if _path == "/api/agent-settings":
            self._send_json(200, self._public_agent_settings_payload(load_agent_settings(create_if_missing=True)))
            return
        if _path == "/api/telegram/connect-link":
            try:
                settings = load_agent_settings(create_if_missing=True)
                link = build_telegram_connect_link(settings["telegram"])
                save_agent_settings(settings)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "connect_link": link,
                    "bot_username": str(settings["telegram"].get("bot_username") or "").strip(),
                },
            )
            return
        if _path == "/api/source-materials":
            self._send_json(200, load_source_materials(create_if_missing=True))
            return
        # Rejection-learning: suggestions endpoint
        import re as _re
        if _re.match(r'^/api/rejection-suggestions', _path):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            job_id = (params.get("job_id") or [""])[0].strip()
            if not job_id:
                self._send_json(400, {"error": "job_id is required"})
                return
            description = self._get_job_description(job_id)
            if not description:
                self._send_json(200, {})
                return
            description_hash = hashlib.sha1(description.encode("utf-8")).hexdigest()
            cached = _rejection_suggestions_cache.get(job_id)
            if isinstance(cached, dict) and cached.get("description_hash") == description_hash:
                suggestions = cached.get("suggestions") or []
                if not isinstance(cached.get("approval_tokens"), dict):
                    cached["approval_tokens"] = self._issue_rejection_suggestion_approval_tokens(job_id, suggestions)
                print(f"[LLM][REJECTION_SUGGESTIONS][CACHE_HIT] job_id={job_id} suggestions={suggestions}")
            else:
                suggestions = llm_suggest_rejection_blockers(description)
                approval_tokens = self._issue_rejection_suggestion_approval_tokens(job_id, suggestions)
                _rejection_suggestions_cache[job_id] = {
                    "description_hash": description_hash,
                    "suggestions": list(suggestions),
                    "approval_tokens": approval_tokens,
                }
            approval_tokens = {}
            if isinstance(_rejection_suggestions_cache.get(job_id), dict):
                approval_tokens = _rejection_suggestions_cache[job_id].get("approval_tokens") or {}
            self._send_json(
                200,
                {
                    "other": suggestions,
                    "approval_tokens": approval_tokens,
                } if suggestions else {}
            )
            return

        if _path == "/api/signal-registry":
            from job_hunter_agent.signal_registry import load_registry
            registry = load_registry()
            signals = sorted(
                registry.values(),
                key=lambda r: (not r.get("needs_review", True), str(r.get("signal", "")).lower()),
            )
            self._send_json(200, {"signals": signals, "total": len(signals)})
            return

        self._send_json(404, {"error": "Not found"})

    def do_PATCH(self) -> None:
      if self.path == "/api/signal-registry":
        try:
            from job_hunter_agent.signal_registry import update_signal

            body = self._read_json_body()
            key = str(body.get("key") or "").strip()
            learning_status = str(body.get("learning_status") or "pending").strip()
            suggested_category = str(body.get("suggested_category") or "").strip()
            target_file = str(body.get("target_file") or "").strip()
            scope = str(body.get("scope") or "global").strip()
            notes = str(body.get("notes") or "").strip()

            if not key:
                self._send_json(400, {"error": "key is required"})
                return

            updated = update_signal(
                key=key,
                learning_status=learning_status,
                suggested_category=suggested_category,
                scope=scope,
                target_file=target_file,
                notes=notes, 
            )

            if updated is None:
                self._send_json(404, {"error": f"Signal '{key}' not found in registry"})
                return

            self._send_json(200, {"ok": True, "signal": updated})

        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
        return

      if self.path == "/api/agent-settings":
          try:
              current = load_agent_settings(create_if_missing=True)
              patch = self._sanitize_agent_settings_payload(self._read_json_body())
              telegram_patch = patch.get("telegram", {})
              if not str(telegram_patch.get("bot_token") or "").strip():
                  telegram_patch.pop("bot_token", None)
              current.setdefault("telegram", {}).update(telegram_patch)
              current.setdefault("llm", {}).update(patch.get("llm", {}))
              current.setdefault("schedule", {}).update(patch.get("schedule", {}))
              updated = save_agent_settings(current)
          except Exception as exc:
              self._send_json(400, {"error": str(exc)})
              return
          self._send_json(200, self._public_agent_settings_payload(updated))
          return
      if self.path != "/api/profile":
          self._send_json(404, {"error": "Not found"})
          return
      try:
          current = load_profile()
          patch = self._normalize_profile_patch_for_save(current, self._read_json_body())
          updated = patch_profile(patch)
          if self._patch_affects_matching_rules(patch):
              self._rebuild_dashboard_after_rule_change("profile matching rules saved")
      except Exception as exc:
          self._send_json(400, {"error": str(exc)})
          return
      self._send_json(200, updated)

    def do_PUT(self) -> None:
        if self.path == "/api/profile":
            try:
                updated = save_profile(self._read_json_body())
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, updated)
            return
        if self.path == "/api/source-materials":
            try:
                updated = save_source_materials(self._read_json_body())
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, updated)
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if self.path == "/api/test/reset-user":
            if not TEST_MODE:
                self._send_json(403, {"error": "Test mode only"})
                return
            try:
                result = self._reset_current_user_state()
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/test/reset-learning":
            if not TEST_MODE:
                self._send_json(403, {"error": "Test mode only"})
                return
            try:
                result = self._reset_global_learning()
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/run":
            try:
                payload = self._read_json_body()
                search_settings = _normalize_search_settings_payload(payload)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return

            if not _try_mark_run_started():
                last_run = _read_last_run_timestamp()
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "status": "running",
                        "last_run_at": last_run,
                        "has_run": last_run is not None,
                    },
                )
                return

            try:
                if search_settings:
                    patch_profile({"search_settings": search_settings})
                thread = threading.Thread(
                    target=_run_scrape_job,
                    daemon=True,
                )
                thread.start()
            except Exception:
                _set_run_in_progress(False)
                raise
            last_run = _read_last_run_timestamp()
            self._send_json(
                200,
                {
                    "ok": True,
                    "status": "started",
                    "last_run_at": last_run,
                    "has_run": last_run is not None,
                },
            )
            return
        if self.path == "/api/onboarding/import":
            try:
                payload = self._read_json_body()
                files = payload.get("files", [])
                search_prefs = _normalize_onboarding_search_preferences(payload.get("search_preferences"))
                onboarding_settings = _normalize_onboarding_settings_payload(payload.get("onboarding_settings"))
                if not isinstance(files, list):
                    raise ValueError("files must be a list")
                if not files:
                    raise ValueError("Please upload your detailed CV before continuing.")
                allowed_suffixes = {".docx", ".md", ".txt"}
                for item in files:
                    if not isinstance(item, dict):
                        raise ValueError("Each uploaded file must include a filename and content.")
                    filename = str(item.get("filename") or "").strip()
                    if not filename:
                        raise ValueError("Each uploaded file needs a filename.")
                    suffix = Path(filename).suffix.lower()
                    if suffix not in allowed_suffixes:
                        raise ValueError("Please upload CV files as .docx, .md, or .txt.")
                materials = (
                    persist_uploaded_source_pack(files)
                    if files
                    else load_source_materials(create_if_missing=True)
                )
                patch_profile({"onboarding_settings": onboarding_settings})
                result = run_onboarding(materials, search_preferences=search_prefs, onboarding_settings=onboarding_settings)
                result["materials"] = materials
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/onboarding/confirm-profile-signals":
            try:
                payload = self._read_json_body()
                target = [str(p).strip() for p in payload.get("primary_job_title_pattern", []) if str(p).strip()]
                secondary = [str(p).strip() for p in payload.get("secondary_title_patterns", []) if str(p).strip()]
                keyword = str(payload.get("search_keyword") or "").strip()
                locations = [str(value).strip() for value in payload.get("search_locations", []) if str(value).strip()]
                engagement_type = str(payload.get("engagement_type") or "").strip().lower()
                raw_minimum_salary_yearly = payload.get("minimum_salary_yearly")
                raw_minimum_daily_rate = payload.get("minimum_daily_rate")
                capability_rules = normalize_capability_rules(payload.get("capability_profile_rules") or [])
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
                    if not _LOCATION_NAME_RE.fullmatch(location):
                        raise ValueError("Search locations should look like normal city, state, or region names.")
                if engagement_type not in _VALID_ENGAGEMENT_TYPES:
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
                    "primary_job_title_pattern": target,
                    "secondary_title_patterns": secondary,
                }
                if capability_rules:
                    profile_patch["capability_profile_rules"] = capability_rules
                current = load_profile()
                search_settings = dict(current.get("search_settings", {}))
                if keyword:
                    search_settings["keywords"] = keyword
                elif not str(search_settings.get("keywords") or "").strip():
                    search_settings["keywords"] = target[0]
                search_settings["locations"] = locations
                profile_patch["search_settings"] = search_settings
                match_preferences = dict(current.get("match_preferences", {}))
                match_preferences["engagement_type"] = engagement_type
                profile_patch["match_preferences"] = match_preferences
                profile_patch["salary_preferences"] = {
                    "minimum_salary_yearly": minimum_salary_yearly,
                    "minimum_daily_rate": minimum_daily_rate,
                }
                updated = patch_profile(profile_patch)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "message": "Onboarding profile saved.", "profile": updated})
            return
        if self.path in {"/api/tuning-decisions", "/api/skill-decisions"}:
            try:
                payload = self._read_json_body()
                decisions = payload.get("decisions", [])
                if not isinstance(decisions, list):
                    raise ValueError("decisions must be a list")
                profile = load_profile()
                updated = apply_capability_tuning_decisions(profile, decisions)
                save_profile(updated)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Capability tuning suggestions applied to profile.json.",
                    "profile": updated,
                },
            )
            return
        if self.path == "/api/rule/phrase":
            try:
                payload = self._read_json_body()
                phrase = str(payload.get("phrase") or "").strip().lower()
                reason = str(payload.get("reason") or "").strip()
                if not phrase:
                    raise ValueError("phrase is required")
                profile = load_profile()
                existing = list(profile.get("reject_description_phrase_rules", []))
                if not any(str(r.get("phrase") or "").strip().lower() == phrase for r in existing):
                    existing.append({"phrase": phrase, "reason": reason or f"DESC_REJECT:{phrase}"})
                    profile["reject_description_phrase_rules"] = existing
                    updated = save_profile(profile)
                    self._rebuild_dashboard_after_rule_change(f"description phrase rule added for {phrase}")
                else:
                    updated = profile
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "message": f"Phrase rule added: {phrase}", "profile": updated})
            return
        if self.path == "/api/rejection-feedback/mandatory-blockers":
            try:
                payload = self._read_json_body()
                blockers = payload.get("blockers", [])
                title_block_phrases = payload.get("title_block_phrases", [])
                description_block_phrases = payload.get("description_block_phrases", [])
                approved_suggestion_tokens = payload.get("approved_suggestion_tokens") or {}
                if not isinstance(blockers, list):
                    raise ValueError("blockers must be a list")
                if title_block_phrases is None:
                    title_block_phrases = []
                if description_block_phrases is None:
                    description_block_phrases = []
                if not isinstance(title_block_phrases, list):
                    raise ValueError("title_block_phrases must be a list")
                if not isinstance(description_block_phrases, list):
                    raise ValueError("description_block_phrases must be a list")
                if not isinstance(approved_suggestion_tokens, dict):
                    raise ValueError("approved_suggestion_tokens must be an object")
                resolved_job_id = str(payload.get("job_id") or payload.get("job_key") or "").strip()
                self._validate_llm_suggestion_approvals(
                    resolved_job_id,
                    [str(item or "") for item in blockers],
                    approved_suggestion_tokens=approved_suggestion_tokens,
                )
                result = self._save_requirement_blockers_feedback(
                    resolved_job_id,
                    url=str(payload.get("url") or "").strip(),
                    title=str(payload.get("job_title") or payload.get("title") or "").strip(),
                    company=str(payload.get("company") or "").strip(),
                    teaser=str(payload.get("teaser") or "").strip(),
                    blockers=[str(item or "") for item in blockers],
                    title_block_phrases=[str(item or "") for item in title_block_phrases],
                    description_block_phrases=[str(item or "") for item in description_block_phrases],
                )
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, result)
            return
        if self.path == "/api/telegram/sync":
            try:
                settings = load_agent_settings(create_if_missing=True)
                result = sync_telegram_subscribers(settings["telegram"])
                updated = save_agent_settings(settings)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": f"Telegram sync complete. {result['total_subscribers']} connected Telegram account(s) found.",
                    "result": result,
                    "settings": self._public_agent_settings_payload(updated),
                },
            )
            return
        if self.path == "/api/telegram/test-message":
            try:
                self._read_json_body()
                settings = load_agent_settings(create_if_missing=True)
                message_text = "Job Hunter test alert. Telegram is connected correctly."
                result = send_telegram_notification(message_text, "", settings["telegram"])
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "Telegram test message sent.",
                    "result": result,
                },
            )
            return
        if self.path == "/api/rejection-rules":
            try:
                payload = self._read_json_body()
                job_id = str(payload.get("job_id") or "").strip()
                job_title = str(payload.get("job_title") or "").strip()
                raw_rules = payload.get("rules")
                if not isinstance(raw_rules, list):
                    raise ValueError("rules must be a list")
                validated = []
                now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
                approved_suggestion_tokens = payload.get("approved_suggestion_tokens") or {}
                if not isinstance(approved_suggestion_tokens, dict):
                    raise ValueError("approved_suggestion_tokens must be an object")
                raw_values = [str(r.get("value") or "").strip() for r in raw_rules if isinstance(r, dict)]
                self._validate_llm_suggestion_approvals(
                    job_id,
                    raw_values,
                    approved_suggestion_tokens=approved_suggestion_tokens,
                )
                for i, r in enumerate(raw_rules):
                    value = str(r.get("value") or "").strip()
                    category = str(r.get("category") or "other").strip()
                    if not value or len(value) < 3:
                        continue
                    if value.lower() in _REJECTION_RULE_JUNK_VALUES:
                        continue
                    if category not in _VALID_REJECTION_RULE_CATEGORIES:
                        category = "other"
                    validated.append({
                        "id": f"{job_id}_{now_iso}_{i}",
                        "job_id": job_id,
                        "job_title": job_title,
                        "value": value,
                        "category": category,
                        "source": str(r.get("source") or "user_selected"),
                        "active": True,
                        "created_at": now_iso,
                    })
                if not validated:
                    raise ValueError("No valid rules provided (check minimum length >= 3)")
                existing = self._load_rejection_rules()
                existing.extend(validated)
                self._save_rejection_rules_list(existing)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "saved": len(validated)})
            return

        if self.path == "/api/title-block-preview":
            try:
                import re as _re
                payload = self._read_json_body()
                phrases = [str(p).strip() for p in (payload.get("phrases") or []) if str(p).strip()]
                titles: list[str] = []
                if AUDIT_RECORDS_PATH.exists():
                    try:
                        rows = json.loads(AUDIT_RECORDS_PATH.read_text(encoding="utf-8"))
                        if isinstance(rows, list):
                            titles = [str(r.get("title") or "").lower() for r in rows if r.get("title")]
                    except Exception:
                        pass
                counts: dict[str, int] = {}
                for phrase in phrases:
                    norm = _re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
                    tokens = [t for t in norm.split() if t]
                    if not tokens:
                        counts[phrase] = 0
                        continue
                    pattern = r"\b" + r"\s+".join(_re.escape(t) for t in tokens[:3]) + r"\b"
                    counts[phrase] = sum(1 for t in titles if _re.search(pattern, t))
                matched_titles: set[str] = set()
                for phrase in phrases:
                    norm = _re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
                    tokens = [t for t in norm.split() if t]
                    if not tokens:
                        continue
                    pattern = r"\b" + r"\s+".join(_re.escape(t) for t in tokens[:3]) + r"\b"
                    for t in titles:
                        if _re.search(pattern, t):
                            matched_titles.add(t)
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"counts": counts, "total": len(matched_titles)})
            return

        if self.path != "/api/review":
            self._send_json(404, {"error": "Not found"})
            return
        try:
            payload = self._read_json_body()
            action = str(payload.get("action", "")).strip().lower()
            job_key = str(payload.get("job_key") or payload.get("url") or "").strip()
            url = str(payload.get("url") or "").strip()
            title = str(payload.get("title") or "").strip()
            company = str(payload.get("company") or "").strip()
            teaser = str(payload.get("teaser") or "").strip()
            if action == "viewed":
                result = self._record_job_view(
                    job_key,
                    url,
                    title,
                )
            elif action == "not_for_me":
                result = self._save_not_for_me_feedback(
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
            elif action == "block_similar":
                raw = payload.get("block_phrases")
                if isinstance(raw, list) and raw:
                    phrases_arg = [str(p).strip() for p in raw if str(p).strip()]
                else:
                    single = str(payload.get("block_phrase") or "").strip()
                    phrases_arg = [single] if single else []
                result = self._save_block_similar_feedback(
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                    block_phrases=phrases_arg or None,
                )
            elif action in {"unapply", "unhide"}:
                result = self._remove_review_key(
                    action,
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
            else:
                result = self._append_review_key(
                    action,
                    job_key,
                    url,
                    title,
                    company,
                    teaser,
                )
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})
            return
        self._send_json(200, result)

    def do_DELETE(self) -> None:
        if self.path == "/api/rule/title-block":
            try:
                payload = self._read_json_body()
                pattern = str(payload.get("pattern") or "").strip()
                if not pattern:
                    raise ValueError("pattern is required")
                profile = load_profile()
                existing = list(profile.get("reject_title_rules", []))
                updated_rules = [r for r in existing if str(r.get("pattern") or "").strip() != pattern]
                if len(updated_rules) == len(existing):
                    self._send_json(404, {"error": "Rule not found"})
                    return
                profile["reject_title_rules"] = updated_rules
                saved = save_profile(profile)
                self._rebuild_dashboard_after_rule_change(f"title block rule removed: {pattern}")
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
                return
            self._send_json(200, {"ok": True, "reject_title_rules": saved.get("reject_title_rules", [])})
            return
        self._send_json(404, {"error": "Not found"})

    def log_message(self, format: str, *args) -> None:
        if TEST_MODE:
            super().log_message(format, *args)
        return


AdminHandler = SettingsHandler


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), SettingsHandler)
    print(f"Local server running at http://{HOST}:{PORT}")
    print(f"Test mode:  {'ON (--test-mode)' if TEST_MODE else 'OFF'}")
    print(f"Workspace:  http://{HOST}:{PORT}/")
    print(f"Settings:   http://{HOST}:{PORT}/settings")
    print(f"Onboarding: http://{HOST}:{PORT}/start")
    server.serve_forever()
