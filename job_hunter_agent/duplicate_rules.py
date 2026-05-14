from __future__ import annotations

import json
from typing import Any

from job_hunter_agent.paths import DUPLICATE_RULES_PATH


def _load_payload() -> dict[str, Any]:
    if not DUPLICATE_RULES_PATH.exists():
        return {}
    try:
        payload = json.loads(DUPLICATE_RULES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    source_priority = normalized.get("source_priority")
    if not isinstance(source_priority, dict):
        raise ValueError("duplicate_rules.json must define source_priority as an object")
    cleaned_priority: dict[str, int] = {}
    for key, value in source_priority.items():
        cleaned_key = str(key).strip().lower()
        if not cleaned_key:
            continue
        cleaned_priority[cleaned_key] = int(value)
    if not cleaned_priority:
        raise ValueError("duplicate_rules.json must define at least one source priority")
    normalized["source_priority"] = cleaned_priority
    return normalized


def load_duplicate_rules() -> dict[str, Any]:
    payload = _load_payload()
    if not payload:
        raise ValueError("duplicate_rules.json must contain a rules object")
    return _normalize_config(payload)


def save_duplicate_rules(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_config(payload)
    normalized.setdefault("kind", "system_config")
    normalized.setdefault("name", "duplicate_rules")
    normalized.setdefault("version", 1)
    DUPLICATE_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    DUPLICATE_RULES_PATH.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return normalized
