"""Helpers for job types."""

import logging
import re
from typing import Dict, List, Optional

from job_hunter_agent.text_processing import compact_whitespace

"""Manages job type normalization and filter groups.

This module loads, caches, and persists mappings for various job type
strings (e.g., "contract", "permanent") to canonical forms, and defines
filter groups for UI presentation."""

logger = logging.getLogger(__name__)

_cached_mapping: Optional[Dict[str, str]] = None
_cached_filter_groups: Optional[List[dict]] = None
_cached_inference_rules: Optional[List[dict]] = None


def _clean_text(value: object) -> str:
    return compact_whitespace(value)


def _normalize_key(value: object) -> str:
    return _clean_text(value).lower().replace(" ", "")


def _canonical_compare(value: object) -> str:
    return _normalize_key(value).replace("-", "").replace("_", "")


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
        logger.warning(
            "[JOB_TYPES][WARN] Job type mapping was not a dict; returning an empty mapping."
        )
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
    payload = {
        "mapping": cleaned,
        "filter_groups": existing.get("filter_groups", []),
        "work_type_inference": existing.get("work_type_inference", {}),
    }
    set_knowledge("job_type", payload)

    global _cached_mapping, _cached_filter_groups, _cached_inference_rules
    _cached_mapping = cleaned
    _cached_filter_groups = payload["filter_groups"]
    _cached_inference_rules = None
    return cleaned


def load_work_type_inference_rules(force_reload: bool = False) -> list[dict]:
    """Return the enabled work-type inference rules from the job_type knowledge entry."""
    global _cached_inference_rules

    if _cached_inference_rules is not None and not force_reload:
        return _cached_inference_rules

    raw = _load_raw()
    rules = raw.get("work_type_inference", {}).get("rules", [])
    if not isinstance(rules, list):
        _cached_inference_rules = []
        return _cached_inference_rules

    _cached_inference_rules = [r for r in rules if isinstance(r, dict) and r.get("enabled")]
    return _cached_inference_rules


def infer_work_type_from_description(
    current_work_type: str,
    description_text: str,
    _rules: list[dict] | None = None,
) -> dict | None:
    """Return an inference result dict or None when no rule applies.

    Result shape: {"inferred_type": str, "rule_id": str, "evidence": str}

    Called only after the job description has been fetched — never called pre-description.
    Rules and keywords live in data/knowledge/job_type.json; nothing is hardcoded here.

    _rules is for testing only — pass a minimal rules list to avoid the knowledge store.
    """
    if not current_work_type or not description_text:
        return None

    raw_rules = _rules if _rules is not None else load_work_type_inference_rules()
    rules = [r for r in raw_rules if isinstance(r, dict) and r.get("enabled")]
    if not rules:
        return None

    current_compare = _canonical_compare(current_work_type)
    desc_lower = description_text.lower()
    for rule in rules:
        trigger_types = [
            _canonical_compare(t) for t in (rule.get("trigger_work_types") or []) if _clean_text(t)
        ]
        if current_compare not in trigger_types:
            continue

        keywords = [
            str(k).strip().lower()
            for k in (rule.get("contract_signal_keywords") or [])
            if str(k).strip()
        ]
        matched_keyword = next((k for k in keywords if k in desc_lower), None)
        if matched_keyword:
            inferred = str(rule.get("contract_signal_infers") or "").strip()
            if inferred:
                return {
                    "inferred_type": inferred,
                    "rule_id": str(rule.get("id") or ""),
                    "evidence": matched_keyword,
                }
        else:
            inferred = str(rule.get("no_signal_infers") or "").strip()
            if inferred:
                return {
                    "inferred_type": inferred,
                    "rule_id": str(rule.get("id") or ""),
                    "evidence": "no contract keywords in description",
                }
    return None


def upsert_job_type_entry(value: str, canonical: str | None = None) -> dict[str, str]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    mapping = dict(load_job_type())
    mapping[_normalize_key(cleaned_value)] = _clean_text(canonical) or cleaned_value
    return save_job_type(mapping)
