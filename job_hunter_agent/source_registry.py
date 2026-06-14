"""Helpers for source registry."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

SOURCE_SEEK = "seek"

SOURCE_LINKEDIN = "linkedin"


def _normalize_source_registry(payload: dict[str, Any]) -> dict[str, Any]:

    normalized = dict(payload or {})

    domain_to_source_map = normalized.get("domain_to_source_map")

    if not isinstance(domain_to_source_map, dict):
        raise ValueError("source_registry.json must define domain_to_source_map as an object")

    cleaned_domain_map: dict[str, str] = {}

    for domain, source in domain_to_source_map.items():
        cleaned_domain = str(domain).strip().lower()

        cleaned_source = str(source).strip().lower()

        if not cleaned_domain or not cleaned_source:
            continue

        cleaned_domain_map[cleaned_domain] = cleaned_source

    if not cleaned_domain_map:
        raise ValueError("source_registry.json must define at least one domain to source mapping")

    source_display_labels = normalized.get("source_display_labels")

    if not isinstance(source_display_labels, dict):
        raise ValueError("source_registry.json must define source_display_labels as an object")

    cleaned_labels: dict[str, str] = {}

    for source, label in source_display_labels.items():
        cleaned_source = str(source).strip().lower()

        cleaned_label = str(label).strip()

        if not cleaned_source or not cleaned_label:
            continue

        cleaned_labels[cleaned_source] = cleaned_label

    if not cleaned_labels:
        raise ValueError("source_registry.json must define at least one source display label")

    normalized["domain_to_source_map"] = cleaned_domain_map

    normalized["source_display_labels"] = cleaned_labels

    return normalized


@lru_cache(maxsize=1)
def load_source_registry() -> dict[str, Any]:

    from job_hunter_agent.knowledge_store import get_knowledge

    payload = get_knowledge("source_registry")

    if not payload:
        raise RuntimeError("source_registry not found in knowledge table — seed the DB first")

    return _normalize_source_registry(payload)


def get_domain_to_source_map() -> dict[str, str]:

    return load_source_registry()["domain_to_source_map"]


def get_source_display_label(source: str) -> str:

    source_key = str(source or "").strip().lower()

    labels = load_source_registry()["source_display_labels"]

    label = labels.get(source_key)

    if label:
        return label

    return source_key.upper()
