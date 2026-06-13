"""Helpers for managed knowledge store."""

from __future__ import annotations

import re
from typing import Any

from job_hunter_agent.text_processing import compact_whitespace


def clean_knowledge_text(value: Any) -> str:
    """Normalize whitespace and coerce to a trimmed string."""
    return compact_whitespace(value)


def clean_knowledge_term(value: Any) -> str:
    """Clean text and return it lowercased for matching."""
    return clean_knowledge_text(value).lower()


def clean_knowledge_aliases(values: Any, *, canonical: str = "") -> list[str]:
    """Clean a list or comma-separated string of aliases, excluding the canonical value."""
    if isinstance(values, str):
        raw_values = re.split(r"[\n,]", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    canonical_key = clean_knowledge_term(canonical)
    aliases: list[str] = []
    seen: set[str] = {canonical_key} if canonical_key else set()

    for value in raw_values:
        alias = clean_knowledge_text(value)
        alias_key = alias.lower()
        if not alias or alias_key in seen:
            continue
        seen.add(alias_key)
        aliases.append(alias)

    return aliases


def merge_knowledge_entries(
    entries: list[dict[str, Any]],
    *,
    value_key: str = "value",
    aliases_key: str = "aliases",
) -> list[dict[str, Any]]:
    """Merge duplicate knowledge entries by primary value while combining aliases."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        val = clean_knowledge_text(entry.get(value_key))
        if not val:
            continue

        incoming_aliases = clean_knowledge_aliases(entry.get(aliases_key), canonical=val)
        vk = val.lower()
        bucket = merged.get(vk)
        if bucket is None:
            bucket = {value_key: val, aliases_key: []}
            merged[vk] = bucket
            order.append(vk)

        seen_aliases = {bucket[value_key].lower(), *(a.lower() for a in bucket[aliases_key])}
        for alias in incoming_aliases:
            ak = alias.lower()
            if ak in seen_aliases:
                continue
            seen_aliases.add(ak)
            bucket[aliases_key].append(alias)

    return [merged[key] for key in order]


def load_managed_knowledge_payload(key: str, *, entries_key: str) -> dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge

    payload = get_knowledge(key)
    if payload is None:
        return {entries_key: []}
    if not isinstance(payload, dict):
        raise ValueError(f"Knowledge '{key}' must contain a JSON object")
    return payload


def save_managed_knowledge_payload(key: str, payload: dict[str, Any]) -> dict[str, Any]:
    from job_hunter_agent.knowledge_store import set_knowledge

    set_knowledge(key, payload)
    return payload
