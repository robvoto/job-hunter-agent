from __future__ import annotations

import json
import re
from typing import Any

from job_hunter_agent.paths import ROLE_TITLE_KNOWLEDGE_PATH


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_payload() -> dict[str, Any]:
    if not ROLE_TITLE_KNOWLEDGE_PATH.exists():
        return {"entries": []}
    try:
        payload = json.loads(ROLE_TITLE_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    value = _clean_text(entry.get("value"))
    if not value:
        return None
    return {"value": value}


def _merge_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in entries:
        normalized = _normalize_entry(entry)
        if normalized is None:
            continue
        value_key = normalized["value"].lower()
        bucket = merged.get(value_key)
        if bucket is None:
            bucket = {"value": normalized["value"]}
            merged[value_key] = bucket
            order.append(value_key)
    return [merged[key] for key in order]


def load_role_title_knowledge() -> list[dict[str, Any]]:
    payload = _load_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("role_title_knowledge.json must contain an entries list")

    cleaned_entries = _merge_entries(entries)
    if cleaned_entries != entries:
        save_role_title_knowledge(cleaned_entries)
    return cleaned_entries


def save_role_title_knowledge(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _load_payload()
    payload.setdefault("kind", "managed_knowledge")
    payload.setdefault("name", "role_title_knowledge")
    payload.setdefault("version", 1)
    payload.setdefault("updated_at", "")
    payload.setdefault("description", "")
    cleaned_entries = _merge_entries(entries)
    payload["entries"] = cleaned_entries
    ROLE_TITLE_KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROLE_TITLE_KNOWLEDGE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def upsert_role_title_entry(value: str) -> dict[str, Any]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    entries = list(load_role_title_knowledge())
    for entry in entries:
        if _clean_text(entry.get("value")).lower() != cleaned_value.lower():
            continue
        entry["value"] = cleaned_value
        return save_role_title_knowledge(entries)

    entries.append({"value": cleaned_value})
    return save_role_title_knowledge(entries)
