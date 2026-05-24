"""Role title normalisation helpers."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from job_hunter_agent.llm_gate import llm_should_consider_learning_candidates
from job_hunter_agent.role_title_knowledge import load_role_title_knowledge
from job_hunter_agent.signal_schema import (
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE,
    LEARNING_CONFIDENCE_KEY,
    LEARNING_CONTEXT_TERMS_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_SUGGESTED_VALUES_KEY,
)


NORMALIZATION_STRIP_OUTER_PUNCTUATION_KEY = "strip_outer_punctuation"
NORMALIZATION_COLLAPSE_SPACES_KEY = "collapse_spaces"
NORMALIZATION_LOWERCASE_FOR_MATCHING_KEY = "lowercase_for_matching"

NORMALIZED_TITLE_KEY = "normalized_title"
SENIORITY_TITLE_KEY = "seniority_modifiers"
BASE_ROLE_KEY = "base_role"
VARIANT_TERMS_KEY = "variant_terms"

RULES_KIND = "rules"
RULES_NAME = "title_normalization_rules"
RULES_KIND_KEY = "kind"
RULES_NAME_KEY = "name"
RULES_VERSION_KEY = "version"
RULES_UPDATED_AT_KEY = "updated_at"
RULES_SENIORITY_MODIFIERS_KEY = "seniority_modifiers"
RULES_ABBREVIATION_EXPANSIONS_KEY = "abbreviation_expansions"
RULES_CONTEXTUAL_ABBREVIATION_EXPANSIONS_KEY = "contextual_abbreviation_expansions"
RULES_NORMALIZATION_KEY = "normalization"

VALUE_KEY = "value"
SUGGESTED_VALUES_KEY = "suggested_values"
CONTEXT_TERMS_KEY = "context_terms"
EVIDENCE_KEY = "evidence"
CONFIDENCE_KEY = "confidence"
NEEDS_REVIEW_KEY = "needs_review"
AMBIGUOUS = "ambiguous"

TITLE_NORMALIZATION_CANDIDATE = CATEGORY_TITLE_NORMALIZATION_CANDIDATE


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_payload() -> dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge
    return get_knowledge("title_normalization_rules") or {}


def load_title_normalization_rules() -> dict[str, Any]:
    payload = _load_payload()
    if not payload:
        raise ValueError("title_normalization_rules.json must contain a rules object")
    return payload


def _strip_outer_punctuation(value: str) -> str:
    return re.sub(r"^[\s\W_]+|[\s\W_]+$", "", value).strip()


def _clean_rule_token(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _clean_rule_text_list(values: Any) -> list[str]:
    if isinstance(values, str):
        raw_values = re.split(r"[\n,]", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        token = _clean_rule_token(value)
        if not token or token in seen:
            continue
        seen.add(token)
        cleaned.append(token)
    return cleaned


def _load_seniority_modifiers() -> frozenset[str]:
    try:
        payload = load_title_normalization_rules()
    except Exception:
        return frozenset()
    modifiers = payload.get(RULES_SENIORITY_MODIFIERS_KEY)
    if not isinstance(modifiers, list):
        return frozenset()
    return frozenset(
        token
        for token in (_clean_rule_token(value) for value in modifiers)
        if token
    )


def _load_contextual_abbreviation_expansions(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw = payload.get(RULES_CONTEXTUAL_ABBREVIATION_EXPANSIONS_KEY)
    if not isinstance(raw, dict):
        return {}

    contextual: dict[str, list[dict[str, Any]]] = {}
    for raw_abbreviation, entries in raw.items():
        abbreviation = _clean_rule_token(raw_abbreviation)
        if not abbreviation or not isinstance(entries, list):
            continue
        cleaned_entries: list[dict[str, Any]] = []
        seen: set[tuple[str, tuple[str, ...]]] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            expansion = _clean_rule_token(entry.get("expansion"))
            context_terms = _clean_rule_text_list(entry.get(CONTEXT_TERMS_KEY))
            if not expansion or not context_terms:
                continue
            entry_key = (expansion, tuple(context_terms))
            if entry_key in seen:
                continue
            seen.add(entry_key)
            cleaned_entries.append({
                "expansion": expansion,
                CONTEXT_TERMS_KEY: context_terms,
            })
        if cleaned_entries:
            contextual[abbreviation] = cleaned_entries
    return contextual


def _context_terms_in_text(context_terms: list[str], source_text: str) -> bool:
    if not context_terms or not source_text:
        return False
    haystack = _clean_text(source_text).lower()
    if not haystack:
        return False
    for term in context_terms:
        if not term:
            return False
        if not re.search(rf"(?<!\w){re.escape(term)}(?!\w)", haystack):
            return False
    return True


def find_approved_title_normalization(
    signal: Any,
    suggested_values: Any = None,
    context_terms: Any = None,
) -> tuple[bool, str]:
    raw_signal = _clean_rule_token(signal)
    if not raw_signal:
        return False, ""

    try:
        payload = load_title_normalization_rules()
    except Exception:
        return False, ""

    expansions = payload.get(RULES_ABBREVIATION_EXPANSIONS_KEY)
    if isinstance(expansions, dict):
        expansion = _clean_rule_token(expansions.get(raw_signal))
        if expansion:
            return True, expansion

    contextual = _load_contextual_abbreviation_expansions(payload)
    entries = contextual.get(raw_signal, [])
    if not entries:
        return False, ""

    candidate_context = _clean_rule_text_list(context_terms)
    candidate_values = set(_clean_rule_text_list(suggested_values))
    matches: list[str] = []
    for entry in entries:
        expansion = _clean_rule_token(entry.get("expansion"))
        if not expansion:
            continue
        entry_context = _clean_rule_text_list(entry.get(CONTEXT_TERMS_KEY))
        if not candidate_context:
            continue
        if not set(entry_context).issubset(candidate_context):
            continue
        if candidate_values and expansion not in candidate_values:
            continue
        matches.append(expansion)
    if len(matches) == 1:
        return True, matches[0]
    return False, ""


def extract_seniority_modifiers(value: Any) -> list[str]:
    normalized = normalize_title_text(value)
    if not normalized:
        return []

    modifiers = _load_seniority_modifiers()
    if not modifiers:
        return []

    seen: set[str] = set()
    matched: list[str] = []
    for token in normalized.split():
        if token in modifiers and token not in seen:
            seen.add(token)
            matched.append(token)
    return matched


@lru_cache(maxsize=1)
def _load_role_title_tokens() -> frozenset[str]:
    try:
        entries = load_role_title_knowledge()
    except Exception:
        return frozenset()

    tokens: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        value = _clean_rule_token(entry.get("value"))
        token = re.sub(r"[^a-z0-9+#/&-]", "", value.lower()).strip("-/")
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 4 and not token.endswith("ss") and not token.endswith("is"):
            token = token[:-1]
        if token:
            tokens.append(token)
    return frozenset(tokens)


def decompose_title_text(value: Any, source_text: Any = "") -> dict[str, Any]:
    normalized = normalize_title_text(value, source_text)
    if not normalized:
        return {
            NORMALIZED_TITLE_KEY: "",
            SENIORITY_TITLE_KEY: [],
            BASE_ROLE_KEY: "",
            VARIANT_TERMS_KEY: "",
        }

    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return {
            NORMALIZED_TITLE_KEY: normalized,
            SENIORITY_TITLE_KEY: [],
            BASE_ROLE_KEY: "",
            VARIANT_TERMS_KEY: "",
        }

    seniority_modifiers = extract_seniority_modifiers(normalized)
    seniority_set = set(seniority_modifiers)
    family_tokens = [token for token in tokens if token not in seniority_set]
    if not family_tokens:
        return {
            NORMALIZED_TITLE_KEY: normalized,
            SENIORITY_TITLE_KEY: seniority_modifiers,
            BASE_ROLE_KEY: "",
            VARIANT_TERMS_KEY: "",
        }

    role_tokens = _load_role_title_tokens()
    base_role_tokens = list(family_tokens)
    variant_terms_tokens: list[str] = []
    if role_tokens:
        role_indices = [index for index, token in enumerate(family_tokens) if token in role_tokens]
        if role_indices:
            last_role_index = role_indices[-1] + 1
            base_role_tokens = family_tokens[:last_role_index]
            variant_terms_tokens = family_tokens[last_role_index:]

    base_role = " ".join(base_role_tokens).strip()
    variant_terms = " ".join(variant_terms_tokens).strip()
    return {
        NORMALIZED_TITLE_KEY: normalized,
        SENIORITY_TITLE_KEY: seniority_modifiers,
        BASE_ROLE_KEY: base_role,
        VARIANT_TERMS_KEY: variant_terms,
    }


def derive_base_title_from_seniority(value: Any, source_text: Any = "") -> str:
    return str(decompose_title_text(value, source_text).get(BASE_ROLE_KEY) or "").strip()


def _load_search_qualifier_prefix_strip() -> frozenset[str]:
    try:
        payload = load_title_normalization_rules()
    except Exception:
        return frozenset()
    tokens = payload.get("search_qualifier_prefix_strip")
    if not isinstance(tokens, list):
        return frozenset()
    return frozenset(
        token
        for token in (_clean_rule_token(value) for value in tokens)
        if token
    )


def derive_search_keyword(value: Any, source_text: Any = "") -> str:
    """Derive a SEEK search keyword: strip seniority then leading qualifier prefixes."""
    base = derive_base_title_from_seniority(value, source_text)
    if not base:
        return ""
    qualifier_prefixes = _load_search_qualifier_prefix_strip()
    if not qualifier_prefixes:
        return base
    tokens = base.split()
    while tokens and tokens[0] in qualifier_prefixes:
        tokens = tokens[1:]
    return " ".join(tokens) if tokens else base


def classify_title_normalization_candidate(title: Any, source_text: Any = "") -> dict[str, Any] | None:
    raw_title = _clean_text(title)
    if not raw_title:
        return None

    llm_text = "\n".join(part for part in [raw_title, _clean_text(source_text)] if part)
    try:
        candidates = llm_should_consider_learning_candidates(llm_text)
    except Exception:
        return None

    for candidate in candidates:
        if _clean_rule_token(candidate.get(LEARNING_SUGGESTED_CATEGORY_KEY)) != CATEGORY_TITLE_NORMALIZATION_CANDIDATE:
            continue
        signal = _clean_text(candidate.get(LEARNING_SIGNAL_KEY))
        if not signal:
            continue
        known, _ = find_approved_title_normalization(
            signal,
            candidate.get(LEARNING_SUGGESTED_VALUES_KEY) or None,
            candidate.get(LEARNING_CONTEXT_TERMS_KEY) or None,
        )
        if known:
            continue
        return {
            VALUE_KEY: _clean_rule_token(signal),
            SUGGESTED_VALUES_KEY: [
                _clean_text(value)
                for value in (candidate.get(LEARNING_SUGGESTED_VALUES_KEY) or [])
                if _clean_text(value)
            ],
            CONTEXT_TERMS_KEY: _clean_rule_text_list(candidate.get(LEARNING_CONTEXT_TERMS_KEY)),
            EVIDENCE_KEY: [
                _clean_text(value)
                for value in (candidate.get(LEARNING_ORIGINAL_TEXTS_KEY) or [raw_title])
                if _clean_text(value)
            ] or [raw_title],
            CONFIDENCE_KEY: _clean_rule_token(candidate.get(LEARNING_CONFIDENCE_KEY)) or AMBIGUOUS,
            NEEDS_REVIEW_KEY: bool(candidate.get(LEARNING_NEEDS_REVIEW_KEY, True)),
        }
    return None


def normalize_title_text(value: Any, source_text: Any = "") -> str:
    payload = load_title_normalization_rules()
    normalization = payload.get(RULES_NORMALIZATION_KEY) if isinstance(payload.get(RULES_NORMALIZATION_KEY), dict) else {}
    text = _clean_text(value)
    if not text:
        return ""

    if normalization.get(NORMALIZATION_STRIP_OUTER_PUNCTUATION_KEY, True):
        text = _strip_outer_punctuation(text)

    if normalization.get(NORMALIZATION_COLLAPSE_SPACES_KEY, True):
        text = re.sub(r"\s+", " ", text).strip()

    if normalization.get(NORMALIZATION_LOWERCASE_FOR_MATCHING_KEY, True):
        text = text.lower()

    expansions = payload.get(RULES_ABBREVIATION_EXPANSIONS_KEY)
    contextual_expansions = _load_contextual_abbreviation_expansions(payload)
    if not isinstance(expansions, dict) and not contextual_expansions:
        return text

    expanded_tokens: list[str] = []
    for token in re.split(r"\s+", text):
        cleaned_token = _strip_outer_punctuation(token)
        if not cleaned_token:
            continue
        expansion = ""
        if contextual_expansions and source_text:
            expansion = _contextual_expansion_for_token(cleaned_token, source_text, contextual_expansions)
        if not expansion and isinstance(expansions, dict):
            expansion = _clean_rule_token(expansions.get(cleaned_token))
        if expansion:
            expanded_tokens.extend(part for part in expansion.split() if part)
            continue
        expanded_tokens.append(cleaned_token)

    normalized = " ".join(expanded_tokens)
    if normalization.get(NORMALIZATION_COLLAPSE_SPACES_KEY, True):
        normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalization.get(NORMALIZATION_LOWERCASE_FOR_MATCHING_KEY, True):
        normalized = normalized.lower()
    return normalized


def _contextual_expansion_for_token(
    token: str,
    source_text: Any,
    contextual_expansions: dict[str, list[dict[str, Any]]],
) -> str:
    entries = contextual_expansions.get(_clean_rule_token(token), [])
    if not entries:
        return ""
    matches: list[str] = []
    for entry in entries:
        expansion = _clean_rule_token(entry.get("expansion"))
        context_terms = _clean_rule_text_list(entry.get(CONTEXT_TERMS_KEY))
        if not expansion or not context_terms:
            continue
        if _context_terms_in_text(context_terms, _clean_text(source_text)):
            matches.append(expansion)
    if len(matches) == 1:
        return matches[0]
    return ""
