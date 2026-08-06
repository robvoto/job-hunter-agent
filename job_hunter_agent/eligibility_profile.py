"""User-managed generic eligibility facts.

Managed clearances remain in the existing clearance catalogue. This module owns
only free-text eligibility facts and the shared add/update preparation used by
settings and job-result actions.
"""

from __future__ import annotations

from typing import Any

from job_hunter_agent.text_processing import compact_whitespace

KEY_NAME = "name"
KEY_VALUE = "value"
KEY_EVIDENCE = "evidence"


def normalize_eligibility_facts(facts: Any) -> list[dict[str, Any]]:
    """Normalize facts and prevent canonical name collisions in one profile."""

    cleaned: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for raw in facts if isinstance(facts, list) else []:
        if not isinstance(raw, dict):
            continue
        name = compact_whitespace(raw.get(KEY_NAME) or raw.get("label"))
        name_key = name.casefold()
        if not name_key or name_key in seen_names:
            continue

        evidence = raw.get(KEY_EVIDENCE) or []
        if isinstance(evidence, str):
            evidence = [evidence]
        evidence = [compact_whitespace(item) for item in evidence if compact_whitespace(item)] if isinstance(evidence, list) else []

        item: dict[str, Any] = {
            KEY_NAME: name,
            KEY_VALUE: raw.get(KEY_VALUE) is not False,
            KEY_EVIDENCE: evidence,
        }
        cleaned.append(item)
        seen_names.add(name_key)
    return cleaned


def _find_fact_index(facts: list[dict[str, Any]], name: str) -> int | None:
    target = compact_whitespace(name).casefold()
    if not target:
        return None
    for index, fact in enumerate(facts):
        if compact_whitespace(fact.get(KEY_NAME)).casefold() == target:
            return index
    return None


def prepare_eligibility_fact(
    existing_facts: Any,
    *,
    name: str,
    value: Any = True,
    evidence: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return an updated fact list and the fact that was added or updated."""

    facts = normalize_eligibility_facts(existing_facts)
    canonical_name = compact_whitespace(name)
    if not canonical_name:
        raise ValueError("Eligibility name is required")

    index = _find_fact_index(facts, canonical_name)
    current = dict(facts[index]) if index is not None else {}
    merged = {
        **current,
        KEY_NAME: current.get(KEY_NAME) or canonical_name,
        KEY_VALUE: value is not False,
        KEY_EVIDENCE: evidence if evidence is not None else current.get(KEY_EVIDENCE, []),
    }

    if index is None:
        facts.append(merged)
    else:
        facts[index] = merged
    normalized = normalize_eligibility_facts(facts)
    saved_index = _find_fact_index(normalized, canonical_name)
    if saved_index is None:
        raise ValueError("Eligibility fact could not be saved after normalization")
    return normalized, normalized[saved_index]
