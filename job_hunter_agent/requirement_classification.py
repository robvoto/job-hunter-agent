"""Deterministic capability/eligibility validation for job requirements.

The LLM proposes a requirement_type ("capability" or "eligibility") for each
requirement it extracts. This module cross-checks that proposal against
managed knowledge and a generic experience-duration signal, so the LLM's
answer is never trusted on its own:

- A requirement matching an approved eligibility term (managed in
  requirement_classification_terms.json, or a human-approved override from
  the Learning/Needs Review flow) is always eligibility, regardless of what
  the LLM said.
- A requirement carrying an explicit years/months duration and no eligibility
  term is always capability, regardless of what the LLM said.
- A requirement matching both signals at once is contradictory and returned
  as uncertain for human review rather than guessed. Education, degrees, and
  certifications intentionally remain LLM-classified as qualifications; their
  wording is too varied for a deterministic gate.
- Anything else defers to the LLM's own (valid) answer.
"""

from __future__ import annotations

import re

from job_hunter_agent.experience_requirements import extract_required_experience_months
from job_hunter_agent.knowledge_store import get_knowledge, set_knowledge
from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES,
    LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE,
)
from job_hunter_agent.text_processing import compact_whitespace

_TERMS_KNOWLEDGE_KEY = "requirement_classification_terms"
_OVERRIDES_KNOWLEDGE_KEY = "requirement_classification_overrides"

_CAPABILITY = "capability"
_ELIGIBILITY = "eligibility"
_UNCERTAIN = LLM_UNCERTAIN_COVERAGE_REQUIREMENT_TYPE


def _clean(value: object) -> str:
    return compact_whitespace(value)


def _load_eligibility_term_groups() -> dict[str, list[str]]:
    """Return the managed eligibility subtype vocabulary and its matching terms."""
    payload = get_knowledge(_TERMS_KNOWLEDGE_KEY) or {}
    categories = payload.get("eligibility_terms")
    if not isinstance(categories, dict):
        return {}
    groups: dict[str, list[str]] = {}
    for category, values in categories.items():
        subtype = _clean(category).lower()
        # Formal qualifications and certifications are a first-class LLM
        # classification, not deterministic eligibility subtypes.
        if not subtype or subtype in {"qualification", "certification"}:
            continue
        if not isinstance(values, list):
            continue
        groups[subtype] = [
            cleaned
            for term in values
            if (cleaned := _clean(term).lower())
        ]
    return groups


def load_eligibility_subtypes() -> tuple[str, ...]:
    """Return canonical eligibility subtype keys in managed display order."""
    return tuple(_load_eligibility_term_groups().keys())


def load_default_eligibility_subtype() -> str:
    """Return the managed catch-all subtype used for unresolved eligibility detail."""
    payload = get_knowledge(_TERMS_KNOWLEDGE_KEY) or {}
    default_subtype = _clean(payload.get("default_eligibility_subtype")).lower()
    if default_subtype not in set(load_eligibility_subtypes()):
        raise ValueError(
            "requirement_classification_terms must define a valid default_eligibility_subtype"
        )
    return default_subtype


def _load_eligibility_terms() -> list[str]:
    return [term for terms in _load_eligibility_term_groups().values() for term in terms]


def _term_matches(term: str, text_norm: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
    return re.search(pattern, text_norm) is not None


def _matches_eligibility_term(text_norm: str) -> bool:
    return any(_term_matches(term, text_norm) for term in _load_eligibility_terms())


def _load_requirement_classification_override_entries() -> dict[str, dict[str, str]]:
    payload = get_knowledge(_OVERRIDES_KNOWLEDGE_KEY) or {}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return {}
    allowed_subtypes = set(load_eligibility_subtypes())
    overrides: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = _clean(entry.get("value")).lower()
        classification = _clean(entry.get("classification")).lower()
        subtype = _clean(entry.get("subtype")).lower()
        if not text or classification not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            continue
        if classification != _ELIGIBILITY or subtype not in allowed_subtypes:
            subtype = ""
        overrides[text] = {"classification": classification, "subtype": subtype}
    return overrides


def load_requirement_classification_overrides() -> dict[str, str]:
    """Return {normalized requirement text: human-approved top-level type}."""
    return {
        text: entry["classification"]
        for text, entry in _load_requirement_classification_override_entries().items()
    }


def load_requirement_subtype_overrides() -> dict[str, str]:
    """Return human-approved eligibility subtypes where one was explicitly reviewed."""
    return {
        text: entry["subtype"]
        for text, entry in _load_requirement_classification_override_entries().items()
        if entry.get("subtype")
    }


def upsert_requirement_classification_override(
    text: str,
    classification: str,
    subtype: str = "",
) -> dict[str, str]:
    """Persist a human-approved requirement type and optional eligibility subtype."""
    text_norm = _clean(text).lower()
    classification_norm = _clean(classification).lower()
    subtype_norm = _clean(subtype).lower()
    if not text_norm:
        raise ValueError("text is required")
    if classification_norm not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
        raise ValueError(f"classification must be one of {sorted(LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES)}")
    allowed_subtypes = set(load_eligibility_subtypes())
    if subtype_norm and classification_norm != _ELIGIBILITY:
        raise ValueError("subtype is only valid for eligibility requirements")
    if subtype_norm and subtype_norm not in allowed_subtypes:
        raise ValueError(f"subtype must be one of {sorted(allowed_subtypes)}")

    overrides = _load_requirement_classification_override_entries()
    overrides[text_norm] = {"classification": classification_norm, "subtype": subtype_norm}
    set_knowledge(
        _OVERRIDES_KNOWLEDGE_KEY,
        {
            "kind": "managed_knowledge",
            "entries": [
                {
                    "value": value,
                    "classification": entry["classification"],
                    **({"subtype": entry["subtype"]} if entry.get("subtype") else {}),
                }
                for value, entry in overrides.items()
            ],
        },
    )
    return load_requirement_classification_overrides()


def classify_requirement_subtype(
    requirement_text: str,
    matched_job_text: str = "",
    llm_requirement_subtype: str = "",
) -> str:
    """Resolve an eligibility subtype without changing the top-level type.

    Human-approved subtype knowledge wins, then managed subtype terms, then the
    LLM proposal. Ambiguous managed matches stay unresolved instead of guessing.
    """
    combined_norm = _clean(f"{requirement_text} {matched_job_text}").lower()
    if not combined_norm:
        return ""

    for override_text, override_subtype in load_requirement_subtype_overrides().items():
        if override_text and _term_matches(override_text, combined_norm):
            return override_subtype

    matched_subtypes = [
        subtype
        for subtype, terms in _load_eligibility_term_groups().items()
        if any(_term_matches(term, combined_norm) for term in terms)
    ]
    if len(matched_subtypes) == 1:
        return matched_subtypes[0]
    if len(matched_subtypes) > 1:
        return ""

    proposed = _clean(llm_requirement_subtype).lower()
    return proposed if proposed in set(load_eligibility_subtypes()) else ""


def classify_requirement_type(
    requirement_text: str,
    matched_job_text: str = "",
    llm_requirement_type: str = "",
) -> str:
    """Return the deterministically-validated requirement_type.

    llm_requirement_type must already be a validated member of
    LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES (or empty); malformed LLM output is
    handled by the caller before this function runs.
    """
    combined_norm = _clean(f"{requirement_text} {matched_job_text}").lower()
    if not combined_norm:
        return _UNCERTAIN

    overrides = load_requirement_classification_overrides()
    for override_text, override_classification in overrides.items():
        if override_text and _term_matches(override_text, combined_norm):
            return override_classification

    has_eligibility_term = _matches_eligibility_term(combined_norm)
    has_duration_signal = bool(
        extract_required_experience_months(requirement_text, matched_job_text)
    )

    if has_eligibility_term and has_duration_signal:
        return _UNCERTAIN
    if has_eligibility_term:
        return _ELIGIBILITY
    if has_duration_signal:
        return _CAPABILITY

    if llm_requirement_type in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
        return llm_requirement_type
    return _UNCERTAIN
