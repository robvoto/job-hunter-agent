"""Signal inbox and approved knowledge store helpers."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from job_hunter_agent.capability_knowledge import (
    load_capability_knowledge,
    save_capability_knowledge,
    upsert_capability_entry,
)
from job_hunter_agent.hard_blocker_rules import (
    load_hard_blocker_rules,
    save_hard_blocker_rules,
    upsert_hard_blocker_rule,
)
from job_hunter_agent.job_quality import upsert_cv_farming_rule
from job_hunter_agent.job_types import load_job_type, save_job_type, upsert_job_type_entry
from job_hunter_agent.knowledge_store import get_knowledge, set_knowledge
from job_hunter_agent.llm_protocol import LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES
from job_hunter_agent.parsing_schema import (
    KEY_P_ROUTING,
    KEY_P_ROUTING_PRIMARY,
    KEY_P_ROUTING_SECONDARY,
    KEY_P_ROUTING_SUPPLEMENTARY,
)
from job_hunter_agent.requirement_classification import (
    upsert_requirement_classification_override,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_CV_FARMING_PATTERN,
    CATEGORY_HARD_BLOCKER_PATTERN,
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
    CATEGORY_PROFILE_SECTION_LABEL,
    CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW,
    LEARNING_CATEGORY_KEY,
    LEARNING_CONFIDENCE_KEY,
    LEARNING_CONTEXT_KEY,
    LEARNING_CONTEXT_TERMS_KEY,
    LEARNING_EVIDENCE_KEY,
    LEARNING_HISTORY_KEY,
    LEARNING_KNOWLEDGE_MATCH_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_NORMALIZED_KEY,
    LEARNING_NOTES_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SOURCE_KEY,
    LEARNING_STATUS_APPROVED,
    LEARNING_STATUS_IGNORED,
    LEARNING_STATUS_PENDING,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_SUGGESTED_VALUES_KEY,
    SIGNAL_ALIASES_KEY,
    VALID_SIGNAL_CATEGORIES,
)
from job_hunter_agent.text_processing import compact_whitespace

logger = logging.getLogger(__name__)

# Maps signal categories to knowledge store keys.
_CATEGORY_KNOWLEDGE_PATHS = {
    CATEGORY_CAPABILITY_CONCEPT: "capability_knowledge",
    CATEGORY_CV_FARMING_PATTERN: "cv_farming_rules",
    CATEGORY_HARD_BLOCKER_PATTERN: "hard_blocker_rules",
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE: "job_type",
}

# Categories handled by dedicated save functions in clear_signal_learning_state.
_SPECIALIZED_CLEAR_CATEGORIES = {
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
    CATEGORY_HARD_BLOCKER_PATTERN,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    return compact_whitespace(value)


def _clean_term(value: Any) -> str:
    return _clean_text(value).lower()


def _clean_text_list(values: Any) -> list[str]:
    if isinstance(values, str):
        raw_values = re.split(r"[\n,]", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        item = _clean_text(value)
        key = item.lower()
        if not item or key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _clean_aliases(values: Any, *, canonical: str = "") -> list[str]:
    if isinstance(values, str):
        raw_values = re.split(r"[\n,]", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    canonical_key = _clean_term(canonical)
    aliases: list[str] = []
    seen: set[str] = {canonical_key} if canonical_key else set()
    for value in raw_values:
        alias = _clean_text(value)
        alias_key = alias.lower()
        if not alias or alias_key in seen:
            continue
        seen.add(alias_key)
        aliases.append(alias)
    return aliases


def _clean_context_payload(record: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    source = _clean_text(record.get(LEARNING_SOURCE_KEY))
    if source:
        cleaned[LEARNING_SOURCE_KEY] = source

    aliases = _clean_aliases(
        record.get(SIGNAL_ALIASES_KEY), canonical=record.get(LEARNING_SIGNAL_KEY) or ""
    )
    if aliases:
        cleaned[SIGNAL_ALIASES_KEY] = aliases

    context = _clean_text_list(record.get(LEARNING_CONTEXT_KEY))
    if context:
        cleaned[LEARNING_CONTEXT_KEY] = context

    context_terms = _clean_text_list(record.get(LEARNING_CONTEXT_TERMS_KEY))
    if context_terms:
        cleaned[LEARNING_CONTEXT_TERMS_KEY] = context_terms

    evidence = _clean_text_list(record.get(LEARNING_EVIDENCE_KEY))
    if evidence:
        cleaned[LEARNING_EVIDENCE_KEY] = evidence

    confidence = _clean_term(record.get(LEARNING_CONFIDENCE_KEY))
    if confidence:
        cleaned[LEARNING_CONFIDENCE_KEY] = confidence

    notes = _clean_text(record.get(LEARNING_NOTES_KEY))
    if notes:
        cleaned[LEARNING_NOTES_KEY] = notes

    if record.get(LEARNING_NEEDS_REVIEW_KEY) is not None:
        cleaned[LEARNING_NEEDS_REVIEW_KEY] = bool(record.get(LEARNING_NEEDS_REVIEW_KEY))

    knowledge_match = _clean_text(record.get(LEARNING_KNOWLEDGE_MATCH_KEY))
    if knowledge_match:
        cleaned[LEARNING_KNOWLEDGE_MATCH_KEY] = knowledge_match

    suggested_category = _clean_term(record.get(LEARNING_SUGGESTED_CATEGORY_KEY))
    if suggested_category:
        cleaned[LEARNING_SUGGESTED_CATEGORY_KEY] = suggested_category

    suggested_values = _clean_text_list(record.get(LEARNING_SUGGESTED_VALUES_KEY))
    if suggested_values:
        cleaned[LEARNING_SUGGESTED_VALUES_KEY] = suggested_values

    return cleaned


def _clean_history(history: Any) -> list[dict[str, Any]]:
    if not isinstance(history, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        action = _clean_text(entry.get("action"))
        timestamp = _clean_text(entry.get("timestamp"))
        category = _clean_term(entry.get(LEARNING_CATEGORY_KEY))
        if not action or not timestamp:
            continue
        item: dict[str, Any] = {"action": action, "timestamp": timestamp}
        if category:
            item[LEARNING_CATEGORY_KEY] = category
        cleaned.append(item)
    return cleaned


def _signal_key(signal: Any) -> str:
    return _clean_term(signal)


def _make_pending_record(
    signal: str, category: str = "", metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    now = _now_iso()
    cleaned_signal = _clean_text(signal)
    metadata = metadata or {}
    original_texts = _clean_text_list(metadata.get("original_texts"))
    aliases = _clean_aliases(metadata.get(SIGNAL_ALIASES_KEY), canonical=cleaned_signal)
    if cleaned_signal:
        original_texts = [cleaned_signal, *original_texts]
    original_texts = _clean_text_list(original_texts)
    record = {
        LEARNING_SIGNAL_KEY: cleaned_signal,
        LEARNING_NORMALIZED_KEY: _signal_key(cleaned_signal),
        LEARNING_ORIGINAL_TEXTS_KEY: original_texts or [cleaned_signal],
        LEARNING_CATEGORY_KEY: _clean_term(category),
        LEARNING_HISTORY_KEY: [
            {
                "action": "added",
                "timestamp": now,
            }
        ],
    }
    if aliases:
        record[SIGNAL_ALIASES_KEY] = aliases
    record.update(_clean_context_payload(metadata or {}))
    return record


def _normalize_pending_record(key: str, record: Any) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None

    status = _clean_term(record.get("learning_status") or record.get("decision"))
    if status in {LEARNING_STATUS_APPROVED, LEARNING_STATUS_IGNORED, "use", "ignore"}:
        return None

    signal = _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
    if not signal:
        return None

    original_texts: list[str] = []
    seen: set[str] = set()
    for value in [signal, *(record.get(LEARNING_ORIGINAL_TEXTS_KEY) or [])]:
        cleaned = _clean_text(value)
        cleaned_key = cleaned.lower()
        if not cleaned or cleaned_key in seen:
            continue
        seen.add(cleaned_key)
        original_texts.append(cleaned)

    category = _clean_term(record.get(LEARNING_CATEGORY_KEY))
    suggested_category = _clean_term(record.get(LEARNING_SUGGESTED_CATEGORY_KEY))
    context = _clean_context_payload(record)
    aliases = _clean_aliases(record.get(SIGNAL_ALIASES_KEY), canonical=signal)

    history = _clean_history(record.get(LEARNING_HISTORY_KEY))
    if not history:
        history = [
            {
                "action": "added",
                "timestamp": _now_iso(),
            }
        ]

    return {
        LEARNING_SIGNAL_KEY: signal,
        LEARNING_NORMALIZED_KEY: _signal_key(key or signal),
        LEARNING_ORIGINAL_TEXTS_KEY: original_texts,
        LEARNING_CATEGORY_KEY: category,
        LEARNING_SUGGESTED_CATEGORY_KEY: suggested_category,
        LEARNING_HISTORY_KEY: history,
        **context,
        **({SIGNAL_ALIASES_KEY: aliases} if aliases else {}),
    }


def _normalize_registry(registry: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(registry, dict):
        return {}
    cleaned: dict[str, dict[str, Any]] = {}
    for raw_key, record in registry.items():
        key = _signal_key(raw_key)
        normalized = _normalize_pending_record(key, record)
        if normalized is None:
            continue
        cleaned[key] = normalized
    return cleaned


def _load_approved_knowledge_payload(knowledge_key: str) -> dict[str, Any]:
    payload = get_knowledge(knowledge_key) or {}
    payload.setdefault("kind", "managed_knowledge")
    payload.setdefault("entries", [])
    return payload


def _save_approved_knowledge_payload(knowledge_key: str, payload: dict[str, Any]) -> None:
    payload = dict(payload or {})
    payload["kind"] = "managed_knowledge"
    payload.setdefault("entries", [])
    payload["entries"] = [
        entry
        for entry in payload["entries"]
        if isinstance(entry, dict) and _clean_text(entry.get("value"))
    ]
    set_knowledge(knowledge_key, payload)


def _entry_terms(entry: dict[str, Any]) -> list[str]:
    value = _clean_text(entry.get("value"))
    aliases = _clean_aliases(entry.get("aliases"), canonical=value)
    return [value, *aliases] if value else []


def _append_knowledge_entry(knowledge_key: str, value: str, aliases: list[str]) -> None:
    payload = _load_approved_knowledge_payload(knowledge_key)
    entries = payload.setdefault("entries", [])
    canonical = _clean_text(value)
    if not canonical:
        return
    canonical_key = canonical.lower()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if _clean_term(entry.get("value")) == canonical_key:
            existing_aliases = _clean_aliases(entry.get("aliases"), canonical=canonical)
            merged = []
            seen = {canonical_key}
            for alias in [*existing_aliases, *aliases]:
                alias_key = alias.lower()
                if alias_key in seen:
                    continue
                seen.add(alias_key)
                merged.append(alias)
            entry["value"] = canonical
            entry["aliases"] = merged
            _save_approved_knowledge_payload(knowledge_key, payload)
            return
    entries.append(
        {
            "value": canonical,
            "aliases": aliases,
        }
    )
    _save_approved_knowledge_payload(knowledge_key, payload)


def load_registry() -> dict[str, dict[str, Any]]:
    return _normalize_registry(get_knowledge("signal_registry") or {})


def _approved_signal_keys() -> set[str]:
    keys: set[str] = set()
    for item in load_approved_signal_catalog():
        if not isinstance(item, dict):
            continue
        for term in item.get("terms", []) or []:
            term_key = _clean_term(term)
            if term_key:
                keys.add(term_key)
    return keys


def filter_registerable_signals(
    signal_names: list[str | dict[str, Any]],
) -> list[str | dict[str, Any]]:
    if not signal_names:
        return []
    registry_keys = set(load_registry().keys())
    ignored_keys = set((get_knowledge("ignored_signal") or {}).keys())
    approved_keys = _approved_signal_keys()
    filtered: list[str | dict[str, Any]] = []
    seen: set[str] = set()
    for item in signal_names:
        if isinstance(item, dict):
            signal = _clean_text(
                item.get(LEARNING_SIGNAL_KEY) or item.get("value") or item.get("name")
            )
        else:
            signal = _clean_text(item)
        key = _signal_key(signal)
        if not key or key in seen:
            continue
        if key in registry_keys or key in ignored_keys or key in approved_keys:
            continue
        seen.add(key)
        filtered.append(item)
    return filtered


def save_registry(registry: dict[str, dict[str, Any]]) -> None:
    set_knowledge("signal_registry", _normalize_registry(registry))


def signal_in_approved_knowledge(
    category: str,
    signal: str,
    aliases: list[str] | None = None,
    context_terms: list[str] | None = None,
) -> tuple[bool, str]:
    category_key = _clean_term(category)
    if (
        category_key not in _CATEGORY_KNOWLEDGE_PATHS
        and category_key != CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE
    ):
        return False, ""

    query_terms = _clean_text_list([signal, *(aliases or [])])
    if not query_terms:
        return False, ""

    if category_key == CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE:
        query_keys = {_signal_key(term) for term in query_terms}
        for raw_value, canonical_value in load_job_type().items():
            if _signal_key(raw_value) in query_keys or _signal_key(canonical_value) in query_keys:
                return True, _clean_text(canonical_value)
        return False, ""

    for item in load_approved_signal_catalog():
        if item.get(LEARNING_CATEGORY_KEY) != category_key:
            continue
        if category_key == CATEGORY_HARD_BLOCKER_PATTERN:
            continue
        terms = [term for term in item.get("terms", []) if isinstance(term, str)]
        if not terms:
            continue
        term_keys = {_clean_term(term) for term in terms}
        if any(_clean_term(term) in term_keys for term in query_terms):
            return True, _clean_text(item.get("label"))
    return False, ""


def register_signals(signal_names: list[str | dict[str, Any]], category: str = "") -> None:
    if not signal_names:
        return
    signal_names = filter_registerable_signals(signal_names)
    if not signal_names:
        return
    registry = load_registry()
    changed = False
    category_key = _clean_term(category)
    for name in signal_names:
        metadata: dict[str, Any] = {}
        if isinstance(name, dict):
            signal = _clean_text(
                name.get(LEARNING_SIGNAL_KEY) or name.get("value") or name.get("name")
            )
            metadata = {
                key: value
                for key, value in name.items()
                if key not in {LEARNING_SIGNAL_KEY, "value", "name", LEARNING_CATEGORY_KEY}
            }
            item_category = _clean_term(name.get(LEARNING_CATEGORY_KEY) or category_key)
        else:
            signal = _clean_text(name)
            item_category = category_key
        if not signal:
            continue
        key = _signal_key(signal)
        existing = registry.get(key)
        if existing is None:
            registry[key] = _make_pending_record(signal, item_category, metadata)
            changed = True
            continue
        original_texts = existing.setdefault(LEARNING_ORIGINAL_TEXTS_KEY, [])
        incoming_originals = _clean_text_list(metadata.get(LEARNING_ORIGINAL_TEXTS_KEY))
        for value in _clean_text_list([signal, *incoming_originals]):
            if value not in original_texts:
                original_texts.append(value)
                changed = True
        suggested_category = _clean_term(metadata.get(LEARNING_SUGGESTED_CATEGORY_KEY))
        if suggested_category and not _clean_term(existing.get(LEARNING_SUGGESTED_CATEGORY_KEY)):
            existing[LEARNING_SUGGESTED_CATEGORY_KEY] = suggested_category
            changed = True
        if item_category and not _clean_term(existing.get(LEARNING_CATEGORY_KEY)):
            existing[LEARNING_CATEGORY_KEY] = item_category
            existing.setdefault(LEARNING_HISTORY_KEY, []).append(
                {
                    "action": "categorized",
                    "timestamp": _now_iso(),
                    LEARNING_CATEGORY_KEY: item_category,
                }
            )
            changed = True
        if metadata:
            context = _clean_context_payload({**existing, **metadata})
            for key_name, value in context.items():
                if existing.get(key_name) == value:
                    continue
                existing[key_name] = value
                changed = True
    if changed:
        save_registry(registry)


def set_signal_category(key: str, category: str) -> dict[str, Any] | None:
    key = _signal_key(key)
    category_key = _clean_term(category)
    if not key:
        return None
    registry = load_registry()
    record = registry.get(key)
    if record is None:
        return None
    current = _clean_term(record.get(LEARNING_CATEGORY_KEY))
    if current == category_key:
        return record
    record[LEARNING_CATEGORY_KEY] = category_key
    record.setdefault(LEARNING_HISTORY_KEY, []).append(
        {
            "action": "categorized",
            "timestamp": _now_iso(),
            LEARNING_CATEGORY_KEY: category_key,
        }
    )
    save_registry(registry)
    return record


_BUCKET_TO_ROUTING_KEY = {
    "primary": KEY_P_ROUTING_PRIMARY,
    "secondary": KEY_P_ROUTING_SECONDARY,
    "supplementary": KEY_P_ROUTING_SUPPLEMENTARY,
}


def upsert_profile_section_label(word: str, bucket: str) -> None:
    """Append word to the correct routing list in parsing_rules."""
    word = _clean_term(word)
    list_key = _BUCKET_TO_ROUTING_KEY.get(bucket)
    if not word or not list_key:
        return
    payload = get_knowledge("parsing_rules")
    if not payload:
        return
    routing = payload.get(KEY_P_ROUTING)
    if not isinstance(routing, dict):
        return
    labels = routing.get(list_key)
    if not isinstance(labels, list):
        return
    existing = [str(l).strip().lower() for l in labels]
    if word in existing:
        return
    labels.append(word)
    payload["version"] = int(payload.get("version", 0)) + 1
    set_knowledge("parsing_rules", payload)
    logger.info("Auto-added profile section label '%s' to %s", word, list_key)


def approve_signal(
    key: str,
    category: str = "",
    value: str = "",
    classification: str = "",
) -> dict[str, Any] | None:
    """Promote a reviewed signal into its owning knowledge store.

    Requirement-type review is an explicit human classification; never infer or
    default that classification from an LLM suggestion.
    """
    key = _signal_key(key)
    if not key:
        return None
    registry = load_registry()
    record = registry.get(key)
    if record is None:
        return None

    category_key = _clean_term(
        category or record.get(LEARNING_CATEGORY_KEY) or record.get(LEARNING_SUGGESTED_CATEGORY_KEY)
    )
    if category_key not in VALID_SIGNAL_CATEGORIES:
        raise ValueError(f"Invalid category '{category_key}'.")

    explicit_value = _clean_text(value)
    aliases = _clean_aliases(
        record.get(SIGNAL_ALIASES_KEY),
        canonical=explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key),
    )
    if category_key == CATEGORY_CAPABILITY_CONCEPT:
        value = explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
        upsert_capability_entry(value, aliases)
    elif category_key == CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE:
        value = explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
        suggested = _clean_text_list(record.get(LEARNING_SUGGESTED_VALUES_KEY))
        upsert_job_type_entry(value, suggested[0] if suggested else value)
    elif category_key == CATEGORY_HARD_BLOCKER_PATTERN:
        value = explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
        upsert_hard_blocker_rule(value, aliases)
    elif category_key == CATEGORY_CV_FARMING_PATTERN:
        value = explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
        upsert_cv_farming_rule(value, aliases)
    elif category_key == CATEGORY_PROFILE_SECTION_LABEL:
        value = explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
        suggested = _clean_text_list(record.get(LEARNING_SUGGESTED_VALUES_KEY))
        upsert_profile_section_label(value, suggested[0] if suggested else "primary")
    elif category_key == CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW:
        value = explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
        classification_key = _clean_term(classification)
        if not classification_key:
            raise ValueError(
                "Requirement classification is required; choose capability, eligibility, or qualification."
            )
        if classification_key not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            raise ValueError(
                f"Invalid requirement classification '{classification_key}'; choose capability, eligibility, or qualification."
            )
        upsert_requirement_classification_override(value, classification_key)
    else:
        value = explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
        _append_knowledge_entry(_CATEGORY_KNOWLEDGE_PATHS[category_key], value, aliases)

    approved_record = {
        LEARNING_SIGNAL_KEY: explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key),
        LEARNING_NORMALIZED_KEY: key,
        LEARNING_ORIGINAL_TEXTS_KEY: record.get(LEARNING_ORIGINAL_TEXTS_KEY)
        or [explicit_value or _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)],
        LEARNING_CATEGORY_KEY: category_key,
    }
    if aliases:
        approved_record[SIGNAL_ALIASES_KEY] = aliases
    registry.pop(key, None)
    save_registry(registry)
    return approved_record


def ignore_signal(key: str) -> dict[str, Any] | None:
    key = _signal_key(key)
    if not key:
        return None
    registry = load_registry()
    record = registry.pop(key, None)
    if record is None:
        return None
    ignored_archive = get_knowledge("ignored_signal") or {}
    record = dict(record)
    record.setdefault(LEARNING_HISTORY_KEY, []).append(
        {
            "action": "ignored",
            "timestamp": _now_iso(),
        }
    )
    ignored_archive[key] = record
    save_registry(registry)
    set_knowledge("ignored_signal", ignored_archive)
    return record


def clear_signal_learning_state() -> None:
    set_knowledge("signal_registry", {})
    set_knowledge("ignored_signal", {})
    save_capability_knowledge([])
    save_job_type({})
    save_hard_blocker_rules([])
    for category, knowledge_key in _CATEGORY_KNOWLEDGE_PATHS.items():
        if category in _SPECIALIZED_CLEAR_CATEGORIES:
            continue
        _save_approved_knowledge_payload(
            knowledge_key,
            {
                "kind": "managed_knowledge",
                "entries": [],
            },
        )


def load_approved_signal_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for category, knowledge_key in _CATEGORY_KNOWLEDGE_PATHS.items():
        if category == CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE:
            for raw_value, canonical_value in load_job_type().items():
                cleaned_raw = _clean_text(raw_value)
                cleaned_canonical = _clean_text(canonical_value)
                if not cleaned_raw or not cleaned_canonical:
                    continue
                terms = [cleaned_raw]
                if cleaned_canonical.lower() != cleaned_raw.lower():
                    terms.append(cleaned_canonical)
                catalog.append(
                    {
                        "category": category,
                        "label": cleaned_canonical,
                        "terms": terms,
                    }
                )
            continue
        if category == CATEGORY_CAPABILITY_CONCEPT:
            entries = load_capability_knowledge()
        elif category == CATEGORY_CV_FARMING_PATTERN:
            payload = _load_approved_knowledge_payload(knowledge_key)
            entries = payload.get("entries", [])
        elif category == CATEGORY_HARD_BLOCKER_PATTERN:
            entries = load_hard_blocker_rules()
        else:
            payload = _load_approved_knowledge_payload(knowledge_key)
            entries = payload.get("entries", [])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            value = _clean_text(entry.get("value"))
            if not value:
                continue
            terms = _entry_terms(entry)
            if not terms:
                continue
            catalog.append(
                {
                    "category": category,
                    "label": value,
                    "terms": terms,
                }
            )
    return catalog


def get_learning_status(signal_name: str) -> str:
    key = _signal_key(signal_name)
    if not key:
        return LEARNING_STATUS_PENDING
    if key in load_registry():
        return LEARNING_STATUS_PENDING
    if key in (get_knowledge("ignored_signal") or {}):
        return LEARNING_STATUS_IGNORED
    return LEARNING_STATUS_APPROVED
