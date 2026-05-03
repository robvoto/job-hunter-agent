from __future__ import annotations

import json
import re
from typing import Any

from job_hunter_agent.paths import HARD_BLOCKER_KNOWLEDGE_PATH


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _clean_term(value: Any) -> str:
    return _clean_text(value).lower()


def _clean_aliases(values: Any, *, canonical: str = "") -> list[str]:
    if isinstance(values, str):
        raw_values = re.split(r"[\n,]", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    canonical_key = _clean_term(canonical)
    aliases: list[str] = []
    seen: set[str] = {canonical_key} if canonical_key else set()
    for value in raw_values:
        alias = _clean_text(value)
        alias_key = alias.lower()
        if not alias or alias_key in seen:
            continue
        seen.add(alias_key)
        aliases.append(alias)
    return aliases


def _load_payload() -> dict[str, Any]:
    if not HARD_BLOCKER_KNOWLEDGE_PATH.exists():
        return {"entries": []}
    try:
        payload = json.loads(HARD_BLOCKER_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    value = _clean_text(entry.get("value"))
    if not value:
        return None
    return {
        "value": value,
        "aliases": _clean_aliases(entry.get("aliases"), canonical=value),
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


def load_hard_blocker_knowledge() -> list[dict[str, Any]]:
    payload = _load_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []

    cleaned_entries = _merge_entries(entries)
    if cleaned_entries != entries:
        save_hard_blocker_knowledge(cleaned_entries)
    return cleaned_entries


def save_hard_blocker_knowledge(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "kind": "managed_knowledge",
        "name": "hard_blocker_knowledge",
        "version": 1,
        "entries": _merge_entries(entries),
    }
    HARD_BLOCKER_KNOWLEDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    HARD_BLOCKER_KNOWLEDGE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def upsert_hard_blocker_entry(value: str, aliases: list[str] | None = None) -> dict[str, Any]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    cleaned_aliases = _clean_aliases(aliases or [], canonical=cleaned_value)
    entries = list(load_hard_blocker_knowledge())
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
        return save_hard_blocker_knowledge(entries)

    entries.append({
        "value": cleaned_value,
        "aliases": cleaned_aliases,
    })
    return save_hard_blocker_knowledge(entries)


def expand_hard_blocker_terms(entry: dict[str, Any]) -> list[str]:
    normalized = _normalize_entry(entry)
    if normalized is None:
        return []
    return [normalized["value"], *normalized["aliases"]]


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(value).lower()).strip()


def find_hard_block_matches(text: str) -> list[dict[str, str]]:
    normalized_text = _normalize_match_text(text)
    if not normalized_text:
        return []

    matches: list[tuple[int, dict[str, str]]] = []
    seen: set[tuple[str, str, int]] = set()
    for entry in load_hard_blocker_knowledge():
        canonical = _clean_text(entry.get("value"))
        if not canonical:
            continue
        for term in expand_hard_blocker_terms(entry):
            normalized_term = _normalize_match_text(term)
            if not normalized_term:
                continue
            pattern = rf"(?<!\w){re.escape(normalized_term)}(?!\w)"
            for match in re.finditer(pattern, normalized_text):
                key = (canonical.lower(), normalized_term, match.start())
                if key in seen:
                    continue
                seen.add(key)
                context_start = max(match.start() - 40, 0)
                context_end = min(match.end() + 40, len(normalized_text))
                context = normalized_text[context_start:context_end].strip()
                matches.append(
                    (
                        match.start(),
                        {
                            "value": canonical,
                            "matched_term": _clean_text(term),
                            "context": context,
                        },
                    )
                )
    matches.sort(key=lambda item: item[0])
    return [item[1] for item in matches]
