import json
import re
from typing import Dict, Optional

from job_hunter_agent.paths import DATA_DIR

JOB_TYPE_STORE_PATH = DATA_DIR / "job_type.json"

_cached_mapping: Optional[Dict[str, str]] = None


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_key(value: object) -> str:
    return _clean_text(value).lower().replace(" ", "")


def load_job_type(force_reload: bool = False) -> dict:
    """
    Load the job type normalization mapping from persistent storage.

    The mapping is cached in memory to avoid repeated file reads.
    Set force_reload=True to refresh the cache from disk.
    """
    global _cached_mapping

    if _cached_mapping is not None and not force_reload:
        return _cached_mapping

    if JOB_TYPE_STORE_PATH.exists():
        payload = json.loads(JOB_TYPE_STORE_PATH.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            _cached_mapping = {
                _normalize_key(key): _clean_text(value)
                for key, value in payload.items()
                if _normalize_key(key) and _clean_text(value)
            }
        else:
            _cached_mapping = {}
    else:
        _cached_mapping = {}

    return _cached_mapping


def save_job_type(mapping: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for raw_key, raw_value in mapping.items():
        key = _normalize_key(raw_key)
        value = _clean_text(raw_value)
        if key and value:
            cleaned[key] = value
    JOB_TYPE_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOB_TYPE_STORE_PATH.write_text(json.dumps(cleaned, indent=2, ensure_ascii=False), encoding="utf-8")
    global _cached_mapping
    _cached_mapping = cleaned
    return cleaned


def upsert_job_type_entry(value: str, canonical: str | None = None) -> dict[str, str]:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    mapping = dict(load_job_type())
    mapping[_normalize_key(cleaned_value)] = _clean_text(canonical) or cleaned_value
    return save_job_type(mapping)
