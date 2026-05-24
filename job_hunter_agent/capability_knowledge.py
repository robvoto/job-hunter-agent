from __future__ import annotations

from typing import Any

from job_hunter_agent.signal_schema import (
    MANAGED_KNOWLEDGE_ALIASES_KEY,
    MANAGED_KNOWLEDGE_DESCRIPTION_KEY,
    MANAGED_KNOWLEDGE_ENTRIES_KEY,
    MANAGED_KNOWLEDGE_KIND_KEY,
    MANAGED_KNOWLEDGE_NAME_KEY,
    MANAGED_KNOWLEDGE_UPDATED_AT_KEY,
    MANAGED_KNOWLEDGE_VALUE_KEY,
    MANAGED_KNOWLEDGE_VERSION_KEY,
)
from job_hunter_agent.managed_knowledge_store import (
    clean_knowledge_aliases,
    clean_knowledge_text,
    merge_knowledge_entries,
)

def _load_payload() -> dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge
    return get_knowledge("capability_knowledge") or {MANAGED_KNOWLEDGE_ENTRIES_KEY: []}


def load_capability_knowledge() -> list[dict[str, Any]]:
    payload = _load_payload()
    entries = payload.get(MANAGED_KNOWLEDGE_ENTRIES_KEY)
    if not isinstance(entries, list):
        raise ValueError("capability_knowledge.json must contain an entries list")
    
    cleaned_entries = merge_knowledge_entries(
        entries,
        value_key=MANAGED_KNOWLEDGE_VALUE_KEY,
        aliases_key=MANAGED_KNOWLEDGE_ALIASES_KEY,
    )

    if cleaned_entries != entries:
        save_capability_knowledge(cleaned_entries)

    return cleaned_entries


def save_capability_knowledge(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _load_payload()
    payload.setdefault(MANAGED_KNOWLEDGE_KIND_KEY, "managed_knowledge")
    payload.setdefault(MANAGED_KNOWLEDGE_NAME_KEY, "capability_knowledge")
    payload.setdefault(MANAGED_KNOWLEDGE_VERSION_KEY, 1)
    payload.setdefault(MANAGED_KNOWLEDGE_UPDATED_AT_KEY, "")
    payload.setdefault(MANAGED_KNOWLEDGE_DESCRIPTION_KEY, "")
    cleaned_entries = merge_knowledge_entries(
        entries,
        value_key=MANAGED_KNOWLEDGE_VALUE_KEY,
        aliases_key=MANAGED_KNOWLEDGE_ALIASES_KEY,
    )
    payload[MANAGED_KNOWLEDGE_ENTRIES_KEY] = cleaned_entries
    from job_hunter_agent.knowledge_store import set_knowledge
    set_knowledge("capability_knowledge", payload)
    return payload


def upsert_capability_entry(value: str, aliases: list[str] | None = None) -> dict[str, Any]:
    cleaned_value = clean_knowledge_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    cleaned_aliases = clean_knowledge_aliases(aliases or [], canonical=cleaned_value)
    entries = list(load_capability_knowledge())
    for entry in entries:
        if clean_knowledge_text(entry.get(MANAGED_KNOWLEDGE_VALUE_KEY)).lower() != cleaned_value.lower():
            continue
        existing_aliases = clean_knowledge_aliases(entry.get(MANAGED_KNOWLEDGE_ALIASES_KEY), canonical=cleaned_value)
        merged: list[str] = []
        seen: set[str] = {cleaned_value.lower()}
        for alias in [*existing_aliases, *cleaned_aliases]:
            alias_key = alias.lower()
            if alias_key in seen:
                continue
            seen.add(alias_key)
            merged.append(alias)
        entry[MANAGED_KNOWLEDGE_VALUE_KEY] = cleaned_value
        entry[MANAGED_KNOWLEDGE_ALIASES_KEY] = merged
        return save_capability_knowledge(entries)

    entries.append({
        MANAGED_KNOWLEDGE_VALUE_KEY: cleaned_value,
        MANAGED_KNOWLEDGE_ALIASES_KEY: cleaned_aliases,
    })
    return save_capability_knowledge(entries)
