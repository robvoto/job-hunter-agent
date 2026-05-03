from __future__ import annotations

import json
import re
from typing import Any

from job_hunter_agent.paths import CAPABILITY_KNOWLEDGE_PATH


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_aliases(value: Any, *, canonical: str) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]", value)
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []

    canonical_key = _clean_text(canonical).lower()
    aliases: list[str] = []
    seen: set[str] = {canonical_key} if canonical_key else set()
    for item in raw_items:
        alias = _clean_text(item)
        alias_key = alias.lower()
        if not alias or alias_key in seen:
            continue
        seen.add(alias_key)
        aliases.append(alias)
    return aliases


def _load_payload() -> dict[str, Any]:
    if not CAPABILITY_KNOWLEDGE_PATH.exists():
        return {"entries": []}
    try:
        payload = json.loads(CAPABILITY_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    value = _clean_text(entry.get("value"))
    if not value:
        return None
    aliases = _clean_aliases(entry.get("aliases"), canonical=value)
    return {
        "value": value,
        "aliases": aliases,
    }


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
            bucket = {
                "value": normalized["value"],
                "aliases": [],
            }
            merged[value_key] = bucket
            order.append(value_key)
        seen_aliases = {bucket["value"].lower(), *(alias.lower() for alias in bucket["aliases"])}
        for alias in normalized["aliases"]:
            alias_key = alias.lower()
            if alias_key in seen_aliases:
                continue
            seen_aliases.add(alias_key)
            bucket["aliases"].append(alias)
    return [merged[key] for key in order]


def load_capability_knowledge() -> list[dict[str, Any]]:
    payload = _load_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError("capability_knowledge.json must contain an entries list")

    cleaned_entries = _merge_entries(entries)

    if cleaned_entries != entries:
        save_capability_knowledge(cleaned_entries)

    return cleaned_entries


def save_capability_knowledge(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _load_payload()
    payload.setdefault("kind", "managed_knowledge")
    payload.setdefault("name", "capability_knowledge")
    payload.setdefault("version", 1)
    payload.setdefault("updated_at", "")
    payload.setdefault("description", "")
    cleaned_entries = _merge_entries(entries)
    payload["entries"] = cleaned_entries
    CAPABILITY_KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPABILITY_KNOWLEDGE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def upsert_capability_entry(value: str, aliases: list[str] | None = None) -> dict[str, Any]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    cleaned_aliases = _clean_aliases(aliases or [], canonical=cleaned_value)
    entries = list(load_capability_knowledge())
    for entry in entries:
        if _clean_text(entry.get("value")).lower() != cleaned_value.lower():
            continue
        existing_aliases = _clean_aliases(entry.get("aliases"), canonical=cleaned_value)
        merged: list[str] = []
        seen: set[str] = {cleaned_value.lower()}
        for alias in [*existing_aliases, *cleaned_aliases]:
            alias_key = alias.lower()
            if alias_key in seen:
                continue
            seen.add(alias_key)
            merged.append(alias)
        entry["value"] = cleaned_value
        entry["aliases"] = merged
        return save_capability_knowledge(entries)

    entries.append({
        "value": cleaned_value,
        "aliases": cleaned_aliases,
    })
    return save_capability_knowledge(entries)
