"""Derived per-employer views over the canonical activity ledger."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from job_hunter_agent import activity_ledger as activity
from job_hunter_agent.database import db_conn
from job_hunter_agent.employer_identity import resolve_employer

EVENT_APPLIED = activity.ACTIVITY_APPLIED
EVENT_WITHDRAWN = activity.ACTIVITY_WITHDRAWN
EVENT_REJECTED = activity.ACTIVITY_REJECTED
EVENT_UNREJECTED = activity.ACTIVITY_UNREJECTED
EVENT_INTERVIEW = activity.ACTIVITY_INTERVIEW
EVENT_PROGRESSED = activity.ACTIVITY_PROGRESSED
EVENT_NO_RESPONSE = activity.ACTIVITY_NO_RESPONSE
EVENT_UN_NO_RESPONSE = activity.ACTIVITY_UN_NO_RESPONSE
VALID_EVENT_TYPES = frozenset(activity.OUTCOME_ACTIVITY_TYPES)

SOURCE_SEEK_APPLIED = "seek_applied"
SOURCE_GMAIL_ACK = "gmail_ack"
SOURCE_REJECTION_SHEET = activity.SOURCE_REJECTION_SHEET
SOURCE_DERIVED_SILENCE = "derived_silence"
SOURCE_JH_MANUAL_ACTION = activity.SOURCE_JOB_HUNTER
VALID_SOURCES = frozenset(
    {
        SOURCE_SEEK_APPLIED,
        SOURCE_GMAIL_ACK,
        SOURCE_REJECTION_SHEET,
        SOURCE_DERIVED_SILENCE,
        SOURCE_JH_MANUAL_ACTION,
        activity.SOURCE_CHATGPT,
        activity.SOURCE_CLAUDE,
        activity.SOURCE_MANUAL,
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def make_event_id(user_id: str, idempotency_key: str) -> str:
    return activity.make_activity_event_id(user_id, idempotency_key)


def record_application_event(
    *,
    user_id: str,
    job_key: str,
    employer_raw: str,
    role_title: str,
    event_type: str,
    event_date: str,
    source: str,
    evidence_ref: str,
    confidence: str = "",
    data: dict[str, Any] | None = None,
    agent_id: str = activity.AGENT_MANUAL,
    idempotency_key: str | None = None,
    db_path: Path | None = None,
) -> str:
    """Append one keyed outcome event; retained as the importer adapter."""
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"unknown event_type: {event_type!r}")
    if source not in VALID_SOURCES:
        raise ValueError(f"unknown source: {source!r}")
    if not str(evidence_ref or "").strip():
        raise ValueError("evidence_ref is required so every event stays auditable")
    normalized_date = str(event_date or "").strip()[:10]
    if len(normalized_date) != 10:
        raise ValueError("event_date must start with yyyy-mm-dd")
    resolve_employer(employer_raw)
    stable_key = idempotency_key or f"{source}:{evidence_ref}:{event_type}:{job_key}"
    event = activity.record_activity_event(
        user_id=user_id,
        job_key=job_key,
        activity_type=event_type,
        agent_id=agent_id,
        source=source,
        occurred_at=f"{normalized_date}T00:00:00+00:00",
        evidence_ref=evidence_ref,
        idempotency_key=stable_key,
        metadata={**(data or {}), "confidence": str(confidence or "")},
        employer_raw=employer_raw,
        role_title=role_title,
        db_path=db_path,
    )
    return str(event["event_id"])


def load_application_events(
    user_id: str, *, employer_key: str | None = None, db_path: Path | None = None
) -> list[dict[str, Any]]:
    """Load canonical outcome events in the rollup's established shape."""
    events = activity.load_activity_events(
        user_id, activity_types=VALID_EVENT_TYPES, db_path=db_path
    )
    if employer_key is not None:
        events = [event for event in events if event.get("employer_key") == employer_key]
    return [
        {
            "employer_key": str(event.get("employer_key") or ""),
            "employer_raw": str(event.get("employer_raw") or ""),
            "role_title": str(event.get("role_title") or ""),
            "event_type": str(event.get("activity_type") or ""),
            "event_date": str(event.get("occurred_at") or "")[:10],
            "occurred_at": str(event.get("occurred_at") or ""),
            "source": str(event.get("source") or ""),
            "evidence_ref": str(event.get("evidence_ref") or ""),
            "confidence": str((event.get("metadata") or {}).get("confidence") or ""),
            "event_id": str(event.get("event_id") or ""),
        }
        for event in reversed(events)
    ]


def build_employer_rollup(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        events,
        key=lambda event: (
            str(event.get("occurred_at") or event.get("event_date") or ""),
            str(event.get("event_id") or ""),
        ),
    )
    if not ordered:
        raise ValueError("cannot build a rollup from zero events")
    counts = {event_type: 0 for event_type in sorted(VALID_EVENT_TYPES)}
    roles: list[dict[str, str]] = []
    for event in ordered:
        event_type = str(event.get("event_type") or "")
        if event_type not in counts:
            raise ValueError(f"unknown event_type in stored events: {event_type!r}")
        event_date = str(event.get("event_date") or event.get("occurred_at") or "")[:10]
        counts[event_type] += 1
        roles.append(
            {
                "role_title": str(event.get("role_title") or ""),
                "event_type": event_type,
                "event_date": event_date,
            }
        )
    first, last = ordered[0], ordered[-1]
    return {
        "employer_key": str(first.get("employer_key") or ""),
        "employer_display": str(last.get("employer_raw") or ""),
        "counts": counts,
        "first_event_date": str(first.get("event_date") or first.get("occurred_at") or "")[:10],
        "last_event_date": str(last.get("event_date") or last.get("occurred_at") or "")[:10],
        "roles": roles,
    }


def rebuild_employer_outcomes(user_id: str, *, db_path: Path | None = None) -> int:
    events = load_application_events(user_id, db_path=db_path)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("employer_key") or ""), []).append(event)
    with db_conn(db_path) as conn:
        conn.execute("DELETE FROM candidate_employer_outcomes WHERE user_id = ?", (user_id,))
        for key, employer_events in grouped.items():
            conn.execute(
                "INSERT INTO candidate_employer_outcomes (user_id, employer_key, data, updated_at) VALUES (?, ?, ?, ?)",
                (user_id, key, json.dumps(build_employer_rollup(employer_events)), _now_iso()),
            )
    return len(grouped)


def load_manual_action_job_keys(user_id: str, *, db_path: Path | None = None) -> set[str]:
    events = activity.load_activity_events(
        user_id,
        activity_types=activity.OUTCOME_ACTIVITY_TYPES,
        agent_id=activity.AGENT_JOB_HUNTER,
        db_path=db_path,
    )
    return {str(event["job_key"]) for event in events if event.get("job_key")}


def get_employer_outcome(
    user_id: str, employer_raw: str, *, db_path: Path | None = None
) -> dict[str, Any] | None:
    key, _display = resolve_employer(employer_raw)
    return get_employer_outcome_by_key(user_id, key, db_path=db_path)


def get_employer_outcome_by_key(
    user_id: str, employer_key: str, *, db_path: Path | None = None
) -> dict[str, Any] | None:
    with db_conn(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM candidate_employer_outcomes WHERE user_id = ? AND employer_key = ?",
            (user_id, employer_key),
        ).fetchone()
    return json.loads(row["data"]) if row is not None else None
