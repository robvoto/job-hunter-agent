"""Append-only audit evidence for explicit candidate fact confirmations."""

from __future__ import annotations

import json
from typing import Any

from job_hunter_agent.database import db_conn, ensure_user_row
from job_hunter_agent.paths import get_active_user_id

PROFILE_FACT_CONFIRMATION_EVENT = "profile_fact_confirmation"


def record_profile_fact_confirmation(
    *,
    fact: str,
    requirement_type: str,
    has_fact: bool,
    source: str,
    action: str,
    job_key: str = "",
    evidence: str = "",
) -> None:
    """Audit an explicit fact answer without duplicating authoritative profile state."""
    canonical_fact = " ".join(str(fact or "").split())
    if not canonical_fact:
        raise ValueError("fact is required for profile confirmation audit")
    payload: dict[str, Any] = {
        "fact": canonical_fact,
        "requirement_type": str(requirement_type or "capability").strip().lower(),
        "has_fact": bool(has_fact),
        "source": str(source or "").strip(),
        "action": str(action or "").strip(),
    }
    if job_key:
        payload["job_key"] = str(job_key).strip()
    if evidence:
        payload["evidence"] = " ".join(str(evidence).split())
    user_id = get_active_user_id()
    ensure_user_row(user_id)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO audit_records (user_id, event, data) VALUES (?, ?, ?)",
            (user_id, PROFILE_FACT_CONFIRMATION_EVENT, json.dumps(payload, ensure_ascii=False)),
        )
