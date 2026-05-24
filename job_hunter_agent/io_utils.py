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
import io
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from job_hunter_agent.paths import (
    DEBUG_SOURCE_PAYLOADS_DIR,
    LLM_CACHE_PATH,
)
from job_hunter_agent.config import AUTH_ENCODING, DEFAULT_ERRORS, DEBUG_MODE

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
    from job_hunter_agent.knowledge_store import get_knowledge
    return get_knowledge("parsing_rules") or {}


def load_ui_labels() -> Dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge
    return get_knowledge("ui_labels") or {}


def load_work_mode_rules() -> Dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge
    return get_knowledge("work_mode_rules") or {}


def load_signal_defaults() -> Dict[str, Any]:
    from job_hunter_agent.knowledge_store import get_knowledge
    payload = get_knowledge("signal_defaults") or {}
    defaults = payload.get("signal_defaults")
    if isinstance(defaults, dict):
        return defaults
    logger.warning("[IO_UTILS][WARN] signal_defaults missing or invalid in knowledge store; returning an empty dict.")
    return {}


def load_job_history() -> Dict[str, dict]:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id
    user_id = get_active_user_id()
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT job_key, data FROM job_history WHERE user_id = ? AND data IS NOT NULL",
            (user_id,),
        ).fetchall()
    return {row["job_key"]: json.loads(row["data"]) for row in rows}


def save_job_history(history: Dict[str, dict]) -> None:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.paths import get_active_user_id
    if not history:
        return
    user_id = get_active_user_id()
    ensure_user_row(user_id)
    with db_conn() as conn:
        for job_key, entry in history.items():
            if not isinstance(entry, dict):
                continue
            source, _, platform_id = str(job_key).partition(":")
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
                    entry.get("first_seen_at"),
                    entry.get("last_seen_at"),
                    json.dumps(entry, ensure_ascii=False),
                ),
            )


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
    target_dir = DEBUG_SOURCE_PAYLOADS_DIR / _slugify_debug_component(source) / _slugify_debug_component(job_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "raw.html").write_text(str(raw_html or ""), encoding=AUTH_ENCODING)
    save_json(target_dir / "raw.json", _json_safe_payload(raw_json if raw_json is not None else {}))
    save_json(target_dir / "normalized.json", _json_safe_payload(normalized_record if normalized_record is not None else {}))


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
