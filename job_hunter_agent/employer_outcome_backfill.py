"""Populate the outcome ledger from evidence the application already holds.

Reads the candidate rejection history that `candidate_application_history`
already maintains and replays it as ledger events, then rebuilds the rollup.

Safe to run repeatedly: events are keyed on the source record's identity, so a
second run writes nothing new.

Rows that cannot be attributed to an employer are counted and reported, never
silently dropped and never guessed at.
"""

from __future__ import annotations

import logging
from typing import Any

from job_hunter_agent import employer_outcome_store as store

logger = logging.getLogger(__name__)


def _default_history_loader() -> list[dict]:
    # Imported lazily: candidate_application_history pulls in the LLM gate, which
    # requires a seeded knowledge table just to import.
    from job_hunter_agent.candidate_application_history import (
        load_candidate_job_rejection_history,
    )

    return load_candidate_job_rejection_history()


def backfill_from_rejection_history(
    user_id: str, *, db_path=None, load_history=None
) -> dict[str, Any]:
    """Import known rejections into the ledger and rebuild the rollup.

    `load_history` is an injection seam for tests; production always uses the
    candidate rejection history the application already maintains.
    """
    rows = (load_history or _default_history_loader)()
    imported = 0
    skipped_no_employer = 0
    skipped_no_date = 0

    for row in rows:
        employer = str(row.get("company") or "").strip()
        event_date = str(row.get("date") or "").strip()
        if not employer:
            skipped_no_employer += 1
            continue
        if not event_date:
            skipped_no_date += 1
            continue

        store.record_application_event(
            user_id=user_id,
            employer_raw=employer,
            role_title=str(row.get("role") or ""),
            event_type=store.EVENT_REJECTED,
            event_date=event_date,
            source=store.SOURCE_REJECTION_SHEET,
            evidence_ref=str(row.get("message_id") or row.get("id") or ""),
            confidence=str(row.get("confidence") or ""),
            data={"evidence": row.get("evidence"), "job_key": row.get("job_key")},
            db_path=db_path,
        )
        imported += 1

    employers = store.rebuild_employer_outcomes(user_id, db_path=db_path)
    summary = {
        "rows_read": len(rows),
        "events_imported": imported,
        "skipped_no_employer": skipped_no_employer,
        "skipped_no_date": skipped_no_date,
        "employers_in_rollup": employers,
    }
    logger.info("[employer_outcome_backfill] %s", summary)
    return summary
