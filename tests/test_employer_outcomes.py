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
