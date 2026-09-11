"""JH-307 read-only cutover audit contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from job_hunter_agent.database import db_conn, init_db
from job_hunter_agent.jh307_audit import (
    CLASS_ALREADY_CANONICAL,
    CLASS_EXACT_IDENTITY_RECOVERABLE,
    CLASS_EXACT_MIGRATABLE,
    CLASS_HISTORICAL_UNLINKED,
    CLASS_JUNK_OR_DUPLICATE,
    CLASS_UNSCOPED,
    OWNER_AGENT,
    OWNER_TEST,
    build_audit_report,
)


def _insert_event(
    db: Path,
    *,
    user_id: str,
    event_id: str,
    event_type: str,
    job_key: str,
    source: str = "rejection_sheet",
    data: dict | None = None,
    evidence_ref: str | None = None,
) -> None:
    payload = dict(data or {})
    payload.setdefault("job_key", job_key)
    with db_conn(db) as conn:
        conn.execute(
            """
            INSERT INTO candidate_application_events
                (user_id, event_id, employer_key, employer_raw, role_title,
                 event_type, event_date, source, evidence_ref, confidence, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                event_id,
                "acme",
                "Acme",
                "Analyst",
                event_type,
                "2026-09-01",
                source,
                evidence_ref or event_id,
                "high",
                json.dumps(payload),
            ),
        )


def _insert_activity(db: Path, *, user_id: str, job_key: str, activity_type: str) -> None:
    with db_conn(db) as conn:
        conn.execute(
            """
            INSERT INTO job_activity_events
                (user_id, event_id, job_key, activity_type, agent_id, occurred_at,
                 source, evidence_ref, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                f"canonical-{activity_type}",
                job_key,
                activity_type,
                "manual",
                "2026-09-02T00:00:00+00:00",
                "manual",
                "canonical-evidence",
                f"canonical-{activity_type}",
            ),
        )


def test_audit_classifies_explicit_identity_without_text_inference(tmp_path):
    db = tmp_path / "audit.db"
    init_db(db)
    with db_conn(db) as conn:
        conn.executemany(
            "INSERT INTO users (user_id, email) VALUES (?, ?)",
            [("rob", "rob@example.test"), ("fixture", "fixture@example.test"), ("agent", None)],
        )
        conn.execute(
            "INSERT INTO candidate_application_history (user_id, job_key, data) VALUES (?, ?, ?)",
            (
                "rob",
                "seek:history-table-1",
                json.dumps(
                    {
                        "event_type": "rejection",
                        "company": "Acme",
                        "role": "Analyst",
                    }
                ),
            ),
        )
        conn.execute(
            "INSERT INTO user_profile (user_id, data) VALUES (?, ?)",
            (
                "rob",
                json.dumps({"review_controls": {"applied_job_keys": ["seek:profile-1"]}}),
            ),
        )
    _insert_activity(db, user_id="rob", job_key="seek:canonical-1", activity_type="rejected")
    _insert_event(
        db,
        user_id="rob",
        event_id="canonical-legacy",
        event_type="rejected",
        job_key="seek:canonical-1",
        evidence_ref="canonical-message",
    )
    _insert_event(
        db,
        user_id="rob",
        event_id="direct",
        event_type="applied",
        job_key="linkedin:direct-1",
    )
    _insert_event(
        db,
        user_id="agent",
        event_id="agent-row",
        event_type="applied",
        job_key="seek:agent-1",
    )

    local_rows = [
        {
            "id": "url-row",
            "date": "2026-08-01",
            "company": "Acme",
            "role": "Analyst",
            "status": "rejection",
            "source": "sheet_import",
            "job_url": "https://seek.example/jobs/123",
        },
    ]
    sheet_rows = [
        {
            "Run Date": "2026-08-02",
            "Company": "Other",
            "Subject": "ignored subject text",
            "Content": "private body must not enter the report",
            "Thread ID": "thread-1",
            "Message ID": "message-1",
            "Status": "Rejection",
        },
        {
            "Run Date": "2026-08-03",
            "Company": "Junk",
            "Thread ID": "thread-junk",
            "Message ID": "message-junk",
            "Status": "Not Job-related",
        },
    ]
    local_path = tmp_path / "history.json"
    local_path.write_text(json.dumps(local_rows), encoding="utf-8")
    report = build_audit_report(
        db,
        target_user_id="rob",
        local_history_path=local_path,
        local_history_user_id="rob",
        sheet_rows=sheet_rows,
        sheet_user_id="rob",
        sheet_status={"status": "read", "rows": len(sheet_rows)},
        explicit_user_scopes={"agent": OWNER_AGENT, "fixture": OWNER_TEST},
        repo_root=tmp_path,
    )

    by_ref = {row["record_ref"]: row for row in report["records"]}
    assert (
        by_ref["candidate_application_events:rob:canonical-legacy"]["classification"]
        == CLASS_ALREADY_CANONICAL
    )
    assert (
        by_ref["candidate_application_events:rob:direct"]["classification"]
        == CLASS_EXACT_MIGRATABLE
    )
    assert (
        by_ref["candidate_application_events:agent:agent-row"]["classification"] == CLASS_UNSCOPED
    )
    assert by_ref["candidate_application_events:agent:agent-row"]["owner"] == OWNER_AGENT
    assert (
        by_ref["candidate_application_history_db:rob:seek:history-table-1"]["classification"]
        == CLASS_EXACT_MIGRATABLE
    )
    assert (
        by_ref["candidate_application_history:url-row"]["classification"]
        == CLASS_EXACT_IDENTITY_RECOVERABLE
    )
    assert by_ref["Job_Rejections:message-1:0"]["classification"] == CLASS_HISTORICAL_UNLINKED
    assert by_ref["Job_Rejections:message-junk:1"]["classification"] == CLASS_JUNK_OR_DUPLICATE
    serialized = json.dumps(report)
    assert "private body" not in serialized
    assert "ignored subject text" not in serialized
    assert (
        report["job_key_collections"]["user_profile"]["rob"]["collections"]["applied_job_keys"] == 1
    )


def test_audit_is_deterministic_and_does_not_write_database(tmp_path):
    db = tmp_path / "audit.db"
    init_db(db)
    with db_conn(db) as conn:
        conn.execute(
            "INSERT INTO users (user_id, email) VALUES (?, ?)", ("rob", "rob@example.test")
        )
    _insert_event(db, user_id="rob", event_id="one", event_type="applied", job_key="seek:one")
    before = db.read_bytes()

    first = build_audit_report(db, target_user_id="rob", repo_root=tmp_path)
    second = build_audit_report(db, target_user_id="rob", repo_root=tmp_path)

    assert first == second
    assert db.read_bytes() == before
    assert first["read_only"] is True
    assert first["policy"]["no_gmail_search"] is True
    assert first["policy"]["no_jmm_mapping"] is True


def test_duplicate_durable_evidence_is_not_migratable(tmp_path):
    db = tmp_path / "audit.db"
    init_db(db)
    with db_conn(db) as conn:
        conn.execute("INSERT INTO users (user_id) VALUES (?)", ("rob",))
    rows = [
        {"Run Date": "2026-08-01", "Company": "Acme", "Message ID": "same", "Status": "Rejection"},
        {"Run Date": "2026-08-01", "Company": "Acme", "Message ID": "same", "Status": "Rejection"},
    ]
    report = build_audit_report(
        db,
        target_user_id="rob",
        sheet_rows=rows,
        sheet_user_id="rob",
        sheet_status={"status": "read", "rows": 2},
        repo_root=tmp_path,
    )
    rows_by_ref = {row["record_ref"]: row for row in report["records"]}
    assert rows_by_ref["Job_Rejections:same:0"]["classification"] == CLASS_HISTORICAL_UNLINKED
    assert rows_by_ref["Job_Rejections:same:1"]["classification"] == CLASS_JUNK_OR_DUPLICATE
    assert rows_by_ref["Job_Rejections:same:1"]["duplicate_of"] == "Job_Rejections:same:0"
