"""SQLite database connection and schema management."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


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

-- Per-user agent/scrape-loop runtime state
CREATE TABLE IF NOT EXISTS agent_state (
    user_id    TEXT PRIMARY KEY REFERENCES users(user_id),
    data       TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- One-time data migrations. Entries are retained as audit metadata so a
-- migration never becomes a permanent compatibility path.
CREATE TABLE IF NOT EXISTS schema_migrations (
    name       TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Runtime cache for occupation-title taxonomy decisions.
-- The O*NET taxonomy itself is stored as versioned JSON under data/knowledge,
-- not duplicated into SQLite.
CREATE TABLE IF NOT EXISTS occupation_title_cache (
    normalized_title          TEXT NOT NULL,
    candidate_profile_hash    TEXT NOT NULL,
    taxonomy_version          TEXT NOT NULL,
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

_REQUIREMENT_IMPORTANCE_MIGRATION = "requirement_importance_terminology_v1"
_REQUIREMENT_IMPORTANCE_RENAMES = {
    "mandatory": "required",
    "strongly_preferred": "expected",
    "nice_to_have": "bonus",
}
_JSON_DATA_TABLES = (
    "knowledge",
    "user_profile",
    "user_settings",
    "job_history",
    "review_data",
    "run_stats",
    "audit_records",
    "workspace_pool",
    "profile_documents",
    "candidate_application_history",
    "agent_state",
)


def _rename_requirement_importances(value):
    changed = False
    if isinstance(value, dict):
        renamed = {}
        for key, item in value.items():
            if key == "importance" and item in _REQUIREMENT_IMPORTANCE_RENAMES:
                item = _REQUIREMENT_IMPORTANCE_RENAMES[item]
                changed = True
            item, item_changed = _rename_requirement_importances(item)
            changed = changed or item_changed
            renamed[key] = item
        return renamed, changed
    if isinstance(value, list):
        renamed = []
        for item in value:
            item, item_changed = _rename_requirement_importances(item)
            changed = changed or item_changed
            renamed.append(item)
        return renamed, changed
    return value, False


def _apply_requirement_importance_migration(conn: sqlite3.Connection) -> None:
    """Rename stored requirement importance values once, before new readers run."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name       TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    already_applied = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?",
        (_REQUIREMENT_IMPORTANCE_MIGRATION,),
    ).fetchone()
    if already_applied:
        return

    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    for table in _JSON_DATA_TABLES:
        if table not in tables:
            continue
        for row in conn.execute(f"SELECT rowid, data FROM {table} WHERE data IS NOT NULL").fetchall():
            payload = json.loads(row[1])
            migrated_payload, changed = _rename_requirement_importances(payload)
            if changed:
                conn.execute(
                    f"UPDATE {table} SET data = ? WHERE rowid = ?",
                    (json.dumps(migrated_payload, ensure_ascii=False), row[0]),
                )
    conn.execute(
        "INSERT INTO schema_migrations (name) VALUES (?)",
        (_REQUIREMENT_IMPORTANCE_MIGRATION,),
    )


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


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """One-time schema migrations applied in order on every startup (idempotent)."""
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "application_materials" in tables and "profile_documents" not in tables:
        conn.execute("ALTER TABLE application_materials RENAME TO profile_documents")
    if "occupation_title_cache" in tables:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(occupation_title_cache)").fetchall()
        }
        if "matched_phrase" not in columns:
            conn.execute("ALTER TABLE occupation_title_cache ADD COLUMN matched_phrase TEXT")
        if "match_type" not in columns:
            conn.execute("ALTER TABLE occupation_title_cache ADD COLUMN match_type TEXT")
    _apply_requirement_importance_migration(conn)


def init_db(db_path: Path | None = None) -> None:
    """Create all tables if they do not exist. Safe to call on every startup."""
    path = db_path or _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with db_conn(path) as conn:
        _apply_migrations(conn)
        conn.executescript(_SCHEMA)
        ensure_system_warnings_schema(conn, db_path=db_path)


EXPECTED_TABLES = {
    "knowledge",
    "schema_migrations",
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
    "agent_state",
    "system_warnings",
    "occupation_title_cache",
    "source_discovery_cache",
}


def ensure_user_row(
    user_id: str,
    email: str | None = None,
    display_name: str | None = None,
    db_path: "Path | None" = None,
) -> None:
    """Upsert a user row. Updates email, display_name, and last_seen_at when provided."""
    with db_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, email, display_name, last_seen_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                email         = COALESCE(excluded.email, email),
                display_name  = COALESCE(excluded.display_name, display_name),
                last_seen_at  = excluded.last_seen_at
            """,
            (user_id, email or None, display_name or None),
        )


def get_table_names(db_path: Path | None = None) -> set[str]:
    with db_conn(db_path or _default_db_path()) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row["name"] for row in rows}
