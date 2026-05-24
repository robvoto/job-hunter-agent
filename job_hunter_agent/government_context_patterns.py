from __future__ import annotations

import re
from typing import Any


from job_hunter_agent.managed_knowledge_store import (
    load_managed_knowledge_payload,
    save_managed_knowledge_payload,
)
from job_hunter_agent.signal_schema import (
    MANAGED_KNOWLEDGE_DESCRIPTION_KEY,
    MANAGED_KNOWLEDGE_ENTRIES_KEY,
    MANAGED_KNOWLEDGE_KIND_KEY,
    MANAGED_KNOWLEDGE_NAME_KEY,
    MANAGED_KNOWLEDGE_UPDATED_AT_KEY,
    MANAGED_KNOWLEDGE_VERSION_KEY,
)

_WILDCARD = "[*]"


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _pattern_key(pattern: str) -> str:
    return pattern.strip().lower()


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    pattern = _clean_text(entry.get("pattern"))
    if not pattern or _WILDCARD not in pattern:
        return None
    return {"pattern": pattern}


def _merge_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in entries:
        normalized = _normalize_entry(entry)
        if normalized is None:
            continue
        key = _pattern_key(normalized["pattern"])
        if key not in merged:
            merged[key] = normalized
            order.append(key)
    return [merged[key] for key in order]


def _pattern_to_regex(pattern: str) -> re.Pattern[str]:
    parts = pattern.split(_WILDCARD)
    regex_str = ".+".join(re.escape(p) for p in parts)
    return re.compile(f"^{regex_str}$", re.IGNORECASE)


def load_government_context_patterns() -> list[dict[str, Any]]:
    payload = load_managed_knowledge_payload("government_context_patterns", entries_key=MANAGED_KNOWLEDGE_ENTRIES_KEY)
    entries = payload.get(MANAGED_KNOWLEDGE_ENTRIES_KEY)
    if not isinstance(entries, list):
        raise ValueError("government_context_patterns.json must contain an entries list")
    cleaned_entries = _merge_entries(entries)
    if cleaned_entries != entries:
        save_government_context_patterns(cleaned_entries)
    return cleaned_entries


def save_government_context_patterns(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = load_managed_knowledge_payload("government_context_patterns", entries_key=MANAGED_KNOWLEDGE_ENTRIES_KEY)
    payload.setdefault(MANAGED_KNOWLEDGE_KIND_KEY, "managed_knowledge")
    payload.setdefault(MANAGED_KNOWLEDGE_NAME_KEY, "government_context_patterns")
    payload.setdefault(MANAGED_KNOWLEDGE_VERSION_KEY, 1)
    payload.setdefault(MANAGED_KNOWLEDGE_UPDATED_AT_KEY, "")
    payload.setdefault(MANAGED_KNOWLEDGE_DESCRIPTION_KEY, "")
    payload[MANAGED_KNOWLEDGE_ENTRIES_KEY] = _merge_entries(entries)
    return save_managed_knowledge_payload("government_context_patterns", payload)


def upsert_government_context_pattern(pattern: str) -> dict[str, Any]:
    cleaned = _clean_text(pattern)
    if not cleaned:
        raise ValueError("pattern is required")
    if _WILDCARD not in cleaned:
        raise ValueError(f"pattern must contain '{_WILDCARD}' as a wildcard placeholder")

    entries = list(load_government_context_patterns())
    key = _pattern_key(cleaned)
    for entry in entries:
        if _pattern_key(entry.get("pattern", "")) == key:
            entry["pattern"] = cleaned
            return save_government_context_patterns(entries)

    entries.append({"pattern": cleaned})
    return save_government_context_patterns(entries)


def match_government_context_pattern(text: str) -> str | None:
    """Return the first pattern that matches text, or None."""
    text = _clean_text(text)
    if not text:
        return None
    for entry in load_government_context_patterns():
        pattern = entry.get("pattern", "")
        if not pattern:
            continue
        if _pattern_to_regex(pattern).match(text):
            return pattern
    return None
