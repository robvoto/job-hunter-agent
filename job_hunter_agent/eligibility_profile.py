"""User-managed generic eligibility facts.

Managed clearances remain in the existing clearance catalogue. This module owns
only free-text eligibility facts and the shared add/update preparation used by
settings and job-result actions.
"""

from __future__ import annotations

from typing import Any

from job_hunter_agent.capability_matrix import derive_job_description_aliases
from job_hunter_agent.text_processing import compact_whitespace

KEY_NAME = "name"
KEY_VALUE = "value"
KEY_ALIASES = "aliases"
KEY_SUBTYPE = "subtype"
KEY_EVIDENCE = "evidence"
KEY_NEEDS_REVIEW = "needs_review"
KEY_ALIASES_AUTO_GENERATED = "aliases_auto_generated"
ALIAS_GENERATION_STATUS_KEY = "alias_generation_status"


def normalize_eligibility_facts(facts: Any) -> list[dict[str, Any]]:
    """Normalize facts and prevent canonical/alias collisions in one profile."""

    cleaned: list[dict[str, Any]] = []
    seen_terms: set[str] = set()
    for raw in facts if isinstance(facts, list) else []:
        if not isinstance(raw, dict):
            continue
        name = compact_whitespace(raw.get(KEY_NAME) or raw.get("label"))
        name_key = name.casefold()
        if not name_key or name_key in seen_terms:
            continue

        raw_aliases = raw.get(KEY_ALIASES) or []
        if isinstance(raw_aliases, str):
            raw_aliases = [part for part in raw_aliases.replace("\n", ",").split(",")]
        aliases = derive_job_description_aliases(name, list(raw_aliases) if isinstance(raw_aliases, list) else [])
        unique_aliases: list[str] = []
        for alias in aliases:
            alias_key = alias.casefold()
            if alias_key in seen_terms:
                continue
            seen_terms.add(alias_key)
            unique_aliases.append(alias)

        evidence = raw.get(KEY_EVIDENCE) or []
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence = [compact_whitespace(item) for item in evidence if compact_whitespace(item)] if isinstance(evidence, list) else []

        item: dict[str, Any] = {
            KEY_NAME: name,
            KEY_VALUE: raw.get(KEY_VALUE) is not False,
            KEY_ALIASES: unique_aliases,
            KEY_EVIDENCE: evidence,
            KEY_NEEDS_REVIEW: bool(raw.get(KEY_NEEDS_REVIEW)),
        }
        subtype = compact_whitespace(raw.get(KEY_SUBTYPE))
        if subtype:
            item[KEY_SUBTYPE] = subtype
        if raw.get(KEY_ALIASES_AUTO_GENERATED) is True:
            item[KEY_ALIASES_AUTO_GENERATED] = True
        if str(raw.get(ALIAS_GENERATION_STATUS_KEY) or "").strip():
            item[ALIAS_GENERATION_STATUS_KEY] = str(raw[ALIAS_GENERATION_STATUS_KEY]).strip()
        cleaned.append(item)
        seen_terms.add(name_key)
    return cleaned


def _find_fact_index(facts: list[dict[str, Any]], name: str) -> int | None:
    target = compact_whitespace(name).casefold()
    if not target:
        return None
    for index, fact in enumerate(facts):
        names = [fact.get(KEY_NAME), *(fact.get(KEY_ALIASES) or [])]
        if any(compact_whitespace(value).casefold() == target for value in names):
            return index
    return None


def prepare_eligibility_fact(
    existing_facts: Any,
    *,
    name: str,
    value: Any = True,
    aliases: Any = None,
    subtype: Any = "",
    evidence: Any = None,
    alias_generation: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return an updated fact list and the fact that was added or updated."""

    facts = normalize_eligibility_facts(existing_facts)
    canonical_name = compact_whitespace(name)
    if not canonical_name:
        raise ValueError("Eligibility name is required")

    index = _find_fact_index(facts, canonical_name)
    current = dict(facts[index]) if index is not None else {}
    provided_aliases = aliases if aliases is not None else current.get(KEY_ALIASES, [])
    raw_generation = alias_generation if isinstance(alias_generation, dict) else {}
    generated_aliases = raw_generation.get(KEY_ALIASES) or []
    combined_aliases = list(provided_aliases or []) + list(generated_aliases)
    merged = {
        **current,
        KEY_NAME: current.get(KEY_NAME) or canonical_name,
        KEY_VALUE: value is not False,
        KEY_ALIASES: combined_aliases,
        KEY_EVIDENCE: evidence if evidence is not None else current.get(KEY_EVIDENCE, []),
        KEY_NEEDS_REVIEW: bool(
            raw_generation.get(KEY_NEEDS_REVIEW, current.get(KEY_NEEDS_REVIEW, False))
        ),
    }
    subtype_text = compact_whitespace(subtype) or compact_whitespace(current.get(KEY_SUBTYPE))
    if subtype_text:
        merged[KEY_SUBTYPE] = subtype_text
    if raw_generation.get(KEY_ALIASES_AUTO_GENERATED):
        merged[KEY_ALIASES_AUTO_GENERATED] = True
    if raw_generation.get(ALIAS_GENERATION_STATUS_KEY):
        merged[ALIAS_GENERATION_STATUS_KEY] = raw_generation[ALIAS_GENERATION_STATUS_KEY]

    if index is None:
        facts.append(merged)
    else:
        facts[index] = merged
    normalized = normalize_eligibility_facts(facts)
    saved_index = _find_fact_index(normalized, canonical_name)
    if saved_index is None:
        raise ValueError("Eligibility fact could not be saved after normalization")
    return normalized, normalized[saved_index]
