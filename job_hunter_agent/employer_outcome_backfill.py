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
import re
from typing import Any

from job_hunter_agent import employer_outcome_store as store

logger = logging.getLogger(__name__)

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_SLASH_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})")


def normalise_event_date(raw: str) -> str:
    """Return an ISO yyyy-mm-dd date, or "" when the value is not a date.

    The rejection sheet stores two shapes: ISO, and a slash form. The slash form
    is month-first, and that is measured rather than assumed: of the slash dates
    in the store, 154 carry a value above 12 in the second position, which is
    only possible if that position is the day. No value exceeds 12 in the first
    position, so the reading is consistent across the whole set.

    Anything that matches neither shape returns "" so the caller reports it,
    rather than being coerced into a plausible-looking wrong date.
    """
    value = str(raw or "").strip()
    if not value:
        return ""

    iso = _ISO_DATE.match(value)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"

    slash = _SLASH_DATE.match(value)
    if slash:
        month, day, year = int(slash.group(1)), int(slash.group(2)), slash.group(3)
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year}-{month:02d}-{day:02d}"
    return ""



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
    skipped_already_tracked_manually = 0

    # A job you already clicked Applied/Rejected/No Answer on in JobHunter is
    # a real, first-party fact. If the same job later shows up in the
    # rejection-sheet import too (e.g. the actual rejection email arrives
    # after you'd already marked it yourself), importing it again would count
    # the same real-world outcome twice in the employer rollup. This only
    # catches it when the sheet row has a job_key - most historical rows do
    # not, so this is a forward-looking guard, not a full duplicate cleanup.
    manually_tracked_job_keys = store.load_manual_action_job_keys(user_id, db_path=db_path)

    for row in rows:
        employer = str(row.get("company") or "").strip()
        event_date = normalise_event_date(row.get("date"))
        job_key = str(row.get("job_key") or "").strip()
        if job_key and job_key in manually_tracked_job_keys:
            skipped_already_tracked_manually += 1
            continue
        if not employer:
            skipped_no_employer += 1
            continue
        if not event_date:
            # Covers both a missing date and one in an unrecognised shape. Both
            # are reported in the summary rather than guessed at.
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
        "skipped_already_tracked_manually": skipped_already_tracked_manually,
        "employers_in_rollup": employers,
    }
    logger.info("[employer_outcome_backfill] %s", summary)
    return summary
