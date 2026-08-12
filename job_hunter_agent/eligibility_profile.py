"""User-managed generic eligibility facts.

Managed clearances remain in the existing clearance catalogue. This module owns
only free-text eligibility facts and the shared add/update preparation used by
settings and job-result actions.
"""

from __future__ import annotations

from typing import Any

from job_hunter_agent.profile_item_names import normalize_profile_item_name
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

        value = raw.get(KEY_VALUE, True)
        if not isinstance(value, bool):
            raise ValueError(f"Eligibility value must be a boolean for {name!r}")
        evidence = raw.get(KEY_EVIDENCE, [])
        if not isinstance(evidence, list):
            raise ValueError(f"Eligibility evidence must be a list for {name!r}")
        evidence = [compact_whitespace(item) for item in evidence if compact_whitespace(item)]

        item: dict[str, Any] = {
            KEY_NAME: name,
            KEY_VALUE: value,
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
    if not isinstance(value, bool):
        raise ValueError("Eligibility value must be a boolean")
    if evidence is not None and not isinstance(evidence, list):
        raise ValueError("Eligibility evidence must be a list")
    canonical_name = normalize_profile_item_name(name)
    if not canonical_name:
        raise ValueError("Eligibility name is required")

    index = _find_fact_index(facts, canonical_name)
    current = dict(facts[index]) if index is not None else {}
    merged = {
        **current,
        KEY_NAME: current.get(KEY_NAME) or canonical_name,
        KEY_VALUE: value,
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


def prepare_eligibility_facts_for_profile_save(
    existing_facts: Any,
    submitted_facts: Any,
) -> list[dict[str, Any]]:
    """Prepare a complete settings payload without semantic reinterpretation."""

    normalize_eligibility_facts(existing_facts)  # validate the current shape before replacing it
    prepared: list[dict[str, Any]] = []

    for raw in normalize_eligibility_facts(submitted_facts):
        submitted_name = compact_whitespace(raw.get(KEY_NAME) or raw.get("label"))
        prepared, _ = prepare_eligibility_fact(
            prepared,
            name=submitted_name,
            value=raw.get(KEY_VALUE, True),
            evidence=raw.get(KEY_EVIDENCE),
        )

    return normalize_eligibility_facts(prepared)
