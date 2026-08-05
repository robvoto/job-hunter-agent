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
  as uncertain for human review rather than guessed.
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


def _load_eligibility_terms() -> list[str]:
    payload = get_knowledge(_TERMS_KNOWLEDGE_KEY) or {}
    categories = payload.get("eligibility_terms")
    if not isinstance(categories, dict):
        return []
    terms: list[str] = []
    for values in categories.values():
        if not isinstance(values, list):
            continue
        for term in values:
            cleaned = _clean(term).lower()
            if cleaned:
                terms.append(cleaned)
    return terms


def _term_matches(term: str, text_norm: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
    return re.search(pattern, text_norm) is not None


def _matches_eligibility_term(text_norm: str) -> bool:
    return any(_term_matches(term, text_norm) for term in _load_eligibility_terms())


def load_requirement_classification_overrides() -> dict[str, str]:
    """Return {normalized requirement text: human-approved classification}."""
    payload = get_knowledge(_OVERRIDES_KNOWLEDGE_KEY) or {}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return {}
    overrides: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        text = _clean(entry.get("value")).lower()
        classification = _clean(entry.get("classification")).lower()
        if text and classification in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            overrides[text] = classification
    return overrides


def upsert_requirement_classification_override(text: str, classification: str) -> dict[str, str]:
    """Persist a human-approved requirement classification from the review flow."""
    text_norm = _clean(text).lower()
    classification_norm = _clean(classification).lower()
    if not text_norm:
        raise ValueError("text is required")
    if classification_norm not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
        raise ValueError(f"classification must be one of {sorted(LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES)}")

    overrides = load_requirement_classification_overrides()
    overrides[text_norm] = classification_norm
    set_knowledge(
        _OVERRIDES_KNOWLEDGE_KEY,
        {
            "kind": "managed_knowledge",
            "entries": [
                {"value": value, "classification": value_classification}
                for value, value_classification in overrides.items()
            ],
        },
    )
    return overrides


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
