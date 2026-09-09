"""Manage rules for identifying duplicate job postings.



This module loads, normalizes, and persists configuration for how job records 

are deduplicated, including defining source priority for resolving conflicts 

between duplicate entries from different job boards.

"""

from __future__ import annotations

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

    query_parameters = normalized.get("non_identity_query_parameters", [])
    if not isinstance(query_parameters, list):
        raise ValueError(
            "duplicate_rules.json must define non_identity_query_parameters as an array"
        )
    cleaned_query_parameters = {
        str(parameter).strip().lower()
        for parameter in query_parameters
        if str(parameter).strip()
    }
    normalized["non_identity_query_parameters"] = sorted(cleaned_query_parameters)

    repost = normalized.get("content_repost")
    if not isinstance(repost, dict):
        raise ValueError("duplicate_rules.json must define content_repost as an object")
    required_repost_fields = (
        "min_description_chars",
        "shingle_size",
        "min_jaccard",
        "min_shorter_coverage",
    )
    missing_repost_fields = [field for field in required_repost_fields if field not in repost]
    if missing_repost_fields:
        raise ValueError(
            "duplicate_rules.json content_repost is missing required fields: "
            + ", ".join(missing_repost_fields)
        )
    normalized["content_repost"] = {
        "min_description_chars": int(repost["min_description_chars"]),
        "shingle_size": int(repost["shingle_size"]),
        "min_jaccard": float(repost["min_jaccard"]),
        "min_shorter_coverage": float(repost["min_shorter_coverage"]),
    }

    cross_source = normalized.get("cross_source_content")
    if not isinstance(cross_source, dict):
        raise ValueError("duplicate_rules.json must define cross_source_content as an object")
    required_cross_source_fields = (
        "min_description_chars",
        "shingle_size",
        "min_jaccard",
        "min_shorter_coverage",
        "max_posting_age_difference_days",
    )
    missing_cross_source_fields = [
        field for field in required_cross_source_fields if field not in cross_source
    ]
    if missing_cross_source_fields:
        raise ValueError(
            "duplicate_rules.json cross_source_content is missing required fields: "
            + ", ".join(missing_cross_source_fields)
        )
    normalized["cross_source_content"] = {
        "min_description_chars": int(cross_source["min_description_chars"]),
        "shingle_size": int(cross_source["shingle_size"]),
        "min_jaccard": float(cross_source["min_jaccard"]),
        "min_shorter_coverage": float(cross_source["min_shorter_coverage"]),
        "max_posting_age_difference_days": float(
            cross_source["max_posting_age_difference_days"]
        ),
    }

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
