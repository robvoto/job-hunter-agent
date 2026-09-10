"""Per-user bearer-token storage for authorised external agents."""

from __future__ import annotations

import hashlib
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

from job_hunter_agent.activity_ledger import normalize_occurred_at, validate_agent_id
from job_hunter_agent.database import db_conn, ensure_user_row

TOKEN_PREFIX = "jh_at_"
DEFAULT_ACTIVITY_RATE_LIMIT_PER_MINUTE = 120


def activity_rate_limit_per_minute() -> int:
    raw = os.environ.get(
        "JOB_HUNTER_ACTIVITY_RATE_LIMIT_PER_MINUTE",
        str(DEFAULT_ACTIVITY_RATE_LIMIT_PER_MINUTE),
    )
    try:
        limit = int(raw)
    except ValueError as exc:
        raise ValueError("JOB_HUNTER_ACTIVITY_RATE_LIMIT_PER_MINUTE must be an integer") from exc
    if limit < 1:
        raise ValueError("JOB_HUNTER_ACTIVITY_RATE_LIMIT_PER_MINUTE must be positive")
    return limit


def _hash_token(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _normalise_expiry(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    expiry = normalize_occurred_at(value)
    if expiry <= normalize_occurred_at(None):
        raise ValueError("expires_at must be in the future")
    return expiry


def create_agent_token(
    *, user_id: str, agent_id: str, label: str = "", expires_at: str | None = None
) -> dict[str, Any]:
    user = str(user_id or "").strip()
    if not user:
        raise ValueError("user_id is required")
    normalized_agent = validate_agent_id(agent_id)
    normalized_label = str(label or "").strip()
    if len(normalized_label) > 120:
        raise ValueError("label exceeds the maximum length of 120")
    normalized_expiry = _normalise_expiry(expires_at)
    created_at = normalize_occurred_at(None)
    token_id = uuid.uuid4().hex
    token = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    ensure_user_row(user)
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO agent_tokens
                (token_id, user_id, agent_id, token_hash, label, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                token_id,
                user,
                normalized_agent,
                _hash_token(token),
                normalized_label,
                created_at,
                normalized_expiry,
            ),
        )
    return {
        "token_id": token_id,
        "agent_id": normalized_agent,
        "label": normalized_label,
        "created_at": created_at,
        "expires_at": normalized_expiry,
        "token": token,
    }


def _active_token_row(raw_token: str):
    token = str(raw_token or "").strip()
    if not token.startswith(TOKEN_PREFIX):
        return None
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT token_id, user_id, agent_id, expires_at, revoked_at
              FROM agent_tokens
             WHERE token_hash = ?
            """,
            (_hash_token(token),),
        ).fetchone()
    if row is None or row["revoked_at"]:
        return None
    if row["expires_at"]:
        try:
            expiry = normalize_occurred_at(row["expires_at"])
        except ValueError:
            return None
        if expiry <= normalize_occurred_at(None):
            return None
    return dict(row)


def list_agent_tokens(user_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT token_id, agent_id, label, created_at, expires_at, revoked_at
              FROM agent_tokens
             WHERE user_id = ?
             ORDER BY created_at DESC, token_id DESC
            """,
            (str(user_id or "").strip(),),
        ).fetchall()
    return [dict(row) for row in rows]


def revoke_agent_token(user_id: str, token_id: str) -> bool:
    with db_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE agent_tokens
               SET revoked_at = ?
             WHERE user_id = ? AND token_id = ? AND revoked_at IS NULL
            """,
            (normalize_occurred_at(None), str(user_id or "").strip(), str(token_id or "").strip()),
        )
    return cursor.rowcount == 1


def authenticate_agent_token(raw_token: str) -> dict[str, str] | None:
    row = _active_token_row(raw_token)
    if row is None:
        return None
    return {
        "user_id": str(row["user_id"]),
        "agent_id": validate_agent_id(str(row["agent_id"])),
        "token_id": str(row["token_id"]),
    }


def consume_activity_write(token_id: str) -> tuple[bool, int]:
    """Consume one token write in a UTC minute window.

    Returns ``(allowed, retry_after_seconds)``. The window is persisted in
    SQLite so the bound applies consistently when AWS runs multiple workers.
    """
    now = datetime.now(timezone.utc)
    window = now.replace(second=0, microsecond=0)
    window_text = window.isoformat(timespec="seconds")
    limit = activity_rate_limit_per_minute()
    with db_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT window_started_at, request_count FROM agent_token_rate_windows WHERE token_id = ?",
            (str(token_id or "").strip(),),
        ).fetchone()
        if row is None or str(row["window_started_at"]) != window_text:
            conn.execute(
                "INSERT INTO agent_token_rate_windows (token_id, window_started_at, request_count) VALUES (?, ?, 1) "
                "ON CONFLICT(token_id) DO UPDATE SET window_started_at = excluded.window_started_at, request_count = 1",
                (str(token_id or "").strip(), window_text),
            )
            return True, 0
        count = int(row["request_count"] or 0)
        if count >= limit:
            retry_after = 60 - now.second
            return False, retry_after
        conn.execute(
            "UPDATE agent_token_rate_windows SET request_count = request_count + 1 WHERE token_id = ?",
            (str(token_id or "").strip(),),
        )
    return True, 0
