"""Tests for DB foundation: init, schema, connection behaviour."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from job_hunter_agent.database import (
    EXPECTED_TABLES,
    db_conn,
    ensure_user_row,
    get_connection,
    get_table_names,
    init_db,
)


@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    return db


def test_init_creates_db_file(tmp_path):
    db = tmp_path / "app.db"
    assert not db.exists()
    init_db(db)
    assert db.exists()


def test_init_creates_all_tables(tmp_db):
    tables = get_table_names(tmp_db)
    assert EXPECTED_TABLES.issubset(tables), f"Missing tables: {EXPECTED_TABLES - tables}"


def test_occupation_title_cache_schema(tmp_db):
    with db_conn(tmp_db) as conn:
        conn.execute(
            """
            INSERT INTO occupation_title_cache (
                normalized_title,
                candidate_profile_hash,
                taxonomy_version,
                result,
                matched_occupation_code,
                confidence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "business analyst",
                "profile-hash-1",
                "O*NET-SOC 2019",
                "near",
                "13-1111.00",
                0.91,
            ),
        )
        row = conn.execute(
            """
            SELECT result, matched_occupation_code, confidence
            FROM occupation_title_cache
            WHERE normalized_title = ?
              AND candidate_profile_hash = ?
              AND taxonomy_version = ?
            """,
            ("business analyst", "profile-hash-1", "O*NET-SOC 2019"),
        ).fetchone()

    assert row["result"] == "near"
    assert row["matched_occupation_code"] == "13-1111.00"
    assert row["confidence"] == 0.91


def test_occupation_title_cache_rejects_invalid_result(tmp_db):
    with pytest.raises(sqlite3.IntegrityError):
        with db_conn(tmp_db) as conn:
            conn.execute(
                """
                INSERT INTO occupation_title_cache (
                    normalized_title,
                    candidate_profile_hash,
                    taxonomy_version,
                    result,
                    confidence
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "business analyst",
                    "profile-hash-1",
                    "O*NET-SOC 2019",
                    "maybe",
                    0.5,
                ),
            )


def test_init_is_idempotent(tmp_db):
    # Calling init_db a second time must not raise or lose tables.
    init_db(tmp_db)
    assert EXPECTED_TABLES.issubset(get_table_names(tmp_db))


def test_init_migrates_stored_requirement_importance_values_once(tmp_path):
    db = tmp_path / "legacy-results.db"
    init_db(db)
    with db_conn(db) as conn:
        conn.execute("INSERT INTO users (user_id) VALUES (?)", ("u1",))
        conn.execute(
            """
            INSERT INTO job_history (user_id, job_key, source, platform_id, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "u1",
                "seek:1",
                "seek",
                "1",
                json.dumps(
                    {
                        "last_kept_snapshot": {
                            "requirement_coverage": [
                                {"importance": "mandatory"},
                                {"importance": "strongly_preferred"},
                                {"importance": "preferred"},
                                {"importance": "nice_to_have"},
                            ]
                        }
                    }
                ),
            ),
        )
        conn.execute(
            "DELETE FROM schema_migrations WHERE name = ?",
            ("requirement_importance_terminology_v1",),
        )

    init_db(db)

    with db_conn(db) as conn:
        migrated = json.loads(
            conn.execute(
                "SELECT data FROM job_history WHERE user_id = ? AND job_key = ?",
                ("u1", "seek:1"),
            ).fetchone()[0]
        )
        importances = [
            item["importance"]
            for item in migrated["last_kept_snapshot"]["requirement_coverage"]
        ]
        assert importances == ["required", "expected", "preferred", "bonus"]
        assert conn.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE name = ?",
            ("requirement_importance_terminology_v1",),
        ).fetchone()[0] == 1


def test_wal_mode_enabled(tmp_db):
    conn = get_connection(tmp_db)
    row = conn.execute("PRAGMA journal_mode").fetchone()
    conn.close()
    assert row[0] == "wal"


def test_foreign_keys_enabled(tmp_db):
    conn = get_connection(tmp_db)
    row = conn.execute("PRAGMA foreign_keys").fetchone()
    conn.close()
    assert row[0] == 1


def test_row_factory_returns_dict_like_rows(tmp_db):
    with db_conn(tmp_db) as conn:
        conn.execute("INSERT INTO global_settings (key, value) VALUES (?, ?)", ("k", '"v"'))
    with db_conn(tmp_db) as conn:
        row = conn.execute("SELECT key, value FROM global_settings WHERE key = 'k'").fetchone()
    assert row["key"] == "k"
    assert row["value"] == '"v"'


def test_db_conn_rolls_back_on_error(tmp_db):
    with pytest.raises(ValueError):
        with db_conn(tmp_db) as conn:
            conn.execute(
                "INSERT INTO global_settings (key, value) VALUES (?, ?)", ("rollback_key", '"x"')
            )
            raise ValueError("simulated failure")

    with db_conn(tmp_db) as conn:
        row = conn.execute("SELECT 1 FROM global_settings WHERE key = 'rollback_key'").fetchone()
    assert row is None


def test_foreign_key_constraint_enforced(tmp_db):
    with pytest.raises(sqlite3.IntegrityError):
        with db_conn(tmp_db) as conn:
            conn.execute(
                "INSERT INTO user_profile (user_id, data) VALUES (?, ?)",
                ("nonexistent_user", "{}"),
            )


def test_job_history_unique_constraint(tmp_db):
    with db_conn(tmp_db) as conn:
        conn.execute("INSERT INTO users (user_id) VALUES ('u1')")
        conn.execute(
            "INSERT INTO job_history (user_id, job_key, source, platform_id) VALUES (?, ?, ?, ?)",
            ("u1", "seek:123", "seek", "123"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db_conn(tmp_db) as conn:
            conn.execute(
                "INSERT INTO job_history (user_id, job_key, source, platform_id) VALUES (?, ?, ?, ?)",
                ("u1", "seek:123", "seek", "123"),
            )


def test_init_creates_parent_dirs(tmp_path):
    db = tmp_path / "nested" / "dirs" / "app.db"
    init_db(db)
    assert db.exists()


def test_ensure_user_row_creates_row(tmp_db):
    ensure_user_row("u1", db_path=tmp_db)
    with db_conn(tmp_db) as conn:
        row = conn.execute("SELECT user_id FROM users WHERE user_id = 'u1'").fetchone()
    assert row is not None


def test_ensure_user_row_persists_email_and_display_name(tmp_db):
    ensure_user_row("u1", email="alice@example.com", display_name="Alice", db_path=tmp_db)
    with db_conn(tmp_db) as conn:
        row = conn.execute("SELECT email, display_name FROM users WHERE user_id = 'u1'").fetchone()
    assert row["email"] == "alice@example.com"
    assert row["display_name"] == "Alice"


def test_ensure_user_row_updates_on_repeat_login(tmp_db):
    ensure_user_row("u1", email="alice@example.com", display_name="Alice", db_path=tmp_db)
    ensure_user_row("u1", email="alice@example.com", display_name="Alice B", db_path=tmp_db)
    with db_conn(tmp_db) as conn:
        row = conn.execute("SELECT display_name FROM users WHERE user_id = 'u1'").fetchone()
    assert row["display_name"] == "Alice B"


def test_ensure_user_row_does_not_overwrite_email_with_none(tmp_db):
    ensure_user_row("u1", email="alice@example.com", db_path=tmp_db)
    ensure_user_row("u1", email=None, db_path=tmp_db)
    with db_conn(tmp_db) as conn:
        row = conn.execute("SELECT email FROM users WHERE user_id = 'u1'").fetchone()
    assert row["email"] == "alice@example.com"


def test_ensure_user_row_is_idempotent(tmp_db):
    for _ in range(3):
        ensure_user_row("u1", email="alice@example.com", db_path=tmp_db)
    with db_conn(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM users WHERE user_id = 'u1'").fetchone()[0]
    assert count == 1


def test_concurrent_profile_writes_do_not_corrupt_state(isolated_db):
    from job_hunter_agent import profile_store
    from job_hunter_agent.user_context import set_user_id

    def write_profile(index: int) -> None:
        set_user_id("test_user")
        profile_store.save_profile(
            {
                **profile_store.DEFAULT_PROFILE,
                "star_candidate_profile_text": f"candidate-profile-{index}",
            }
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(write_profile, range(20)))

    with db_conn(isolated_db) as conn:
        row = conn.execute(
            "SELECT data FROM user_profile WHERE user_id = ?",
            ("test_user",),
        ).fetchone()

    assert row is not None
    data = json.loads(row["data"])
    assert isinstance(data, dict)
    assert str(data["star_candidate_profile_text"]).startswith("candidate-profile-")


def test_concurrent_job_history_writes_do_not_corrupt_state(isolated_db):
    from job_hunter_agent.io_utils import load_job_history, save_job_history
    from job_hunter_agent.user_context import set_user_id

    def write_job(index: int) -> None:
        set_user_id("test_user")
        save_job_history(
            {
                f"seek:{index}": {
                    "title": f"Business Analyst {index}",
                    "company": "Example Co",
                    "state": "seen",
                    "first_seen_at": "2026-01-01T00:00:00",
                    "last_seen_at": "2026-01-01T00:00:00",
                }
            }
        )

    with ThreadPoolExecutor(max_workers=6) as executor:
        list(executor.map(write_job, range(20)))

    set_user_id("test_user")
    history = load_job_history()

    assert len(history) == 20
    assert history["seek:0"]["title"] == "Business Analyst 0"
    assert history["seek:19"]["title"] == "Business Analyst 19"
