"""JH-308 exact migration, bounded archive, and quarantine tests."""

from __future__ import annotations

import json
from pathlib import Path

from job_hunter_agent.database import db_conn, init_db
from job_hunter_agent.jh308_cutover import JobMarketMapClient, run_cutover


class _ExactLookupClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def lookup_source_job(self, *, source: str, source_job_id: str) -> dict:
        self.calls.append((source, source_job_id))
        return {
            "api_version": "v3",
            "schema_version": 6,
            "job": {
                "source": source,
                "source_job_id": source_job_id,
                "identity_key": f"{source}:id:{source_job_id}",
            },
        }


def _legacy_event(
    db: Path,
    *,
    event_id: str,
    event_type: str,
    job_key: str = "",
    evidence_ref: str | None = None,
) -> None:
    with db_conn(db) as conn:
        conn.execute(
            """
            INSERT INTO candidate_application_events
                (user_id, event_id, employer_key, employer_raw, role_title,
                 event_type, event_date, source, evidence_ref, confidence, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rob",
                event_id,
                "acme",
                "Acme",
                "Analyst",
                event_type,
                "2026-09-01",
                "seek_applied",
                evidence_ref or event_id,
                "high",
                json.dumps({"job_key": job_key}),
            ),
        )


def _sheet_rows() -> list[dict[str, str]]:
    return [
        {
            "Run Date": "2026-08-01",
            "Company": "Acme",
            "Role": "Analyst",
            "Thread ID": "thread-unlinked",
            "Message ID": "message-unlinked",
            "Status": "Rejection",
        },
        {
            "Run Date": "2026-08-02",
            "Company": "Acme",
            "Role": "Analyst",
            "Thread ID": "thread-exact",
            "Message ID": "message-exact",
            "Status": "Rejection",
            "job_url": "https://www.seek.com.au/job/987654",
        },
        {
            "Run Date": "2026-08-03",
            "Company": "Acme",
            "Role": "Analyst",
            "Thread ID": "thread-junk",
            "Message ID": "message-junk",
            "Status": "Not Job-related",
        },
    ]


def test_cutover_migrates_exact_rows_and_preserves_other_evidence(monkeypatch, tmp_path):
    db = tmp_path / "cutover.db"
    backup = tmp_path / "backup.sqlite"
    init_db(db)
    with db_conn(db) as conn:
        conn.execute("INSERT INTO users (user_id, email) VALUES (?, ?)", ("rob", "rob@test"))
    _legacy_event(db, event_id="applied", event_type="applied", job_key="seek:123")
    monkeypatch.setattr(
        "job_hunter_agent.jh308_cutover.fetch_configured_sheet_rows",
        lambda *args, **kwargs: (_sheet_rows(), {"status": "read", "rows": 3}),
    )
    client = _ExactLookupClient()

    report = run_cutover(
        db,
        target_user_id="rob",
        client=client,
        apply=True,
        backup_path=backup,
        max_entries=10,
    )

    assert backup.is_file()
    assert report["counters"]["activity_migrated"] == 2
    assert report["counters"]["exact_lookup_resolved"] == 1
    assert report["counters"]["historical_inserted"] == 1
    assert report["counters"]["quarantine_inserted"] == 1
    assert client.calls == [("seek", "987654")]
    with db_conn(db) as conn:
        activities = conn.execute(
            "SELECT job_key, activity_type FROM job_activity_events WHERE user_id='rob' ORDER BY job_key"
        ).fetchall()
        assert [(row[0], row[1]) for row in activities] == [
            ("seek:123", "applied"),
            ("seek:987654", "rejected"),
        ]
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(historical_application_evidence)")
        }
        assert "job_key" not in columns
        assert conn.execute(
            "SELECT COUNT(*) FROM historical_application_evidence WHERE user_id='rob'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT reason FROM historical_application_quarantine WHERE user_id='rob'"
        ).fetchone()[0] == "source explicitly marked the row not job-related"


def test_cutover_accepts_canonical_jh_manual_action_source():
    from job_hunter_agent.jh308_cutover import _activity_source

    assert _activity_source({"source": "jh_manual_action"}) == "manual"


def test_apply_does_not_require_jmm_for_already_exact_rows(monkeypatch, tmp_path):
    db = tmp_path / "cutover.db"
    backup = tmp_path / "backup.sqlite"
    init_db(db)
    with db_conn(db) as conn:
        conn.execute("INSERT INTO users (user_id) VALUES (?)", ("rob",))
    _legacy_event(db, event_id="manual-applied", event_type="applied", job_key="seek:123")
    monkeypatch.setattr(
        "job_hunter_agent.jh308_cutover.fetch_configured_sheet_rows",
        lambda *args, **kwargs: ([], {"status": "read", "rows": 0}),
    )

    def fail_if_called():
        raise AssertionError("JMM is not needed for an already exact identity")

    monkeypatch.setattr(JobMarketMapClient, "from_environment", staticmethod(fail_if_called))

    report = run_cutover(db, target_user_id="rob", apply=True, backup_path=backup)

    assert report["counters"]["activity_migrated"] == 1


def test_cutover_is_idempotent_and_does_not_use_employer_matching(monkeypatch, tmp_path):
    db = tmp_path / "cutover.db"
    init_db(db)
    with db_conn(db) as conn:
        conn.execute("INSERT INTO users (user_id) VALUES (?)", ("rob",))
    _legacy_event(db, event_id="applied", event_type="applied", job_key="seek:123")
    monkeypatch.setattr(
        "job_hunter_agent.jh308_cutover.fetch_configured_sheet_rows",
        lambda *args, **kwargs: (_sheet_rows()[:1], {"status": "read", "rows": 1}),
    )
    client = _ExactLookupClient()
    backup = tmp_path / "backup.sqlite"

    first = run_cutover(
        db, target_user_id="rob", client=client, apply=True, backup_path=backup, max_entries=10
    )
    second = run_cutover(
        db, target_user_id="rob", client=client, apply=True, backup_path=backup, max_entries=10
    )

    assert first["counters"]["activity_migrated"] == 1
    assert second["counters"].get("activity_migrated", 0) == 0
    assert second["counters"]["already_canonical"] == 1
    with db_conn(db) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM job_activity_events WHERE user_id='rob'"
        ).fetchone()[0] == 1


def test_plan_is_read_only_and_jmm_lookup_is_not_called_without_apply(monkeypatch, tmp_path):
    db = tmp_path / "cutover.db"
    init_db(db)
    with db_conn(db) as conn:
        conn.execute("INSERT INTO users (user_id) VALUES (?)", ("rob",))
    _legacy_event(db, event_id="applied", event_type="applied", job_key="seek:123")
    monkeypatch.setattr(
        "job_hunter_agent.jh308_cutover.fetch_configured_sheet_rows",
        lambda *args, **kwargs: (_sheet_rows()[:1], {"status": "read", "rows": 1}),
    )
    before = db.read_bytes()
    report = run_cutover(db, target_user_id="rob", apply=False)
    assert report["apply"] is False
    assert report["counters"]["activity_planned"] == 1
    assert db.read_bytes() == before
