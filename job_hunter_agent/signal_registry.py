"""Signal inbox and approved knowledge store helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from job_hunter_agent.paths import (
    GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    CV_FARMING_RULES_PATH,
    HARD_BLOCKER_RULES_PATH,
    IGNORED_SIGNAL_ARCHIVE_PATH,
    PARSING_RULES_PATH,
    ROLE_TITLE_KNOWLEDGE_PATH,
    SIGNAL_REGISTRY_PATH as _REGISTRY_PATH,
    TITLE_NORMALIZATION_RULES_PATH,
)
from job_hunter_agent.parsing_schema import PARSING_TITLE_CANDIDATE_LEADING_VERB_BLOCKERS_KEY
from job_hunter_agent.job_types import JOB_TYPE_STORE_PATH, load_job_type, save_job_type, upsert_job_type_entry
from job_hunter_agent.hard_blocker_rules import (
    load_hard_blocker_rules,
    save_hard_blocker_rules,
    upsert_hard_blocker_rule,
)
from job_hunter_agent.job_quality import upsert_cv_farming_rule
from job_hunter_agent.capability_knowledge import (
    CAPABILITY_KNOWLEDGE_PATH,
    load_capability_knowledge,
    upsert_capability_entry,
    save_capability_knowledge,
)
from job_hunter_agent.role_title_knowledge import (
    load_role_title_knowledge,
    save_role_title_knowledge,
    upsert_role_title_entry,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_CV_FARMING_PATTERN,
    CATEGORY_GOVERNMENT_CONTEXT,
    CATEGORY_HARD_BLOCKER_PATTERN,
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
    CATEGORY_ROLE_TITLE_TOKEN,
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE,
    CATEGORY_TITLE_PARSE_BLOCKER,
    LEARNING_CATEGORY_KEY,
    LEARNING_CONFIDENCE_KEY,
    LEARNING_CONTEXT_KEY,
    LEARNING_HISTORY_KEY,
    LEARNING_EVIDENCE_KEY,
    LEARNING_KNOWLEDGE_MATCH_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_NORMALIZED_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SOURCE_KEY,
    LEARNING_NOTES_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_SUGGESTED_VALUES_KEY,
    LEARNING_STATUS_APPROVED,
    LEARNING_STATUS_IGNORED,
    LEARNING_STATUS_PENDING,
    VALID_SIGNAL_CATEGORIES,
)


CATEGORY_LABELS = {
    CATEGORY_CAPABILITY_CONCEPT: "Capability",
    CATEGORY_CV_FARMING_PATTERN: "CV farming pattern",
    CATEGORY_GOVERNMENT_CONTEXT: "Government context",
    CATEGORY_HARD_BLOCKER_PATTERN: "Hard blocker pattern",
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE: "Job type",
    CATEGORY_ROLE_TITLE_TOKEN: "Role title",
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE: "Title abbreviation",
    CATEGORY_TITLE_PARSE_BLOCKER: "Title parse blocker",
}

_CATEGORY_KNOWLEDGE_PATHS = {
    CATEGORY_CAPABILITY_CONCEPT: CAPABILITY_KNOWLEDGE_PATH,
    CATEGORY_CV_FARMING_PATTERN: CV_FARMING_RULES_PATH,
    CATEGORY_GOVERNMENT_CONTEXT: GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    CATEGORY_HARD_BLOCKER_PATTERN: HARD_BLOCKER_RULES_PATH,
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE: JOB_TYPE_STORE_PATH,
    CATEGORY_ROLE_TITLE_TOKEN: ROLE_TITLE_KNOWLEDGE_PATH,
    CATEGORY_TITLE_NORMALIZATION_CANDIDATE: TITLE_NORMALIZATION_RULES_PATH,
    CATEGORY_TITLE_PARSE_BLOCKER: PARSING_RULES_PATH,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json_dict(path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json_dict(path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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

    context = _clean_text_list(record.get(LEARNING_CONTEXT_KEY))
    if context:
        cleaned[LEARNING_CONTEXT_KEY] = context

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


def _make_pending_record(signal: str, category: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    now = _now_iso()
    cleaned_signal = _clean_text(signal)
    metadata = metadata or {}
    original_texts = _clean_text_list(metadata.get("original_texts"))
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


def _load_approved_knowledge_payload(path) -> dict[str, Any]:
    payload = _load_json_dict(path)
    payload.setdefault("kind", "managed_knowledge")
    payload.setdefault("entries", [])
    return payload


def _save_approved_knowledge_payload(path, payload: dict[str, Any]) -> None:
    payload = dict(payload or {})
    payload["kind"] = "managed_knowledge"
    payload.setdefault("entries", [])
    payload["entries"] = [
        entry
        for entry in payload["entries"]
        if isinstance(entry, dict) and _clean_text(entry.get("value"))
    ]
    _save_json_dict(path, payload)


def _entry_terms(entry: dict[str, Any]) -> list[str]:
    value = _clean_text(entry.get("value"))
    aliases = _clean_aliases(entry.get("aliases"), canonical=value)
    return [value, *aliases] if value else []


def _append_knowledge_entry(path, value: str, aliases: list[str]) -> None:
    payload = _load_approved_knowledge_payload(path)
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
            _save_approved_knowledge_payload(path, payload)
            return
    entries.append({
        "value": canonical,
        "aliases": aliases,
    })
    _save_approved_knowledge_payload(path, payload)


def _append_title_normalization_expansion(path, abbreviation: str, expansion: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("kind", "rules")
    payload.setdefault("name", "title_normalization_rules")
    payload.setdefault("version", 1)
    expansions = payload.get("abbreviation_expansions")
    if not isinstance(expansions, dict):
        expansions = {}
    expansions[abbreviation] = expansion
    payload["abbreviation_expansions"] = expansions
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_title_candidate_leading_verb_blocker(path, blocker: str) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (json.JSONDecodeError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("kind", "rules")
    payload.setdefault("name", "title_normalization_rules")
    payload.setdefault("version", 1)
    blockers = payload.get(PARSING_TITLE_CANDIDATE_LEADING_VERB_BLOCKERS_KEY)
    if not isinstance(blockers, list):
        blockers = []
    blocker_value = _clean_text(blocker)
    blocker_key = blocker_value.lower()
    if blocker_key and blocker_key not in {_clean_text(item).lower() for item in blockers}:
        blockers.append(blocker_value)
    payload[PARSING_TITLE_CANDIDATE_LEADING_VERB_BLOCKERS_KEY] = blockers
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_registry() -> dict[str, dict[str, Any]]:
    if not _REGISTRY_PATH.exists():
        return {}
    try:
        payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return _normalize_registry(payload)


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


def filter_registerable_signals(signal_names: list[str | dict[str, Any]]) -> list[str | dict[str, Any]]:
    if not signal_names:
        return []
    registry_keys = set(load_registry().keys())
    ignored_keys = set(_load_json_dict(IGNORED_SIGNAL_ARCHIVE_PATH).keys())
    approved_keys = _approved_signal_keys()
    filtered: list[str | dict[str, Any]] = []
    seen: set[str] = set()
    for item in signal_names:
        if isinstance(item, dict):
            signal = _clean_text(item.get(LEARNING_SIGNAL_KEY) or item.get("value") or item.get("name"))
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
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_PATH.write_text(
        json.dumps(_normalize_registry(registry), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def signal_in_approved_knowledge(category: str, signal: str, aliases: list[str] | None = None) -> tuple[bool, str]:
    category_key = _clean_term(category)
    if category_key not in _CATEGORY_KNOWLEDGE_PATHS and category_key != CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE:
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
            signal = _clean_text(name.get(LEARNING_SIGNAL_KEY) or name.get("value") or name.get("name"))
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
            existing.setdefault(LEARNING_HISTORY_KEY, []).append({
                "action": "categorized",
                "timestamp": _now_iso(),
                LEARNING_CATEGORY_KEY: item_category,
            })
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
    record.setdefault(LEARNING_HISTORY_KEY, []).append({
        "action": "categorized",
        "timestamp": _now_iso(),
        LEARNING_CATEGORY_KEY: category_key,
    })
    save_registry(registry)
    return record


def approve_signal(key: str, category: str = "") -> dict[str, Any] | None:
    key = _signal_key(key)
    if not key:
        return None
    registry = load_registry()
    record = registry.get(key)
    if record is None:
        return None

    category_key = _clean_term(category or record.get(LEARNING_CATEGORY_KEY) or record.get(LEARNING_SUGGESTED_CATEGORY_KEY))
    if category_key not in VALID_SIGNAL_CATEGORIES:
        raise ValueError(f"Invalid category '{category_key}'.")

    value = _clean_text(record.get(LEARNING_SIGNAL_KEY) or key)
    if category_key == CATEGORY_CAPABILITY_CONCEPT:
        upsert_capability_entry(value, [])
    elif category_key == CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE:
        suggested = _clean_text_list(record.get(LEARNING_SUGGESTED_VALUES_KEY))
        upsert_job_type_entry(value, suggested[0] if suggested else value)
    elif category_key == CATEGORY_ROLE_TITLE_TOKEN:
        upsert_role_title_entry(value)
    elif category_key == CATEGORY_HARD_BLOCKER_PATTERN:
        upsert_hard_blocker_rule(value, [])
    elif category_key == CATEGORY_CV_FARMING_PATTERN:
        upsert_cv_farming_rule(value, [])
    elif category_key == CATEGORY_TITLE_NORMALIZATION_CANDIDATE:
        suggested = _clean_text_list(record.get(LEARNING_SUGGESTED_VALUES_KEY))
        if suggested:
            _append_title_normalization_expansion(
                _CATEGORY_KNOWLEDGE_PATHS[category_key], value, suggested[0]
            )
    elif category_key == CATEGORY_TITLE_PARSE_BLOCKER:
        _append_title_candidate_leading_verb_blocker(_CATEGORY_KNOWLEDGE_PATHS[category_key], value)
    else:
        aliases = _clean_aliases(record.get("original_texts"), canonical=value)
        _append_knowledge_entry(_CATEGORY_KNOWLEDGE_PATHS[category_key], value, aliases)

    approved_record = {
        LEARNING_SIGNAL_KEY: value,
        LEARNING_NORMALIZED_KEY: key,
        LEARNING_ORIGINAL_TEXTS_KEY: record.get(LEARNING_ORIGINAL_TEXTS_KEY) or [value],
        LEARNING_CATEGORY_KEY: category_key,
    }
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
    ignored_archive = _load_json_dict(IGNORED_SIGNAL_ARCHIVE_PATH)
    record = dict(record)
    record.setdefault(LEARNING_HISTORY_KEY, []).append({
        "action": "ignored",
        "timestamp": _now_iso(),
    })
    ignored_archive[key] = record
    save_registry(registry)
    _save_json_dict(IGNORED_SIGNAL_ARCHIVE_PATH, ignored_archive)
    return record


def clear_signal_learning_state() -> None:
    save_registry({})
    _save_json_dict(IGNORED_SIGNAL_ARCHIVE_PATH, {})
    save_capability_knowledge([])
    save_job_type({})
    save_role_title_knowledge([])
    save_hard_blocker_rules([])
    for category, path in _CATEGORY_KNOWLEDGE_PATHS.items():
        if path in {CAPABILITY_KNOWLEDGE_PATH, ROLE_TITLE_KNOWLEDGE_PATH, HARD_BLOCKER_RULES_PATH}:
            continue
        if category == CATEGORY_TITLE_NORMALIZATION_CANDIDATE:
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    payload = {}
                if isinstance(payload, dict):
                    payload["abbreviation_expansions"] = {}
                    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            continue
        if category == CATEGORY_TITLE_PARSE_BLOCKER:
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    payload = {}
                if isinstance(payload, dict):
                    payload[PARSING_TITLE_CANDIDATE_LEADING_VERB_BLOCKERS_KEY] = []
                    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            continue
        _save_approved_knowledge_payload(path, {
            "kind": "managed_knowledge",
            "entries": [],
        })


def load_approved_signal_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for category, path in _CATEGORY_KNOWLEDGE_PATHS.items():
        if category == CATEGORY_TITLE_NORMALIZATION_CANDIDATE:
            try:
                payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except (json.JSONDecodeError, OSError):
                payload = {}
            expansions = payload.get("abbreviation_expansions") if isinstance(payload, dict) else {}
            if isinstance(expansions, dict):
                for abbrev, expansion in expansions.items():
                    abbrev = _clean_text(abbrev)
                    if not abbrev:
                        continue
                    terms = [abbrev]
                    expanded = _clean_text(expansion)
                    if expanded:
                        terms.append(expanded)
                    catalog.append({"category": category, "label": abbrev, "terms": terms})
            continue
        if category == CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE:
            for raw_value, canonical_value in load_job_type().items():
                cleaned_raw = _clean_text(raw_value)
                cleaned_canonical = _clean_text(canonical_value)
                if not cleaned_raw or not cleaned_canonical:
                    continue
                terms = [cleaned_raw]
                if cleaned_canonical.lower() != cleaned_raw.lower():
                    terms.append(cleaned_canonical)
                catalog.append({
                    "category": category,
                    "label": cleaned_canonical,
                    "terms": terms,
                })
            continue
        if category == CATEGORY_TITLE_PARSE_BLOCKER:
            try:
                payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            except (json.JSONDecodeError, OSError):
                payload = {}
            blockers = payload.get(PARSING_TITLE_CANDIDATE_LEADING_VERB_BLOCKERS_KEY) if isinstance(payload, dict) else []
            if isinstance(blockers, list):
                for blocker in blockers:
                    cleaned = _clean_text(blocker)
                    if cleaned:
                        catalog.append({
                            "category": category,
                            "label": cleaned,
                            "terms": [cleaned],
                        })
            continue
        if category == CATEGORY_CAPABILITY_CONCEPT:
            entries = load_capability_knowledge()
        elif category == CATEGORY_CV_FARMING_PATTERN:
            payload = _load_approved_knowledge_payload(path)
            entries = payload.get("entries", [])
        elif category == CATEGORY_ROLE_TITLE_TOKEN:
            entries = load_role_title_knowledge()
        elif category == CATEGORY_HARD_BLOCKER_PATTERN:
            entries = load_hard_blocker_rules()
        else:
            payload = _load_approved_knowledge_payload(path)
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
            catalog.append({
                "category": category,
                "label": value,
                "terms": terms,
            })
    return catalog


def get_learning_status(signal_name: str) -> str:
    key = _signal_key(signal_name)
    if not key:
        return LEARNING_STATUS_PENDING
    if key in load_registry():
        return LEARNING_STATUS_PENDING
    if key in _load_json_dict(IGNORED_SIGNAL_ARCHIVE_PATH):
        return LEARNING_STATUS_IGNORED
    return LEARNING_STATUS_APPROVED
