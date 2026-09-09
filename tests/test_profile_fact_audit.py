"""Tests for explicit candidate-fact confirmation audit evidence."""

import json

from job_hunter_agent.database import db_conn
from job_hunter_agent.profile_fact_audit import (
    PROFILE_FACT_CONFIRMATION_EVENT,
    record_profile_fact_confirmation,
)


def test_profile_fact_confirmation_audit_records_source_evidence_and_timestamp(isolated_db):
    record_profile_fact_confirmation(
        fact="Power BI",
        requirement_type="capability",
        has_fact=False,
        source="workspace_requirement",
        action="confirm_do_not_have",
        job_key="seek:123",
        evidence="Power BI is required",
    )

    with db_conn() as conn:
        row = conn.execute(
            "SELECT event, data, created_at FROM audit_records WHERE event = ? ORDER BY id DESC LIMIT 1",
            (PROFILE_FACT_CONFIRMATION_EVENT,),
        ).fetchone()

    assert row is not None
    payload = json.loads(row["data"])
    assert payload == {
        "fact": "Power BI",
        "requirement_type": "capability",
        "has_fact": False,
        "source": "workspace_requirement",
        "action": "confirm_do_not_have",
        "job_key": "seek:123",
        "evidence": "Power BI is required",
    }
    assert row["created_at"]
