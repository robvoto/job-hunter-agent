"""Canonical per-user activity and external-agent token API."""

from __future__ import annotations

from fastapi import APIRouter, Body, Query, Request

from job_hunter_agent import activity_ledger
from job_hunter_agent.agent_token_store import (
    consume_activity_write,
    create_agent_token,
    list_agent_tokens,
    revoke_agent_token,
)
from job_hunter_agent.auth import read_activity_user, read_session_user
from job_hunter_agent.config import USER_ACCESS_APPROVED
from job_hunter_agent.employer_outcome_store import get_employer_outcome_by_key
from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.workspace_refresh_service import rebuild_workspace_after_rule_change

router = APIRouter()


def _activity_user(request: Request) -> dict:
    user = read_activity_user(request)
    if user is None:
        raise ValueError("Authentication required")
    if str(user.get("access_status") or "").strip().lower() != USER_ACCESS_APPROVED:
        raise ValueError("User access is not approved")
    return user


def _reject_user_id(body: dict) -> None:
    if "user_id" in body:
        raise ValueError("user_id is derived from authentication and must not be supplied")


@router.post("/api/agent-tokens")
def api_agent_token_create(request: Request, body: dict = Body(...)):  # type: ignore[no-untyped-def]
    user = read_session_user(request)
    if user is None:
        return json_response({"error": "Authenticated dashboard session required"}, 401)
    try:
        _reject_user_id(body)
        token = create_agent_token(
            user_id=str(user["user_id"]),
            agent_id=str(body.get("agent_id") or ""),
            label=str(body.get("label") or ""),
            expires_at=body.get("expires_at"),
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"ok": True, **token})


@router.get("/api/agent-tokens")
def api_agent_token_list(request: Request):  # type: ignore[no-untyped-def]
    user = read_session_user(request)
    if user is None:
        return json_response({"error": "Authenticated dashboard session required"}, 401)
    return json_response({"tokens": list_agent_tokens(str(user["user_id"]))})


@router.delete("/api/agent-tokens/{token_id}")
def api_agent_token_revoke(request: Request, token_id: str):  # type: ignore[no-untyped-def]
    user = read_session_user(request)
    if user is None:
        return json_response({"error": "Authenticated dashboard session required"}, 401)
    revoked = revoke_agent_token(str(user["user_id"]), token_id)
    if not revoked:
        return json_response({"error": "Token not found or already revoked"}, 404)
    return json_response({"ok": True, "token_id": token_id, "revoked": True})


@router.post("/api/activity/events")
def api_activity_event(
    request: Request, body: dict = Body(...)
):  # type: ignore[no-untyped-def]
    try:
        user = _activity_user(request)
        _reject_user_id(body)
        authenticated_agent = activity_ledger.validate_agent_id(str(user.get("agent_id") or ""))
        requested_agent = str(body.get("agent_id") or authenticated_agent)
        agent_id = activity_ledger.validate_agent_id(requested_agent)
        if agent_id != authenticated_agent:
            raise ValueError("agent_id does not match the authenticated agent")
        if str(user.get("auth_method") or "") == "agent_token":
            allowed, retry_after = consume_activity_write(str(user["token_id"]))
            if not allowed:
                return json_response(
                    {"error": "Activity write rate limit exceeded", "retry_after_seconds": retry_after},
                    429,
                )
        idempotency_key = str(
            request.headers.get("idempotency-key") or body.get("idempotency_key") or ""
        ).strip()
        metadata = body.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")
        event = activity_ledger.record_activity_event(
            user_id=str(user["user_id"]),
            job_key=str(body.get("job_key") or ""),
            activity_type=str(body.get("activity_type") or ""),
            agent_id=agent_id,
            source=str(body.get("source") or ""),
            occurred_at=body.get("occurred_at"),
            evidence_ref=body.get("evidence_ref"),
            idempotency_key=idempotency_key,
            metadata=metadata,
            employer_raw=body.get("employer_raw") or body.get("company"),
            role_title=body.get("role_title") or body.get("title"),
        )
        current = activity_ledger.load_job_activity(
            str(user["user_id"]), str(event["job_key"]), agent_id=agent_id
        )
        refresh_id = None
        if event["activity_type"] not in {
            activity_ledger.ACTIVITY_PRESENTED,
            activity_ledger.ACTIVITY_VIEWED,
        }:
            refresh_id = rebuild_workspace_after_rule_change("external activity event saved")
    except ValueError as exc:
        return json_response({"error": str(exc)}, 400)
    except Exception as exc:
        return json_response({"error": str(exc)}, 500)
    return json_response(
        {"ok": True, "event": event, "activity": current["activity"], "workspace_refresh_id": refresh_id}
    )


@router.get("/api/activity/jobs/{job_key}")
def api_activity_job(
    request: Request,
    job_key: str,
    agent_id: str | None = Query(None),
):  # type: ignore[no-untyped-def]
    try:
        user = _activity_user(request)
        if agent_id:
            activity_ledger.validate_agent_id(agent_id)
        result = activity_ledger.load_job_activity(
            str(user["user_id"]), job_key, agent_id=agent_id
        )
    except ValueError as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(result)


@router.get("/api/activity/employers/{employer_key}")
def api_activity_employer(request: Request, employer_key: str):  # type: ignore[no-untyped-def]
    try:
        user = _activity_user(request)
    except ValueError as exc:
        return json_response({"error": str(exc)}, 401)
    outcome = get_employer_outcome_by_key(str(user["user_id"]), employer_key)
    if outcome is None:
        return json_response({"error": "Employer activity was not found"}, 404)
    return json_response(outcome)
