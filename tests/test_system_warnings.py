from __future__ import annotations

from job_hunter_agent.database import db_conn, init_db
from job_hunter_agent.system_warnings import (
    is_actionable_system_warning,
    list_system_warnings,
    record_system_warning,
    update_system_warning_status,
)


def test_system_warning_record_dedupes_and_preserves_review_status(tmp_path):
    db = tmp_path / "warnings.db"
    init_db(db)

    first = record_system_warning(
        severity="warning",
        category="requirement_coverage_uncertainty",
        source="fit_scoring",
        message="Requirement needs review.",
        fingerprint="fingerprint-1",
        job_key="seek:123",
        run_id="2026-07-14T00:00:00+00:00",
        context={"reason_code": "example"},
        db_path=db,
    )
    second = record_system_warning(
        severity="warning",
        category="requirement_coverage_uncertainty",
        source="fit_scoring",
        message="Requirement needs review.",
        fingerprint="fingerprint-1",
        job_key="seek:123",
        run_id="2026-07-14T00:00:00+00:00",
        context={"reason_code": "example"},
        db_path=db,
    )

    assert first["count"] == 1
    assert second["count"] == 2
    assert second["status"] == "unresolved"

    updated = update_system_warning_status(first["id"], "reviewed", db_path=db)
    assert updated["status"] == "reviewed"

    third = record_system_warning(
        severity="warning",
        category="requirement_coverage_uncertainty",
        source="fit_scoring",
        message="Requirement needs review.",
        fingerprint="fingerprint-1",
        job_key="seek:123",
        run_id="2026-07-14T00:00:00+00:00",
        context={"reason_code": "example"},
        db_path=db,
    )

    assert third["count"] == 3
    assert third["status"] == "reviewed"
    assert third["context"]["reason_code"] == "example"


def test_system_warning_listing_defaults_to_unresolved_and_hides_dismissed(tmp_path):
    db = tmp_path / "warnings.db"
    init_db(db)

    record_system_warning(
        severity="error",
        category="source_failure",
        source="seek",
        message="SEEK failed.",
        fingerprint="fingerprint-2",
        context={"error_type": "RuntimeError"},
        db_path=db,
    )
    record_system_warning(
        severity="info",
        category="preference_uncertainty",
        source="passes_preference_filters",
        message="Work mode unclear.",
        fingerprint="fingerprint-3",
        context={"reason_code": "WORK_MODE_UNCLEAR"},
        db_path=db,
    )

    warnings = list_system_warnings(db_path=db)
    assert [warning["fingerprint"] for warning in warnings] == ["fingerprint-2", "fingerprint-3"]

    dismissed = update_system_warning_status(warnings[0]["id"], "dismissed", db_path=db)
    assert dismissed["status"] == "dismissed"

    unresolved = list_system_warnings(db_path=db)
    assert [warning["fingerprint"] for warning in unresolved] == ["fingerprint-3"]


def test_system_warning_helpers_bootstrap_missing_table(tmp_path):
    db = tmp_path / "warnings.db"
    init_db(db)

    with db_conn(db) as conn:
        conn.execute("DROP TABLE system_warnings")

    created = record_system_warning(
        severity="warning",
        category="source_failure",
        source="seek",
        message="SEEK failed again.",
        fingerprint="fingerprint-bootstrap",
        db_path=db,
    )
    assert created["fingerprint"] == "fingerprint-bootstrap"

    warnings = list_system_warnings(db_path=db)
    assert [warning["fingerprint"] for warning in warnings] == ["fingerprint-bootstrap"]

    updated = update_system_warning_status(created["id"], "dismissed", db_path=db)
    assert updated["status"] == "dismissed"


def test_actionable_warning_filter_hides_diagnostics(tmp_path):
    db = tmp_path / "warnings.db"
    init_db(db)

    record_system_warning(
        severity="error",
        category="source_failure",
        source="seek",
        message="SEEK failed.",
        fingerprint="fingerprint-error",
        db_path=db,
    )
    record_system_warning(
        severity="info",
        category="preference_uncertainty",
        source="preferences",
        message="Preference is unclear.",
        fingerprint="fingerprint-info",
        db_path=db,
    )
    record_system_warning(
        severity="warning",
        category="job_identity_uncertainty",
        source="annotate_potential_duplicate_links",
        message="Potential duplicate needs review.",
        fingerprint="fingerprint-identity",
        db_path=db,
    )
    record_system_warning(
        severity="warning",
        category="llm_requirement_coverage",
        source="llm_gate",
        message="LLM mapping was downgraded.",
        fingerprint="fingerprint-llm",
        db_path=db,
    )

    warnings = list_system_warnings(db_path=db)
    actionable = [warning for warning in warnings if is_actionable_system_warning(warning)]

    assert [warning["fingerprint"] for warning in actionable] == ["fingerprint-error"]
