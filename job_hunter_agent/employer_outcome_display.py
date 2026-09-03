"""Turn an employer outcome rollup into the line shown on a job card.

Owner of the three-state contract. Every job record resolves to exactly one of:

* HISTORY     - outcomes exist with this employer; show the counts.
* NONE        - the lookup ran and found nothing; there is genuinely no history.
* UNAVAILABLE - the lookup could not run or failed; nothing is known either way.

NONE and UNAVAILABLE must never render the same way. A failed lookup that renders
as silence is indistinguishable from a clean record, and the candidate reads it as
evidence they have never applied there. That exact confusion already occurred in
July 2026, when the history lookup failed on 31 runs and every card simply showed
nothing.

This module holds no thresholds and makes no judgement about whether a history is
good or bad. It formats counts and dates; the reader decides.
"""

from __future__ import annotations

from string import Template
from typing import Any

from job_hunter_agent import employer_outcome_store as store

STATE_HISTORY = "history"
STATE_NONE = "none"
STATE_UNAVAILABLE = "unavailable"

VALID_STATES: frozenset[str] = frozenset({STATE_HISTORY, STATE_NONE, STATE_UNAVAILABLE})


def resolve_employer_outcome_state(
    rollup: dict[str, Any] | None, *, lookup_failed: bool = False
) -> dict[str, Any]:
    """Classify what is known about this employer before any rendering happens.

    Keeping this separate from formatting is what stops "we found nothing" and
    "we could not look" collapsing into the same empty render.
    """
    if lookup_failed:
        return {"state": STATE_UNAVAILABLE}
    if not rollup:
        return {"state": STATE_NONE}
    return {"state": STATE_HISTORY, "rollup": rollup}


def build_employer_outcome_check_item(
    resolved: dict[str, Any], label_lookup
) -> str:
    """Render the card line for a resolved state, or "" when there is nothing to say.

    `label_lookup(key)` returns the managed label text; the caller supplies it so
    this module does not reach into the label store itself.
    """
    state = str(resolved.get("state") or "")
    if state not in VALID_STATES:
        raise ValueError(f"unknown employer outcome state: {state!r}")

    if state == STATE_UNAVAILABLE:
        return label_lookup("employer_outcome_unavailable")

    # A card with no history says nothing here rather than adding a line to
    # almost every result. The distinction that matters is against UNAVAILABLE
    # above, which always speaks up.
    if state == STATE_NONE:
        return ""

    rollup = resolved.get("rollup") or {}
    counts = rollup.get("counts") or {}
    return Template(label_lookup("employer_outcome_history_template")).substitute(
        employer=rollup.get("employer_display") or "",
        applications=counts.get(store.EVENT_APPLIED, 0),
        rejections=counts.get(store.EVENT_REJECTED, 0),
        interviews=counts.get(store.EVENT_INTERVIEW, 0),
        no_response=counts.get(store.EVENT_NO_RESPONSE, 0),
        last_date=rollup.get("last_event_date") or "",
    )


def attach_employer_outcomes_to_records(
    records: list[dict], user_id: str, *, db_path=None
) -> list[dict]:
    """Attach the resolved employer-outcome state to every record.

    Every record gets a state, including records whose employer has no history,
    so a missing key downstream means a wiring fault rather than "no history".
    A lookup failure marks the affected records UNAVAILABLE instead of leaving
    them looking clean.
    """
    from job_hunter_agent.record_schema import RECORD_EMPLOYER_OUTCOME_KEY

    enriched: list[dict] = []
    for record in records:
        employer = str(record.get("company") or "").strip()
        if not employer:
            resolved = resolve_employer_outcome_state(None, lookup_failed=True)
        else:
            rollup = store.get_employer_outcome(user_id, employer, db_path=db_path)
            resolved = resolve_employer_outcome_state(rollup)
        enriched.append({**record, RECORD_EMPLOYER_OUTCOME_KEY: resolved})
    return enriched
