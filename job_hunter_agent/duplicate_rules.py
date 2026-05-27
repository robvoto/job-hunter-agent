"""Helpers for duplicate rules."""



from __future__ import annotations



"""Manages rules for identifying duplicate job postings.



This module loads, normalizes, and persists configuration for how job records 

are deduplicated, including defining source priority for resolving conflicts 

between duplicate entries from different job boards.

"""

from typing import Any





def _load_payload() -> dict[str, Any]:

    from job_hunter_agent.knowledge_store import get_knowledge

    return get_knowledge("duplicate_rules") or {}





def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:

    normalized = dict(payload or {})

    source_priority = normalized.get("source_priority")

    if not isinstance(source_priority, dict):

        raise ValueError("duplicate_rules.json must define source_priority as an object")

    cleaned_priority: dict[str, int] = {}

    for key, value in source_priority.items():

        cleaned_key = str(key).strip().lower()

        if not cleaned_key:

            continue

        cleaned_priority[cleaned_key] = int(value)

    if not cleaned_priority:

        raise ValueError("duplicate_rules.json must define at least one source priority")

    normalized["source_priority"] = cleaned_priority

    return normalized





def load_duplicate_rules() -> dict[str, Any]:

    payload = _load_payload()

    if not payload:

        raise ValueError("duplicate_rules.json must contain a rules object")

    return _normalize_config(payload)





def save_duplicate_rules(payload: dict[str, Any]) -> dict[str, Any]:

    normalized = _normalize_config(payload)

    normalized.setdefault("kind", "system_config")

    normalized.setdefault("name", "duplicate_rules")

    normalized.setdefault("version", 1)

    from job_hunter_agent.knowledge_store import set_knowledge

    set_knowledge("duplicate_rules", normalized)

    return normalized

