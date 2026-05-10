"""Local agent settings and state helpers.

Main goals:
- load a repo-safe agent settings template
- support a local ignored override file for real credentials and delivery targets
- persist lightweight agent state between scheduled runs
"""

import copy
import json
from typing import Any

from job_hunter_agent.paths import DATA_DIR, REPO_ROOT
from job_hunter_agent.match_labels import MATCH_LEVELS


ROOT_DIR = REPO_ROOT
AGENT_SETTINGS_PATH = DATA_DIR / "agent_settings.json"
AGENT_SETTINGS_TEMPLATE_PATH = DATA_DIR / "agent_settings.template.json"
AGENT_STATE_PATH = DATA_DIR / "agent_state.json"

# Settings keys
KEY_DASHBOARD = "dashboard"
KEY_SCHEDULE = "schedule"
KEY_NOTIFICATION_RULES = "notification_rules"
KEY_EMAIL = "email"
KEY_TELEGRAM = "telegram"
KEY_LLM = "llm"
KEY_ONLY_IF_NEW_MATCHES = "only_if_new_matches"


def _possible_fit_threshold() -> int:
    """Derive the dashboard minimum score default from the 'Possible fit' match level."""
    for level in MATCH_LEVELS:
        if str(level.get("label", "")).strip().lower() == "possible fit":
            return int(level["minimum_score"])
    sorted_levels = sorted(MATCH_LEVELS, key=lambda l: int(l.get("minimum_score", 0)))
    if len(sorted_levels) >= 2:
        return int(sorted_levels[1]["minimum_score"])
    return int(sorted_levels[0]["minimum_score"]) if sorted_levels else 0


# Validation limits and defaults
DEFAULT_DASHBOARD_URL = "http://127.0.0.1:8765/dashboard"
DEFAULT_DASHBOARD_MIN_SCORE = _possible_fit_threshold()
MIN_SCORE = 0
MAX_SCORE = 100

DEFAULT_DAILY_TIME_LOCAL = "08:30"
DEFAULT_LOOP_SLEEP_SECONDS = 300
MIN_LOOP_SLEEP_SECONDS = 60
MAX_LOOP_SLEEP_SECONDS = 86400

DEFAULT_MAX_JOBS_IN_DIGEST = 5
MIN_MAX_JOBS_IN_DIGEST = 1
MAX_MAX_JOBS_IN_DIGEST = 20
DEFAULT_MINIMUM_FIT_SCORE = 52
DEFAULT_ONLY_IF_NEW_MATCHES = True

DEFAULT_SMTP_PORT = 587
DEFAULT_SUBJECT_PREFIX = "[Job Hunter]"

MAX_TELEGRAM_UPDATE_ID = 2147483647
DEFAULT_LLM_MODEL = "gpt-4o-mini"

DEFAULT_AGENT_SETTINGS = {
    "dashboard_url": DEFAULT_DASHBOARD_URL,
    KEY_DASHBOARD: {
        "minimum_score": DEFAULT_DASHBOARD_MIN_SCORE,
    },
    KEY_SCHEDULE: {
        "daily_time_local": DEFAULT_DAILY_TIME_LOCAL,
        "loop_sleep_seconds": DEFAULT_LOOP_SLEEP_SECONDS,
    },
    KEY_NOTIFICATION_RULES: {
        "max_jobs_in_digest": DEFAULT_MAX_JOBS_IN_DIGEST,
        "minimum_fit_score": DEFAULT_MINIMUM_FIT_SCORE,
        KEY_ONLY_IF_NEW_MATCHES: DEFAULT_ONLY_IF_NEW_MATCHES,
    },
    KEY_EMAIL: {
        "enabled": False,
        "smtp_host": "",
        "smtp_port": DEFAULT_SMTP_PORT,
        "smtp_username": "",
        "smtp_password": "",
        "use_tls": True,
        "from_address": "",
        "to_addresses": [],
        "subject_prefix": DEFAULT_SUBJECT_PREFIX,
    },
    KEY_TELEGRAM: {
        "enabled": False,
        "bot_token": "",
        "bot_username": "",
        "chat_id": "",
        "disable_link_preview": False,
        "last_update_id": 0,
        "subscribers": [],
    },
    KEY_LLM: {
        "model": DEFAULT_LLM_MODEL,
    },
}


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(patch)


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        resolved = int(value)
    except Exception:
        resolved = default
    return max(minimum, min(maximum, resolved))


def normalize_agent_settings(payload: Any) -> dict[str, Any]:
    defaults = DEFAULT_AGENT_SETTINGS
    settings = _deep_merge(copy.deepcopy(defaults), payload if isinstance(payload, dict) else {})

    settings["dashboard_url"] = str(settings.get("dashboard_url") or "").strip()

    dashboard = settings.get(KEY_DASHBOARD, {})
    settings[KEY_DASHBOARD] = {
        "minimum_score": _coerce_int(
            dashboard.get("minimum_score"),
            defaults[KEY_DASHBOARD]["minimum_score"],
            MIN_SCORE, MAX_SCORE
        ),
    }

    schedule = settings.get(KEY_SCHEDULE, {})
    settings[KEY_SCHEDULE] = {
        "daily_time_local": str(schedule.get("daily_time_local") or defaults[KEY_SCHEDULE]["daily_time_local"]).strip(),
        "loop_sleep_seconds": _coerce_int(
            schedule.get("loop_sleep_seconds"),
            defaults[KEY_SCHEDULE]["loop_sleep_seconds"],
            MIN_LOOP_SLEEP_SECONDS, MAX_LOOP_SLEEP_SECONDS
        ),
    }

    notification_rules = settings.get(KEY_NOTIFICATION_RULES, {})
    settings[KEY_NOTIFICATION_RULES] = {
        "max_jobs_in_digest": _coerce_int(notification_rules.get("max_jobs_in_digest"), defaults[KEY_NOTIFICATION_RULES]["max_jobs_in_digest"], MIN_MAX_JOBS_IN_DIGEST, MAX_MAX_JOBS_IN_DIGEST),
        "minimum_fit_score": _coerce_int(notification_rules.get("minimum_fit_score"), defaults[KEY_NOTIFICATION_RULES]["minimum_fit_score"], MIN_SCORE, MAX_SCORE),
        KEY_ONLY_IF_NEW_MATCHES: bool(notification_rules.get(KEY_ONLY_IF_NEW_MATCHES, defaults[KEY_NOTIFICATION_RULES][KEY_ONLY_IF_NEW_MATCHES])),
    }

    email = settings.get(KEY_EMAIL, {})
    settings[KEY_EMAIL] = {
        "enabled": bool(email.get("enabled", defaults[KEY_EMAIL]["enabled"])),
        "smtp_host": str(email.get("smtp_host") or defaults[KEY_EMAIL]["smtp_host"]).strip(),
        "smtp_port": _coerce_int(email.get("smtp_port"), defaults[KEY_EMAIL]["smtp_port"], 1, 65535),
        "smtp_username": str(email.get("smtp_username") or defaults[KEY_EMAIL]["smtp_username"]).strip(),
        "smtp_password": str(email.get("smtp_password") or defaults[KEY_EMAIL]["smtp_password"]).strip(),
        "use_tls": bool(email.get("use_tls", defaults[KEY_EMAIL]["use_tls"])),
        "from_address": str(email.get("from_address") or defaults[KEY_EMAIL]["from_address"]).strip(),
        "to_addresses": [str(value).strip() for value in email.get("to_addresses", defaults[KEY_EMAIL]["to_addresses"]) if str(value).strip()],
        "subject_prefix": str(email.get("subject_prefix") or defaults[KEY_EMAIL]["subject_prefix"]).strip() or defaults[KEY_EMAIL]["subject_prefix"],
    }

    telegram = settings.get(KEY_TELEGRAM, {})
    subscribers = telegram.get("subscribers", [])
    normalized_subscribers = []
    if isinstance(subscribers, list):
        for item in subscribers:
            if not isinstance(item, dict):
                continue
            chat_id = str(item.get("chat_id") or "").strip()
            if not chat_id:
                continue
            normalized_subscribers.append({
                "chat_id": chat_id,
                "username": str(item.get("username") or "").strip(),
                "first_name": str(item.get("first_name") or "").strip(),
                "last_name": str(item.get("last_name") or "").strip(),
                "connected_at": str(item.get("connected_at") or "").strip(),
                "last_seen_at": str(item.get("last_seen_at") or "").strip(),
            })
    settings[KEY_TELEGRAM] = {
        "enabled": bool(telegram.get("enabled", defaults[KEY_TELEGRAM]["enabled"])),
        "bot_token": str(telegram.get("bot_token") or defaults[KEY_TELEGRAM]["bot_token"]).strip(),
        "bot_username": str(telegram.get("bot_username") or defaults[KEY_TELEGRAM]["bot_username"]).strip().lstrip("@"),
        "chat_id": str(telegram.get("chat_id") or defaults[KEY_TELEGRAM]["chat_id"]).strip(),
        "disable_link_preview": bool(telegram.get("disable_link_preview", defaults[KEY_TELEGRAM]["disable_link_preview"])),
        "last_update_id": _coerce_int(telegram.get("last_update_id"), defaults[KEY_TELEGRAM]["last_update_id"], 0, MAX_TELEGRAM_UPDATE_ID),
        "subscribers": normalized_subscribers,
    }

    return settings


def load_agent_settings(create_if_missing: bool = False) -> dict[str, Any]:
    if AGENT_SETTINGS_PATH.exists():
        try:
            return normalize_agent_settings(json.loads(AGENT_SETTINGS_PATH.read_text(encoding="utf-8")))
        except Exception:
            return copy.deepcopy(DEFAULT_AGENT_SETTINGS)

    if AGENT_SETTINGS_TEMPLATE_PATH.exists():
        try:
            settings = normalize_agent_settings(json.loads(AGENT_SETTINGS_TEMPLATE_PATH.read_text(encoding="utf-8")))
        except Exception:
            settings = copy.deepcopy(DEFAULT_AGENT_SETTINGS)
        if create_if_missing:
            save_agent_settings(settings)
        return settings

    settings = copy.deepcopy(DEFAULT_AGENT_SETTINGS)
    if create_if_missing:
        save_agent_settings(settings)
    return settings


def save_agent_settings(payload: Any) -> dict[str, Any]:
    normalized = normalize_agent_settings(payload)
    AGENT_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_SETTINGS_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def get_dashboard_minimum_score(settings: Any | None = None) -> int:
    if isinstance(settings, dict):
        active_settings = normalize_agent_settings(settings)
    else:
        active_settings = load_agent_settings(create_if_missing=True)
    return int(active_settings[KEY_DASHBOARD]["minimum_score"])


def load_agent_state() -> dict[str, Any]:
    if not AGENT_STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(AGENT_STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def save_agent_state(payload: dict[str, Any]) -> dict[str, Any]:
    AGENT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_STATE_PATH.write_text(
        json.dumps(payload or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload
