"""Application outcome events and the derived per-employer rollup.

Two layers, deliberately separate:

* `candidate_application_events` holds facts. Append-only, one row per observed
  outcome, each carrying `evidence_ref` back to the source record so a rollup can
  always be audited or rebuilt. Writes are idempotent on a content-derived
  `event_id`, so replaying a backfill cannot double-count.
* `candidate_employer_outcomes` holds a rollup per employer. It is a cache: drop
  it and `rebuild_employer_outcomes()` reproduces it exactly from the events.

The rollup stores counts and dates only - no thresholds, labels or verdicts. What
counts as "recent" is applied by the display layer at read time, so changing that
policy never requires a rebuild.

This module owns the event-type vocabulary. Consumers use these constants rather
than raw strings.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from job_hunter_agent.database import db_conn
from job_hunter_agent.employer_identity import resolve_employer

EVENT_APPLIED = "applied"
EVENT_REJECTED = "rejected"
EVENT_INTERVIEW = "interview"
EVENT_NO_RESPONSE = "no_response"

# GUARDRAIL: these four are the full vocabulary this ledger supports, but only
# EVENT_REJECTED currently has a producer (employer_outcome_backfill.py, fed by
# the rejection-sheet import). EVENT_APPLIED, EVENT_INTERVIEW, and
# EVENT_NO_RESPONSE are declared for a generic outcome model but nothing calls
# record_application_event() with them yet. Before wiring a display or a scoring
# signal to one of these three, confirm a real producer exists - do not assume
# a count of 0 means "checked, none found." It means "never collected."

VALID_EVENT_TYPES: frozenset[str] = frozenset(
    {EVENT_APPLIED, EVENT_REJECTED, EVENT_INTERVIEW, EVENT_NO_RESPONSE}
)

SOURCE_SEEK_APPLIED = "seek_applied"
SOURCE_GMAIL_ACK = "gmail_ack"
SOURCE_REJECTION_SHEET = "rejection_sheet"
SOURCE_DERIVED_SILENCE = "derived_silence"
# The candidate clicked a review action (Applied / Rejected / No answer)
# directly on a job card in JobHunter. This is first-party and does not need
# an LLM to interpret an email - it should be trusted over any of the sources
# above, and is the intended long-term replacement for SOURCE_REJECTION_SHEET.
SOURCE_JH_MANUAL_ACTION = "jh_manual_action"

VALID_SOURCES: frozenset[str] = frozenset(
    {
        SOURCE_SEEK_APPLIED,
        SOURCE_GMAIL_ACK,
        SOURCE_REJECTION_SHEET,
        SOURCE_DERIVED_SILENCE,
        SOURCE_JH_MANUAL_ACTION,
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_event_id(source: str, evidence_ref: str, event_type: str) -> str:
    """Content-derived identity so re-importing the same evidence is a no-op."""
    digest = hashlib.sha256(f"{source}|{evidence_ref}|{event_type}".encode("utf-8"))
    return digest.hexdigest()[:32]


def record_application_event(
    *,
    user_id: str,
    employer_raw: str,
    role_title: str,
    event_type: str,
    event_date: str,
    source: str,
    evidence_ref: str,
    confidence: str,
    data: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> str:
    """Append one outcome event. Returns its event_id.

    Rejects unknown event types and sources outright rather than storing an
    unrecognised value that later consumers would have to guess about.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"unknown event_type: {event_type!r}")
    if source not in VALID_SOURCES:
        raise ValueError(f"unknown source: {source!r}")
    if not str(evidence_ref or "").strip():
        raise ValueError("evidence_ref is required so every event stays auditable")
    if not str(event_date or "").strip():
        raise ValueError("event_date is required")

    key, display = resolve_employer(employer_raw)
    event_id = make_event_id(source, evidence_ref, event_type)

    with db_conn(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO candidate_application_events
                (user_id, event_id, employer_key, employer_raw, role_title,
                 event_type, event_date, source, evidence_ref, confidence, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                event_id,
                key,
                display,
                str(role_title or "").strip(),
                event_type,
                event_date,
                source,
                evidence_ref,
                confidence,
                json.dumps(data or {}),
            ),
        )
    return event_id


def load_application_events(
    user_id: str, *, employer_key: str | None = None, db_path: Path | None = None
) -> list[dict[str, Any]]:
    query = (
        "SELECT employer_key, employer_raw, role_title, event_type, event_date, "
        "source, evidence_ref, confidence FROM candidate_application_events WHERE user_id = ?"
    )
    params: list[Any] = [user_id]
    if employer_key is not None:
        query += " AND employer_key = ?"
        params.append(employer_key)
    query += " ORDER BY event_date DESC"

    with db_conn(db_path) as conn:
        rows = conn.execute(query, params).fetchall()

    columns = (
        "employer_key",
        "employer_raw",
        "role_title",
        "event_type",
        "event_date",
        "source",
        "evidence_ref",
        "confidence",
    )
    return [dict(zip(columns, row)) for row in rows]


def build_employer_rollup(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate one employer's events into counts and dates. Pure function."""
    ordered = sorted(events, key=lambda event: str(event.get("event_date") or ""))
    if not ordered:
        raise ValueError("cannot build a rollup from zero events")

    counts = {event_type: 0 for event_type in sorted(VALID_EVENT_TYPES)}
    roles: list[dict[str, str]] = []
    for event in ordered:
        event_type = str(event.get("event_type") or "")
        if event_type not in counts:
            raise ValueError(f"unknown event_type in stored events: {event_type!r}")
        counts[event_type] += 1
        roles.append(
            {
                "role_title": str(event.get("role_title") or ""),
                "event_type": event_type,
                "event_date": str(event.get("event_date") or ""),
            }
        )

    first = ordered[0]
    last = ordered[-1]
    return {
        "employer_key": str(first.get("employer_key") or ""),
        "employer_display": str(last.get("employer_raw") or ""),
        "counts": counts,
        "first_event_date": str(first.get("event_date") or ""),
        "last_event_date": str(last.get("event_date") or ""),
        "roles": roles,
    }


def rebuild_employer_outcomes(user_id: str, *, db_path: Path | None = None) -> int:
    """Regenerate the whole rollup for one candidate. Returns employers written."""
    events = load_application_events(user_id, db_path=db_path)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("employer_key") or ""), []).append(event)

    updated_at = _now_iso()
    with db_conn(db_path) as conn:
        conn.execute("DELETE FROM candidate_employer_outcomes WHERE user_id = ?", (user_id,))
        for key, employer_events in grouped.items():
            rollup = build_employer_rollup(employer_events)
            conn.execute(
                """
                INSERT INTO candidate_employer_outcomes (user_id, employer_key, data, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, key, json.dumps(rollup), updated_at),
            )
    return len(grouped)


def load_manual_action_job_keys(user_id: str, *, db_path: Path | None = None) -> set[str]:
    """Job keys already tracked as a first-party click (SOURCE_JH_MANUAL_ACTION).

    Used to stop the rejection-sheet import from double-counting an outcome
    you already told JobHunter about directly. Only catches sheet rows that
    carry a job_key - most historical rows do not, so this protects new
    imports going forward rather than cleaning up old duplicates.
    """
    with db_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT data FROM candidate_application_events WHERE user_id = ? AND source = ?",
            (user_id, SOURCE_JH_MANUAL_ACTION),
        ).fetchall()
    job_keys: set[str] = set()
    for (raw_data,) in rows:
        try:
            payload = json.loads(raw_data or "{}")
        except (TypeError, ValueError):
            continue
        job_key = str(payload.get("job_key") or "").strip()
        if job_key:
            job_keys.add(job_key)
    return job_keys


def get_employer_outcome(
    user_id: str, employer_raw: str, *, db_path: Path | None = None
) -> dict[str, Any] | None:
    """Return the rollup for one employer, or None when there is no history."""
    key, _display = resolve_employer(employer_raw)
    with db_conn(db_path) as conn:
        row = conn.execute(
            "SELECT data FROM candidate_employer_outcomes WHERE user_id = ? AND employer_key = ?",
            (user_id, key),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row[0])
