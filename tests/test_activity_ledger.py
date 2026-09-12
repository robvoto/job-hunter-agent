"""JH-305 canonical activity ledger contract tests."""

from __future__ import annotations

import pytest

from job_hunter_agent import activity_ledger as ledger
from job_hunter_agent.database import db_conn


def _record(user, key, activity_type, idem, *, agent=ledger.AGENT_JOB_HUNTER, when=None):
    return ledger.record_activity_event(
        user_id=user,
        job_key=key,
        activity_type=activity_type,
        agent_id=agent,
        source=agent if agent != ledger.AGENT_MANUAL else ledger.SOURCE_MANUAL,
        idempotency_key=idem,
        occurred_at=when,
        employer_raw="Northwind Systems",
        role_title="Analyst",
    )


def test_activity_is_per_user_and_presented_is_not_viewed(isolated_db):
    key = "seek:shared-1"
    _record("user-a", key, ledger.ACTIVITY_APPLIED, "a-applied")
    _record("user-b", key, ledger.ACTIVITY_REJECTED, "b-rejected")
    _record("user-a", key, ledger.ACTIVITY_PRESENTED, "a-presented", agent=ledger.AGENT_CHATGPT)

    a = ledger.load_job_activity("user-a", key, agent_id=ledger.AGENT_CHATGPT)
    b = ledger.load_job_activity("user-b", key)
    assert a["activity"]["applied"] is True
    assert a["activity"]["rejected"] is False
    assert a["activity"]["presented_by_any_agent"] is True
    assert a["activity"]["presented_by_agent"] is True
    assert a["activity"]["viewed"] is False
    assert b["activity"]["rejected"] is True
    assert b["activity"]["applied"] is False



def test_presented_event_does_not_create_legacy_history_projection(isolated_db):
    key = "seek:presentation-only"
    _record("user-a", key, ledger.ACTIVITY_PRESENTED, "presented-only")

    current = ledger.load_job_activity("user-a", key)
    assert current["activity"]["presented_by_any_agent"] is True
    with db_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM job_history WHERE user_id = ? AND job_key = ?",
            ("user-a", key),
        ).fetchone()[0] == 0


def test_reversals_are_append_only_and_occurred_at_is_authoritative(isolated_db):
    key = "seek:ordered-1"
    _record("user-a", key, ledger.ACTIVITY_REJECTED, "reject", when="2026-01-02T00:00:00Z")
    _record("user-a", key, ledger.ACTIVITY_UNREJECTED, "unreject", when="2026-01-01T00:00:00Z")
    _record("user-a", key, ledger.ACTIVITY_NO_RESPONSE, "no-response", when="2026-01-03T00:00:00Z")
    current = ledger.load_job_activity("user-a", key)
    assert current["activity"]["rejected"] is True
    assert current["activity"]["no_response"] is True
    assert [event["activity_type"] for event in current["events"]] == [
        ledger.ACTIVITY_UNREJECTED,
        ledger.ACTIVITY_REJECTED,
        ledger.ACTIVITY_NO_RESPONSE,
    ]

    with db_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM job_activity_events WHERE user_id = ? AND job_key = ?",
            ("user-a", key),
        ).fetchone()[0] == 3


def test_idempotent_retry_returns_original_event_and_rejects_reuse(isolated_db):
    first = _record("user-a", "seek:idempotent", ledger.ACTIVITY_LIKED, "same")
    second = _record("user-a", "seek:idempotent", ledger.ACTIVITY_LIKED, "same")
    assert first["event_id"] == second["event_id"]
    with pytest.raises(ValueError, match="different activity"):
        _record("user-a", "seek:other", ledger.ACTIVITY_LIKED, "same")


def test_untrusted_job_identity_is_not_accepted(isolated_db):
    with pytest.raises(ValueError):
        _record("user-a", "just-a-title", ledger.ACTIVITY_APPLIED, "bad-key")


def test_old_unkeyed_event_table_is_not_written(isolated_db):
    _record("user-a", "seek:new", ledger.ACTIVITY_REJECTED, "canonical")
    with db_conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidate_application_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM job_activity_events").fetchone()[0] == 1


def test_applied_and_rejected_are_mutually_exclusive_and_latest_wins(isolated_db):
    key = "seek:exclusive-status"
    _record(
        "user-a", key, ledger.ACTIVITY_APPLIED, "exclusive-applied",
        when="2026-01-01T00:00:00Z",
    )
    _record(
        "user-a", key, ledger.ACTIVITY_REJECTED, "exclusive-rejected",
        when="2026-01-02T00:00:00Z",
    )

    rejected = ledger.load_job_activity("user-a", key)["activity"]
    assert rejected["applied"] is False
    assert rejected["rejected"] is True

    _record(
        "user-a", key, ledger.ACTIVITY_APPLIED, "exclusive-reapplied",
        when="2026-01-03T00:00:00Z",
    )
    reapplied = ledger.load_job_activity("user-a", key)["activity"]
    assert reapplied["applied"] is True
    assert reapplied["rejected"] is False
