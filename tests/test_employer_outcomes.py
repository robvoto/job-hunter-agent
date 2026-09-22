"""Employer identity and outcome-ledger behaviour.

Cases use invented employer names rather than any real employer from the
candidate's history, so the tests prove the general contract instead of a
single reported example.
"""

from __future__ import annotations

import pytest

from job_hunter_agent import employer_identity
from job_hunter_agent import employer_outcome_store as store


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


def test_history_line_reports_rejections_and_the_latest_date():
    """Only rejections render: applied/interview/no_response have no producer
    yet (see the guardrail comment on build_employer_outcome_check_item), so
    showing them would present "never measured" as "confirmed zero"."""
    line = display.build_employer_outcome_check_item(
        display.resolve_employer_outcome_state(
            _rollup(applied=6, rejected=5, interview=0, no_response=1)
        ),
        _label,
    )
    assert "Northwind Systems" in line
    assert "5" in line
    assert "24 Aug 2026" in line


def test_history_line_with_zero_rejections_avoids_zero_count_noise():
    line = display.build_employer_outcome_check_item(
        display.resolve_employer_outcome_state(_rollup(applied=1, rejected=0)),
        _label,
    )
    assert line == "Your history with Northwind Systems. Latest activity 24 Aug 2026."
    assert "rejection" not in line.lower()


def test_history_line_does_not_render_unmeasured_counters():
    """applied/interview/no_response counts must never appear in the line -
    nothing in the system currently produces those events."""
    line = display.build_employer_outcome_check_item(
        display.resolve_employer_outcome_state(_rollup(applied=2, rejected=1, interview=1)),
        _label,
    )
    assert "1 rejection" in line
    assert "applied" not in line
    assert "interviewed" not in line
    assert "no reply" not in line


def test_unknown_state_raises_rather_than_rendering_something_plausible():
    with pytest.raises(ValueError):
        display.build_employer_outcome_check_item({"state": "maybe"}, _label)


def _checks(employer_outcome):
    return _build_checks_before_applying_items(
        [], False, False, None, [], "ok", None, None, employer_outcome
    )


def test_card_shows_the_history_line_when_history_exists():
    items = _checks(display.resolve_employer_outcome_state(_rollup(applied=3, rejected=2)))
    assert any("Northwind Systems" in item for item in items)


def test_card_says_so_explicitly_when_the_lookup_failed():
    items = _checks(display.resolve_employer_outcome_state(None, lookup_failed=True))
    assert any("Could not check" in item for item in items)


def test_card_adds_no_line_when_there_is_genuinely_no_history():
    assert _checks(display.resolve_employer_outcome_state(None)) == []
