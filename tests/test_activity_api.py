"""HTTP contract tests for the JH-305 activity API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from job_hunter_agent import agent_token_store
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
