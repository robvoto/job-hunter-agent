"""Capability term normalization for job description matching."""

import re
from typing import Any


def _clean_term(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def expand_capability_terms(rule: dict[str, Any], max_terms: int = 10) -> list[str]:
    """Return all searchable terms for a capability: name + aliases, deduplicated."""
    name = _clean_term(rule.get("name"))
    aliases = [_clean_term(a) for a in (rule.get("aliases") or []) if _clean_term(a)]
    seen: set[str] = set()
    terms: list[str] = []
    for term in [name, *aliases]:
        if term and term not in seen:
            seen.add(term)
            terms.append(term)
    return terms[:max_terms]


def derive_job_description_aliases(
    name: str,
    raw_aliases: list[str] | None,
    max_aliases: int = 8,
) -> list[str]:
    """Return clean, deduplicated aliases excluding the canonical name."""
    excluded = {_clean_term(name)}
    result: list[str] = []
    for alias in (raw_aliases or []):
        cleaned = _clean_term(alias)
        if cleaned and cleaned not in excluded:
            excluded.add(cleaned)
            result.append(cleaned)
    return result[:max_aliases]


def choose_capability_name(name: str, raw_aliases: list[str] | None) -> str:
    """Return the canonical name, falling back to the first alias."""
    cleaned = _clean_term(name)
    if cleaned:
        return cleaned
    return next((_clean_term(a) for a in (raw_aliases or []) if _clean_term(a)), "")
