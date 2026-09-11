"""HTTP contract tests for the JH-305 activity API.

JH-310 extends this coverage for external read-only plan-agent callers:
exact Job Market Map identity-key compatibility, authenticated reads,
cross-user isolation, applied/hidden/rejected visibility, and proof that a
read never writes activity.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from job_hunter_agent import activity_ledger, agent_token_store
from job_hunter_agent.config import USER_ACCESS_APPROVED
from job_hunter_agent.database import ensure_user_row
from job_hunter_agent.fastapi_app import create_app


def test_activity_api_requires_authentication():
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/activity/events",
            json={
                "job_key": "seek:unauthenticated",
                "activity_type": "presented",
                "agent_id": "chatgpt",
                "source": "chatgpt",
                "idempotency_key": "one",
            },
        )
    assert response.status_code == 401


def test_bearer_agent_can_write_read_and_retry_its_own_activity(isolated_db):
    ensure_user_row("user-a", access_status=USER_ACCESS_APPROVED)
    token = agent_token_store.create_agent_token(user_id="user-a", agent_id="chatgpt")
    headers = {"Authorization": f"Bearer {token['token']}"}
    payload = {
        "job_key": "seek:api-1",
        "activity_type": "presented",
        "source": "chatgpt",
        "idempotency_key": "chatgpt-presentation-1",
        "occurred_at": "2026-01-01T12:00:00+00:00",
        "evidence_ref": "agent-run-1",
        "metadata": {"channel": "external"},
        "employer_raw": "Northwind Systems",
        "role_title": "Analyst",
    }
    with TestClient(create_app()) as client:
        first = client.post("/api/activity/events", headers=headers, json=payload)
        retry = client.post("/api/activity/events", headers=headers, json=payload)
        read = client.get("/api/activity/jobs/seek:api-1?agent_id=chatgpt", headers=headers)
        mismatch = client.post(
            "/api/activity/events",
            headers=headers,
            json={**payload, "idempotency_key": "wrong-agent", "agent_id": "claude"},
        )
    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json()["event"]["event_id"] == retry.json()["event"]["event_id"]
    assert read.status_code == 200
    assert read.json()["activity"]["presented_by_agent"] is True
    assert len(read.json()["events"]) == 1
    assert mismatch.status_code == 400


def test_caller_cannot_select_another_user(isolated_db):
    ensure_user_row("user-a", access_status=USER_ACCESS_APPROVED)
    token = agent_token_store.create_agent_token(user_id="user-a", agent_id="manual")
    with TestClient(create_app()) as client:
        response = client.post(
            "/api/activity/events",
            headers={"Authorization": f"Bearer {token['token']}"},
            json={
                "user_id": "user-b",
                "job_key": "seek:scope",
                "activity_type": "liked",
                "source": "manual",
                "idempotency_key": "scope-1",
            },
        )
    assert response.status_code == 400


def test_external_writes_are_bounded_per_token(isolated_db, monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_ACTIVITY_RATE_LIMIT_PER_MINUTE", "1")
    ensure_user_row("user-a", access_status=USER_ACCESS_APPROVED)
    token = agent_token_store.create_agent_token(user_id="user-a", agent_id="chatgpt")
    headers = {"Authorization": f"Bearer {token['token']}"}
    base = {
        "activity_type": "presented",
        "source": "chatgpt",
        "employer_raw": "Northwind Systems",
    }
    with TestClient(create_app()) as client:
        first = client.post(
            "/api/activity/events",
            headers=headers,
            json={**base, "job_key": "seek:rate-1", "idempotency_key": "rate-1"},
        )
        second = client.post(
            "/api/activity/events",
            headers=headers,
            json={**base, "job_key": "seek:rate-2", "idempotency_key": "rate-2"},
        )
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["retry_after_seconds"] >= 1


def test_activity_read_requires_authentication():
    with TestClient(create_app()) as client:
        response = client.get("/api/activity/jobs/seek:jh310-noauth")
    assert response.status_code == 401


def test_activity_read_accepts_jmm_identity_key_format(isolated_db):
    """An external plan agent only knows a job by JMM's identity_key, e.g.

    'seek:id:94548768'. JH itself stores the same job under its own
    'seek:94548768' canonical key, so a read using the JMM shape must resolve
    to the identical stored activity rather than being rejected or treated as
    a different job (JH-310 AC2/AC5)."""
    ensure_user_row("user-a", access_status=USER_ACCESS_APPROVED)
    plan_token = agent_token_store.create_agent_token(user_id="user-a", agent_id="chatgpt")
    activity_ledger.record_activity_event(
        user_id="user-a",
        job_key="seek:94548768",
        activity_type="presented",
        agent_id="job_hunter",
        source="job_hunter",
        idempotency_key="jh310-presented-1",
        occurred_at="2026-01-01T00:00:00+00:00",
    )
    with TestClient(create_app()) as client:
        response = client.get(
            "/api/activity/jobs/seek:id:94548768",
            headers={"Authorization": f"Bearer {plan_token['token']}"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["job_key"] == "seek:94548768"
    assert body["activity"]["presented_by_any_agent"] is True
    assert len(body["events"]) == 1


def test_activity_read_is_isolated_per_user(isolated_db):
    ensure_user_row("user-a", access_status=USER_ACCESS_APPROVED)
    ensure_user_row("user-b", access_status=USER_ACCESS_APPROVED)
    token_a = agent_token_store.create_agent_token(user_id="user-a", agent_id="chatgpt")
    token_b = agent_token_store.create_agent_token(user_id="user-b", agent_id="chatgpt")
    activity_ledger.record_activity_event(
        user_id="user-a",
        job_key="seek:jh310-isolation",
        activity_type="applied",
        agent_id="chatgpt",
        source="chatgpt",
        idempotency_key="jh310-isolation-1",
    )
    with TestClient(create_app()) as client:
        as_owner = client.get(
            "/api/activity/jobs/seek:jh310-isolation",
            headers={"Authorization": f"Bearer {token_a['token']}"},
        )
        as_other_user = client.get(
            "/api/activity/jobs/seek:jh310-isolation",
            headers={"Authorization": f"Bearer {token_b['token']}"},
        )
    assert as_owner.status_code == 200
    assert as_owner.json()["activity"]["applied"] is True
    assert as_other_user.status_code == 200
    assert as_other_user.json()["activity"]["applied"] is False
    assert as_other_user.json()["events"] == []


def test_activity_read_exposes_applied_hidden_rejected_state(isolated_db):
    ensure_user_row("user-a", access_status=USER_ACCESS_APPROVED)
    plan_token = agent_token_store.create_agent_token(user_id="user-a", agent_id="chatgpt")
    for job_key, activity_type in (
        ("seek:jh310-applied", "applied"),
        ("seek:jh310-hidden", "hidden"),
        ("seek:jh310-rejected", "rejected"),
    ):
        activity_ledger.record_activity_event(
            user_id="user-a",
            job_key=job_key,
            activity_type=activity_type,
            agent_id="job_hunter",
            source="job_hunter",
            idempotency_key=f"jh310-{activity_type}-1",
        )
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {plan_token['token']}"}
        applied = client.get("/api/activity/jobs/seek:jh310-applied", headers=headers)
        hidden = client.get("/api/activity/jobs/seek:jh310-hidden", headers=headers)
        rejected = client.get("/api/activity/jobs/seek:jh310-rejected", headers=headers)
    assert applied.json()["activity"]["applied"] is True
    assert hidden.json()["activity"]["hidden"] is True
    assert rejected.json()["activity"]["rejected"] is True
    assert rejected.json()["activity"]["latest_outcome"]["activity_type"] == "rejected"


def test_activity_read_is_read_only_and_writes_no_event(isolated_db):
    """Analysing or presenting a job in a standalone plan must not itself write

    JH activity (JH-310 AC6): a plain GET must leave the ledger untouched."""
    ensure_user_row("user-a", access_status=USER_ACCESS_APPROVED)
    plan_token = agent_token_store.create_agent_token(user_id="user-a", agent_id="chatgpt")
    with TestClient(create_app()) as client:
        headers = {"Authorization": f"Bearer {plan_token['token']}"}
        first = client.get("/api/activity/jobs/seek:jh310-readonly", headers=headers)
        second = client.get("/api/activity/jobs/seek:jh310-readonly", headers=headers)
    assert first.status_code == 200
    assert first.json()["activity"]["event_count"] == 0
    assert second.json()["activity"]["event_count"] == 0
    assert activity_ledger.load_activity_events("user-a") == []
