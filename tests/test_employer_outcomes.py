"""Employer identity and outcome-ledger behaviour.

Cases use invented employer names rather than any real employer from the
candidate's history, so the tests prove the general contract instead of a
single reported example.
"""

from __future__ import annotations

import pytest

from job_hunter_agent import employer_identity, employer_outcome_store as store


@pytest.fixture
def aliases(monkeypatch):
    """Install a known alias map without touching real managed knowledge."""

    def _install(entries):
        monkeypatch.setattr(
            employer_identity,
            "_load_payload",
            lambda: {"employer_aliases": entries},
        )

    return _install


def test_casing_and_suffix_variants_collapse_without_any_alias(aliases):
    aliases([])
    assert employer_identity.employer_key("Northwind Systems Pty Ltd") == (
        employer_identity.employer_key("NORTHWIND SYSTEMS PTY LIMITED")
    )


def test_unmapped_similar_names_stay_distinct(aliases):
    """Containment must never merge two employers on its own."""
    aliases([])
    assert employer_identity.employer_key("Northwind Systems") != (
        employer_identity.employer_key("Northwind Systems Superannuation")
    )


def test_declared_alias_resolves_to_canonical_identity_and_display(aliases):
    aliases([{"canonical": "Northwind Systems", "aliases": ["NWS", "NWS College"]}])
    key_parent, display_parent = employer_identity.resolve_employer("NWS")
    key_child, display_child = employer_identity.resolve_employer("NWS College")
    assert key_parent == key_child
    assert display_parent == display_child == "Northwind Systems"


def test_malformed_alias_map_raises_rather_than_defaulting(aliases):
    aliases([{"canonical": "", "aliases": []}])
    with pytest.raises(ValueError):
        employer_identity.load_employer_aliases()


def test_empty_employer_name_is_rejected(aliases):
    aliases([])
    with pytest.raises(ValueError):
        employer_identity.resolve_employer("   ")


def test_unknown_event_type_is_rejected():
    with pytest.raises(ValueError):
        store.record_application_event(
            user_id="u1",
            employer_raw="Northwind Systems",
            role_title="Analyst",
            event_type="ghosted",
            event_date="2026-08-01",
            source=store.SOURCE_GMAIL_ACK,
            evidence_ref="msg-1",
            confidence="high",
        )


def test_event_without_evidence_reference_is_rejected():
    with pytest.raises(ValueError):
        store.record_application_event(
            user_id="u1",
            employer_raw="Northwind Systems",
            role_title="Analyst",
            event_type=store.EVENT_APPLIED,
            event_date="2026-08-01",
            source=store.SOURCE_GMAIL_ACK,
            evidence_ref="  ",
            confidence="high",
        )


def test_event_id_is_stable_so_replaying_a_backfill_cannot_double_count():
    first = store.make_event_id(store.SOURCE_GMAIL_ACK, "msg-1", store.EVENT_APPLIED)
    second = store.make_event_id(store.SOURCE_GMAIL_ACK, "msg-1", store.EVENT_APPLIED)
    other = store.make_event_id(store.SOURCE_GMAIL_ACK, "msg-1", store.EVENT_REJECTED)
    assert first == second
    assert first != other


def _event(event_type, event_date, role="Analyst", employer="northwind systems"):
    return {
        "employer_key": employer,
        "employer_raw": "Northwind Systems",
        "role_title": role,
        "event_type": event_type,
        "event_date": event_date,
    }


def test_rollup_counts_every_outcome_type_and_bounds_the_dates():
    rollup = store.build_employer_rollup(
        [
            _event(store.EVENT_APPLIED, "2026-02-02", "Analyst"),
            _event(store.EVENT_REJECTED, "2026-06-18", "Analyst"),
            _event(store.EVENT_APPLIED, "2026-08-10", "Senior Analyst"),
            _event(store.EVENT_INTERVIEW, "2026-08-24", "Senior Analyst"),
        ]
    )
    assert rollup["counts"][store.EVENT_APPLIED] == 2
    assert rollup["counts"][store.EVENT_REJECTED] == 1
    assert rollup["counts"][store.EVENT_INTERVIEW] == 1
    assert rollup["counts"][store.EVENT_NO_RESPONSE] == 0
    assert rollup["first_event_date"] == "2026-02-02"
    assert rollup["last_event_date"] == "2026-08-24"
    assert len(rollup["roles"]) == 4


def test_rollup_records_an_interview_alongside_rejections_without_cancelling_them():
    """An interview is its own fact. It never erases a rejection."""
    rollup = store.build_employer_rollup(
        [
            _event(store.EVENT_REJECTED, "2026-03-01"),
            _event(store.EVENT_INTERVIEW, "2026-04-01"),
            _event(store.EVENT_REJECTED, "2026-05-01"),
        ]
    )
    assert rollup["counts"][store.EVENT_REJECTED] == 2
    assert rollup["counts"][store.EVENT_INTERVIEW] == 1


def test_rollup_carries_no_threshold_verdict_or_label():
    """Display policy is applied at read time, so a rollup holds facts only."""
    rollup = store.build_employer_rollup([_event(store.EVENT_REJECTED, "2026-03-01")])
    forbidden = {"warning", "warning_level", "flag", "label", "severity", "verdict"}
    assert forbidden.isdisjoint(rollup.keys())


def test_rollup_from_zero_events_raises_instead_of_returning_an_empty_shell():
    with pytest.raises(ValueError):
        store.build_employer_rollup([])


def test_rollup_rejects_an_unrecognised_stored_event_type():
    with pytest.raises(ValueError):
        store.build_employer_rollup([_event("ghosted", "2026-03-01")])


# --- card display -----------------------------------------------------------

from job_hunter_agent import employer_outcome_display as display  # noqa: E402
from job_hunter_agent.workspace_renderer import (  # noqa: E402
    _build_checks_before_applying_items,
    _workspace_label,
)


def _label(key):
    return _workspace_label("check_item_labels", key)


def _rollup(applied=0, rejected=0, interview=0, no_response=0, last="2026-08-24"):
    return {
        "employer_display": "Northwind Systems",
        "counts": {
            store.EVENT_APPLIED: applied,
            store.EVENT_REJECTED: rejected,
            store.EVENT_INTERVIEW: interview,
            store.EVENT_NO_RESPONSE: no_response,
        },
        "last_event_date": last,
    }


def test_a_failed_lookup_and_a_clean_record_never_render_the_same():
    """The July 2026 defect: a broken lookup looked exactly like no history."""
    nothing_found = display.build_employer_outcome_check_item(
        display.resolve_employer_outcome_state(None), _label
    )
    could_not_look = display.build_employer_outcome_check_item(
        display.resolve_employer_outcome_state(None, lookup_failed=True), _label
    )
    assert nothing_found != could_not_look
    assert could_not_look.strip()


def test_history_line_reports_every_count_and_the_latest_date():
    line = display.build_employer_outcome_check_item(
        display.resolve_employer_outcome_state(
            _rollup(applied=6, rejected=5, interview=0, no_response=1)
        ),
        _label,
    )
    assert "Northwind Systems" in line
    assert "6" in line and "5" in line
    assert "2026-08-24" in line


def test_history_line_shows_an_interview_without_hiding_rejections():
    line = display.build_employer_outcome_check_item(
        display.resolve_employer_outcome_state(_rollup(applied=2, rejected=1, interview=1)),
        _label,
    )
    assert "rejected 1" in line
    assert "interviewed 1" in line


def test_unknown_state_raises_rather_than_rendering_something_plausible():
    with pytest.raises(ValueError):
        display.build_employer_outcome_check_item({"state": "maybe"}, _label)


def _checks(employer_outcome):
    return _build_checks_before_applying_items(
        [], False, False, None, None, [], "ok", None, None, employer_outcome
    )


def test_card_shows_the_history_line_when_history_exists():
    items = _checks(display.resolve_employer_outcome_state(_rollup(applied=3, rejected=2)))
    assert any("Northwind Systems" in item for item in items)


def test_card_says_so_explicitly_when_the_lookup_failed():
    items = _checks(display.resolve_employer_outcome_state(None, lookup_failed=True))
    assert any("Could not check" in item for item in items)


def test_card_adds_no_line_when_there_is_genuinely_no_history():
    assert _checks(display.resolve_employer_outcome_state(None)) == []


# --- backfill ---------------------------------------------------------------

from job_hunter_agent import employer_outcome_backfill as backfill  # noqa: E402


@pytest.fixture
def ledger_db(tmp_path, monkeypatch, aliases):
    from job_hunter_agent import database as db

    path = tmp_path / "ledger.db"
    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(path))
    db.init_db(path)
    with db.db_conn(path) as conn:
        conn.execute("INSERT INTO users (user_id) VALUES (?)", ("u1",))
    aliases([{"canonical": "Northwind Systems", "aliases": ["NWS"]}])
    return path


def _history_row(idx, company, role, date):
    return {
        "id": f"row-{idx}",
        "message_id": f"msg-{idx}",
        "company": company,
        "role": role,
        "date": date,
        "status": "rejection",
        "confidence": "high",
        "evidence": "",
        "job_key": None,
    }


def test_backfill_imports_rejections_and_collapses_aliases(ledger_db, monkeypatch):
    rows = [
        _history_row(1, "Northwind Systems", "Analyst", "2026-02-02"),
        _history_row(2, "NWS", "Senior Analyst", "2026-06-18"),
    ]
    summary = backfill.backfill_from_rejection_history(
        "u1", db_path=ledger_db, load_history=lambda: rows
    )
    assert summary["events_imported"] == 2
    # Both spellings are one employer, so one rollup, not two.
    assert summary["employers_in_rollup"] == 1

    rollup = store.get_employer_outcome("u1", "NWS", db_path=ledger_db)
    assert rollup["counts"][store.EVENT_REJECTED] == 2
    assert rollup["last_event_date"] == "2026-06-18"


def test_backfill_is_idempotent(ledger_db):
    rows = [_history_row(1, "Northwind Systems", "Analyst", "2026-02-02")]
    loader = lambda: rows
    backfill.backfill_from_rejection_history("u1", db_path=ledger_db, load_history=loader)
    backfill.backfill_from_rejection_history("u1", db_path=ledger_db, load_history=loader)

    rollup = store.get_employer_outcome("u1", "Northwind Systems", db_path=ledger_db)
    assert rollup["counts"][store.EVENT_REJECTED] == 1


def test_backfill_reports_unattributable_rows_instead_of_dropping_them(ledger_db):
    rows = [
        _history_row(1, "Northwind Systems", "Analyst", "2026-02-02"),
        _history_row(2, "", "Analyst", "2026-03-02"),
        _history_row(3, "Northwind Systems", "Analyst", ""),
    ]
    summary = backfill.backfill_from_rejection_history(
        "u1", db_path=ledger_db, load_history=lambda: rows
    )
    assert summary["rows_read"] == 3
    assert summary["events_imported"] == 1
    assert summary["skipped_no_employer"] == 1
    assert summary["skipped_no_date"] == 1


# --- date normalisation -----------------------------------------------------


def test_iso_dates_pass_through_unchanged():
    assert backfill.normalise_event_date("2026-04-02") == "2026-04-02"


def test_slash_dates_are_read_month_first_and_zero_padded():
    assert backfill.normalise_event_date("8/19/2026") == "2026-08-19"
    assert backfill.normalise_event_date("4/4/2024") == "2024-04-04"


def test_trailing_time_is_discarded_not_treated_as_a_parse_failure():
    assert backfill.normalise_event_date("8/7/2026 11:03:22") == "2026-08-07"
    assert backfill.normalise_event_date("2026-04-02T09:00:00+10:00") == "2026-04-02"


def test_an_unrecognised_shape_returns_empty_rather_than_a_plausible_guess():
    for value in ("", "   ", "not a date", "19/8/26", "Aug 19 2026", None):
        assert backfill.normalise_event_date(value) == ""


def test_an_impossible_month_is_rejected_rather_than_silently_swapped():
    assert backfill.normalise_event_date("19/8/2026") == ""


def test_backfill_normalises_mixed_date_shapes_onto_one_scale(ledger_db):
    rows = [
        _history_row(1, "Northwind Systems", "Analyst", "8/19/2026"),
        _history_row(2, "Northwind Systems", "Analyst", "2026-04-02"),
    ]
    backfill.backfill_from_rejection_history(
        "u1", db_path=ledger_db, load_history=lambda: rows
    )
    rollup = store.get_employer_outcome("u1", "Northwind Systems", db_path=ledger_db)
    # Ordering only works once both shapes are on the same scale.
    assert rollup["first_event_date"] == "2026-04-02"
    assert rollup["last_event_date"] == "2026-08-19"
