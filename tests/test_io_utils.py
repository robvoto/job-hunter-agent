"""Tests for I/O helpers."""

from datetime import datetime, timedelta, timezone

from job_hunter_agent import io_utils, llm_gate


def test_prune_llm_cache_for_current_profile_keeps_only_active_contracts(monkeypatch):
    monkeypatch.setattr(llm_gate, "_profile_fingerprint", lambda: "active-fp")

    active_fit = llm_gate.build_llm_cache_key("one")
    active_title = llm_gate.build_title_judgment_cache_key(
        "Business Analyst", ["Business Analyst"], []
    )
    current_version = llm_gate.LLM_CACHE_SCHEMA_VERSION
    stale_fit_version = llm_gate.FIT_REVIEW_CACHE_CONTRACT_VERSION - 1
    cache = {
        active_fit: {"value": 1},
        active_title: {"value": 2},
        f"v{current_version}:stale-fp:fit:v{llm_gate.FIT_REVIEW_CACHE_CONTRACT_VERSION}:old": {"value": 3},
        f"v{current_version - 1}:active-fp:fit:v{llm_gate.FIT_REVIEW_CACHE_CONTRACT_VERSION}:old": {"value": 4},
        f"v{current_version}:active-fp:fit:v{stale_fit_version}:posting:v{llm_gate.POSTING_CHANNEL_CLASSIFIER_VERSION}:old": {"value": 5},
        f"v{current_version}:active-fp:legacy-hash-only": {"value": 6},
    }

    pruned, removed = io_utils.prune_llm_cache_for_current_profile(cache)

    assert removed == 4
    assert pruned == {
        active_fit: {"value": 1},
        active_title: {"value": 2},
    }


def test_load_timestamped_cache_discards_non_timestamped_entries(tmp_path):
    cache_path = tmp_path / "llm_cache.json"
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    io_utils.save_json(
        cache_path,
        {
            "old-entry": {"fit_review": {"decision": "KEEP", "grade": "SOLID"}},
            "new-entry": {
                "value": {"fit_review": {"decision": "KEEP", "grade": "SOLID"}},
                "created_at": now,
                "updated_at": now,
            },
        },
    )

    loaded = io_utils._load_timestamped_cache(
        cache_path,
        max_entries=10,
        max_age_days=365,
    )

    assert loaded == {
        "new-entry": {"fit_review": {"decision": "KEEP", "grade": "SOLID"}}
    }


def test_save_timestamped_cache_prunes_by_age_and_count(tmp_path):
    cache_path = tmp_path / "llm_cache.json"
    now = datetime.now(timezone.utc)
    io_utils.save_json(
        cache_path,
        {
            "keep-existing": {
                "value": {"value": 1},
                "created_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=2)).isoformat(timespec="seconds"),
            },
            "drop-stale": {
                "value": {"value": 2},
                "created_at": (now - timedelta(days=90)).isoformat(timespec="seconds"),
                "updated_at": (now - timedelta(days=90)).isoformat(timespec="seconds"),
            },
        },
    )

    io_utils._save_timestamped_cache(
        cache_path,
        {
            "keep-existing": {"value": 1},
            "keep-new": {"value": 3},
            "drop-overflow": {"value": 4},
        },
        max_entries=2,
        max_age_days=30,
    )

    raw = io_utils.load_json_dict(cache_path)
    assert "drop-stale" not in raw
    assert len(raw) == 2
    assert raw["keep-new"]["created_at"]
    assert raw["keep-new"]["updated_at"]


def test_save_job_history_prunes_old_and_overflow_entries(isolated_db, monkeypatch):
    from job_hunter_agent.database import db_conn
    from job_hunter_agent.user_context import set_user_id

    monkeypatch.setattr("job_hunter_agent.global_settings.get_job_history_max_entries", lambda: 2)
    monkeypatch.setattr("job_hunter_agent.global_settings.get_job_history_max_age_days", lambda: 30)

    recent = datetime.now(timezone.utc)
    older = recent - timedelta(days=5)
    stale = recent - timedelta(days=45)

    set_user_id("test_user")
    history = {
        "seek:newest": {
            "title": "Newest",
            "company": "Example Co",
            "state": "seen",
            "first_seen_at": older.isoformat(timespec="seconds"),
            "last_seen_at": recent.isoformat(timespec="seconds"),
        },
        "seek:older": {
            "title": "Older",
            "company": "Example Co",
            "state": "seen",
            "first_seen_at": older.isoformat(timespec="seconds"),
            "last_seen_at": older.isoformat(timespec="seconds"),
        },
        "seek:stale": {
            "title": "Stale",
            "company": "Example Co",
            "state": "seen",
            "first_seen_at": stale.isoformat(timespec="seconds"),
            "last_seen_at": stale.isoformat(timespec="seconds"),
        },
        "seek:overflow": {
            "title": "Overflow",
            "company": "Example Co",
            "state": "seen",
            "first_seen_at": (recent - timedelta(days=1)).isoformat(timespec="seconds"),
            "last_seen_at": (recent - timedelta(days=1)).isoformat(timespec="seconds"),
        },
    }

    io_utils.save_job_history(history)

    assert list(history) == ["seek:newest", "seek:overflow"]

    loaded = io_utils.load_job_history()
    assert list(loaded) == ["seek:newest", "seek:overflow"]

    with db_conn(isolated_db) as conn:
        rows = conn.execute(
            "SELECT job_key FROM job_history WHERE user_id = ? ORDER BY job_key",
            ("test_user",),
        ).fetchall()

    assert [row["job_key"] for row in rows] == ["seek:newest", "seek:overflow"]


def test_prune_occupation_title_cache_applies_age_and_entry_limits(isolated_db, monkeypatch):
    from job_hunter_agent.database import db_conn

    monkeypatch.setattr(
        "job_hunter_agent.global_settings.get_occupation_title_cache_max_entries",
        lambda: 2,
    )
    monkeypatch.setattr(
        "job_hunter_agent.global_settings.get_occupation_title_cache_max_age_days",
        lambda: 30,
    )

    now = datetime.now(timezone.utc)
    with db_conn(isolated_db) as conn:
        conn.executemany(
            """
            INSERT INTO occupation_title_cache
                (normalized_title, candidate_profile_hash, taxonomy_version, result, matched_occupation_code, confidence, created_at)
            VALUES (?, ?, ?, 'near', NULL, 0.9, ?)
            """,
            [
                (
                    "fresh-one",
                    "profile",
                    "v1",
                    now.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
                ),
                (
                    "fresh-two",
                    "profile",
                    "v1",
                    (now - timedelta(days=1)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
                ),
                (
                    "fresh-three",
                    "profile",
                    "v1",
                    (now - timedelta(days=2)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
                ),
                (
                    "stale",
                    "profile",
                    "v1",
                    (now - timedelta(days=60)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S"),
                ),
            ],
        )

    removed = io_utils.prune_occupation_title_cache(isolated_db)

    assert removed == 2

    with db_conn(isolated_db) as conn:
        rows = conn.execute(
            "SELECT normalized_title FROM occupation_title_cache ORDER BY datetime(created_at) DESC"
        ).fetchall()

    assert [row["normalized_title"] for row in rows] == ["fresh-one", "fresh-two"]


def test_clear_runtime_caches_removes_transient_files_and_occupation_cache(isolated_db, tmp_path, monkeypatch):
    from job_hunter_agent.database import db_conn

    llm_cache_path = tmp_path / "llm_cache.json"
    cv_cache_path = tmp_path / "cv_extraction_cache.json"
    history_cache_path = tmp_path / "candidate_application_history_cache.json"
    history_json_path = tmp_path / "candidate_application_history.json"
    legacy_runtime_db_path = tmp_path / "job_hunter.db"

    for path in (
        llm_cache_path,
        cv_cache_path,
        history_cache_path,
        history_json_path,
        legacy_runtime_db_path,
    ):
        path.write_text("stale", encoding="utf-8")

    monkeypatch.setattr(io_utils, "LLM_CACHE_PATH", llm_cache_path)
    monkeypatch.setattr(io_utils, "CV_EXTRACTION_CACHE_PATH", cv_cache_path)
    monkeypatch.setattr(io_utils, "CANDIDATE_APPLICATION_HISTORY_CACHE_PATH", history_cache_path)
    monkeypatch.setattr(io_utils, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(io_utils, "get_candidate_application_history_path", lambda: history_json_path)

    now = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    with db_conn(isolated_db) as conn:
        conn.execute(
            """
            INSERT INTO occupation_title_cache
                (normalized_title, candidate_profile_hash, taxonomy_version, result, matched_occupation_code, confidence, created_at)
            VALUES (?, ?, ?, 'near', NULL, 0.9, ?)
            """,
            ("business analyst", "profile", "v1", now),
        )

    result = io_utils.clear_runtime_caches(isolated_db)

    assert result["ok"] is True
    assert sorted(result["cleared_files"]) == sorted(
        [
            "llm_cache.json",
            "cv_extraction_cache.json",
            "job_hunter.db",
        ]
    )
    for path in (
        llm_cache_path,
        cv_cache_path,
        legacy_runtime_db_path,
    ):
        assert not path.exists()
    assert history_cache_path.exists()
    assert history_json_path.exists()

    with db_conn(isolated_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM occupation_title_cache").fetchone()[0]

    assert count == 0


def test_clear_candidate_application_history_runtime_removes_only_history_files(
    tmp_path, monkeypatch
):
    history_cache_path = tmp_path / "candidate_application_history_cache.json"
    history_json_path = tmp_path / "candidate_application_history.json"
    history_cache_path.write_text("cache", encoding="utf-8")
    history_json_path.write_text("history", encoding="utf-8")

    monkeypatch.setattr(io_utils, "CANDIDATE_APPLICATION_HISTORY_CACHE_PATH", history_cache_path)
    monkeypatch.setattr(io_utils, "get_candidate_application_history_path", lambda: history_json_path)

    result = io_utils.clear_candidate_application_history_runtime()

    assert result["ok"] is True
    assert sorted(result["cleared_files"]) == sorted(
        ["candidate_application_history_cache.json", "candidate_application_history.json"]
    )
    assert not history_cache_path.exists()
    assert not history_json_path.exists()
