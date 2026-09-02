"""Canonical employer identity for outcome history.

Owner of `employer_key`: the stable identity an application outcome is filed
under. Two spellings of the same employer must produce the same key, or a
candidate's history fragments across near-duplicate rows.

Identity is decided by two things only:

1. `normalize_company_name()` from company_normalization.py, which strips
   punctuation, casing and managed legal suffixes.
2. The managed alias map in `data/knowledge/employer_aliases.json`, which is the
   only place a parent/child or trading-name relationship may be declared.

Names absent from the alias map stay distinct employers. Relationships are never
inferred from string containment or similarity, because a shared word does not
make two organisations one employer. A parent/child or trading-name relationship
exists only when a human declares it in managed knowledge.

The alias map is the exception path, not the mechanism. Normalisation already
collapses casing, punctuation and legal-suffix variants of the same name without
any configuration; the map exists only for the cases normalisation cannot derive,
where two genuinely different strings mean one employer.
"""

from __future__ import annotations

from typing import Any

from job_hunter_agent.company_normalization import normalize_company_name

_EMPLOYER_ALIASES_KEY = "employer_aliases"
_CANONICAL_KEY = "canonical"
_ALIASES_KEY = "aliases"


def _load_payload() -> dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge

    return get_knowledge("employer_aliases") or {}


def load_employer_aliases() -> list[dict[str, Any]]:
    """Return the validated alias entries. Raises when managed knowledge is absent
    or malformed; there is no in-code default employer map."""
    payload = _load_payload()
    if not payload:
        raise ValueError("employer_aliases.json must contain a config object")

    entries = payload.get(_EMPLOYER_ALIASES_KEY)
    if not isinstance(entries, list):
        raise ValueError("employer_aliases.json must define employer_aliases as a list")

    validated: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"employer_aliases[{index}] must be an object")
        canonical = str(entry.get(_CANONICAL_KEY) or "").strip()
        if not canonical:
            raise ValueError(f"employer_aliases[{index}] must define a non-empty canonical name")
        aliases = entry.get(_ALIASES_KEY)
        if not isinstance(aliases, list):
            raise ValueError(f"employer_aliases[{index}] must define aliases as a list")
        cleaned_aliases = [str(alias).strip() for alias in aliases if str(alias or "").strip()]
        validated.append({_CANONICAL_KEY: canonical, _ALIASES_KEY: cleaned_aliases})
    return validated


def _alias_lookup() -> dict[str, str]:
    """Map every normalized alias and canonical spelling to its canonical name."""
    lookup: dict[str, str] = {}
    for entry in load_employer_aliases():
        canonical = entry[_CANONICAL_KEY]
        for name in [canonical, *entry[_ALIASES_KEY]]:
            normalized = normalize_company_name(name)
            if normalized:
                lookup[normalized] = canonical
    return lookup


def resolve_employer(raw_name: str) -> tuple[str, str]:
    """Return (employer_key, employer_display) for a raw employer name.

    employer_key is the normalized canonical name and is used as a primary key,
    so it must stay deterministic for a given alias map. employer_display is the
    canonical spelling when one is declared, otherwise the caller's raw name
    with surrounding whitespace removed.
    """
    cleaned = str(raw_name or "").strip()
    normalized = normalize_company_name(cleaned)
    if not normalized:
        raise ValueError("employer name must not be empty")

    canonical = _alias_lookup().get(normalized)
    if canonical is None:
        return normalized, cleaned
    return normalize_company_name(canonical), canonical


def employer_key(raw_name: str) -> str:
    """Convenience accessor when only the identity is needed."""
    return resolve_employer(raw_name)[0]
