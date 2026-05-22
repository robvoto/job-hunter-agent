"""SQLite database connection and schema management."""

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

-- Global (admin) settings: one row per setting key
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

-- Per-user onboarding source materials (CV, cover letters, etc.)
CREATE TABLE IF NOT EXISTS application_materials (
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
"""


def init_db(db_path: Path | None = None) -> None:
    """Create all tables if they do not exist. Safe to call on every startup."""
    path = db_path or _default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with db_conn(path) as conn:
        conn.executescript(_SCHEMA)


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
    "application_materials",
    "candidate_application_history",
    "agent_state",
}


def ensure_user_row(user_id: str, db_path: "Path | None" = None) -> None:
    """Upsert a user row so FK constraints on per-user tables are satisfied."""
    with db_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO users (user_id) VALUES (?) ON CONFLICT(user_id) DO NOTHING",
            (user_id,),
        )


def get_table_names(db_path: Path | None = None) -> set[str]:
    with db_conn(db_path or _default_db_path()) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    return {row["name"] for row in rows}
