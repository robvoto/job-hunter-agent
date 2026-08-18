"""Persistent source-discovery snapshots used before source connectors run.

This cache owns only normalized, pre-decision source evidence. Filtering,
history, title judgment, detail review, and fit decisions remain downstream.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from job_hunter_agent.global_settings import (
    get_linkedin_failure_backoff_minutes,
    get_source_discovery_cache_max_entries,
    get_source_discovery_cache_max_age_minutes,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_source_search_signature(source: str, inputs: dict[str, Any]) -> str:
    """Hash the complete normalized source-discovery input payload."""
    payload = {"source": str(source).strip().lower(), "inputs": inputs}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _cache_row(source: str, signature: str, status: str, data: list[dict]) -> tuple:
    return (
        str(source).strip().lower(),
        str(signature),
        status,
        _canonical_json(data),
        _utc_now().isoformat(timespec="seconds"),
    )


def _load_row(source: str, signature: str, status: str) -> dict[str, Any] | None:
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT data, updated_at
            FROM source_discovery_cache
            WHERE user_id = ? AND source = ? AND signature = ? AND status = ?
            """,
            (get_active_user_id(), str(source).strip().lower(), signature, status),
        ).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row["data"])
        updated_at = datetime.fromisoformat(str(row["updated_at"]).replace("Z", "+00:00"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Invalid source discovery cache row") from exc
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise RuntimeError("Source discovery cache row must contain a list of objects")
    return {"records": data, "updated_at": updated_at}


def load_source_discovery_snapshot(source: str, signature: str) -> list[dict] | None:
    """Return a fresh successful snapshot, or ``None`` when it must be fetched."""
    row = _load_row(source, signature, "success")
    if row is None:
        return None
    age = timedelta(minutes=get_source_discovery_cache_max_age_minutes())
    if _utc_now() - row["updated_at"] > age:
        return None
    return [dict(item) for item in row["records"]]


def load_source_discovery_stale_snapshot(
    source: str, signature: str, max_age_minutes: int
) -> dict[str, Any] | None:
    """Return a bounded, expired-but-known-good snapshot without refreshing it.

    Used only as a fallback when a live fetch is currently unavailable (active
    failure backoff, or a same-run live failure). This never substitutes for
    ``load_source_discovery_snapshot`` and never touches the stored row, so an
    unused stale snapshot keeps aging out normally.
    """
    row = _load_row(source, signature, "success")
    if row is None:
        return None
    if _utc_now() - row["updated_at"] > timedelta(minutes=max_age_minutes):
        return None
    return {
        "records": [dict(item) for item in row["records"]],
        "updated_at": row["updated_at"],
    }


def load_linkedin_failure_backoff(source: str, signature: str) -> bool:
    """Return whether an identical LinkedIn failure is still in its backoff window."""
    row = _load_row(source, signature, "failure")
    if row is None:
        return False
    return _utc_now() - row["updated_at"] <= timedelta(
        minutes=get_linkedin_failure_backoff_minutes()
    )


def _prune_for_user(conn, user_id: str) -> None:
    conn.execute(
        """
        DELETE FROM source_discovery_cache
        WHERE user_id = ? AND rowid IN (
            SELECT rowid FROM source_discovery_cache
            WHERE user_id = ?
            ORDER BY datetime(updated_at) DESC, rowid DESC
            LIMIT -1 OFFSET ?
        )
        """,
        (user_id, user_id, get_source_discovery_cache_max_entries()),
    )


def save_source_discovery_snapshot(source: str, signature: str, records: list[dict]) -> None:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    ensure_user_row(user_id)
    row = _cache_row(source, signature, "success", records)
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO source_discovery_cache
                (user_id, source, signature, status, data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, source, signature, status) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (user_id, *row),
        )
        _prune_for_user(conn, user_id)


def save_source_failure_state(source: str, signature: str) -> None:
    from job_hunter_agent.database import db_conn, ensure_user_row
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()
    ensure_user_row(user_id)
    row = _cache_row(source, signature, "failure", [])
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO source_discovery_cache
                (user_id, source, signature, status, data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, source, signature, status) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (user_id, *row),
        )
        _prune_for_user(conn, user_id)
