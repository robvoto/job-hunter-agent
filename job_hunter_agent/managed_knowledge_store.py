from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def clean_knowledge_text(value: Any) -> str:
    """Normalize whitespace and coerce to a trimmed string."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_knowledge_term(value: Any) -> str:
    """Clean text and return it lowercased for matching."""
    return clean_knowledge_text(value).lower()


def clean_knowledge_aliases(values: Any, *, canonical: str = "") -> list[str]:
    """Clean a list (or comma-separated string) of aliases, excluding the canonical value."""
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
    """Merge duplicate knowledge entries by their primary value while combining aliases."""
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        val = clean_knowledge_text(entry.get(value_key))
        if not val:
            continue

        incoming_aliases = clean_knowledge_aliases(
            entry.get(aliases_key), canonical=val
        )

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


def load_managed_knowledge_payload(path: Path, *, entries_key: str) -> dict[str, Any]:
    if not path.exists():
        return {entries_key: []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OSError(f"Failed to read {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def save_managed_knowledge_payload(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
