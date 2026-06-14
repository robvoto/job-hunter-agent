"""Capability term normalization for job description matching."""

import re
from typing import Any

from job_hunter_agent.text_processing import compact_whitespace


def _clean_term(value: Any) -> str:
    return compact_whitespace(value).lower()


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


def canonical_capability_term(rule: dict[str, Any]) -> str:
    """Return the canonical searchable term for a capability."""
    return _clean_term(rule.get("name"))


def _term_tokens(value: Any) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", _clean_term(value)) if token]


def _is_structurally_valid_alias(raw_alias: Any) -> bool:
    # ── SEALED — see data/ALIAS_LOGIC_RATIONALE.md ────────────────────────────
    # Validates basic formatting only. No token-overlap check against the
    # canonical name — that rule was too strict for abbreviated capability names
    # like "bpmn modelling" where valid aliases ("business process modelling",
    # "bpmn") share few or no tokens with the stored name.
    alias_tokens = _term_tokens(raw_alias)
    if not alias_tokens:
        return False
    if len(alias_tokens) > 4:
        return False
    if len(set(alias_tokens)) != len(alias_tokens):
        return False
    return True
    # ──────────────────────────────────────────────────────────────────────────


def derive_job_description_aliases(
    name: str,
    raw_aliases: list[str] | None,
    max_aliases: int = 10,
) -> list[str]:
    """Return clean, deduplicated aliases excluding the canonical name."""
    excluded = {_clean_term(name)}
    result: list[str] = []
    for alias in raw_aliases or []:
        cleaned = _clean_term(alias)
        if cleaned and cleaned not in excluded and _is_structurally_valid_alias(alias):
            excluded.add(cleaned)
            result.append(cleaned)
    return result[:max_aliases]


def choose_capability_name(name: str, raw_aliases: list[str] | None) -> str:
    """Return the canonical name, falling back to the first alias."""
    cleaned = _clean_term(name)
    if cleaned:
        return cleaned
    return next((_clean_term(a) for a in (raw_aliases or []) if _clean_term(a)), "")
