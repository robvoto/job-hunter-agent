from __future__ import annotations

import json
import re
from typing import Any

from job_hunter_agent.paths import ROLE_TITLE_KNOWLEDGE_PATH
from job_hunter_agent.signal_schema import (
    MANAGED_KNOWLEDGE_DESCRIPTION_KEY,
    MANAGED_KNOWLEDGE_ENTRIES_KEY,
    MANAGED_KNOWLEDGE_KIND_KEY,
    MANAGED_KNOWLEDGE_NAME_KEY,
    MANAGED_KNOWLEDGE_UPDATED_AT_KEY,
    MANAGED_KNOWLEDGE_VALUE_KEY,
    MANAGED_KNOWLEDGE_VERSION_KEY,
)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_payload() -> dict[str, Any]:
    if not ROLE_TITLE_KNOWLEDGE_PATH.exists():
        return {MANAGED_KNOWLEDGE_ENTRIES_KEY: []}
    try:
        payload = json.loads(ROLE_TITLE_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    value = _clean_text(entry.get(MANAGED_KNOWLEDGE_VALUE_KEY))
    if not value:
        return None
    return {MANAGED_KNOWLEDGE_VALUE_KEY: value}


def _merge_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in entries:
        normalized = _normalize_entry(entry)
        if normalized is None:
            continue
        value_key = normalized[MANAGED_KNOWLEDGE_VALUE_KEY].lower()
        bucket = merged.get(value_key)
        if bucket is None:
            bucket = {MANAGED_KNOWLEDGE_VALUE_KEY: normalized[MANAGED_KNOWLEDGE_VALUE_KEY]}
            merged[value_key] = bucket
            order.append(value_key)
    return [merged[key] for key in order]


def load_role_title_knowledge() -> list[dict[str, Any]]:
    payload = _load_payload()
    entries = payload.get(MANAGED_KNOWLEDGE_ENTRIES_KEY)
    if not isinstance(entries, list):
        raise ValueError("role_title_knowledge.json must contain an entries list")

    cleaned_entries = _merge_entries(entries)
    if cleaned_entries != entries:
        save_role_title_knowledge(cleaned_entries)
    return cleaned_entries


def save_role_title_knowledge(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _load_payload()
    payload.setdefault(MANAGED_KNOWLEDGE_KIND_KEY, "managed_knowledge")
    payload.setdefault(MANAGED_KNOWLEDGE_NAME_KEY, "role_title_knowledge")
    payload.setdefault(MANAGED_KNOWLEDGE_VERSION_KEY, 1)
    payload.setdefault(MANAGED_KNOWLEDGE_UPDATED_AT_KEY, "")
    payload.setdefault(MANAGED_KNOWLEDGE_DESCRIPTION_KEY, "")
    cleaned_entries = _merge_entries(entries)
    payload[MANAGED_KNOWLEDGE_ENTRIES_KEY] = cleaned_entries
    ROLE_TITLE_KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROLE_TITLE_KNOWLEDGE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def upsert_role_title_entry(value: str) -> dict[str, Any]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    entries = list(load_role_title_knowledge())
    for entry in entries:
        if _clean_text(entry.get(MANAGED_KNOWLEDGE_VALUE_KEY)).lower() != cleaned_value.lower():
            continue
        entry[MANAGED_KNOWLEDGE_VALUE_KEY] = cleaned_value
        return save_role_title_knowledge(entries)

    entries.append({MANAGED_KNOWLEDGE_VALUE_KEY: cleaned_value})
    return save_role_title_knowledge(entries)
