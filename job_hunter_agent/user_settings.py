"""Per-user settings and agent state helpers.

This module manages user-specific configurations and the persistent state of the agent. 
It provides functions for loading, normalizing, and saving user settings, including
workspace preferences, scheduling, notification rules (email, Telegram), and LLM model choices.
It also handles the loading and saving of the agent's runtime state.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from job_hunter_agent.match_labels import MATCH_LEVELS
from job_hunter_agent.paths import DEFAULT_USER_SETTINGS_PATH, get_user_settings_path
from job_hunter_agent.utils import coerce_int, deep_merge


USER_STATE_FILENAME = "agent_state.json"

# Settings keys
KEY_WORKSPACE = "workspace"
KEY_SCHEDULE = "schedule"
KEY_NOTIFICATION_RULES = "notification_rules"
KEY_EMAIL = "email"
KEY_TELEGRAM = "telegram"
KEY_LLM = "llm"
KEY_ONLY_IF_NEW_MATCHES = "only_if_new_matches"


def _possible_fit_threshold() -> int:
    for level in MATCH_LEVELS:
        if str(level.get("label", "")).strip().lower() == "possible fit":
            return int(level["minimum_score"])
    sorted_levels = sorted(MATCH_LEVELS, key=lambda l: int(l.get("minimum_score", 0)))
    if len(sorted_levels) >= 2:
        return int(sorted_levels[1]["minimum_score"])
    return int(sorted_levels[0]["minimum_score"]) if sorted_levels else 0


MIN_SCORE = 0
MAX_SCORE = 100

MIN_LOOP_SLEEP_SECONDS = 60
MAX_LOOP_SLEEP_SECONDS = 86400

MIN_MAX_JOBS_IN_DIGEST = 1
MAX_MAX_JOBS_IN_DIGEST = 20

MAX_TELEGRAM_UPDATE_ID = 2147483647

def _load_default_user_settings_seed() -> dict[str, Any]:
    payload = json.loads(DEFAULT_USER_SETTINGS_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("user_settings.json must contain a JSON object")
    return payload


DEFAULT_USER_SETTINGS = _load_default_user_settings_seed()

DEFAULT_WORKSPACE_URL = str(DEFAULT_USER_SETTINGS.get("workspace_url") or "").strip()
DEFAULT_WORKSPACE_MIN_SCORE = int(DEFAULT_USER_SETTINGS[KEY_WORKSPACE]["minimum_score"])
DEFAULT_DAILY_TIME_LOCAL = str(DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["daily_time_local"]).strip()
DEFAULT_LOOP_SLEEP_SECONDS = int(DEFAULT_USER_SETTINGS[KEY_SCHEDULE]["loop_sleep_seconds"])
DEFAULT_MAX_JOBS_IN_DIGEST = int(DEFAULT_USER_SETTINGS[KEY_NOTIFICATION_RULES]["max_jobs_in_digest"])
DEFAULT_MINIMUM_FIT_SCORE = int(DEFAULT_USER_SETTINGS[KEY_NOTIFICATION_RULES]["minimum_fit_score"])
DEFAULT_ONLY_IF_NEW_MATCHES = bool(DEFAULT_USER_SETTINGS[KEY_NOTIFICATION_RULES][KEY_ONLY_IF_NEW_MATCHES])
DEFAULT_SMTP_PORT = int(DEFAULT_USER_SETTINGS[KEY_EMAIL]["smtp_port"])
DEFAULT_SUBJECT_PREFIX = str(DEFAULT_USER_SETTINGS[KEY_EMAIL]["subject_prefix"]).strip()
DEFAULT_LLM_MODEL = str(DEFAULT_USER_SETTINGS[KEY_LLM]["model"]).strip()


def normalize_user_settings(payload: Any) -> dict[str, Any]:
    defaults = DEFAULT_USER_SETTINGS
    settings = deep_merge(copy.deepcopy(defaults), payload if isinstance(payload, dict) else {})

    settings["workspace_url"] = str(settings.get("workspace_url") or "").strip()

    workspace = settings.get(KEY_WORKSPACE, {})
    settings[KEY_WORKSPACE] = {
        "minimum_score": coerce_int(
            workspace.get("minimum_score"),
            defaults[KEY_WORKSPACE]["minimum_score"],
            MIN_SCORE,
            MAX_SCORE,
        ),
    }

    schedule = settings.get(KEY_SCHEDULE, {})
    settings[KEY_SCHEDULE] = {
        "daily_time_local": str(schedule.get("daily_time_local") or defaults[KEY_SCHEDULE]["daily_time_local"]).strip(),
        "loop_sleep_seconds": coerce_int(
            schedule.get("loop_sleep_seconds"),
            defaults[KEY_SCHEDULE]["loop_sleep_seconds"],
            MIN_LOOP_SLEEP_SECONDS,
            MAX_LOOP_SLEEP_SECONDS,
        ),
    }

    notification_rules = settings.get(KEY_NOTIFICATION_RULES, {})
    settings[KEY_NOTIFICATION_RULES] = {
        "max_jobs_in_digest": coerce_int(
            notification_rules.get("max_jobs_in_digest"),
            defaults[KEY_NOTIFICATION_RULES]["max_jobs_in_digest"],
            MIN_MAX_JOBS_IN_DIGEST,
            MAX_MAX_JOBS_IN_DIGEST,
        ),
        "minimum_fit_score": coerce_int(
            notification_rules.get("minimum_fit_score"),
            defaults[KEY_NOTIFICATION_RULES]["minimum_fit_score"],
            MIN_SCORE,
            MAX_SCORE,
        ),
        KEY_ONLY_IF_NEW_MATCHES: bool(notification_rules.get(KEY_ONLY_IF_NEW_MATCHES, defaults[KEY_NOTIFICATION_RULES][KEY_ONLY_IF_NEW_MATCHES])),
    }

    email = settings.get(KEY_EMAIL, {})
    settings[KEY_EMAIL] = {
        "enabled": bool(email.get("enabled", defaults[KEY_EMAIL]["enabled"])),
        "smtp_host": str(email.get("smtp_host") or defaults[KEY_EMAIL]["smtp_host"]).strip(),
        "smtp_port": coerce_int(email.get("smtp_port"), defaults[KEY_EMAIL]["smtp_port"], 1, 65535),
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
        "last_update_id": coerce_int(
            telegram.get("last_update_id"),
            defaults[KEY_TELEGRAM]["last_update_id"],
            0,
            MAX_TELEGRAM_UPDATE_ID,
        ),
        "subscribers": normalized_subscribers,
    }

    return settings


def load_user_settings(user_id: str | None, create_if_missing: bool = False) -> dict[str, Any]:
    settings_path = get_user_settings_path(user_id)
    if settings_path.exists():
        return normalize_user_settings(json.loads(settings_path.read_text(encoding="utf-8")))

    settings = copy.deepcopy(DEFAULT_USER_SETTINGS)
    if create_if_missing:
        save_user_settings(user_id, settings)
    return settings


def save_user_settings(user_id: str | None, payload: Any) -> dict[str, Any]:
    normalized = normalize_user_settings(payload)
    settings_path = get_user_settings_path(user_id)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def get_workspace_minimum_score(settings: Any | None = None, *, user_id: str | None = None) -> int:
    if isinstance(settings, dict):
        active_settings = normalize_user_settings(settings)
    else:
        active_settings = load_user_settings(user_id, create_if_missing=True)
    return int(active_settings[KEY_WORKSPACE]["minimum_score"])


def load_agent_state(user_id: str | None = None) -> dict[str, Any]:
    state_path = get_user_settings_path(user_id).parent / USER_STATE_FILENAME
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception as exc:
        print(f"[USER_SETTINGS][WARN] Failed to load agent state from {state_path}: {exc}")
        pass
    return {}


def save_agent_state(payload: dict[str, Any], user_id: str | None = None) -> dict[str, Any]:
    state_path = get_user_settings_path(user_id).parent / USER_STATE_FILENAME
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(payload or {}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload
