"""Canonical per-user job activity ledger.

This is the single personal activity owner for Job Hunter.  Job identity is
always the current ``source:id`` contract owned by ``job_identity``; the
ledger never accepts a caller-supplied user id and never infers identity from
an arbitrary URL or display text.

Events are append-only.  Reversible state is represented by explicit paired
events, and current state is derived by UTC ``occurred_at`` followed by the
stable event id.  ``job_history`` and profile review lists are projections for
existing workspace consumers, not a second activity authority.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from job_hunter_agent.database import db_conn, ensure_user_row
from job_hunter_agent.job_identity import normalize_job_key

AGENT_JOB_HUNTER = "job_hunter"
AGENT_CHATGPT = "chatgpt"
AGENT_CLAUDE = "claude"
AGENT_MANUAL = "manual"
MANAGED_AGENT_IDS: frozenset[str] = frozenset(
    {AGENT_JOB_HUNTER, AGENT_CHATGPT, AGENT_CLAUDE, AGENT_MANUAL}
)

SOURCE_JOB_HUNTER = "job_hunter"
SOURCE_CHATGPT = "chatgpt"
SOURCE_CLAUDE = "claude"
SOURCE_MANUAL = "manual"
SOURCE_GMAIL = "gmail"
SOURCE_REJECTION_SHEET = "rejection_sheet"
SOURCE_SEEK_APPLIED = "seek_applied"
SOURCE_GMAIL_ACK = "gmail_ack"
SOURCE_DERIVED_SILENCE = "derived_silence"
VALID_ACTIVITY_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_JOB_HUNTER,
        SOURCE_CHATGPT,
        SOURCE_CLAUDE,
        SOURCE_MANUAL,
        SOURCE_GMAIL,
        SOURCE_REJECTION_SHEET,
        SOURCE_SEEK_APPLIED,
        SOURCE_GMAIL_ACK,
        SOURCE_DERIVED_SILENCE,
    }
)

ACTIVITY_PRESENTED = "presented"
ACTIVITY_VIEWED = "viewed"
ACTIVITY_LIKED = "liked"
ACTIVITY_UNLIKED = "unliked"
ACTIVITY_HIDDEN = "hidden"
ACTIVITY_UNHIDDEN = "unhidden"
ACTIVITY_APPLIED = "applied"
ACTIVITY_WITHDRAWN = "withdrawn"
ACTIVITY_REJECTED = "rejected"
ACTIVITY_UNREJECTED = "unrejected"
ACTIVITY_INTERVIEW = "interview"
ACTIVITY_PROGRESSED = "progressed"
ACTIVITY_NO_RESPONSE = "no_response"
ACTIVITY_UN_NO_RESPONSE = "un_no_response"

VALID_ACTIVITY_TYPES: frozenset[str] = frozenset(
    {
        ACTIVITY_PRESENTED,
        ACTIVITY_VIEWED,
        ACTIVITY_LIKED,
        ACTIVITY_UNLIKED,
        ACTIVITY_HIDDEN,
        ACTIVITY_UNHIDDEN,
        ACTIVITY_APPLIED,
        ACTIVITY_WITHDRAWN,
        ACTIVITY_REJECTED,
        ACTIVITY_UNREJECTED,
        ACTIVITY_INTERVIEW,
        ACTIVITY_PROGRESSED,
        ACTIVITY_NO_RESPONSE,
        ACTIVITY_UN_NO_RESPONSE,
    }
)

OUTCOME_ACTIVITY_TYPES: frozenset[str] = frozenset(
    {
        ACTIVITY_APPLIED,
        ACTIVITY_WITHDRAWN,
        ACTIVITY_REJECTED,
        ACTIVITY_UNREJECTED,
        ACTIVITY_INTERVIEW,
        ACTIVITY_PROGRESSED,
        ACTIVITY_NO_RESPONSE,
        ACTIVITY_UN_NO_RESPONSE,
    }
)

_PAIR_TYPES: dict[str, tuple[str, str]] = {
    "liked": (ACTIVITY_LIKED, ACTIVITY_UNLIKED),
    "hidden": (ACTIVITY_HIDDEN, ACTIVITY_UNHIDDEN),
    "applied": (ACTIVITY_APPLIED, ACTIVITY_WITHDRAWN),
    "rejected": (ACTIVITY_REJECTED, ACTIVITY_UNREJECTED),
    "no_response": (ACTIVITY_NO_RESPONSE, ACTIVITY_UN_NO_RESPONSE),
}


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def normalize_occurred_at(value: str | None) -> str:
    """Require a timezone-aware timestamp and normalise it to UTC.

    Activity ordering is a business contract, so naive timestamps are rejected
    rather than interpreted using the server's local timezone.
    """
    raw = str(value or "").strip()
    if not raw:
        return now_utc_iso()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("occurred_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("occurred_at must include a timezone offset")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def validate_agent_id(value: str) -> str:
    agent_id = str(value or "").strip().lower()
    if agent_id not in MANAGED_AGENT_IDS:
        raise ValueError(f"Unsupported agent_id: {agent_id!r}")
    return agent_id


def validate_activity_type(value: str) -> str:
    activity_type = str(value or "").strip().lower()
    if activity_type not in VALID_ACTIVITY_TYPES:
        raise ValueError(f"Unsupported activity_type: {activity_type!r}")
    return activity_type


def _required_text(value: str, field: str, *, max_length: int = 512) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    if len(cleaned) > max_length:
        raise ValueError(f"{field} exceeds the maximum length of {max_length}")
    return cleaned


def _optional_text(value: str | None, field: str, *, max_length: int = 512) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) > max_length:
        raise ValueError(f"{field} exceeds the maximum length of {max_length}")
    return cleaned


def make_activity_event_id(user_id: str, idempotency_key: str) -> str:
    user = _required_text(user_id, "user_id", max_length=128)
    key = _required_text(idempotency_key, "idempotency_key", max_length=512)
    return hashlib.sha256(f"{user}|{key}".encode("utf-8")).hexdigest()[:32]


def _decode_row(row: Any) -> dict[str, Any]:
    event = {key: row[key] for key in row.keys()}
    raw_metadata = event.pop("metadata", "{}")
    try:
        metadata = json.loads(raw_metadata or "{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("Stored activity metadata is not valid JSON") from exc
    if not isinstance(metadata, dict):
        raise ValueError("Stored activity metadata must be an object")
    event["metadata"] = metadata
    return event


def _normalise_event_input(
    *,
    user_id: str,
    job_key: str,
    activity_type: str,
    agent_id: str,
    occurred_at: str | None,
    source: str,
    evidence_ref: str | None,
    idempotency_key: str,
    metadata: dict[str, Any] | None,
    employer_raw: str | None,
    role_title: str | None,
) -> dict[str, Any]:
    normalized_job_key = normalize_job_key(_required_text(job_key, "job_key"))
    if not normalized_job_key:
        raise ValueError("job_key must use the canonical source:id identity")
    user = _required_text(user_id, "user_id", max_length=128)
    normalized_metadata = metadata if isinstance(metadata, dict) else None
    if metadata is not None and normalized_metadata is None:
        raise ValueError("metadata must be an object")
    return {
        "user_id": user,
        "event_id": make_activity_event_id(user, idempotency_key),
        "job_key": normalized_job_key,
        "activity_type": validate_activity_type(activity_type),
        "agent_id": validate_agent_id(agent_id),
        "occurred_at": normalize_occurred_at(occurred_at),
        "source": _validate_source(source),
        "evidence_ref": _optional_text(evidence_ref, "evidence_ref", max_length=1024),
        "idempotency_key": _required_text(idempotency_key, "idempotency_key", max_length=512),
        "metadata": normalized_metadata or {},
        "employer_raw": _optional_text(employer_raw, "employer_raw", max_length=256),
        "role_title": _optional_text(role_title, "role_title", max_length=256),
}


def _validate_source(value: str) -> str:
    source = _required_text(value, "source", max_length=128).lower()
    if source not in VALID_ACTIVITY_SOURCES:
        raise ValueError(f"Unsupported activity source: {source!r}")
    return source


def _events_for_job(conn, user_id: str, job_key: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT user_id, event_id, job_key, activity_type, agent_id, occurred_at, source,
               evidence_ref, idempotency_key, metadata, employer_key, employer_raw,
               role_title, created_at
          FROM job_activity_events
         WHERE user_id = ? AND job_key = ?
         ORDER BY occurred_at ASC, event_id ASC
        """,
        (user_id, job_key),
    ).fetchall()
    return [_decode_row(row) for row in rows]


def _latest_pair_state(events: list[dict[str, Any]], pair: tuple[str, str]) -> dict[str, Any] | None:
    matching = [event for event in events if event["activity_type"] in pair]
    return matching[-1] if matching else None


def build_activity_state(
    events: Iterable[dict[str, Any]], *, agent_id: str | None = None
) -> dict[str, Any]:
    ordered = sorted(
        (dict(event) for event in events),
        key=lambda event: (str(event.get("occurred_at") or ""), str(event.get("event_id") or "")),
    )
    presented_events = [event for event in ordered if event.get("activity_type") == ACTIVITY_PRESENTED]
    viewed_events = [event for event in ordered if event.get("activity_type") == ACTIVITY_VIEWED]
    latest_pairs = {
        name: _latest_pair_state(ordered, pair) for name, pair in _PAIR_TYPES.items()
    }

    def pair_active(name: str) -> bool:
        latest = latest_pairs[name]
        return bool(latest and latest["activity_type"] == _PAIR_TYPES[name][0])

    presented_by = []
    seen_agents: set[str] = set()
    for event in reversed(presented_events):
        current_agent = str(event.get("agent_id") or "")
        if current_agent and current_agent not in seen_agents:
            seen_agents.add(current_agent)
            presented_by.append(
                {
                    "agent_id": current_agent,
                    "occurred_at": event.get("occurred_at"),
                    "evidence_ref": event.get("evidence_ref") or "",
                }
            )
    outcomes = [event for event in ordered if event.get("activity_type") in OUTCOME_ACTIVITY_TYPES]
    latest_outcome = outcomes[-1] if outcomes else None

    # A job has one current application disposition.  The ledger keeps the
    # chronological applied/rejected events as evidence, but the projected
    # current state must never be both applied and rejected.  If both positive
    # pairs are active, the later event wins (for example applied -> rejected
    # becomes rejected; rejected -> applied becomes applied).
    applied_active = pair_active("applied")
    rejected_active = pair_active("rejected")
    if applied_active and rejected_active:
        applied_event = latest_pairs["applied"]
        rejected_event = latest_pairs["rejected"]
        applied_key = (
            str((applied_event or {}).get("occurred_at") or ""),
            str((applied_event or {}).get("event_id") or ""),
        )
        rejected_key = (
            str((rejected_event or {}).get("occurred_at") or ""),
            str((rejected_event or {}).get("event_id") or ""),
        )
        if rejected_key >= applied_key:
            applied_active = False
        else:
            rejected_active = False

    selected_agent = validate_agent_id(agent_id) if agent_id else None
    return {
        "presented": bool(presented_events),
        "presented_by_any_agent": bool(presented_events),
        "presented_by_agent": bool(
            selected_agent
            and any(event.get("agent_id") == selected_agent for event in presented_events)
        ),
        "presented_by": presented_by,
        "viewed": bool(viewed_events),
        "viewed_count": len(viewed_events),
        "liked": pair_active("liked"),
        "hidden": pair_active("hidden"),
        "applied": applied_active,
        "rejected": rejected_active,
        "no_response": pair_active("no_response"),
        "interview": any(event.get("activity_type") == ACTIVITY_INTERVIEW for event in ordered),
        "progressed": any(event.get("activity_type") == ACTIVITY_PROGRESSED for event in ordered),
        "latest_outcome": dict(latest_outcome) if latest_outcome else None,
        "event_count": len(ordered),
    }


def _project_user_state(conn, event: dict[str, Any]) -> None:
    """Project current ledger state to existing workspace/profile consumers."""
    from job_hunter_agent.record_schema import (
        RECORD_FIRST_APPLIED_AT_KEY,
        RECORD_FIRST_HIDDEN_AT_KEY,
        RECORD_FIRST_LIKED_AT_KEY,
        RECORD_FIRST_NO_RESPONSE_AT_KEY,
        RECORD_FIRST_REJECTED_AT_KEY,
        RECORD_FIRST_VIEWED_AT_KEY,
        RECORD_IS_HIDDEN_KEY,
        RECORD_IS_LIKED_KEY,
        RECORD_JOB_KEY,
        RECORD_LAST_APPLIED_AT_KEY,
        RECORD_LAST_HIDDEN_AT_KEY,
        RECORD_LAST_LIKED_AT_KEY,
        RECORD_LAST_NO_RESPONSE_AT_KEY,
        RECORD_LAST_REJECTED_AT_KEY,
        RECORD_LAST_UN_NO_RESPONSE_AT_KEY,
        RECORD_LAST_UNAPPLIED_AT_KEY,
        RECORD_LAST_UNHIDDEN_AT_KEY,
        RECORD_LAST_UNLIKED_AT_KEY,
        RECORD_LAST_UNREJECTED_AT_KEY,
        RECORD_LAST_VIEWED_AT_KEY,
        RECORD_TIMES_VIEWED_KEY,
    )

    user_id = event["user_id"]
    job_key = event["job_key"]
    events = _events_for_job(conn, user_id, job_key)
    state = build_activity_state(events)
    existing_row = conn.execute(
        "SELECT data FROM job_history WHERE user_id = ? AND job_key = ?",
        (user_id, job_key),
    ).fetchone()
    history = json.loads(existing_row["data"] or "{}") if existing_row else {}
    if not isinstance(history, dict):
        history = {}
    history[RECORD_JOB_KEY] = job_key
    if event.get("employer_raw") and not history.get("company"):
        history["company"] = event["employer_raw"]
    if event.get("role_title") and not history.get("title"):
        history["title"] = event["role_title"]
    activity_events = {
        item["activity_type"]: item
        for item in events
        if item["activity_type"] in VALID_ACTIVITY_TYPES
    }
    history[RECORD_IS_LIKED_KEY] = state["liked"]
    history[RECORD_IS_HIDDEN_KEY] = state["hidden"]
    history[RECORD_TIMES_VIEWED_KEY] = max(
        int(history.get(RECORD_TIMES_VIEWED_KEY, 0) or 0), state["viewed_count"]
    )
    for positive, first_key, last_key in (
        (ACTIVITY_LIKED, RECORD_FIRST_LIKED_AT_KEY, RECORD_LAST_LIKED_AT_KEY),
        (ACTIVITY_HIDDEN, RECORD_FIRST_HIDDEN_AT_KEY, RECORD_LAST_HIDDEN_AT_KEY),
        (ACTIVITY_APPLIED, RECORD_FIRST_APPLIED_AT_KEY, RECORD_LAST_APPLIED_AT_KEY),
        (ACTIVITY_REJECTED, RECORD_FIRST_REJECTED_AT_KEY, RECORD_LAST_REJECTED_AT_KEY),
        (ACTIVITY_NO_RESPONSE, RECORD_FIRST_NO_RESPONSE_AT_KEY, RECORD_LAST_NO_RESPONSE_AT_KEY),
        (ACTIVITY_VIEWED, RECORD_FIRST_VIEWED_AT_KEY, RECORD_LAST_VIEWED_AT_KEY),
    ):
        positive_events = [item for item in events if item["activity_type"] == positive]
        if positive_events:
            history[first_key] = positive_events[0]["occurred_at"]
            history[last_key] = positive_events[-1]["occurred_at"]
    for activity_type, field in (
        (ACTIVITY_UNLIKED, RECORD_LAST_UNLIKED_AT_KEY),
        (ACTIVITY_UNHIDDEN, RECORD_LAST_UNHIDDEN_AT_KEY),
        (ACTIVITY_WITHDRAWN, RECORD_LAST_UNAPPLIED_AT_KEY),
        (ACTIVITY_UNREJECTED, RECORD_LAST_UNREJECTED_AT_KEY),
        (ACTIVITY_UN_NO_RESPONSE, RECORD_LAST_UN_NO_RESPONSE_AT_KEY),
    ):
        if activity_type in activity_events:
            history[field] = activity_events[activity_type]["occurred_at"]

    source, platform_id = job_key.split(":", 1)
    source = source.strip().lower()
    platform_id = platform_id.strip()
    if existing_row:
        conn.execute(
            "UPDATE job_history SET data = ?, source = ?, platform_id = ?, title = ?, company = ? WHERE user_id = ? AND job_key = ?",
            (
                json.dumps(history, ensure_ascii=False),
                source,
                platform_id,
                str(history.get("title") or ""),
                str(history.get("company") or ""),
                user_id,
                job_key,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO job_history
                (user_id, job_key, source, platform_id, title, company, state, data)
            VALUES (?, ?, ?, ?, ?, ?, 'seen', ?)
            """,
            (
                user_id,
                job_key,
                source,
                platform_id,
                str(history.get("title") or ""),
                str(history.get("company") or ""),
                json.dumps(history, ensure_ascii=False),
            ),
        )

    profile_row = conn.execute(
        "SELECT data FROM user_profile WHERE user_id = ?", (user_id,)
    ).fetchone()
    if profile_row is None:
        return
    try:
        profile = json.loads(profile_row["data"] or "{}")
    except (TypeError, ValueError):
        profile = {}
    if not isinstance(profile, dict):
        profile = {}
    controls = profile.setdefault("review_controls", {})
    state_lists = {
        "liked_job_keys": state["liked"],
        "hidden_job_keys": state["hidden"],
        "applied_job_keys": state["applied"],
        "rejected_job_keys": state["rejected"],
        "no_response_job_keys": state["no_response"],
    }
    for list_name, active in state_lists.items():
        values = [str(value) for value in controls.get(list_name, []) if str(value).strip()]
        values = [value for value in values if value != job_key]
        if active:
            values.append(job_key)
        controls[list_name] = values
    conn.execute(
        """
        INSERT INTO user_profile (user_id, data, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at
        """,
        (user_id, json.dumps(profile, ensure_ascii=False)),
    )


def record_activity_event(
    *,
    user_id: str,
    job_key: str,
    activity_type: str,
    agent_id: str,
    source: str,
    idempotency_key: str,
    occurred_at: str | None = None,
    evidence_ref: str | None = None,
    metadata: dict[str, Any] | None = None,
    employer_raw: str | None = None,
    role_title: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    event = _normalise_event_input(
        user_id=user_id,
        job_key=job_key,
        activity_type=activity_type,
        agent_id=agent_id,
        occurred_at=occurred_at,
        source=source,
        evidence_ref=evidence_ref,
        idempotency_key=idempotency_key,
        metadata=metadata,
        employer_raw=employer_raw,
        role_title=role_title,
    )
    ensure_user_row(event["user_id"], db_path=db_path)
    employer_key = ""
    if event["employer_raw"]:
        from job_hunter_agent.employer_identity import resolve_employer

        employer_key, _display = resolve_employer(event["employer_raw"])
    with db_conn(db_path) as conn:
        existing = conn.execute(
            """
            SELECT user_id, event_id, job_key, activity_type, agent_id, occurred_at, source,
                   evidence_ref, idempotency_key, metadata, employer_key, employer_raw,
                   role_title, created_at
              FROM job_activity_events
             WHERE user_id = ? AND idempotency_key = ?
            """,
            (event["user_id"], event["idempotency_key"]),
        ).fetchone()
        if existing:
            stored = _decode_row(existing)
            if any(stored.get(key) != event.get(key) for key in ("job_key", "activity_type", "agent_id")):
                raise ValueError("idempotency_key was already used for a different activity")
            return stored
        conn.execute(
            """
            INSERT INTO job_activity_events
                (user_id, event_id, job_key, activity_type, agent_id, occurred_at,
                 source, evidence_ref, idempotency_key, metadata, employer_key,
                 employer_raw, role_title)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["user_id"],
                event["event_id"],
                event["job_key"],
                event["activity_type"],
                event["agent_id"],
                event["occurred_at"],
                event["source"],
                event["evidence_ref"],
                event["idempotency_key"],
                json.dumps(event["metadata"], ensure_ascii=False, sort_keys=True),
                employer_key,
                event["employer_raw"],
                event["role_title"],
            ),
        )
        row = conn.execute(
            """
            SELECT user_id, event_id, job_key, activity_type, agent_id, occurred_at, source,
                   evidence_ref, idempotency_key, metadata, employer_key, employer_raw,
                   role_title, created_at
              FROM job_activity_events
             WHERE user_id = ? AND event_id = ?
            """,
            (event["user_id"], event["event_id"]),
        ).fetchone()
        if row is None:
            raise RuntimeError("Activity event was not persisted")
        stored = _decode_row(row)
        # A presentation is telemetry only. It belongs in the canonical ledger,
        # but it does not change any workspace/profile state and must not create
        # a legacy job_history projection row. Avoiding that redundant projection
        # also keeps the lightweight card-presentation write fast during page load.
        if stored["activity_type"] != ACTIVITY_PRESENTED:
            _project_user_state(conn, stored)
    if event["activity_type"] in OUTCOME_ACTIVITY_TYPES:
        from job_hunter_agent.employer_outcome_store import rebuild_employer_outcomes

        rebuild_employer_outcomes(event["user_id"], db_path=db_path)
    return stored


def load_activity_events(
    user_id: str,
    *,
    job_key: str | None = None,
    activity_types: Iterable[str] | None = None,
    agent_id: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    user = _required_text(user_id, "user_id", max_length=128)
    query = """
        SELECT user_id, event_id, job_key, activity_type, agent_id, occurred_at, source,
               evidence_ref, idempotency_key, metadata, employer_key, employer_raw,
               role_title, created_at
          FROM job_activity_events
         WHERE user_id = ?
    """
    params: list[Any] = [user]
    if job_key is not None:
        normalized_job_key = normalize_job_key(_required_text(job_key, "job_key"))
        if not normalized_job_key:
            raise ValueError("job_key must use the canonical source:id identity")
        query += " AND job_key = ?"
        params.append(normalized_job_key)
    if activity_types is not None:
        normalized_types = [validate_activity_type(value) for value in activity_types]
        if not normalized_types:
            return []
        placeholders = ", ".join("?" for _ in normalized_types)
        query += f" AND activity_type IN ({placeholders})"
        params.extend(normalized_types)
    if agent_id is not None:
        query += " AND agent_id = ?"
        params.append(validate_agent_id(agent_id))
    query += " ORDER BY occurred_at ASC, event_id ASC"
    with db_conn(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [_decode_row(row) for row in rows]


def load_job_activity(
    user_id: str,
    job_key: str,
    *,
    agent_id: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    events = load_activity_events(user_id, job_key=job_key, db_path=db_path)
    return {
        "job_key": normalize_job_key(job_key),
        "activity": build_activity_state(events, agent_id=agent_id),
        "events": events,
    }
