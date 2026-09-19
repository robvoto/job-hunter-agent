"""Regression coverage for JH-297 incremental source discovery."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_hunter_agent.database import db_conn
from job_hunter_agent.incremental_search import (
    load_incremental_checkpoints,
    plan_incremental_search,
    save_incremental_checkpoints,
)
from job_hunter_agent.scrapers.apsjobs import _new_candidate_links
from job_hunter_agent.scrapers.linkedin import build_linkedin_search_targets
from job_hunter_agent.scrapers.seek import build_seek_search_targets

UTC = timezone.utc
TARGETS = [{"keywords": "policy", "location": "Sydney", "url": "https://seek.test"}]


def _reset_state() -> None:
    with db_conn() as conn:
        conn.execute("DELETE FROM incremental_search_state")


def _record(job_key: str, *, age: int | None = None) -> dict:
    record = {
        "job_key": job_key,
        "search_location": "Sydney",
        "search_keywords": "policy",
    }
    if age is not None:
        record["posted_age_days"] = age
    return record


def test_first_run_is_full_and_next_healthy_run_is_incremental(monkeypatch):
    from job_hunter_agent import incremental_search

    _reset_state()
    monkeypatch.setattr(incremental_search, "get_incremental_search_overlap_days", lambda: 2)
    monkeypatch.setattr(incremental_search, "get_incremental_search_catch_up_interval_days", lambda: 7)
    t0 = datetime(2026, 9, 1, 9, tzinfo=UTC)

    first = plan_incremental_search(
        source="seek",
        signature="sig-1",
        targets=TARGETS,
        configured_window_days=7,
        now=t0,
    )
    assert first.mode == "full"
    assert first.reason == "no_trustworthy_checkpoint"
    save_incremental_checkpoints(
        first,
        targets=TARGETS,
        discovery_records=[_record("seek:1", age=1)],
        completed=True,
        run_at=t0,
    )

    next_run = plan_incremental_search(
        source="seek",
        signature="sig-1",
        targets=TARGETS,
        configured_window_days=7,
        now=t0 + timedelta(days=1),
    )
    assert next_run.mode == "incremental"
    assert next_run.reason == "healthy_checkpoint"
    assert next_run.effective_window_days == 2
    assert next_run.known_job_keys == frozenset({"seek:1"})


def test_failed_run_does_not_advance_checkpoint_and_periodic_catchup_is_full(monkeypatch):
    from job_hunter_agent import incremental_search

    _reset_state()
    monkeypatch.setattr(incremental_search, "get_incremental_search_overlap_days", lambda: 2)
    monkeypatch.setattr(incremental_search, "get_incremental_search_catch_up_interval_days", lambda: 7)
    t0 = datetime(2026, 9, 1, 9, tzinfo=UTC)
    first = plan_incremental_search(
        source="seek", signature="sig-1", targets=TARGETS, configured_window_days=7, now=t0
    )
    save_incremental_checkpoints(
        first, targets=TARGETS, discovery_records=[_record("seek:1")], completed=True, run_at=t0
    )
    failed = plan_incremental_search(
        source="seek", signature="sig-1", targets=TARGETS, configured_window_days=7, now=t0 + timedelta(days=1)
    )
    assert save_incremental_checkpoints(
        failed,
        targets=TARGETS,
        discovery_records=[_record("seek:2")],
        completed=False,
        run_at=t0 + timedelta(days=1),
    )["advanced"] is False
    state = load_incremental_checkpoints(source="seek", signature="sig-1", targets=TARGETS)
    assert state[("Sydney", "policy")]["last_successful_at"] == t0.isoformat(timespec="seconds")
    assert "seek:2" not in state[("Sydney", "policy")]["known_job_keys"]

    catch_up = plan_incremental_search(
        source="seek", signature="sig-1", targets=TARGETS, configured_window_days=7, now=t0 + timedelta(days=8)
    )
    assert catch_up.mode == "full"
    assert catch_up.reason == "periodic_catch_up"


def test_signature_change_and_force_refresh_require_full_window(monkeypatch):
    from job_hunter_agent import incremental_search

    _reset_state()
    monkeypatch.setattr(incremental_search, "get_incremental_search_overlap_days", lambda: 2)
    monkeypatch.setattr(incremental_search, "get_incremental_search_catch_up_interval_days", lambda: 30)
    t0 = datetime(2026, 9, 1, 9, tzinfo=UTC)
    first = plan_incremental_search(
        source="seek", signature="sig-1", targets=TARGETS, configured_window_days=7, now=t0
    )
    save_incremental_checkpoints(
        first, targets=TARGETS, discovery_records=[_record("seek:1")], completed=True, run_at=t0
    )
    changed = plan_incremental_search(
        source="seek", signature="sig-2", targets=TARGETS, configured_window_days=7, now=t0 + timedelta(days=1)
    )
    forced = plan_incremental_search(
        source="seek", signature="sig-1", targets=TARGETS, configured_window_days=7,
        force_refresh=True, now=t0 + timedelta(days=1)
    )
    assert (changed.mode, changed.reason) == ("full", "no_trustworthy_checkpoint")
    assert (forced.mode, forced.reason) == ("full", "force_refresh")


def test_late_discovery_is_persisted_as_per_target_distribution(monkeypatch):
    from job_hunter_agent import incremental_search

    _reset_state()
    monkeypatch.setattr(incremental_search, "get_incremental_search_overlap_days", lambda: 2)
    monkeypatch.setattr(incremental_search, "get_incremental_search_catch_up_interval_days", lambda: 30)
    monkeypatch.setattr(incremental_search, "get_incremental_search_late_discovery_threshold_days", lambda: 2)
    t0 = datetime(2026, 9, 1, 9, tzinfo=UTC)
    first = plan_incremental_search(
        source="seek", signature="sig-1", targets=TARGETS, configured_window_days=7, now=t0
    )
    save_incremental_checkpoints(
        first, targets=TARGETS, discovery_records=[_record("seek:1", age=1)], completed=True, run_at=t0
    )
    incremental = plan_incremental_search(
        source="seek", signature="sig-1", targets=TARGETS, configured_window_days=7, now=t0 + timedelta(days=1)
    )
    stats = save_incremental_checkpoints(
        incremental,
        targets=TARGETS,
        discovery_records=[_record("seek:1", age=1), _record("seek:2", age=4)],
        completed=True,
        run_at=t0 + timedelta(days=1),
    )
    assert stats["late_discoveries"] == 1
    state = load_incremental_checkpoints(source="seek", signature="sig-1", targets=TARGETS)
    assert state[("Sydney", "policy")]["late_discovery"] == {
        "age_distribution": {"4": 1},
        "discovery_count": 2,
        "late_count": 1,
        "rate": 0.5,
        "threshold_days": 2,
    }


def test_source_native_windows_and_aps_seen_frontier_are_explicit():
    profile = {"search_settings": {"keywords": "policy", "locations": ["Sydney"]}}
    seek_targets = build_seek_search_targets(profile, 7, True, effective_date_range=2)
    assert "daterange=2" in seek_targets[0]["url"]

    linkedin_targets = build_linkedin_search_targets(
        {"keywords": "policy", "locations": ["Sydney"], "linkedin_hours_old": 168},
        profile,
        effective_hours_old=48,
    )
    assert linkedin_targets[0]["hours_old"] == 48

    links = [
        {"url": "https://www.apsjobs.gov.au/s/job-details?Id=1", "text": "old"},
        {"url": "https://www.apsjobs.gov.au/s/job-details?Id=2", "text": "new"},
    ]
    filtered = _new_candidate_links(links, set(), {"apsjobs:1"})
    assert [link["url"] for link in filtered] == [links[1]["url"]]
