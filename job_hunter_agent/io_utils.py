"""Utility functions for file I/O operations, especially JSON.

This module provides helpers for loading and saving JSON data,
handling file paths, and normalizing text for consistent processing
across the job hunter agent. It centralizes common I/O patterns
to ensure data integrity and error handling.
"""

import io
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_hunter_agent.config import AUTH_ENCODING, DEBUG_MODE, DEFAULT_ERRORS
from job_hunter_agent.paths import (
    CANDIDATE_APPLICATION_HISTORY_CACHE_PATH,
    CV_EXTRACTION_CACHE_PATH,
    DEBUG_SOURCE_PAYLOADS_DIR,
    LLM_CACHE_PATH,
    RUNTIME_DIR,
    get_candidate_application_history_path,
)
from job_hunter_agent.system_warnings import make_system_warning_fingerprint, record_system_warning

DEBUG_CAPTURE_SOURCE_PAYLOADS = DEBUG_MODE
logger = logging.getLogger(__name__)

_ANSI_RESET = "\x1b[0m"
_ANSI_RED = "\x1b[31m"
_ANSI_YELLOW = "\x1b[33m"


def _color_for_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    if "[ERROR]" in stripped or stripped.startswith("ERROR") or " ERROR " in f" {stripped} ":
        return _ANSI_RED
    if "[WARN]" in stripped or stripped.startswith("WARN") or " WARNING " in f" {stripped} ":
        return _ANSI_YELLOW
    return ""


class _ColorizingStream(io.TextIOBase):
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        chunk = str(text or "")
        if not chunk:
            return 0
        self._buffer += chunk
        written = len(chunk)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._wrapped.write(self._style_line(line) + "\n")
        return written

    def flush(self) -> None:
        if self._buffer:
            self._wrapped.write(self._style_line(self._buffer))
            self._buffer = ""
        self._wrapped.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._wrapped, "isatty", lambda: False)())

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)

    def _style_line(self, line: str) -> str:
        color = _color_for_line(line)
        if not color:
            return line
        return f"{color}{line}{_ANSI_RESET}"


def normalize_posted_text(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "N/A"
    return re.sub(r"^\s*posted\s+", "", text, flags=re.IGNORECASE).strip()


def configure_console_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding=AUTH_ENCODING, errors=DEFAULT_ERRORS)
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding=AUTH_ENCODING, errors=DEFAULT_ERRORS)
    if sys.stdout.isatty() and not isinstance(sys.stdout, _ColorizingStream):
        sys.stdout = _ColorizingStream(sys.stdout)
    if sys.stderr.isatty() and not isinstance(sys.stderr, _ColorizingStream):
        sys.stderr = _ColorizingStream(sys.stderr)


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
        record_system_warning(
            severity="warning",
            category="json_parse_failure",
            source="load_json_dict",
            message=f"Failed to parse JSON dictionary at {path}: {exc}",
            fingerprint=make_system_warning_fingerprint("json_parse_failure", str(path)),
            context={"path": str(path), "error": str(exc)},
        )
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
        record_system_warning(
            severity="warning",
            category="json_parse_failure",
            source="load_json_list",
            message=f"Failed to parse JSON list at {path}: {exc}",
            fingerprint=make_system_warning_fingerprint("json_parse_failure", str(path)),
            context={"path": str(path), "error": str(exc)},
        )
    return []


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding=AUTH_ENCODING,
    )


def _parse_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_CACHE_ENTRY_VALUE_KEY = "value"
_CACHE_ENTRY_CREATED_AT_KEY = "created_at"
_CACHE_ENTRY_UPDATED_AT_KEY = "updated_at"


def _cache_timestamp_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_strict_cache_entries(raw: Dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        key_text = str(key or "").strip()
        if not key_text or not isinstance(entry, dict):
            continue
        if _CACHE_ENTRY_VALUE_KEY not in entry:
            continue
        created_at = str(entry.get(_CACHE_ENTRY_CREATED_AT_KEY) or "").strip()
        updated_at = str(entry.get(_CACHE_ENTRY_UPDATED_AT_KEY) or "").strip()
        created_dt = _parse_timestamp(created_at)
        updated_dt = _parse_timestamp(updated_at)
        if created_dt is None or updated_dt is None:
            continue
        entries[key_text] = {
            _CACHE_ENTRY_VALUE_KEY: entry[_CACHE_ENTRY_VALUE_KEY],
            _CACHE_ENTRY_CREATED_AT_KEY: created_at,
            _CACHE_ENTRY_UPDATED_AT_KEY: updated_at,
            "_created_dt": created_dt,
            "_updated_dt": updated_dt,
        }
    return entries


def _prune_strict_cache_entries(
    entries: dict[str, dict[str, Any]],
    *,
    max_entries: int,
    max_age_days: int,
    now: datetime | None = None,
) -> tuple[dict[str, dict[str, Any]], int]:
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=max_age_days)
    valid_items = [
        (key, entry)
        for key, entry in entries.items()
        if entry["_updated_dt"] >= cutoff
    ]
    valid_items.sort(key=lambda item: (item[1]["_updated_dt"], item[0]), reverse=True)
    kept_items = valid_items[: max(max_entries, 0)]
    removed = len(entries) - len(kept_items)
    return {
        key: {
            _CACHE_ENTRY_VALUE_KEY: entry[_CACHE_ENTRY_VALUE_KEY],
            _CACHE_ENTRY_CREATED_AT_KEY: entry[_CACHE_ENTRY_CREATED_AT_KEY],
            _CACHE_ENTRY_UPDATED_AT_KEY: entry[_CACHE_ENTRY_UPDATED_AT_KEY],
        }
        for key, entry in kept_items
    }, removed


def _load_timestamped_cache(
    path: Path,
    *,
    max_entries: int,
    max_age_days: int,
) -> Dict[str, Any]:
    raw = load_json_dict(path)
    strict_entries = _load_strict_cache_entries(raw)
    pruned_entries, removed = _prune_strict_cache_entries(
        strict_entries,
        max_entries=max_entries,
        max_age_days=max_age_days,
    )
    if removed > 0 or len(strict_entries) != len(raw):
        save_json(path, pruned_entries)
    return {
        key: entry[_CACHE_ENTRY_VALUE_KEY]
        for key, entry in pruned_entries.items()
    }


def _save_timestamped_cache(
    path: Path,
    cache: Dict[str, Any],
    *,
    max_entries: int,
    max_age_days: int,
) -> None:
    existing_entries = _load_strict_cache_entries(load_json_dict(path))
    now_text = _cache_timestamp_now()
    timestamped_entries: dict[str, dict[str, Any]] = {}
    for key, value in cache.items():
        key_text = str(key or "").strip()
        if not key_text:
            continue
        existing = existing_entries.get(key_text)
        created_at = (
            str(existing.get(_CACHE_ENTRY_CREATED_AT_KEY) or "").strip()
            if isinstance(existing, dict)
            else ""
        ) or now_text
        timestamped_entries[key_text] = {
            _CACHE_ENTRY_VALUE_KEY: value,
            _CACHE_ENTRY_CREATED_AT_KEY: created_at,
            _CACHE_ENTRY_UPDATED_AT_KEY: now_text,
        }
    pruned_entries, _ = _prune_strict_cache_entries(
        _load_strict_cache_entries(timestamped_entries),
        max_entries=max_entries,
        max_age_days=max_age_days,
    )
    save_json(path, pruned_entries)


def _job_history_sort_key(job_key: str, entry: dict) -> tuple[datetime, str]:
    last_seen = (
        _parse_timestamp(entry.get("last_seen_at"))
        or _parse_timestamp(entry.get("first_seen_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )
    return (last_seen, str(job_key))


def _prune_job_history_entries(
    history: Dict[str, dict],
    *,
    max_entries: int,
    max_age_days: int,
    now: datetime | None = None,
) -> tuple[Dict[str, dict], set[str]]:
    current_time = now or datetime.now(timezone.utc)
    cutoff = current_time - timedelta(days=max_age_days)
    kept_items: list[tuple[str, dict]] = []
    removed_keys: set[str] = set()

    for job_key, entry in history.items():
        if not isinstance(entry, dict):
            removed_keys.add(str(job_key))
            continue
        latest_seen = _parse_timestamp(entry.get("last_seen_at")) or _parse_timestamp(
            entry.get("first_seen_at")
        )
        if latest_seen is None:
            removed_keys.add(str(job_key))
            continue
        if latest_seen < cutoff:
            removed_keys.add(str(job_key))
            continue
        kept_items.append((str(job_key), entry))

    kept_items.sort(key=lambda item: _job_history_sort_key(item[0], item[1]), reverse=True)
    if max_entries > 0 and len(kept_items) > max_entries:
        overflow = kept_items[max_entries:]
        removed_keys.update(job_key for job_key, _ in overflow)
        kept_items = kept_items[:max_entries]
    return dict(kept_items), removed_keys


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
    from job_hunter_agent.global_settings import (
        get_llm_cache_max_age_days,
        get_llm_cache_max_entries,
    )

    return _load_timestamped_cache(
        LLM_CACHE_PATH,
        max_entries=get_llm_cache_max_entries(),
        max_age_days=get_llm_cache_max_age_days(),
    )


def save_llm_cache(cache: Dict[str, Any]) -> None:
    from job_hunter_agent.global_settings import (
        get_llm_cache_max_age_days,
        get_llm_cache_max_entries,
    )

    _save_timestamped_cache(
        LLM_CACHE_PATH,
        {str(key): value for key, value in cache.items()},
        max_entries=get_llm_cache_max_entries(),
        max_age_days=get_llm_cache_max_age_days(),
    )


def prune_llm_cache_for_current_profile(cache: Dict[str, Any]) -> tuple[Dict[str, Any], int]:
    """Keep only cache entries for the active schema and profile fingerprint."""

    from job_hunter_agent.llm_gate import LLM_CACHE_SCHEMA_VERSION, _profile_fingerprint

    fingerprint = _profile_fingerprint()
    prefix = f"v{LLM_CACHE_SCHEMA_VERSION}:{fingerprint}:"
    pruned: Dict[str, Any] = {}
    removed = 0

    for key, value in cache.items():
        key_text = str(key)
        if key_text.startswith(prefix):
            pruned[key_text] = value
        else:
            removed += 1

    return pruned, removed


def load_cv_extraction_cache() -> Dict[str, Any]:
    from job_hunter_agent.global_settings import (
        get_cv_extraction_cache_max_age_days,
        get_cv_extraction_cache_max_entries,
    )

    return _load_timestamped_cache(
        CV_EXTRACTION_CACHE_PATH,
        max_entries=get_cv_extraction_cache_max_entries(),
        max_age_days=get_cv_extraction_cache_max_age_days(),
    )


def save_cv_extraction_cache(cache: Dict[str, Any]) -> None:
    from job_hunter_agent.global_settings import (
        get_cv_extraction_cache_max_age_days,
        get_cv_extraction_cache_max_entries,
    )

    _save_timestamped_cache(
        CV_EXTRACTION_CACHE_PATH,
        {str(key): value for key, value in cache.items()},
        max_entries=get_cv_extraction_cache_max_entries(),
        max_age_days=get_cv_extraction_cache_max_age_days(),
    )


def load_candidate_application_history_cache(path: Path | None = None) -> Dict[str, Any]:
    from job_hunter_agent.global_settings import (
        get_candidate_application_history_cache_max_age_days,
        get_candidate_application_history_cache_max_entries,
    )

    cache_path = path or CANDIDATE_APPLICATION_HISTORY_CACHE_PATH
    return _load_timestamped_cache(
        cache_path,
        max_entries=get_candidate_application_history_cache_max_entries(),
        max_age_days=get_candidate_application_history_cache_max_age_days(),
    )


def save_candidate_application_history_cache(cache: Dict[str, Any], path: Path | None = None) -> None:
    from job_hunter_agent.global_settings import (
        get_candidate_application_history_cache_max_age_days,
        get_candidate_application_history_cache_max_entries,
    )

    cache_path = path or CANDIDATE_APPLICATION_HISTORY_CACHE_PATH
    _save_timestamped_cache(
        cache_path,
        {str(key): value for key, value in cache.items()},
        max_entries=get_candidate_application_history_cache_max_entries(),
        max_age_days=get_candidate_application_history_cache_max_age_days(),
    )


def load_parsing_rules() -> Dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge

    return get_knowledge("parsing_rules") or {}


def load_ui_labels() -> Dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge
    from job_hunter_agent.knowledge_store import validate_ui_labels_payload

    payload = get_knowledge("ui_labels") or {}
    validate_ui_labels_payload(payload)
    return payload


def load_work_mode_rules() -> Dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge

    return get_knowledge("work_mode_rules") or {}


def load_signal_defaults() -> Dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge

    payload = get_knowledge("signal_defaults") or {}
    defaults = payload.get("signal_defaults")
    if isinstance(defaults, dict):
        return defaults
    logger.warning(
        "[IO_UTILS][WARN] signal_defaults missing or invalid in knowledge store; returning an empty dict."
    )
    return {}


def load_job_history() -> Dict[str, dict]:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.global_settings import (
        get_job_history_max_age_days,
        get_job_history_max_entries,
    )
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT job_key, data
              FROM job_history
             WHERE user_id = ?
               AND data IS NOT NULL
            """,
            (user_id,),
        ).fetchall()
        loaded: Dict[str, dict] = {}
        for row in rows:
            job_key = str(row["job_key"] or "").strip()
            if not job_key:
                continue
            payload = json.loads(row["data"])
            if isinstance(payload, dict):
                loaded[job_key] = payload
        pruned, removed_keys = _prune_job_history_entries(
            loaded,
            max_entries=get_job_history_max_entries(),
            max_age_days=get_job_history_max_age_days(),
        )
        if removed_keys:
            conn.executemany(
                "DELETE FROM job_history WHERE user_id = ? AND job_key = ?",
                [(user_id, job_key) for job_key in sorted(removed_keys)],
            )
    return pruned


def save_job_history(history: Dict[str, dict]) -> None:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.global_settings import (
        get_job_history_max_age_days,
        get_job_history_max_entries,
    )
    from job_hunter_agent.paths import get_active_user_id

    if not history:
        return
    user_id = get_active_user_id()
    ensure_user_row(user_id)
    pruned_history, removed_keys = _prune_job_history_entries(
        history,
        max_entries=get_job_history_max_entries(),
        max_age_days=get_job_history_max_age_days(),
    )
    history.clear()
    history.update(pruned_history)
    with db_conn() as conn:
        if removed_keys:
            conn.executemany(
                "DELETE FROM job_history WHERE user_id = ? AND job_key = ?",
                [(user_id, job_key) for job_key in sorted(removed_keys)],
            )
        for job_key, entry in pruned_history.items():
            if not isinstance(entry, dict):
                continue
            source, _, platform_id = str(job_key).partition(":")
            fallback_seen_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            first_seen_at = entry.get("first_seen_at") or entry.get("last_seen_at") or fallback_seen_at
            last_seen_at = entry.get("last_seen_at") or entry.get("first_seen_at") or fallback_seen_at
            conn.execute(
                """INSERT INTO job_history (user_id, job_key, source, platform_id, title, company, state, first_seen, last_seen, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, job_key) DO UPDATE SET
                    title      = excluded.title,
                    company    = excluded.company,
                    state      = excluded.state,
                    last_seen  = excluded.last_seen,
                    data       = excluded.data""",
                (
                    user_id,
                    job_key,
                    source,
                    platform_id,
                    entry.get("title"),
                    entry.get("company"),
                    entry.get("state", "seen"),
                    first_seen_at,
                    last_seen_at,
                    json.dumps(entry, ensure_ascii=False),
                ),
            )


def prune_occupation_title_cache(db_path: Path | None = None) -> int:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.global_settings import (
        get_occupation_title_cache_max_age_days,
        get_occupation_title_cache_max_entries,
    )

    max_entries = get_occupation_title_cache_max_entries()
    max_age_days = get_occupation_title_cache_max_age_days()
    removed = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    cutoff_text = cutoff.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")

    with db_conn(db_path) as conn:
        age_result = conn.execute(
            "DELETE FROM occupation_title_cache WHERE datetime(created_at) < datetime(?)",
            (cutoff_text,),
        )
        removed += max(int(age_result.rowcount or 0), 0)
        overflow_rows = conn.execute(
            """
            SELECT normalized_title, candidate_profile_hash, taxonomy_version
              FROM occupation_title_cache
             ORDER BY datetime(created_at) DESC, normalized_title, candidate_profile_hash, taxonomy_version
             LIMIT -1 OFFSET ?
            """,
            (max_entries,),
        ).fetchall()
        if overflow_rows:
            conn.executemany(
                """
                DELETE FROM occupation_title_cache
                 WHERE normalized_title = ?
                   AND candidate_profile_hash = ?
                   AND taxonomy_version = ?
                """,
                [
                    (
                        str(row["normalized_title"]),
                        str(row["candidate_profile_hash"]),
                        str(row["taxonomy_version"]),
                    )
                    for row in overflow_rows
                ],
            )
            removed += len(overflow_rows)
    return removed


def clear_runtime_caches(db_path: Path | None = None) -> dict[str, Any]:
    from job_hunter_agent.database import db_conn

    cleared_files: list[str] = []
    for path in (
        LLM_CACHE_PATH,
        CV_EXTRACTION_CACHE_PATH,
        CANDIDATE_APPLICATION_HISTORY_CACHE_PATH,
        get_candidate_application_history_path(),
        RUNTIME_DIR / "job_hunter.db",
    ):
        try:
            path.unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("[IO_UTILS][WARN] Failed to remove runtime cache %s: %s", path, exc)
        else:
            cleared_files.append(path.name)

    with db_conn(db_path) as conn:
        conn.execute("DELETE FROM occupation_title_cache")
        conn.execute("DELETE FROM source_discovery_cache")

    return {
        "ok": True,
        "cleared_files": cleared_files,
        "message": "Runtime caches cleared.",
    }


def clear_job_history() -> None:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        conn.execute("DELETE FROM job_history WHERE user_id = ?", (user_id,))


def clear_user_settings() -> None:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        conn.execute("DELETE FROM user_settings WHERE user_id = ?", (user_id,))


def clear_workspace_pool() -> None:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        conn.execute("DELETE FROM workspace_pool WHERE user_id = ?", (user_id,))


def clear_agent_state() -> None:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        conn.execute("DELETE FROM agent_state WHERE user_id = ?", (user_id,))


def load_audit_rows() -> List[dict]:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM audit_records WHERE user_id = ? AND event = 'latest_scrape_run' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
    if row is None:
        return []
    data = json.loads(row["data"])
    return data if isinstance(data, list) else []


def write_debug_json(records: List[dict]) -> None:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM audit_records WHERE user_id = ? AND event = 'latest_scrape_run'",
            (user_id,),
        )
        conn.execute(
            "INSERT INTO audit_records (user_id, event, data) VALUES (?, 'latest_scrape_run', ?)",
            (user_id, json.dumps(records, ensure_ascii=False)),
        )


def clear_audit_rows() -> None:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM audit_records WHERE user_id = ? AND event = 'latest_scrape_run'",
            (user_id,),
        )


def write_source_payload_debug(
    source: str,
    job_id: str,
    raw_html: str = "",
    raw_json=None,
    normalized_record=None,
) -> None:
    target_dir = (
        DEBUG_SOURCE_PAYLOADS_DIR
        / _slugify_debug_component(source)
        / _slugify_debug_component(job_id)
    )
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "raw.html").write_text(str(raw_html or ""), encoding=AUTH_ENCODING)
    save_json(target_dir / "raw.json", _json_safe_payload(raw_json if raw_json is not None else {}))
    save_json(
        target_dir / "normalized.json",
        _json_safe_payload(normalized_record if normalized_record is not None else {}),
    )


def load_run_stats() -> dict:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM run_stats WHERE user_id = ? AND run_id = 'latest'",
            (user_id,),
        ).fetchone()
    if row is None:
        return {}
    data = json.loads(row["data"])
    return data if isinstance(data, dict) else {}


def write_run_stats(payload: dict) -> None:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO run_stats (user_id, run_id, data)
            VALUES (?, 'latest', ?)
            ON CONFLICT(user_id, run_id) DO UPDATE SET data = excluded.data""",
            (user_id, json.dumps(payload, ensure_ascii=False)),
        )


def write_run_attempt(run_started_at: datetime) -> None:
    run_stats = load_run_stats()
    run_stats["last_run_attempt_at"] = run_started_at.isoformat(timespec="seconds")
    write_run_stats(run_stats)


def clear_run_stats() -> None:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        conn.execute("DELETE FROM run_stats WHERE user_id = ?", (user_id,))


def load_review_data() -> dict:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM review_data WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return {}
    data = json.loads(row["data"])
    return data if isinstance(data, dict) else {}


def write_review_data(payload: dict) -> None:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO review_data (user_id, data, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at""",
            (user_id, json.dumps(payload, ensure_ascii=False)),
        )


def clear_review_data() -> None:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    with db_conn() as conn:
        conn.execute("DELETE FROM review_data WHERE user_id = ?", (user_id,))
