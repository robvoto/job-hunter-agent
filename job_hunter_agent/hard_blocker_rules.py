from __future__ import annotations

import json
import re
from typing import Any

from job_hunter_agent.paths import HARD_BLOCKER_RULES_PATH

_TERM_PLACEHOLDER = "{term}"


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
    if not HARD_BLOCKER_RULES_PATH.exists():
        return {"entries": []}
    try:
        payload = json.loads(HARD_BLOCKER_RULES_PATH.read_text(encoding="utf-8"))
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


def load_hard_blocker_rules() -> list[dict[str, Any]]:
    payload = _load_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    return _merge_entries(entries)


def save_hard_blocker_rules(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "kind": "managed_knowledge",
        "name": "hard_blocker_rules",
        "version": 1,
        "description": "Approved reusable patterns that detect when a candidate-specific rejected term is a non-negotiable job requirement.",
        "entries": _merge_entries(entries),
    }
    HARD_BLOCKER_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    HARD_BLOCKER_RULES_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def upsert_hard_blocker_rule(value: str, aliases: list[str] | None = None) -> dict[str, Any]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")
    if _TERM_PLACEHOLDER not in cleaned_value.lower():
        raise ValueError("hard blocker rules must include {term}")

    entries = list(load_hard_blocker_rules())
    for entry in entries:
        if _clean_text(entry.get("value")).lower() != cleaned_value.lower():
            continue
        entry["value"] = cleaned_value
        entry["aliases"] = []
        return save_hard_blocker_rules(entries)

    entries.append({
        "value": cleaned_value,
        "aliases": [],
    })
    return save_hard_blocker_rules(entries)


def expand_hard_blocker_terms(entry: dict[str, Any]) -> list[str]:
    normalized = _normalize_entry(entry)
    if normalized is None:
        return []
    return [normalized["value"], *normalized["aliases"]]


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", _clean_text(value).lower()).strip()


def _normalize_pattern_text(value: Any) -> str:
    return _normalize_match_text(value).replace(" term ", " {term} ")


def _near_desirable_language(text: str, term: str, window: int = 90) -> bool:
    cleaned_text = _normalize_match_text(text)
    cleaned_term = _normalize_match_text(term)
    if not cleaned_text or not cleaned_term:
        return False
    for match in re.finditer(rf"(?<!\w){re.escape(cleaned_term)}(?!\w)", cleaned_text):
        start = max(match.start() - window, 0)
        end = min(match.end() + window, len(cleaned_text))
        context = cleaned_text[start:end]
        if re.search(r"\b(desirable|preferred|highly regarded|nice to have|advantageous|beneficial)\b", context):
            return True
    return False


def _render_rule(value: str, term: str) -> str:
    rendered = _clean_text(value).replace(_TERM_PLACEHOLDER, _clean_text(term))
    return _normalize_pattern_text(rendered)


def find_hard_block_matches(text: str, terms: list[str] | None = None) -> list[dict[str, str]]:
    normalized_text = _normalize_match_text(text)
    if not normalized_text:
        return []

    terms = [_clean_text(term) for term in (terms or []) if _clean_text(term)]
    if not terms:
        return []

    matches: list[tuple[int, dict[str, str]]] = []
    seen: set[tuple[str, str, int]] = set()
    for entry in load_hard_blocker_rules():
        canonical = _clean_text(entry.get("value"))
        if not canonical:
            continue
        for term in terms:
            for rule_text in expand_hard_blocker_terms(entry):
                rendered = _render_rule(rule_text, term)
                if not rendered:
                    continue
                pattern = rf"(?<!\w){re.escape(rendered)}(?!\w)"
                for match in re.finditer(pattern, normalized_text):
                    key = (canonical.lower(), term.lower(), match.start())
                    if key in seen or _near_desirable_language(text, term):
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


def generalize_hard_block_pattern(text: str, term: str) -> str:
    cleaned_text = _clean_text(text)
    cleaned_term = _clean_text(term)
    if not cleaned_text or not cleaned_term:
        return ""

    term_norm = _normalize_match_text(cleaned_term)
    for chunk in re.split(r"(?<=[.!?])\s+|\n+", cleaned_text):
        normalized_chunk = _normalize_match_text(chunk)
        if not normalized_chunk or term_norm not in normalized_chunk:
            continue
        generalized = normalized_chunk.replace(term_norm, _TERM_PLACEHOLDER)
        generalized = re.sub(r"\s+", " ", generalized).strip(" .,:;")
        return generalized

    fallback = _normalize_match_text(cleaned_text)
    if term_norm and term_norm in fallback:
        return fallback.replace(term_norm, _TERM_PLACEHOLDER)
    return ""
