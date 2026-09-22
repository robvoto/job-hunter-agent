"""Read-only workspace view of JH-308's non-canonical history archive."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from job_hunter_agent.database import db_conn


def _runtime_application_status(outcome: object) -> str:
    value = str(outcome or "").strip().lower()
    if value == "rejected":
        return "rejection"
    if value == "applied":
        return "not_rejection"
    return value or "unknown"


def load_historical_application_evidence(
    user_id: str, *, db_path: Path | None = None
) -> list[dict[str, Any]]:
    """Load body-free historical evidence for employer/role context only.

    The archive intentionally has no job identity.  These rows are adapted to
    the existing display enrichment shape, but are never used to set current
    job activity or any job-level state.
    """
    with db_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT evidence_id, outcome, event_date, employer_raw, role_title,
                   source, evidence_ref, actor_id, thread_id, message_id,
                   source_url, source_job_id, requisition_id
              FROM historical_application_evidence
             WHERE user_id = ?
             ORDER BY event_date DESC, evidence_id DESC
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "id": str(row["evidence_id"]),
            "message_id": str(row["message_id"] or "") or None,
            "date": str(row["event_date"] or ""),
            "run_date": str(row["event_date"] or ""),
            "company": str(row["employer_raw"] or ""),
            "role": str(row["role_title"] or ""),
            "status": str(row["outcome"] or ""),
            "source": str(row["source"] or ""),
            "evidence": str(row["evidence_ref"] or ""),
            "job_key": None,
            "confidence": "low",
            "needs_review": True,
            "review_reason": "unlinked_historical_evidence",
            "raw_company": str(row["employer_raw"] or ""),
            "raw_role": str(row["role_title"] or ""),
            "subject": str(row["evidence_ref"] or ""),
            "content": str(row["evidence_ref"] or ""),
            "llm_company": str(row["employer_raw"] or ""),
            "llm_role": str(row["role_title"] or ""),
            "llm_is_rejection": str(row["outcome"] or "").strip().lower() == "rejected",
            "llm_application_status": _runtime_application_status(row["outcome"]),
            "llm_confidence": "low",
            "llm_evidence": str(row["evidence_ref"] or ""),
            "llm_needs_review": True,
            "llm_review_reason": "unlinked_historical_evidence",
            "historical_identity_evidence": {
                "source_url": str(row["source_url"] or ""),
                "source_job_id": str(row["source_job_id"] or ""),
                "requisition_id": str(row["requisition_id"] or ""),
                "actor_id": str(row["actor_id"] or ""),
                "thread_id": str(row["thread_id"] or ""),
            },
        }
        for row in rows
    ]
