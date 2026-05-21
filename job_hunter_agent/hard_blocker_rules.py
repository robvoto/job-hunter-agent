"""Hard blocker rule management and detection logic.

This module handles the loading, normalisation, and persistence of rules used 
to detect mandatory requirements in job ads that conflict with a candidate's 
profile. It provides logic for matching these rules against job text to 
automatically identify dealbreakers using candidate-specific exclusion terms.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from job_hunter_agent.io_utils import load_json_dict
from job_hunter_agent.managed_knowledge_store import (
    clean_knowledge_aliases,
    clean_knowledge_text,
    merge_knowledge_entries,
)

from job_hunter_agent.paths import HARD_BLOCKER_RULES_PATH
from job_hunter_agent.signal_schema import (
    MANAGED_KNOWLEDGE_ALIASES_KEY,
    MANAGED_KNOWLEDGE_DESCRIPTION_KEY,
    MANAGED_KNOWLEDGE_ENTRIES_KEY,
    MANAGED_KNOWLEDGE_KIND_KEY,
    MANAGED_KNOWLEDGE_NAME_KEY,
    MANAGED_KNOWLEDGE_VALUE_KEY,
    MANAGED_KNOWLEDGE_VERSION_KEY,
)

_TERM_PLACEHOLDER = "{term}"
REJECTION_BLOCKER_MIN_LENGTH = 2
REJECTION_BLOCKER_MAX_LENGTH = 80 
logger = logging.getLogger(__name__)

def _load_payload() -> dict[str, Any]:
    return load_json_dict(HARD_BLOCKER_RULES_PATH) or {MANAGED_KNOWLEDGE_ENTRIES_KEY: []}


def _normalize_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    value = clean_knowledge_text(entry.get(MANAGED_KNOWLEDGE_VALUE_KEY))
    if not value:
        return None
    return {
        MANAGED_KNOWLEDGE_VALUE_KEY: value,
        MANAGED_KNOWLEDGE_ALIASES_KEY: clean_knowledge_aliases(entry.get(MANAGED_KNOWLEDGE_ALIASES_KEY), canonical=value),
    }


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
            bucket = {
                MANAGED_KNOWLEDGE_VALUE_KEY: normalized[MANAGED_KNOWLEDGE_VALUE_KEY],
                MANAGED_KNOWLEDGE_ALIASES_KEY: [],
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
    entries = payload.get(MANAGED_KNOWLEDGE_ENTRIES_KEY)
    if not isinstance(entries, list):
        return []
    return _merge_entries(entries)


def save_hard_blocker_rules(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        MANAGED_KNOWLEDGE_KIND_KEY: "managed_knowledge",
        MANAGED_KNOWLEDGE_NAME_KEY: "hard_blocker_rules",
        MANAGED_KNOWLEDGE_VERSION_KEY: 1,
        "description": "Sentence patterns that detect when a term is a non-negotiable requirement in a job ad. Each entry must contain a {term} placeholder — the engine substitutes candidate-specific rejected skills from profile.must_not_require_skills. These are detection grammar, not a blocklist.",
        MANAGED_KNOWLEDGE_ENTRIES_KEY: _merge_entries(entries),
    }
    HARD_BLOCKER_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    HARD_BLOCKER_RULES_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def upsert_hard_blocker_rule(value: str, aliases: list[str] | None = None) -> dict[str, Any]:
    cleaned_value = clean_knowledge_text(value)
    if not cleaned_value:
        raise ValueError("value is required")
    if _TERM_PLACEHOLDER not in cleaned_value.lower():
        raise ValueError("hard blocker rules must include {term}")

    entries = list(load_hard_blocker_rules())
    incoming_aliases = clean_knowledge_aliases(aliases or [], canonical=cleaned_value)
    for entry in entries:
        if clean_knowledge_text(entry.get(MANAGED_KNOWLEDGE_VALUE_KEY)).lower() != cleaned_value.lower():
            continue
        existing_aliases = clean_knowledge_aliases(entry.get(MANAGED_KNOWLEDGE_ALIASES_KEY), canonical=cleaned_value)
        merged: list[str] = []
        seen: set[str] = {cleaned_value.lower()}
        for alias in [*existing_aliases, *incoming_aliases]:
            alias_key = alias.lower()
            if alias_key in seen:
                continue
            seen.add(alias_key)
            merged.append(alias)
        entry[MANAGED_KNOWLEDGE_VALUE_KEY] = cleaned_value
        entry[MANAGED_KNOWLEDGE_ALIASES_KEY] = merged
        return save_hard_blocker_rules(entries)

    entries.append({
        MANAGED_KNOWLEDGE_VALUE_KEY: cleaned_value,
        MANAGED_KNOWLEDGE_ALIASES_KEY: incoming_aliases,
    })
    return save_hard_blocker_rules(entries)


def expand_hard_blocker_terms(entry: dict[str, Any]) -> list[str]:
    normalized = _normalize_entry(entry)
    if normalized is None:
        return []
    return [normalized[MANAGED_KNOWLEDGE_VALUE_KEY], *normalized[MANAGED_KNOWLEDGE_ALIASES_KEY]]


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_knowledge_text(value).lower()).strip()


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


def normalize_rejection_blocker_suggestions(
    value: Any,
    *,
    max_items: int,
    max_words: int,
) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception as exc:
            logger.warning("[HARD_BLOCKERS][WARN] Failed to parse blocker suggestions JSON: %s", exc)
            return []
    if isinstance(value, dict):
        blockers = value.get("blockers")
        suggestions = value.get("suggestions")
        if blockers is None and suggestions is None:
            logger.warning(
                "[HARD_BLOCKERS][WARN] Blocker suggestions payload did not include blockers or suggestions keys; returning an empty list.",
            )
        value = blockers or suggestions or []
    if not isinstance(value, list):
        logger.warning(
            "[HARD_BLOCKERS][WARN] Blocker suggestions were not a list after normalisation; returning an empty list.",
        )
        return []

    suggestions: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        phrase = re.sub(r"\s+", " ", str(item.get("term") or "").strip().lower())
        if not phrase:
            continue
        if len(phrase) < REJECTION_BLOCKER_MIN_LENGTH or len(phrase) > REJECTION_BLOCKER_MAX_LENGTH:
            continue
        if re.search(r"[\r\n.;!?]", phrase):
            continue
        if len(phrase.split()) > max_words:
            continue
        if phrase in seen:
            continue
        seen.add(phrase)
        suggestions.append(phrase)
        if len(suggestions) >= max_items:
            break
    return suggestions


def _render_rule(value: str, term: str) -> str:
    rendered = clean_knowledge_text(value).replace(_TERM_PLACEHOLDER, clean_knowledge_text(term))
    return _normalize_pattern_text(rendered)


def find_hard_block_matches(text: str, terms: list[str] | None = None) -> list[dict[str, str]]:
    normalized_text = _normalize_match_text(text)
    if not normalized_text:
        return []

    terms = [clean_knowledge_text(term) for term in (terms or []) if clean_knowledge_text(term)]
    if not terms:
        return []

    matches: list[tuple[int, dict[str, str]]] = []
    seen: set[tuple[str, str, int]] = set()
    for entry in load_hard_blocker_rules():
        canonical = clean_knowledge_text(entry.get(MANAGED_KNOWLEDGE_VALUE_KEY))
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
                                MANAGED_KNOWLEDGE_VALUE_KEY: canonical,
                                "matched_term": clean_knowledge_text(term),
                                "context": context,
                            },
                        )
                    )
    matches.sort(key=lambda item: item[0])
    return [item[1] for item in matches]


def generalize_hard_block_pattern(text: str, term: str) -> str:
    cleaned_text = clean_knowledge_text(text)
    cleaned_term = clean_knowledge_text(term)
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
