"""Runtime behaviour for historical application evidence and Gmail fallback identity."""

from job_hunter_agent import activity_ledger as activity
from job_hunter_agent.candidate_application_history import (
    candidate_history_is_confirmed_rejection,
    enrich_records_with_application_history,
)
from job_hunter_agent.database import db_conn, ensure_user_row
from job_hunter_agent.employer_outcome_store import get_employer_outcome
from job_hunter_agent.historical_application_evidence import load_historical_application_evidence
from job_hunter_agent.workspace_renderer import _build_checks_before_applying_items


def _insert_history(db, *, outcome: str = "rejected", role: str = "Technical Business Analyst") -> None:
    ensure_user_row("rob", db_path=db)
    with db_conn(db) as conn:
        conn.execute(
            """
            INSERT INTO historical_application_evidence
                (user_id, evidence_id, outcome, event_date, employer_raw, role_title,
                 source, evidence_ref, origin_store, origin_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "rob", "history-1", outcome, "2026-08-23", "Northwind Networks", role,
                "gmail", "gmail:message-1", "historical_reconciliation", "gmail:message-1",
            ),
        )


def test_exact_company_and_role_surfaces_confirmed_rejection(isolated_db):
    _insert_history(isolated_db)
    history = load_historical_application_evidence("rob", db_path=isolated_db)
    record = enrich_records_with_application_history(
        [{"company": "Northwind Networks", "title": "Technical Business Analyst"}], history
    )[0]
    match = record["candidate_application_history"]

    assert match["llm_application_status"] == "rejection"
    assert match["_match_score"] == 1.0
    assert candidate_history_is_confirmed_rejection(match) is True
    checks = _build_checks_before_applying_items([], False, False, None, match, [], "unknown")
    assert "Rejected before: Northwind Networks — Technical Business Analyst" in checks


def test_same_employer_different_role_stays_possible_previous_application(isolated_db):
    _insert_history(isolated_db)
    history = load_historical_application_evidence("rob", db_path=isolated_db)
    record = enrich_records_with_application_history(
        [{"company": "Northwind Networks", "title": "Platform Engineer"}], history
    )[0]
    match = record["candidate_application_history"]

    assert candidate_history_is_confirmed_rejection(match) is False
    checks = _build_checks_before_applying_items([], False, False, None, match, [], "unknown")
    assert any("Possible previous application" in item for item in checks)


def test_gmail_confirmation_job_key_rolls_up_application_and_rejection_by_employer(isolated_db):
    common = {
        "user_id": "rob",
        "job_key": "gmail:applicationmessage123",
        "agent_id": activity.AGENT_MANUAL,
        "source": activity.SOURCE_GMAIL,
        "employer_raw": "Northwind Networks",
        "role_title": "Technical Business Analyst",
        "db_path": isolated_db,
    }
    activity.record_activity_event(
        **common, activity_type=activity.ACTIVITY_APPLIED,
        occurred_at="2026-08-06T00:00:00+00:00", evidence_ref="gmail:applicationmessage123",
        idempotency_key="test:gmail-fallback:applied",
        metadata={"identity_basis": "application_confirmation_message_id"},
    )
    activity.record_activity_event(
        **common, activity_type=activity.ACTIVITY_REJECTED,
        occurred_at="2026-08-23T00:00:00+00:00", evidence_ref="gmail:rejectionmessage456",
        idempotency_key="test:gmail-fallback:rejected",
        metadata={"identity_basis": "application_confirmation_message_id"},
    )

    rollup = get_employer_outcome("rob", "Northwind Networks", db_path=isolated_db)
    assert rollup is not None
    assert rollup["counts"][activity.ACTIVITY_APPLIED] == 1
    assert rollup["counts"][activity.ACTIVITY_REJECTED] == 1
    assert rollup["roles"][-1]["role_title"] == "Technical Business Analyst"
