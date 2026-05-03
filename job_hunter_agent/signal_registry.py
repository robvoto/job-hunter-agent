"""Signal inbox and approved knowledge store helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from job_hunter_agent.paths import (
    GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    HARD_BLOCKER_KNOWLEDGE_PATH,
    IGNORED_SIGNAL_ARCHIVE_PATH,
    ROLE_TITLE_KNOWLEDGE_PATH,
    SIGNAL_REGISTRY_PATH as _REGISTRY_PATH,
)
from job_hunter_agent.hard_blocker_knowledge import (
    load_hard_blocker_knowledge,
    save_hard_blocker_knowledge,
    upsert_hard_blocker_entry,
)
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


VALID_SIGNAL_CATEGORIES = frozenset({
    "capability_concept",
    "government_context",
    "hard_blocker_concept",
    "role_title_token",
})

CATEGORY_LABELS = {
    "capability_concept": "Capability",
    "government_context": "Government context",
    "hard_blocker_concept": "Hard blocker",
    "role_title_token": "Role title",
}

_CATEGORY_KNOWLEDGE_PATHS = {
    "capability_concept": CAPABILITY_KNOWLEDGE_PATH,
    "government_context": GOVERNMENT_CONTEXT_KNOWLEDGE_PATH,
    "hard_blocker_concept": HARD_BLOCKER_KNOWLEDGE_PATH,
    "role_title_token": ROLE_TITLE_KNOWLEDGE_PATH,
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
    source = _clean_text(record.get("source"))
    if source:
        cleaned["source"] = source

    context = _clean_text_list(record.get("context"))
    if context:
        cleaned["context"] = context

    evidence = _clean_text_list(record.get("evidence"))
    if evidence:
        cleaned["evidence"] = evidence

    confidence = _clean_term(record.get("confidence"))
    if confidence:
        cleaned["confidence"] = confidence

    notes = _clean_text(record.get("notes"))
    if notes:
        cleaned["notes"] = notes

    if record.get("needs_review") is not None:
        cleaned["needs_review"] = bool(record.get("needs_review"))

    knowledge_match = _clean_text(record.get("knowledge_match"))
    if knowledge_match:
        cleaned["knowledge_match"] = knowledge_match

    suggested_category = _clean_term(record.get("suggested_category"))
    if suggested_category:
        cleaned["suggested_category"] = suggested_category

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
        category = _clean_term(entry.get("category"))
        if not action or not timestamp:
            continue
        item: dict[str, Any] = {"action": action, "timestamp": timestamp}
        if category:
            item["category"] = category
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
        "signal": cleaned_signal,
        "normalized_key": _signal_key(cleaned_signal),
        "original_texts": original_texts or [cleaned_signal],
        "category": _clean_term(category),
        "history": [
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
    if status in {"approved", "ignored", "use", "ignore"}:
        return None

    signal = _clean_text(record.get("signal") or key)
    if not signal:
        return None

    original_texts: list[str] = []
    seen: set[str] = set()
    for value in [signal, *(record.get("original_texts") or [])]:
        cleaned = _clean_text(value)
        cleaned_key = cleaned.lower()
        if not cleaned or cleaned_key in seen:
            continue
        seen.add(cleaned_key)
        original_texts.append(cleaned)

    category = _clean_term(record.get("category"))
    suggested_category = _clean_term(record.get("suggested_category"))
    context = _clean_context_payload(record)

    history = _clean_history(record.get("history"))
    if not history:
        history = [
            {
                "action": "added",
                "timestamp": _now_iso(),
            }
        ]

    return {
        "signal": signal,
        "normalized_key": _signal_key(key or signal),
        "original_texts": original_texts,
        "category": category,
        "suggested_category": suggested_category,
        "history": history,
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


def load_registry() -> dict[str, dict[str, Any]]:
    if not _REGISTRY_PATH.exists():
        return {}
    try:
        payload = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return _normalize_registry(payload)


def save_registry(registry: dict[str, dict[str, Any]]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _REGISTRY_PATH.write_text(
        json.dumps(_normalize_registry(registry), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def signal_in_approved_knowledge(category: str, signal: str, aliases: list[str] | None = None) -> tuple[bool, str]:
    category_key = _clean_term(category)
    if category_key not in _CATEGORY_KNOWLEDGE_PATHS:
        return False, ""

    query_terms = _clean_text_list([signal, *(aliases or [])])
    if not query_terms:
        return False, ""

    for item in load_approved_signal_catalog():
        if item.get("category") != category_key:
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
    registry = load_registry()
    changed = False
    category_key = _clean_term(category)
    for name in signal_names:
        metadata: dict[str, Any] = {}
        if isinstance(name, dict):
            signal = _clean_text(name.get("signal") or name.get("value") or name.get("name"))
            metadata = {
                key: value
                for key, value in name.items()
                if key not in {"signal", "value", "name", "category"}
            }
            item_category = _clean_term(name.get("category") or category_key)
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
        original_texts = existing.setdefault("original_texts", [])
        incoming_originals = _clean_text_list(metadata.get("original_texts"))
        for value in _clean_text_list([signal, *incoming_originals]):
            if value not in original_texts:
                original_texts.append(value)
                changed = True
        suggested_category = _clean_term(metadata.get("suggested_category"))
        if suggested_category and not _clean_term(existing.get("suggested_category")):
            existing["suggested_category"] = suggested_category
            changed = True
        if item_category and not _clean_term(existing.get("category")):
            existing["category"] = item_category
            existing.setdefault("history", []).append({
                "action": "categorized",
                "timestamp": _now_iso(),
                "category": item_category,
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
    current = _clean_term(record.get("category"))
    if current == category_key:
        return record
    record["category"] = category_key
    record.setdefault("history", []).append({
        "action": "categorized",
        "timestamp": _now_iso(),
        "category": category_key,
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

    category_key = _clean_term(category or record.get("category") or record.get("suggested_category"))
    if category_key not in VALID_SIGNAL_CATEGORIES:
        raise ValueError(f"Invalid category '{category_key}'.")

    value = _clean_text(record.get("signal") or key)
    if category_key == "capability_concept":
        upsert_capability_entry(value, [])
    elif category_key == "role_title_token":
        upsert_role_title_entry(value)
    elif category_key == "hard_blocker_concept":
        aliases = _clean_aliases(record.get("original_texts"), canonical=value)
        upsert_hard_blocker_entry(value, aliases)
    else:
        aliases = _clean_aliases(record.get("original_texts"), canonical=value)
        _append_knowledge_entry(_CATEGORY_KNOWLEDGE_PATHS[category_key], value, aliases)

    approved_record = {
        "signal": value,
        "normalized_key": key,
        "original_texts": record.get("original_texts") or [value],
        "category": category_key,
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
    record.setdefault("history", []).append({
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
    save_role_title_knowledge([])
    save_hard_blocker_knowledge([])
    for path in _CATEGORY_KNOWLEDGE_PATHS.values():
        if path in {CAPABILITY_KNOWLEDGE_PATH, ROLE_TITLE_KNOWLEDGE_PATH, HARD_BLOCKER_KNOWLEDGE_PATH}:
            continue
        _save_approved_knowledge_payload(path, {
            "kind": "managed_knowledge",
            "entries": [],
        })


def load_approved_signal_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for category, path in _CATEGORY_KNOWLEDGE_PATHS.items():
        if category == "capability_concept":
            entries = load_capability_knowledge()
        elif category == "role_title_token":
            entries = load_role_title_knowledge()
        elif category == "hard_blocker_concept":
            entries = load_hard_blocker_knowledge()
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
        return "pending"
    if key in load_registry():
        return "pending"
    if key in _load_json_dict(IGNORED_SIGNAL_ARCHIVE_PATH):
        return "ignored"
    return "approved"
