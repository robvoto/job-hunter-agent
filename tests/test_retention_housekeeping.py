"""Retention housekeeping keeps workspace state and manual review state aligned."""

import json
from datetime import datetime, timedelta, timezone

from job_hunter_agent import retention_housekeeping
from job_hunter_agent.database import db_conn, ensure_user_row
from job_hunter_agent.user_context import set_user_id


def test_housekeeping_expires_hidden_prunes_pool_and_keeps_applied(
    isolated_db, monkeypatch
):
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(days=5)).isoformat(timespec="seconds")
    old = (now - timedelta(days=20)).isoformat(timespec="seconds")
    set_user_id("test_user")
    ensure_user_row("test_user")

    profile = {
        "review_controls": {
            "applied_job_keys": ["seek:applied"],
            "hidden_job_keys": ["seek:hidden-recent", "seek:hidden-expired"],
        }
    }
    history = {
        "seek:applied": {"last_applied_at": old, "last_kept_at": old},
        "seek:hidden-recent": {
            "last_hidden_at": recent,
            "is_hidden": True,
            "last_kept_at": old,
        },
        "seek:hidden-expired": {
            "last_hidden_at": old,
            "is_hidden": True,
            "last_kept_at": old,
        },
        "seek:potential-recent": {"last_kept_at": recent},
        "seek:potential-stale": {"last_kept_at": old},
    }
    pool = [
        {"job_key": job_key, "url": f"https://example.test/{job_key}"}
        for job_key in history
    ]
    with db_conn(isolated_db) as conn:
        conn.execute(
            "INSERT INTO workspace_pool (user_id, data, updated_at) VALUES (?, ?, datetime('now'))",
            ("test_user", json.dumps(pool)),
        )

    saved_profiles = []
    monkeypatch.setattr(retention_housekeeping, "save_profile", lambda value: saved_profiles.append(value))
    monkeypatch.setattr(retention_housekeeping, "get_potential_retention_days", lambda: 15)
    monkeypatch.setattr(retention_housekeeping, "get_hidden_retention_days", lambda: 15)

    applied, hidden = retention_housekeeping.run_retention_housekeeping(profile, history, now)

    assert applied == {"seek:applied"}
    assert hidden == {"seek:hidden-recent"}
    assert profile["review_controls"]["hidden_job_keys"] == ["seek:hidden-recent"]
    assert saved_profiles

    with db_conn(isolated_db) as conn:
        row = conn.execute(
            "SELECT data FROM workspace_pool WHERE user_id = ?", ("test_user",)
        ).fetchone()
    retained = json.loads(row["data"])
    assert {item["job_key"] for item in retained} == {
        "seek:applied",
        "seek:hidden-recent",
        "seek:potential-recent",
    }
