"""Local agent settings and state helpers.

Main goals:
- load a repo-safe agent settings template
- support a local ignored override file for real credentials and delivery targets
- persist lightweight agent state between scheduled runs
"""

import copy
import json
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
AGENT_SETTINGS_PATH = DATA_DIR / "agent_settings.json"
AGENT_SETTINGS_TEMPLATE_PATH = DATA_DIR / "agent_settings.template.json"
AGENT_STATE_PATH = DATA_DIR / "agent_state.json"

DEFAULT_AGENT_SETTINGS = {
    "dashboard_url": "http://127.0.0.1:8765/dashboard",
    "schedule": {
        "daily_time_local": "08:30",
        "loop_sleep_seconds": 300,
    },
    "notification_rules": {
        "max_jobs_in_digest": 5,
        "minimum_fit_score": 52,
        "only_if_new_matches": True,
    },
    "email": {
        "enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_username": "",
        "smtp_password": "",
        "use_tls": True,
        "from_address": "",
        "to_addresses": [],
        "subject_prefix": "[Job Hunter]",
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": "",
        "disable_link_preview": False,
    },
}


def _deep_merge(base: Any, patch: Any) -> Any:
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = _deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(patch)


def normalize_agent_settings(payload: Any) -> dict[str, Any]:
    settings = _deep_merge(copy.deepcopy(DEFAULT_AGENT_SETTINGS), payload if isinstance(payload, dict) else {})

    settings["dashboard_url"] = str(settings.get("dashboard_url") or "").strip()

    schedule = settings.get("schedule", {})
    settings["schedule"] = {
        "daily_time_local": str(schedule.get("daily_time_local") or DEFAULT_AGENT_SETTINGS["schedule"]["daily_time_local"]).strip(),
        "loop_sleep_seconds": max(60, int(schedule.get("loop_sleep_seconds", DEFAULT_AGENT_SETTINGS["schedule"]["loop_sleep_seconds"]) or 300)),
    }

    notification_rules = settings.get("notification_rules", {})
    settings["notification_rules"] = {
        "max_jobs_in_digest": max(1, min(int(notification_rules.get("max_jobs_in_digest", 5) or 5), 20)),
        "minimum_fit_score": max(0, min(int(notification_rules.get("minimum_fit_score", 52) or 52), 100)),
        "only_if_new_matches": bool(notification_rules.get("only_if_new_matches", True)),
    }

    email = settings.get("email", {})
    settings["email"] = {
        "enabled": bool(email.get("enabled", False)),
        "smtp_host": str(email.get("smtp_host") or "").strip(),
        "smtp_port": int(email.get("smtp_port", 587) or 587),
        "smtp_username": str(email.get("smtp_username") or "").strip(),
        "smtp_password": str(email.get("smtp_password") or "").strip(),
        "use_tls": bool(email.get("use_tls", True)),
        "from_address": str(email.get("from_address") or "").strip(),
        "to_addresses": [str(value).strip() for value in email.get("to_addresses", []) if str(value).strip()],
        "subject_prefix": str(email.get("subject_prefix") or "[Job Hunter]").strip() or "[Job Hunter]",
    }

    telegram = settings.get("telegram", {})
    settings["telegram"] = {
        "enabled": bool(telegram.get("enabled", False)),
        "bot_token": str(telegram.get("bot_token") or "").strip(),
        "chat_id": str(telegram.get("chat_id") or "").strip(),
        "disable_link_preview": bool(telegram.get("disable_link_preview", False)),
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
