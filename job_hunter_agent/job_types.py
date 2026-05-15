import json
import re
from typing import Dict, List, Optional

from job_hunter_agent.paths import KNOWLEDGE_DIR

JOB_TYPE_STORE_PATH = KNOWLEDGE_DIR / "job_type.json"

_cached_mapping: Optional[Dict[str, str]] = None
_cached_filter_groups: Optional[List[dict]] = None


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_key(value: object) -> str:
    return _clean_text(value).lower().replace(" ", "")


def _load_raw() -> dict:
    if not JOB_TYPE_STORE_PATH.exists():
        return {}
    payload = json.loads(JOB_TYPE_STORE_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_job_type(force_reload: bool = False) -> dict:
    """Return the job type normalization mapping {normalized_key: canonical_label}."""
    global _cached_mapping

    if _cached_mapping is not None and not force_reload:
        return _cached_mapping

    raw = _load_raw()
    # Support both old flat format and new {mapping, filter_groups} format.
    source = raw.get("mapping", raw) if "mapping" in raw else raw
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
    _cached_filter_groups = groups if isinstance(groups, list) else []
    return _cached_filter_groups


def save_job_type(mapping: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in mapping.items():
        key = _normalize_key(raw_key)
        value = _clean_text(raw_value)
        if key and value:
            cleaned[key] = value

    existing = _load_raw()
    payload = {"mapping": cleaned, "filter_groups": existing.get("filter_groups", [])}
    JOB_TYPE_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOB_TYPE_STORE_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

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
