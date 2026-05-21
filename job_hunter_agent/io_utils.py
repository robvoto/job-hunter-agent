"""Utility functions for file I/O operations, especially JSON.

This module provides helpers for loading and saving JSON data,
handling file paths, and normalizing text for consistent processing
across the job hunter agent. It centralizes common I/O patterns
to ensure data integrity and error handling.
"""
import json
import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_hunter_agent.paths import (
    DEBUG_SOURCE_PAYLOADS_DIR,
    LLM_CACHE_PATH,
    PARSING_RULES_PATH,
    SIGNAL_DEFAULTS_PATH,
    UI_LABELS_PATH,
    WORK_MODE_RULES_PATH,
    get_audit_records_path,
    get_job_history_path,
    get_review_data_path,
    get_run_stats_path,
)
from job_hunter_agent.config import AUTH_ENCODING, DEFAULT_ERRORS, DEBUG_MODE

DEBUG_CAPTURE_SOURCE_PAYLOADS = DEBUG_MODE
logger = logging.getLogger(__name__)


def normalize_posted_text(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "N/A"
    return re.sub(r"^\s*posted\s+", "", text, flags=re.IGNORECASE).strip()


def configure_console_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding=AUTH_ENCODING, errors=DEFAULT_ERRORS)


def load_json_dict(path: Path) -> Dict[str, dict]:
    if not path.exists():
        logger.warning(
            "[IO_UTILS][WARN] Missing JSON dictionary at %s; returning an empty dict because callers treat absent files as initial state.",
            path,
        )
        return {}
    try:
        data = json.loads(path.read_text(encoding=AUTH_ENCODING))
        if isinstance(data, dict):
            return data
        logger.warning(
            "[IO_UTILS][WARN] JSON dictionary at %s did not contain a dict; returning an empty dict.",
            path,
        )
    except Exception as exc:
        logger.warning("[IO_UTILS][WARN] Failed to load JSON dictionary from %s: %s", path, exc)
    return {}


def load_json_list(path: Path) -> List[dict]:
    if not path.exists():
        logger.warning(
            "[IO_UTILS][WARN] Missing JSON list at %s; returning an empty list because callers treat absent files as initial state.",
            path,
        )
        return []
    try:
        data = json.loads(path.read_text(encoding=AUTH_ENCODING))
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
            if len(items) != len(data):
                logger.warning(
                    "[IO_UTILS][WARN] JSON list at %s contained non-dict entries; skipping them.",
                    path,
                )
            return items
        logger.warning(
            "[IO_UTILS][WARN] JSON list at %s did not contain a list; returning an empty list.",
            path,
        )
    except Exception as exc:
        logger.warning("[IO_UTILS][WARN] Failed to load JSON list from %s: %s", path, exc)
    return []


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding=AUTH_ENCODING,
    )


def _slugify_debug_component(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return slug or "unknown"


def _json_safe_payload(payload):
    if isinstance(payload, dict):
        return {str(key): _json_safe_payload(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_json_safe_payload(item) for item in payload]
    if isinstance(payload, tuple):
        return [_json_safe_payload(item) for item in payload]
    if isinstance(payload, (datetime, date)):
        return payload.isoformat()
    if isinstance(payload, Path):
        return str(payload)
    try:
        json.dumps(payload)
        return payload
    except Exception:
        logger.warning(
            "[IO_UTILS][WARN] Falling back to string serialization for unsupported payload type %s.",
            type(payload).__name__,
        )
        return str(payload)


def load_llm_cache() -> Dict[str, Any]:
    raw = load_json_dict(LLM_CACHE_PATH)
    return {str(k): v for k, v in raw.items()}


def save_llm_cache(cache: Dict[str, Any]) -> None:
    save_json(LLM_CACHE_PATH, cache)


def load_parsing_rules() -> Dict[str, Any]:
    """Load centralized parsing rules from managed knowledge."""
    return load_json_dict(PARSING_RULES_PATH)


def load_ui_labels() -> Dict[str, Any]:
    """Load UI wording labels from managed knowledge."""
    return load_json_dict(UI_LABELS_PATH)


def load_work_mode_rules() -> Dict[str, Any]:
    """Load work mode parsing rules from managed knowledge."""
    return load_json_dict(WORK_MODE_RULES_PATH)


def load_signal_defaults() -> Dict[str, Any]:
    payload = load_json_dict(SIGNAL_DEFAULTS_PATH)
    defaults = payload.get("signal_defaults")
    if isinstance(defaults, dict):
        return defaults
    logger.warning(
        "[IO_UTILS][WARN] signal_defaults missing or invalid in %s; returning an empty dict.",
        SIGNAL_DEFAULTS_PATH,
    )
    return {}


def load_job_history() -> Dict[str, dict]:
    return load_json_dict(get_job_history_path())


def save_job_history(history: Dict[str, dict]) -> None:
    save_json(get_job_history_path(), history)


def write_debug_json(records: List[dict]) -> None:
    save_json(get_audit_records_path(), records)


def write_source_payload_debug(
    source: str,
    job_id: str,
    raw_html: str = "",
    raw_json=None,
    normalized_record=None,
) -> None:
    target_dir = DEBUG_SOURCE_PAYLOADS_DIR / _slugify_debug_component(source) / _slugify_debug_component(job_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "raw.html").write_text(str(raw_html or ""), encoding=AUTH_ENCODING)
    save_json(target_dir / "raw.json", _json_safe_payload(raw_json if raw_json is not None else {}))
    save_json(target_dir / "normalized.json", _json_safe_payload(normalized_record if normalized_record is not None else {}))


def write_run_stats(payload: dict) -> None:
    save_json(get_run_stats_path(), payload)


def write_run_attempt(run_started_at: datetime) -> None:
    run_stats = load_json_dict(get_run_stats_path())
    run_stats["last_run_attempt_at"] = run_started_at.isoformat(timespec="seconds")
    save_json(get_run_stats_path(), run_stats)


def write_review_data(payload: dict) -> None:
    save_json(get_review_data_path(), payload)
