from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from job_hunter_agent.role_title_knowledge import load_role_title_knowledge
from job_hunter_agent.paths import OUTPUT_DIR, TITLE_NORMALIZATION_RULES_PATH
from job_hunter_agent.signal_registry import register_signals
from job_hunter_agent.signal_schema import (
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE,
    LEARNING_CATEGORY_KEY,
    LEARNING_EVIDENCE_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SOURCE_KEY,
    SOURCE_CV_PARSING,
)
from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.parsing_schema import (
    PARSING_STOPWORDS_KEY,
    KEY_P_TITLE_VERB_BLOCKERS,
)


TITLE_NORMALIZATION_REVIEW_PATH = OUTPUT_DIR / "title_normalization_review.json"

NORMALIZATION_STRIP_OUTER_PUNCTUATION_KEY = "strip_outer_punctuation"
NORMALIZATION_COLLAPSE_SPACES_KEY = "collapse_spaces"
NORMALIZATION_LOWERCASE_FOR_MATCHING_KEY = "lowercase_for_matching"

NORMALIZED_TITLE_KEY = "normalized_title"
SENIORITY_TITLE_KEY = "seniority_modifiers"
BASE_ROLE_KEY = "base_role"
VARIANT_TERMS_KEY = "variant_terms"

SUMMARY_PENDING_KEY = "pending"

RULES_KIND = "rules"
RULES_NAME = "title_normalization_rules"
RULES_KIND_KEY = "kind"
RULES_NAME_KEY = "name"
RULES_VERSION_KEY = "version"
RULES_UPDATED_AT_KEY = "updated_at"
RULES_SENIORITY_MODIFIERS_KEY = "seniority_modifiers"
RULES_ABBREVIATION_EXPANSIONS_KEY = "abbreviation_expansions"
RULES_NORMALIZATION_KEY = "normalization"

REVIEW_KIND = "title_normalization_review"
REVIEW_NAME = "title_normalization_review"
REVIEW_ENTRIES_KEY = "entries"

VALUE_KEY = "value"
SUGGESTED_VALUES_KEY = "suggested_values"
EVIDENCE_KEY = "evidence"
SOURCES_KEY = "sources"
CONFIDENCE_KEY = "confidence"
NEEDS_REVIEW_KEY = LEARNING_NEEDS_REVIEW_KEY
NOTE_KEY = "note"
AMBIGUOUS = "ambiguous"

LEARNING_CANDIDATES_KEY = "learning_candidates"
TITLE_DISCOVERY_CONFIG_KEY = "title_discovery_config"
STOPWORDS_KEY = "stopwords"
MIN_TOKEN_LEN_KEY = "min_token_len"
MAX_TOKEN_LEN_KEY = "max_token_len"
DISCOVERY_CONFIDENCE_KEY = "discovery_confidence"

TITLE_NORMALIZATION_CANDIDATE = CATEGORY_TITLE_NORMALIZATION_CANDIDATE
SOURCE_LABEL = SOURCE_CV_PARSING
SIGNAL_KEY = LEARNING_SIGNAL_KEY
CATEGORY_KEY = LEARNING_CATEGORY_KEY
SOURCE_FIELD_KEY = LEARNING_SOURCE_KEY


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _load_payload() -> dict[str, Any]:
    if not TITLE_NORMALIZATION_RULES_PATH.exists():
        return {}
    try:
        payload = json.loads(TITLE_NORMALIZATION_RULES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def load_title_normalization_rules() -> dict[str, Any]:
    payload = _load_payload()
    if not payload:
        raise ValueError("title_normalization_rules.json must contain a rules object")
    return payload


@lru_cache(maxsize=1)
def load_title_candidate_leading_verb_blockers() -> frozenset[str]:
    try:
        payload = load_parsing_rules()
    except Exception:
        return frozenset()
    blockers = payload.get(KEY_P_TITLE_VERB_BLOCKERS)
    if not isinstance(blockers, list):
        return frozenset()
    return frozenset(
        _clean_rule_token(value)
        for value in blockers
        if _clean_rule_token(value)
    )

def _save_rules_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault(RULES_KIND_KEY, RULES_KIND)
    normalized.setdefault(RULES_NAME_KEY, RULES_NAME)
    normalized.setdefault(RULES_VERSION_KEY, 1)
    normalized.setdefault(RULES_UPDATED_AT_KEY, "")
    normalized.setdefault(RULES_SENIORITY_MODIFIERS_KEY, [])
    normalized.setdefault(RULES_ABBREVIATION_EXPANSIONS_KEY, {})
    normalized.setdefault(RULES_NORMALIZATION_KEY, {})
    TITLE_NORMALIZATION_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    TITLE_NORMALIZATION_RULES_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _strip_outer_punctuation(value: str) -> str:
    return re.sub(r"^[\s\W_]+|[\s\W_]+$", "", value).strip()


def _clean_rule_token(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _load_seniority_modifiers() -> frozenset[str]:
    try:
        payload = load_title_normalization_rules()
    except Exception:
        return frozenset()
    modifiers = payload.get(RULES_SENIORITY_MODIFIERS_KEY)
    if not isinstance(modifiers, list):
        return frozenset()
    return frozenset(
        _clean_rule_token(value)
        for value in modifiers
        if _clean_rule_token(value)
    )


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

def decompose_title_text(value: Any) -> dict[str, Any]:
    normalized = normalize_title_text(value)
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


def derive_base_title_from_seniority(value: Any) -> str:
    return str(decompose_title_text(value).get(BASE_ROLE_KEY) or "").strip()


def _load_review_payload() -> dict[str, Any]:
    if not TITLE_NORMALIZATION_REVIEW_PATH.exists():
        return {RULES_KIND_KEY: REVIEW_KIND, RULES_NAME_KEY: REVIEW_NAME, RULES_VERSION_KEY: 1, REVIEW_ENTRIES_KEY: []}
    try:
        payload = json.loads(TITLE_NORMALIZATION_REVIEW_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}

def _save_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    normalized.setdefault(RULES_KIND_KEY, REVIEW_KIND)
    normalized.setdefault(RULES_NAME_KEY, REVIEW_NAME)
    normalized.setdefault(RULES_VERSION_KEY, 1)
    normalized.setdefault(RULES_UPDATED_AT_KEY, "")
    normalized.setdefault(REVIEW_ENTRIES_KEY, [])
    TITLE_NORMALIZATION_REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    TITLE_NORMALIZATION_REVIEW_PATH.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _normalize_review_entry(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    value = _clean_rule_token(entry.get(VALUE_KEY))
    if not value:
        return None
    suggested_values = []
    seen: set[str] = {value}
    for item in entry.get(SUGGESTED_VALUES_KEY) or []:
        suggested = _clean_rule_token(item)
        if not suggested or suggested in seen:
            continue
        seen.add(suggested)
        suggested_values.append(suggested)
    evidence = []
    seen_evidence: set[str] = set()
    for item in entry.get(EVIDENCE_KEY) or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        lowered = text.lower()
        if not text or lowered in seen_evidence:
            continue
        seen_evidence.add(lowered)
        evidence.append(text)
    sources = []
    seen_sources: set[str] = set()
    for item in entry.get(SOURCES_KEY) or []:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        lowered = text.lower()
        if not text or lowered in seen_sources:
            continue
        seen_sources.add(lowered)
        sources.append(text)
    normalized: dict[str, Any] = {
        VALUE_KEY: value,
        SUGGESTED_VALUES_KEY: suggested_values,
        EVIDENCE_KEY: evidence,
        SOURCES_KEY: sources,
        CONFIDENCE_KEY: _clean_rule_token(entry.get(CONFIDENCE_KEY)) or AMBIGUOUS,
        NEEDS_REVIEW_KEY: bool(entry.get(NEEDS_REVIEW_KEY, True)),
    }
    note = re.sub(r"\s+", " ", str(entry.get(NOTE_KEY) or "")).strip()
    if note:
        normalized[NOTE_KEY] = note
    return normalized

def load_title_normalization_review() -> list[dict[str, Any]]:
    payload = _load_review_payload()
    entries = payload.get(REVIEW_ENTRIES_KEY)
    if not isinstance(entries, list):
        raise ValueError("title_normalization_review.json must contain an entries list")
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        normalized = _normalize_review_entry(entry)
        if normalized is None:
            continue
        key = normalized[VALUE_KEY]
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(normalized)
    if cleaned != entries:
        save_title_normalization_review(cleaned)
    return cleaned

def save_title_normalization_review(entries: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _load_review_payload()
    payload.setdefault(RULES_KIND_KEY, REVIEW_KIND)
    payload.setdefault(RULES_NAME_KEY, REVIEW_NAME)
    payload.setdefault(RULES_VERSION_KEY, 1)
    payload.setdefault(RULES_UPDATED_AT_KEY, "")
    payload[REVIEW_ENTRIES_KEY] = [
        entry
        for entry in (
            _normalize_review_entry(item)
            for item in entries
        )
        if entry is not None
    ]
    return _save_review_payload(payload)

def classify_title_normalization_candidate(title: Any, source_text: Any = "") -> dict[str, Any] | None:
    raw_title = _clean_text(title)
    if not raw_title:
        return None

    lowered = raw_title.lower()
    tokens = re.findall(r"[a-z0-9]+", lowered)
    if not tokens:
        return None

    title_rules = load_title_normalization_rules()
    parsing_rules = load_parsing_rules()

    candidates = title_rules.get(LEARNING_CANDIDATES_KEY, {})
    expansions = title_rules.get(RULES_ABBREVIATION_EXPANSIONS_KEY, {})
    config = parsing_rules.get(TITLE_DISCOVERY_CONFIG_KEY, {})
    sw = set(parsing_rules.get(PARSING_STOPWORDS_KEY, []))

    for token in tokens:
        # 1. Existing candidate in knowledge base
        if token in candidates:
            cand_config = candidates[token]
            return {
                VALUE_KEY: token,
                SUGGESTED_VALUES_KEY: cand_config.get(SUGGESTED_VALUES_KEY, []),
                CONFIDENCE_KEY: cand_config.get(CONFIDENCE_KEY, AMBIGUOUS),
                EVIDENCE_KEY: [raw_title],
            }
        if token in expansions:
            expansion = _clean_text(expansions.get(token))
            if expansion:
                return {
                    VALUE_KEY: token,
                    SUGGESTED_VALUES_KEY: [expansion],
                    CONFIDENCE_KEY: config.get(DISCOVERY_CONFIDENCE_KEY, AMBIGUOUS),
                    EVIDENCE_KEY: [raw_title],
                }

        # 2. Discovery: find new abbreviations (e.g., 'ba', 'pm')
        if len(token) >= config.get(MIN_TOKEN_LEN_KEY, 2) and len(token) <= config.get(MAX_TOKEN_LEN_KEY, 3):
            if token not in sw:
                return {
                    VALUE_KEY: token,
                    SUGGESTED_VALUES_KEY: [],
                    CONFIDENCE_KEY: config.get(DISCOVERY_CONFIDENCE_KEY, AMBIGUOUS),
                    EVIDENCE_KEY: [raw_title],
                }
    return None


def learn_title_normalization_candidates(titles: list[str], source: str = "", source_text: str = "") -> dict[str, int]:
    summary = {SUMMARY_PENDING_KEY: 0}
    if not titles:
        return summary

    signals = []
    seen_tokens = set()
    for raw_title in titles:
        candidate = classify_title_normalization_candidate(raw_title, source_text)
        if not candidate:
            continue

        token = candidate["value"]
        if token in seen_tokens:
            continue
        seen_tokens.add(token)

        signal = {
            SIGNAL_KEY: token,
            LEARNING_SUGGESTED_CATEGORY_KEY: TITLE_NORMALIZATION_CANDIDATE,
            SOURCE_FIELD_KEY: source or SOURCE_LABEL,
            EVIDENCE_KEY: candidate.get(EVIDENCE_KEY, []),
            CONFIDENCE_KEY: candidate.get(CONFIDENCE_KEY, AMBIGUOUS),
            SUGGESTED_VALUES_KEY: candidate.get(SUGGESTED_VALUES_KEY, []),
            NEEDS_REVIEW_KEY: True,
        }
        signals.append(signal)

    if signals:
        register_signals(signals)
        summary[SUMMARY_PENDING_KEY] = len(signals)
    return summary


def normalize_title_text(value: Any) -> str:
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
    if not isinstance(expansions, dict) or not expansions:
        return text

    expanded_tokens: list[str] = []
    for token in re.split(r"\s+", text):
        cleaned_token = _strip_outer_punctuation(token)
        if not cleaned_token:
            continue
        expansion = _clean_text(expansions.get(cleaned_token))
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
