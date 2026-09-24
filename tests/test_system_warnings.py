from __future__ import annotations

from job_hunter_agent import preferences
from job_hunter_agent.database import db_conn, init_db
from job_hunter_agent.system_warnings import (
    aggregate_system_warning_diagnostics,
    is_actionable_system_warning,
    list_system_warnings,
    record_system_warning,
    system_warning_operator_action,
    update_system_warning_status,
)


def test_system_warning_record_dedupes_and_reopens_when_fault_recurs(tmp_path):
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
    assert third["status"] == "unresolved"
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
        severity="warning",
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
        severity="warning",
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


def test_preference_work_mode_uncertainty_keeps_production_shape_and_passes_filter(monkeypatch):
    recorded = []
    monkeypatch.setattr(preferences, "append_uncertainty_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        preferences,
        "record_system_warning",
        lambda **kwargs: recorded.append(kwargs) or kwargs,
    )

    ok, reason = preferences.passes_preference_filters(
        {"job_key": "seek:work-mode", "work_type": "Permanent", "work_mode": ""},
        {"match_preferences": {"work_mode_preference": ["remote"]}},
    )

    assert (ok, reason) == (True, "OK")
    warning = next(
        item for item in recorded if item["context"]["reason_code"] == "WORK_MODE_UNCLEAR"
    )
    assert warning["severity"] == "warning"
    assert warning["category"] == "preference_uncertainty"
    assert warning["source"] == "passes_preference_filters"
    assert is_actionable_system_warning(warning) is False


def test_diagnostics_aggregate_by_category_and_source_without_deleting_records(tmp_path):
    db = tmp_path / "warnings.db"
    init_db(db)

    record_system_warning(
        severity="warning",
        category="preference_uncertainty",
        source="passes_preference_filters",
        message="Work mode unclear for first job.",
        fingerprint="preference-1",
        job_key="seek:1",
        db_path=db,
    )
    record_system_warning(
        severity="warning",
        category="preference_uncertainty",
        source="passes_preference_filters",
        message="Work mode unclear for first job.",
        fingerprint="preference-1",
        job_key="seek:1",
        db_path=db,
    )
    record_system_warning(
        severity="warning",
        category="preference_uncertainty",
        source="passes_preference_filters",
        message="Work mode unclear for second job.",
        fingerprint="preference-2",
        job_key="seek:2",
        db_path=db,
    )

    diagnostics = [
        warning for warning in list_system_warnings(db_path=db)
        if not is_actionable_system_warning(warning)
    ]
    groups = aggregate_system_warning_diagnostics(diagnostics)

    assert len(diagnostics) == 2
    assert len(groups) == 1
    assert groups[0]["category"] == "preference_uncertainty"
    assert groups[0]["source"] == "passes_preference_filters"
    assert groups[0]["record_count"] == 2
    assert groups[0]["occurrence_count"] == 3
    assert groups[0]["sample"]["id"] in {warning["id"] for warning in diagnostics}


def test_system_warning_operator_action_only_offers_a_real_supported_check():
    source_failure = {
        "severity": "error",
        "category": "source_failure",
        "source": "seek",
    }
    source_timeout = {
        "severity": "warning",
        "category": "source_timeout",
        "source": "linkedin",
    }
    data_failure = {
        "severity": "warning",
        "category": "json_parse_failure",
        "source": "load_json_dict",
    }
    run_stats_warning = {
        "severity": "warning",
        "category": "run_stats_warning",
        "source": "run_stats",
    }

    assert is_actionable_system_warning(source_failure) is True
    assert is_actionable_system_warning(source_timeout) is True
    assert is_actionable_system_warning(run_stats_warning) is False
    expected_scraper_action = {
        "type": "run_scraper_validation",
        "label_key": "system_health_scraper_validation_action_label",
        "guidance_key": "system_health_scraper_investigation_help",
    }
    assert system_warning_operator_action(source_failure) == expected_scraper_action
    assert system_warning_operator_action(source_timeout) == expected_scraper_action
    assert system_warning_operator_action(run_stats_warning) is None
    assert system_warning_operator_action(data_failure) is None


def test_run_stats_warnings_aggregate_into_one_compact_diagnostic_group(tmp_path):
    db = tmp_path / "warnings.db"
    init_db(db)

    for message in (
        "Job Market Map: request failed: timed out",
        "Job Market Map: partial_failure",
        "Job Market Map: request failed: connection refused",
    ):
        record_system_warning(
            severity="warning",
            category="run_stats_warning",
            source="run_stats",
            message=message,
            fingerprint=message,
            run_id="2026-09-17T17:04:30+10:00",
            db_path=db,
        )

    diagnostics = [
        warning
        for warning in list_system_warnings(db_path=db)
        if not is_actionable_system_warning(warning)
    ]
    groups = aggregate_system_warning_diagnostics(diagnostics)

    assert len(diagnostics) == 3
    assert len(groups) == 1
    assert groups[0]["category"] == "run_stats_warning"
    assert groups[0]["source"] == "run_stats"
    assert groups[0]["record_count"] == 3
    assert groups[0]["occurrence_count"] == 3
