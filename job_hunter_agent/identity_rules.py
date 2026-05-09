from __future__ import annotations

import json
from typing import Any

from job_hunter_agent.paths import IDENTITY_RULES_PATH


def _load_payload() -> dict[str, Any]:
    if not IDENTITY_RULES_PATH.exists():
        return {}
    try:
        payload = json.loads(IDENTITY_RULES_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    source_priority = normalized.get("source_priority")
    if not isinstance(source_priority, dict):
        raise ValueError("identity_rules.json must define source_priority as an object")
    cleaned_priority: dict[str, int] = {}
    for key, value in source_priority.items():
        cleaned_key = str(key).strip().lower()
        if not cleaned_key:
            continue
        cleaned_priority[cleaned_key] = int(value)
    if not cleaned_priority:
        raise ValueError("identity_rules.json must define at least one source priority")
    normalized["source_priority"] = cleaned_priority

    # Similar-title thresholds are intentionally not part of identity rules.
    # Deduplication must be based on deterministic identifiers only.
    normalized.pop("title_similarity_threshold", None)

    company_suffixes = normalized.get("company_suffixes")
    if not isinstance(company_suffixes, list):
        raise ValueError("identity_rules.json must define company_suffixes as a list")
    cleaned_suffixes = []
    seen: set[str] = set()
    for value in company_suffixes:
        suffix = str(value or "").strip()
        if not suffix:
            continue
        key = suffix.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned_suffixes.append(suffix)
    normalized["company_suffixes"] = cleaned_suffixes
    return normalized


def load_identity_rules() -> dict[str, Any]:
    payload = _load_payload()
    if not payload:
        raise ValueError("identity_rules.json must contain a rules object")
    return _normalize_config(payload)


def save_identity_rules(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_config(payload)
    normalized.setdefault("kind", "sysetm_config")
    normalized.setdefault("name", "identity_rules")
    normalized.setdefault("version", 1)
    IDENTITY_RULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    IDENTITY_RULES_PATH.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return normalized
