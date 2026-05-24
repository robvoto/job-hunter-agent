import logging
import re
from typing import Dict, List, Optional

"""Manages job type normalization and filter groups.

This module loads, caches, and persists mappings for various job type
strings (e.g., "contract", "permanent") to canonical forms, and defines
filter groups for UI presentation."""

logger = logging.getLogger(__name__)

_cached_mapping: Optional[Dict[str, str]] = None
_cached_filter_groups: Optional[List[dict]] = None


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_key(value: object) -> str:
    return _clean_text(value).lower().replace(" ", "")


def _load_raw() -> dict:
    from job_hunter_agent.knowledge_store import get_knowledge
    payload = get_knowledge("job_type")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        logger.warning("[JOB_TYPES][WARN] job_type knowledge was not a dict; returning empty.")
        return {}
    return payload


def load_job_type(force_reload: bool = False) -> dict:
    """Return the job type normalization mapping {normalized_key: canonical_label}."""
    global _cached_mapping

    if _cached_mapping is not None and not force_reload:
        return _cached_mapping

    raw = _load_raw()
    source = raw.get("mapping", raw) if "mapping" in raw else raw
    if not isinstance(source, dict):
        logger.warning("[JOB_TYPES][WARN] Job type mapping was not a dict; returning an empty mapping.")
        _cached_mapping = {}
        return _cached_mapping
    _cached_mapping = {
        _normalize_key(key): _clean_text(value)
        for key, value in source.items()
        if isinstance(value, str) and _normalize_key(key) and _clean_text(value)
    }
    return _cached_mapping


def load_job_type_filter_groups(force_reload: bool = False) -> List[dict]:
    """Return the filter group definitions [{label, values}, ...]."""
    global _cached_filter_groups

    if _cached_filter_groups is not None and not force_reload:
        return _cached_filter_groups

    raw = _load_raw()
    groups = raw.get("filter_groups", [])
    if isinstance(groups, list):
        _cached_filter_groups = groups
    else:
        logger.warning("[JOB_TYPES][WARN] Filter groups were not a list; returning an empty list.")
        _cached_filter_groups = []
    return _cached_filter_groups


def save_job_type(mapping: dict[str, str]) -> dict[str, str]:
    from job_hunter_agent.knowledge_store import set_knowledge
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in mapping.items():
        key = _normalize_key(raw_key)
        value = _clean_text(raw_value)
        if key and value:
            cleaned[key] = value

    existing = _load_raw()
    payload = {"mapping": cleaned, "filter_groups": existing.get("filter_groups", [])}
    set_knowledge("job_type", payload)

    global _cached_mapping, _cached_filter_groups
    _cached_mapping = cleaned
    _cached_filter_groups = payload["filter_groups"]
    return cleaned


def upsert_job_type_entry(value: str, canonical: str | None = None) -> dict[str, str]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    mapping = dict(load_job_type())
    mapping[_normalize_key(cleaned_value)] = _clean_text(canonical) or cleaned_value
    return save_job_type(mapping)
