"""SQLite database connection and schema management."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from job_hunter_agent.config import (
    USER_ACCESS_APPROVED,
    USER_ACCESS_BLOCKED,
    USER_ACCESS_PENDING,
    USER_ACCESS_STATUSES,
    USER_ACCESS_VERIFIED,
)


def _default_db_path() -> Path:
    from job_hunter_agent.paths import get_db_path

    return get_db_path()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Return an open connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(db_path or _default_db_path())
    _apply_pragmas(conn)
    return conn


@contextmanager
def db_conn(db_path: Path | None = None):
    """Context manager yielding a connection that auto-commits or rolls back."""
    conn = get_connection(db_path or _default_db_path())
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_SCHEMA = """
-- Managed knowledge files (JSON blobs keyed by filename stem)
CREATE TABLE IF NOT EXISTS knowledge (
    key         TEXT PRIMARY KEY,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Signal registry: pending / approved / ignored signals
CREATE TABLE IF NOT EXISTS signals (
    signal_id   TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    source      TEXT,
    data        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_signals_status   ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_category ON signals(category);

-- Keyed JSON settings documents.
-- Application-wide settings are stored as one document under "global_settings".
CREATE TABLE IF NOT EXISTS global_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Registered users
CREATE TABLE IF NOT EXISTS users (
    user_id      TEXT PRIMARY KEY,
    email        TEXT,
    display_name TEXT,
    access_status TEXT NOT NULL DEFAULT 'verified',
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-user candidate profile (capabilities, preferences, learning state)
CREATE TABLE IF NOT EXISTS user_profile (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-user workspace settings
CREATE TABLE IF NOT EXISTS user_settings (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-user job history: dedup, state tracking
CREATE TABLE IF NOT EXISTS job_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT    NOT NULL REFERENCES users(user_id),
    job_key      TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    platform_id  TEXT    NOT NULL,
    title        TEXT,
    company      TEXT,
    state        TEXT    NOT NULL DEFAULT 'seen',
    first_seen   TEXT    NOT NULL DEFAULT (datetime('now')),
    last_seen    TEXT    NOT NULL DEFAULT (datetime('now')),
    data         TEXT,
    UNIQUE (user_id, job_key)
);
CREATE INDEX IF NOT EXISTS idx_job_history_user    ON job_history(user_id);
CREATE INDEX IF NOT EXISTS idx_job_history_job_key ON job_history(user_id, job_key);

-- Per-user review data (pending review decisions)
CREATE TABLE IF NOT EXISTS review_data (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-user scrape run statistics
CREATE TABLE IF NOT EXISTS run_stats (
    run_id     TEXT NOT NULL,
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_run_stats_user ON run_stats(user_id);

-- Per-user audit log
CREATE TABLE IF NOT EXISTS audit_records (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT    NOT NULL REFERENCES users(user_id),
    event      TEXT    NOT NULL,
    data       TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_records(user_id);

-- Per-user workspace job pool (scored shortlist)
CREATE TABLE IF NOT EXISTS workspace_pool (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-user CV and profile documents (content stored directly, not as filesystem paths)
CREATE TABLE IF NOT EXISTS profile_documents (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Application history (cross-user, keyed by user + job)
CREATE TABLE IF NOT EXISTS candidate_application_history (
    user_id    TEXT NOT NULL REFERENCES users(user_id),
    job_key    TEXT NOT NULL,
    data       TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, job_key)
);
CREATE INDEX IF NOT EXISTS idx_app_history_user ON candidate_application_history(user_id);

-- Pre-JH-305 application events. This table is retained as inert legacy
-- evidence only; the runtime never reads or writes it. Unkeyed historical rows
-- are not migrated into the canonical activity ledger.
CREATE TABLE IF NOT EXISTS candidate_application_events (
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    event_id     TEXT NOT NULL,
    employer_key TEXT NOT NULL,
    employer_raw TEXT NOT NULL,
    role_title   TEXT NOT NULL DEFAULT '',
    event_type   TEXT NOT NULL,
    event_date   TEXT NOT NULL,
    source       TEXT NOT NULL,
    evidence_ref TEXT NOT NULL,
    confidence   TEXT NOT NULL,
    data         TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, event_id)
);
CREATE INDEX IF NOT EXISTS idx_app_events_user_employer
    ON candidate_application_events(user_id, employer_key);
CREATE INDEX IF NOT EXISTS idx_app_events_user_date
    ON candidate_application_events(user_id, event_date DESC);

-- Bounded, non-canonical historical evidence that cannot be safely attached
-- to one exact job. This table deliberately has no job_key or JMM identity.
CREATE TABLE IF NOT EXISTS historical_application_evidence (
    user_id       TEXT NOT NULL REFERENCES users(user_id),
    evidence_id   TEXT NOT NULL,
    outcome       TEXT NOT NULL,
    event_date    TEXT NOT NULL,
    employer_raw  TEXT NOT NULL,
    role_title    TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL,
    evidence_ref  TEXT NOT NULL,
    actor_id      TEXT NOT NULL DEFAULT '',
    thread_id     TEXT NOT NULL DEFAULT '',
    message_id    TEXT NOT NULL DEFAULT '',
    source_url    TEXT NOT NULL DEFAULT '',
    source_job_id TEXT NOT NULL DEFAULT '',
    requisition_id TEXT NOT NULL DEFAULT '',
    origin_store  TEXT NOT NULL,
    origin_ref    TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_historical_application_evidence_user
    ON historical_application_evidence(user_id, event_date DESC);

-- Body-free quarantine/audit records for excluded junk, malformed rows and
-- duplicate evidence. Quarantine is never read as application history.
CREATE TABLE IF NOT EXISTS historical_application_quarantine (
    user_id       TEXT NOT NULL REFERENCES users(user_id),
    evidence_id   TEXT NOT NULL,
    reason        TEXT NOT NULL,
    outcome       TEXT NOT NULL DEFAULT '',
    event_date    TEXT NOT NULL DEFAULT '',
    employer_raw  TEXT NOT NULL DEFAULT '',
    role_title    TEXT NOT NULL DEFAULT '',
    source        TEXT NOT NULL DEFAULT '',
    evidence_ref  TEXT NOT NULL DEFAULT '',
    origin_store  TEXT NOT NULL,
    origin_ref    TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, evidence_id)
);
CREATE INDEX IF NOT EXISTS idx_historical_application_quarantine_user
    ON historical_application_quarantine(user_id, created_at DESC);

-- Canonical per-user activity ledger. Every personal event has the current
-- source:id job identity, managed agent identity, event time and an explicit
-- idempotency key. Reversals are new rows; projections are disposable views.
CREATE TABLE IF NOT EXISTS job_activity_events (
    user_id        TEXT NOT NULL REFERENCES users(user_id),
    event_id       TEXT NOT NULL,
    job_key        TEXT NOT NULL,
    activity_type  TEXT NOT NULL,
    agent_id       TEXT NOT NULL,
    occurred_at    TEXT NOT NULL,
    source         TEXT NOT NULL,
    evidence_ref   TEXT NOT NULL DEFAULT '',
    idempotency_key TEXT NOT NULL,
    metadata       TEXT NOT NULL DEFAULT '{}',
    employer_key   TEXT NOT NULL DEFAULT '',
    employer_raw   TEXT NOT NULL DEFAULT '',
    role_title     TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, event_id),
    UNIQUE (user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_job_activity_user_job_time
    ON job_activity_events(user_id, job_key, occurred_at, event_id);
CREATE INDEX IF NOT EXISTS idx_job_activity_user_agent_job
    ON job_activity_events(user_id, agent_id, job_key, occurred_at);
CREATE INDEX IF NOT EXISTS idx_job_activity_user_employer_time
    ON job_activity_events(user_id, employer_key, occurred_at);

-- Per-user managed bearer tokens for external agents. Only token hashes are
-- stored; plaintext is returned once at creation and cannot be recovered.
CREATE TABLE IF NOT EXISTS agent_tokens (
    token_id    TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    agent_id    TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,
    label       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    expires_at  TEXT,
    revoked_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_agent_tokens_user
    ON agent_tokens(user_id, created_at DESC);

-- Durable per-token write window so external agents cannot create an unbounded
-- stream of activity events across multiple AWS worker processes.
CREATE TABLE IF NOT EXISTS agent_token_rate_windows (
    token_id          TEXT PRIMARY KEY REFERENCES agent_tokens(token_id),
    window_started_at TEXT NOT NULL,
    request_count     INTEGER NOT NULL DEFAULT 0
);

-- Derived per-employer rollup of the canonical job_activity_events ledger. This is a cache:
-- it is safe to drop and rebuild from the events table at any time, and it is
-- never hand-edited. It stores counts and dates only, no thresholds or labels,
-- so display rules can change without a rebuild. Owner: employer_outcome_store.py.
CREATE TABLE IF NOT EXISTS candidate_employer_outcomes (
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    employer_key TEXT NOT NULL,
    data         TEXT NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, employer_key)
);

-- Per-user agent/scrape-loop runtime state
CREATE TABLE IF NOT EXISTS agent_state (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);


-- Runtime cache for occupation-title taxonomy decisions.
-- The O*NET taxonomy itself is stored as versioned JSON under data/knowledge,
-- not duplicated into SQLite.
CREATE TABLE IF NOT EXISTS occupation_title_cache (
    normalized_title          TEXT NOT NULL,
    candidate_profile_hash    TEXT NOT NULL,
    taxonomy_version          TEXT NOT NULL,
    database_release          TEXT NOT NULL DEFAULT '',
    dataset_fingerprint       TEXT NOT NULL DEFAULT '',
    result                    TEXT NOT NULL CHECK (result IN ('near', 'far', 'uncertain')),
    matched_occupation_code   TEXT,
    confidence                REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    matched_phrase            TEXT,
    match_type                TEXT,
    created_at                TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (normalized_title, candidate_profile_hash, taxonomy_version)
);
CREATE INDEX IF NOT EXISTS idx_occupation_title_cache_lookup
    ON occupation_title_cache(normalized_title, candidate_profile_hash, taxonomy_version);
CREATE INDEX IF NOT EXISTS idx_occupation_title_cache_result
    ON occupation_title_cache(result);

-- Per-user source discovery evidence. Success and failure rows are separate so
-- a transient failure cannot overwrite the last known-good snapshot.
CREATE TABLE IF NOT EXISTS source_discovery_cache (
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    source      TEXT NOT NULL,
    signature   TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('success', 'failure')),
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, source, signature, status)
);
CREATE INDEX IF NOT EXISTS idx_source_discovery_cache_lookup
    ON source_discovery_cache(user_id, source, signature, status, updated_at);

-- Per-user, per-location remembered SEEK search-plan probe/selection history.
CREATE TABLE IF NOT EXISTS search_plan_state (
    user_id     TEXT NOT NULL REFERENCES users(user_id),
    source      TEXT NOT NULL,
    signature   TEXT NOT NULL,
    location    TEXT NOT NULL,
    data        TEXT NOT NULL,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, source, signature, location)
);
CREATE INDEX IF NOT EXISTS idx_search_plan_state_lookup
    ON search_plan_state(user_id, source, signature, location, updated_at);

-- Per-user incremental source-discovery checkpoints. The exact role target is
-- stored separately from location so no semantic role mapping is inferred.
CREATE TABLE IF NOT EXISTS incremental_search_state (
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    source       TEXT NOT NULL,
    signature    TEXT NOT NULL,
    location     TEXT NOT NULL,
    role_target  TEXT NOT NULL,
    data         TEXT NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, source, signature, location, role_target)
);
CREATE INDEX IF NOT EXISTS idx_incremental_search_state_lookup
    ON incremental_search_state(user_id, source, signature, updated_at);
"""

_SYSTEM_WARNINGS_SCHEMA = """
-- Central runtime warnings store for admin review.
CREATE TABLE IF NOT EXISTS system_warnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    severity      TEXT NOT NULL,
    category      TEXT NOT NULL,
    source        TEXT NOT NULL,
    message       TEXT NOT NULL,
    fingerprint   TEXT NOT NULL UNIQUE,
    status        TEXT NOT NULL DEFAULT 'unresolved' CHECK (status IN ('unresolved', 'reviewed', 'dismissed')),
    job_key       TEXT,
    run_id        TEXT,
    context_json  TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at  TEXT NOT NULL DEFAULT (datetime('now')),
    count         INTEGER NOT NULL DEFAULT 1 CHECK (count >= 1)
);
CREATE INDEX IF NOT EXISTS idx_system_warnings_status
    ON system_warnings(status, last_seen_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_system_warnings_category
    ON system_warnings(category);
"""

_system_warnings_schema_ensured_paths: set[str] = set()


def ensure_system_warnings_schema(
    conn: sqlite3.Connection, *, db_path: Path | None = None, force: bool = False
) -> None:
    """Create the system warnings table/indexes if they do not already exist.

    record_system_warning() calls this on every warning, and init_db() already
    creates this schema once at startup, so re-running the (idempotent)
    executescript per warning is pure waste -- measured via profiling a
    247-record cached SEEK repeat search as ~5s across just 20 warnings.
    Memoized per resolved db path (not a single process-wide flag) because
    tests repoint JOB_HUNTER_DB_PATH at different isolated databases within
    the same process while still calling with db_path=None. Pass force=True
    to bypass the memo, e.g. after the table unexpectedly went missing.
    """

    resolved_path = str(db_path) if db_path is not None else str(_default_db_path())
    if not force and resolved_path in _system_warnings_schema_ensured_paths:
        return
    conn.executescript(_SYSTEM_WARNINGS_SCHEMA)
    _system_warnings_schema_ensured_paths.add(resolved_path)


def _apply_runtime_admin_access(conn: sqlite3.Connection) -> None:
    """Keep the configured admin account approved in the canonical schema."""
    admin_email = os.getenv("JOB_HUNTER_ADMIN_EMAIL", "").strip().lower()
    if admin_email:
        conn.execute(
            "UPDATE users SET access_status = ? WHERE lower(email) = ?",
            (USER_ACCESS_APPROVED, admin_email),
        )


def init_db(db_path: Path | None = None) -> None:
    """Create all tables if they do not exist. Safe to call on every startup."""
    path = db_path or _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with db_conn(path) as conn:
        conn.executescript(_SCHEMA)
        ensure_system_warnings_schema(conn, db_path=db_path)
        _apply_runtime_admin_access(conn)


EXPECTED_TABLES = {
    "knowledge",
    "signals",
    "global_settings",
    "users",
    "user_profile",
    "user_settings",
    "job_history",
    "review_data",
    "run_stats",
    "audit_records",
    "workspace_pool",
    "profile_documents",
    "candidate_application_history",
    "candidate_application_events",
    "historical_application_evidence",
    "historical_application_quarantine",
    "job_activity_events",
    "agent_tokens",
    "agent_token_rate_windows",
    "candidate_employer_outcomes",
    "agent_state",
    "system_warnings",
    "occupation_title_cache",
    "source_discovery_cache",
    "search_plan_state",
    "incremental_search_state",
}


def ensure_user_row(
    user_id: str,
    email: str | None = None,
    display_name: str | None = None,
    access_status: str | None = None,
    db_path: "Path | None" = None,
) -> None:
    """Upsert a user row. Updates email, display_name, and last_seen_at when provided."""
    with db_conn(db_path) as conn:
        if access_status is None:
            conn.execute(
                """
                INSERT INTO users (user_id, email, display_name, access_status, last_seen_at)
                VALUES (?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id) DO UPDATE SET
                    email         = COALESCE(excluded.email, email),
                    display_name  = COALESCE(excluded.display_name, display_name),
                    last_seen_at  = excluded.last_seen_at
                """,
                (user_id, email or None, display_name or None, USER_ACCESS_VERIFIED),
            )
            return
        if access_status not in USER_ACCESS_STATUSES:
            raise ValueError(f"Unsupported user access status: {access_status}")
        conn.execute(
            """
            INSERT INTO users (user_id, email, display_name, access_status, last_seen_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                email         = COALESCE(excluded.email, email),
                display_name  = COALESCE(excluded.display_name, display_name),
                access_status = excluded.access_status,
                last_seen_at  = excluded.last_seen_at
            """,
            (user_id, email or None, display_name or None, access_status),
        )


def get_user_access_status(user_id: str, db_path: "Path | None" = None) -> str | None:
    """Read the persisted access status for one authenticated user."""
    with db_conn(db_path) as conn:
        row = conn.execute(
            "SELECT access_status FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    status = str(row["access_status"] or "").strip().lower()
    if status not in USER_ACCESS_STATUSES:
        raise RuntimeError(f"Invalid persisted user access status for {user_id}")
    return status


def list_users_with_access(db_path: "Path | None" = None) -> list[dict]:
    """Return the user directory needed by Global Admin access management."""
    with db_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT user_id, email, display_name, access_status, created_at, last_seen_at
            FROM users
            ORDER BY
                CASE access_status
                    WHEN ? THEN 0
                    WHEN ? THEN 1
                    WHEN ? THEN 2
                    ELSE 3
                END,
                created_at ASC,
                user_id ASC
            """,
            (USER_ACCESS_PENDING, USER_ACCESS_APPROVED, USER_ACCESS_BLOCKED),
        ).fetchall()
    return [dict(row) for row in rows]


def update_user_access_status(
    user_id: str,
    status: str,
    admin_email: str | None,
    db_path: "Path | None" = None,
) -> dict:
    """Update one user's access status while protecting the configured admin."""
    if status not in {USER_ACCESS_PENDING, USER_ACCESS_APPROVED, USER_ACCESS_BLOCKED}:
        raise ValueError(f"Unsupported user access status: {status}")
    with db_conn(db_path) as conn:
        row = conn.execute(
            "SELECT user_id, email FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise LookupError("User not found")
        target_email = str(row["email"] or "").strip().lower()
        configured_admin = str(admin_email or "").strip().lower()
        if configured_admin and target_email == configured_admin:
            raise ValueError("The configured administrator access cannot be changed")
        conn.execute(
            "UPDATE users SET access_status = ?, last_seen_at = last_seen_at WHERE user_id = ?",
            (status, user_id),
        )
        updated = conn.execute(
            """
            SELECT user_id, email, display_name, access_status, created_at, last_seen_at
            FROM users WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    return dict(updated)


def request_user_access(user_id: str, db_path: "Path | None" = None) -> dict:
    """Move a verified candidate into the real approval queue."""
    with db_conn(db_path) as conn:
        row = conn.execute(
            "SELECT user_id, email, display_name, access_status FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise LookupError("User not found")
        status = str(row["access_status"] or "").strip().lower()
        if status == USER_ACCESS_VERIFIED:
            conn.execute(
                "UPDATE users SET access_status = ? WHERE user_id = ?",
                (USER_ACCESS_PENDING, user_id),
            )
        elif status != USER_ACCESS_PENDING:
            raise ValueError("Only verified users can request access")
        updated = conn.execute(
            """
            SELECT user_id, email, display_name, access_status, created_at, last_seen_at
            FROM users WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
    return dict(updated)


def get_table_names(db_path: Path | None = None) -> set[str]:
    with db_conn(db_path or _default_db_path()) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row["name"] for row in rows}
