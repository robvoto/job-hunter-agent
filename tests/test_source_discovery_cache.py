"""Regression coverage for persisted source-discovery snapshots."""

from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

import pytest

from job_hunter_agent.database import db_conn
from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.source_discovery_cache import (
    build_source_search_signature,
    load_linkedin_failure_backoff,
    load_source_discovery_snapshot,
    save_source_discovery_snapshot,
    save_source_failure_state,
)
from job_hunter_agent.source_registry import SOURCE_APSJOBS, SOURCE_LINKEDIN, SOURCE_SEEK


def _clear_cache() -> None:
    with db_conn() as conn:
        conn.execute("DELETE FROM source_discovery_cache")


def _make_context() -> ScrapeRunContext:
    started = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)
    return ScrapeRunContext(
        profile={"search_settings": {"keywords": "policy", "locations": ["Sydney"]}},
        search_settings={"keywords": "policy", "locations": ["Sydney"]},
        dashboard_min_score=50,
        configured_seek_max_pages=1,
        configured_date_range=3,
        sort_newest_first=True,
        playwright_viewport_width=1400,
        playwright_viewport_height=900,
        playwright_selector_timeout=8000,
        seek_parallel_detail_workers=1,
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_started_at=started,
        run_iso=started.isoformat(timespec="seconds"),
        previous_audit_rows=[],
        previous_run_stats={},
        llm_cache={},
        job_history={},
        enabled_sources=[SOURCE_APSJOBS],
        no_llm_mode=True,
        dashboard_debug_mode=False,
        reset_new_to_you=False,
    )


def test_identical_search_persists_and_reuses_snapshot_across_module_reload():
    _clear_cache()
    signature = build_source_search_signature(SOURCE_APSJOBS, {"keywords": "policy", "limit": 25})
    records = [{"job_key": "apsjobs:1", "title": "Policy Officer"}]

    assert load_source_discovery_snapshot(SOURCE_APSJOBS, signature) is None
    save_source_discovery_snapshot(SOURCE_APSJOBS, signature, records)
    importlib.invalidate_caches()
    importlib.reload(importlib.import_module("job_hunter_agent.source_discovery_cache"))

    assert load_source_discovery_snapshot(SOURCE_APSJOBS, signature) == records


def test_changed_input_is_a_miss_and_expired_snapshot_is_a_miss():
    _clear_cache()
    signature = build_source_search_signature(SOURCE_APSJOBS, {"keywords": "policy"})
    changed = build_source_search_signature(SOURCE_APSJOBS, {"keywords": "program"})
    save_source_discovery_snapshot(SOURCE_APSJOBS, signature, [{"job_key": "apsjobs:1"}])

    assert load_source_discovery_snapshot(SOURCE_APSJOBS, changed) is None
    with db_conn() as conn:
        conn.execute(
            "UPDATE source_discovery_cache SET updated_at = ? WHERE source = ? AND signature = ? AND status = 'success'",
            ("2000-01-01T00:00:00+00:00", SOURCE_APSJOBS, signature),
        )
    assert load_source_discovery_snapshot(SOURCE_APSJOBS, signature) is None


def test_failure_state_does_not_replace_known_good_snapshot():
    _clear_cache()
    signature = build_source_search_signature(SOURCE_LINKEDIN, {"term": "analyst"})
    records = [{"job_key": "linkedin:1"}]
    save_source_discovery_snapshot(SOURCE_LINKEDIN, signature, records)
    save_source_failure_state(SOURCE_LINKEDIN, signature)

    assert load_source_discovery_snapshot(SOURCE_LINKEDIN, signature) == records
    with db_conn() as conn:
        statuses = conn.execute(
            "SELECT status FROM source_discovery_cache WHERE source = ? AND signature = ? ORDER BY status",
            (SOURCE_LINKEDIN, signature),
        ).fetchall()
    assert [row["status"] for row in statuses] == ["failure", "success"]


def test_linkedin_failure_backoff_expires_without_permanent_suppression():
    _clear_cache()
    signature = build_source_search_signature(SOURCE_LINKEDIN, {"term": "analyst"})
    save_source_failure_state(SOURCE_LINKEDIN, signature)

    assert load_linkedin_failure_backoff(SOURCE_LINKEDIN, signature) is True
    with db_conn() as conn:
        conn.execute(
            "UPDATE source_discovery_cache SET updated_at = ? WHERE source = ? AND signature = ? AND status = 'failure'",
            ("2000-01-01T00:00:00+00:00", SOURCE_LINKEDIN, signature),
        )
    assert load_linkedin_failure_backoff(SOURCE_LINKEDIN, signature) is False


def test_force_refresh_is_a_miss_at_source_boundary(monkeypatch):
    from job_hunter_agent import source_runner

    _clear_cache()
    context = _make_context()
    context.force_source_refresh = True

    signature, status, records = source_runner._source_cache_lookup(context, SOURCE_APSJOBS)

    assert signature
    assert status == "MISS"
    assert records is None


def test_first_search_misses_and_second_identical_search_avoids_source(monkeypatch):
    from job_hunter_agent import source_runner

    _clear_cache()
    calls = []

    class FakeAPSJobsScraper:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self.discovery_records = kwargs["discovery_records"]
            self.discovery_capture = kwargs["discovery_capture"]

        def scrape(self):
            if self.discovery_records is None:
                self.discovery_capture.append({"job_key": "apsjobs:1", "title": "Policy"})
            return [], [], []

    monkeypatch.setattr(source_runner, "APSJobsScraper", FakeAPSJobsScraper)
    first = _make_context()
    source_runner.run_enabled_sources(first)
    second = _make_context()
    source_runner.run_enabled_sources(second)

    assert first.source_cache_stats[SOURCE_APSJOBS]["status"] == "MISS"
    assert second.source_cache_stats[SOURCE_APSJOBS]["status"] == "HIT"
    assert len(calls) == 2
    assert calls[0]["discovery_records"] is None
    assert calls[1]["discovery_records"] == [{"job_key": "apsjobs:1", "title": "Policy"}]


def test_expired_search_plan_bypasses_fresh_source_snapshot(monkeypatch):
    from job_hunter_agent import source_runner

    _clear_cache()
    context = _make_context()
    context.enabled_sources = [SOURCE_APSJOBS]
    signature = source_runner._source_search_signature(context, SOURCE_APSJOBS)
    save_source_discovery_snapshot(SOURCE_APSJOBS, signature, [{"job_key": "apsjobs:1"}])

    monkeypatch.setattr(
        source_runner,
        "load_search_plan_state",
        lambda **kwargs: {"probe_terms": ["policy"], "selected_terms": ["policy"]},
    )
    monkeypatch.setattr(
        source_runner,
        "planned_search_terms",
        lambda *args, **kwargs: (["policy"], "probe_required"),
    )

    signature, status, records = source_runner._source_cache_lookup(context, SOURCE_APSJOBS)

    assert signature
    assert status == "MISS"
    assert records is None


def test_all_linkedin_timeouts_enter_bounded_backoff(monkeypatch):
    from job_hunter_agent.scrapers import linkedin
    from job_hunter_agent import source_runner

    _clear_cache()
    calls = []

    class FakeLinkedInScraper:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def scrape(self):
            calls[-1]["discovery_status"].update(
                {
                    "complete": False,
                    "total_targets": 3,
                    "attempted_targets": 3,
                    "succeeded_targets": 0,
                    "timed_out_targets": 3,
                    "failed_targets": 3,
                    "skipped_after_breaker": 0,
                    "circuit_breaker_tripped": False,
                    "rows_collected": 0,
                    "elapsed_seconds": 60.0,
                    "final_status": "full_failure",
                }
            )
            return [], [], []

    monkeypatch.setattr(linkedin, "LinkedInScraper", FakeLinkedInScraper)
    first = _make_context()
    first.enabled_sources = [SOURCE_LINKEDIN]
    source_runner.run_enabled_sources(first)
    second = _make_context()
    second.enabled_sources = [SOURCE_LINKEDIN]
    source_runner.run_enabled_sources(second)

    assert first.source_cache_stats[SOURCE_LINKEDIN]["status"] == "MISS"
    assert second.source_cache_stats[SOURCE_LINKEDIN]["status"] == "BACKOFF"
    assert calls[0]["discovery_records"] is None
    assert calls[1]["discovery_records"] == []


def test_cached_source_jobs_are_given_to_current_review_pipeline(monkeypatch):
    from job_hunter_agent.scrapers import apsjobs

    record = {
        "job_key": "apsjobs:cached",
        "title": "Cached role",
        "decision": None,
        "details_text": "A sufficiently complete cached description.",
    }
    reviewed = []

    def fake_pre(current_record, context):
        reviewed.append(("pre", current_record["job_key"]))
        return ({"decision": "KEEP"}, current_record, [], True)

    def fake_post(current_record, context, hooks):
        reviewed.append(("post", current_record["job_key"]))
        return ({"decision": "KEEP"}, current_record, [])

    monkeypatch.setattr(apsjobs, "review_pre_detail_normalized_job", fake_pre)
    monkeypatch.setattr(apsjobs, "review_post_detail_normalized_job", fake_post)
    scraper = apsjobs.APSJobsScraper(
        profile={"search_settings": {"keywords": "policy", "locations": ["Sydney"]}},
        llm_cache={},
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-08-15T09:00:00+00:00",
        discovery_records=[record],
    )

    kept, audit, skills = scraper.scrape()

    assert [item["job_key"] for item in kept] == ["apsjobs:cached"]
    assert reviewed == [("pre", "apsjobs:cached"), ("post", "apsjobs:cached")]
    assert audit == []
    assert skills == []


def _seek_scrape_kwargs(**overrides):
    kwargs = dict(
        profile={"search_settings": {}},
        search_targets=[],
        job_history={},
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        run_iso="2026-08-15T09:00:00+00:00",
        configured_date_range=3,
        configured_seek_max_pages=1,
        playwright_viewport_width=1400,
        playwright_viewport_height=900,
        playwright_selector_timeout=8000,
        seek_parallel_detail_workers=1,
        headless=True,
        assisted_verification_enabled=False,
    )
    kwargs.update(overrides)
    return kwargs


def test_seek_cache_hit_does_not_launch_playwright_when_no_detail_fetch_needed(monkeypatch):
    """A SEEK discovery-cache HIT must never open the list browser, and must not
    create the async detail session at all when no cached record needs a fresh
    detail fetch (its decision/detail evidence is fully reusable)."""
    from job_hunter_agent.scrapers import seek_runner

    def _fail_sync_playwright():
        raise AssertionError("sync_playwright() must not be called on a discovery-cache HIT")

    class _FailAsyncDetailSession:
        def __init__(self, **kwargs):
            raise AssertionError(
                "_AsyncDetailSession must not be created when no cached record needs a detail fetch"
            )

    def fake_pre_detail(record, context):
        return ({"decision": "KEEP"}, record, [], False)

    monkeypatch.setattr(seek_runner, "sync_playwright", _fail_sync_playwright)
    monkeypatch.setattr(seek_runner, "_AsyncDetailSession", _FailAsyncDetailSession)
    monkeypatch.setattr(seek_runner, "review_pre_detail_normalized_job", fake_pre_detail)

    record = {"job_key": "seek:1", "title": "Policy Officer"}
    kept, audit, skills = seek_runner.seek_scrape_to_records(
        **_seek_scrape_kwargs(discovery_records=[record])
    )

    assert [item["job_key"] for item in kept] == ["seek:1"]


def test_seek_cache_hit_lazily_creates_detail_session_when_detail_fetch_needed(monkeypatch):
    """When a cached record's detail evidence isn't reusable, the async detail
    session may still be created on a cache HIT -- but the list browser must
    still never be opened."""
    from job_hunter_agent.scrapers import seek_runner

    def _fail_sync_playwright():
        raise AssertionError("sync_playwright() must not be called on a discovery-cache HIT")

    created = []

    class _FakeAsyncDetailSession:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def run_batch(self, needs_detail, review_context):
            results = {}
            for index, rec in needs_detail:
                results[index] = ({"decision": "KEEP"}, rec, [], 0.0)
            return results

        def close(self):
            pass

    def fake_pre_detail(record, context):
        return ({"decision": "KEEP"}, record, [], True)

    monkeypatch.setattr(seek_runner, "sync_playwright", _fail_sync_playwright)
    monkeypatch.setattr(seek_runner, "_AsyncDetailSession", _FakeAsyncDetailSession)
    monkeypatch.setattr(seek_runner, "review_pre_detail_normalized_job", fake_pre_detail)

    record = {"job_key": "seek:1", "title": "Policy Officer"}
    kept, audit, skills = seek_runner.seek_scrape_to_records(
        **_seek_scrape_kwargs(discovery_records=[record])
    )

    assert [item["job_key"] for item in kept] == ["seek:1"]
    assert len(created) == 1


def test_first_seek_search_misses_and_second_identical_search_is_cache_hit(monkeypatch):
    from job_hunter_agent import source_runner

    _clear_cache()
    calls = []

    def fake_seek_scrape_to_records(**kwargs):
        calls.append(kwargs)
        if kwargs["discovery_records"] is None:
            kwargs["discovery_capture"].append({"job_key": "seek:1", "title": "Policy Officer"})
        return [], [], []

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)
    first = _make_context()
    first.enabled_sources = [SOURCE_SEEK]
    source_runner.run_enabled_sources(first)
    second = _make_context()
    second.enabled_sources = [SOURCE_SEEK]
    source_runner.run_enabled_sources(second)

    assert first.source_cache_stats[SOURCE_SEEK]["status"] == "MISS"
    assert second.source_cache_stats[SOURCE_SEEK]["status"] == "HIT"
    assert len(calls) == 2
    assert calls[0]["discovery_records"] is None
    assert calls[1]["discovery_records"] == [{"job_key": "seek:1", "title": "Policy Officer"}]


def test_seek_changed_discovery_settings_is_a_miss(monkeypatch):
    from job_hunter_agent import source_runner

    _clear_cache()
    first_context = _make_context()
    first_context.enabled_sources = [SOURCE_SEEK]
    signature1, status1, _ = source_runner._source_cache_lookup(first_context, SOURCE_SEEK)
    assert status1 == "MISS"
    save_source_discovery_snapshot(SOURCE_SEEK, signature1, [{"job_key": "seek:1"}])

    second_context = _make_context()
    second_context.enabled_sources = [SOURCE_SEEK]
    second_context.search_settings = {"keywords": "different", "locations": ["Sydney"]}
    second_context.profile = {"search_settings": second_context.search_settings}
    signature2, status2, records2 = source_runner._source_cache_lookup(second_context, SOURCE_SEEK)

    assert signature2 != signature1
    assert status2 == "MISS"
    assert records2 is None


def test_seek_added_profile_role_term_changes_discovery_signature():
    """Search-plan inputs must include profile role terms, not just keywords:
    adding a role to also_consider_roles must invalidate the SEEK signature
    even when search_settings itself is unchanged."""
    from job_hunter_agent import source_runner

    _clear_cache()
    first_context = _make_context()
    first_context.enabled_sources = [SOURCE_SEEK]
    first_context.profile = {
        "search_settings": first_context.search_settings,
        "target_roles": ["Business Analyst"],
        "also_consider_roles": [],
    }
    signature1, status1, _ = source_runner._source_cache_lookup(first_context, SOURCE_SEEK)
    assert status1 == "MISS"
    save_source_discovery_snapshot(SOURCE_SEEK, signature1, [{"job_key": "seek:1"}])

    second_context = _make_context()
    second_context.enabled_sources = [SOURCE_SEEK]
    second_context.search_settings = dict(first_context.search_settings)
    second_context.profile = {
        "search_settings": second_context.search_settings,
        "target_roles": ["Business Analyst"],
        "also_consider_roles": ["Senior Business Analyst"],
    }
    signature2, status2, records2 = source_runner._source_cache_lookup(second_context, SOURCE_SEEK)

    assert signature2 != signature1
    assert status2 == "MISS"
    assert records2 is None


def test_seek_force_refresh_is_a_miss_at_source_boundary(monkeypatch):
    from job_hunter_agent import source_runner

    _clear_cache()
    context = _make_context()
    context.enabled_sources = [SOURCE_SEEK]
    context.force_source_refresh = True

    signature, status, records = source_runner._source_cache_lookup(context, SOURCE_SEEK)

    assert signature
    assert status == "MISS"
    assert records is None


def test_stopped_seek_collection_does_not_save_success_snapshot(monkeypatch):
    """A run_stop_requested()-triggered break must not leave a "success" snapshot
    behind: source_collection_complete must reach False and the save loop must
    skip it, so a later search is still a MISS."""
    from job_hunter_agent import source_runner

    _clear_cache()

    def fake_seek_scrape_to_records(**kwargs):
        kwargs["discovery_capture"].append({"job_key": "seek:1", "title": "Policy Officer"})
        kwargs["discovery_status"]["complete"] = False
        return [], [], []

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)
    first = _make_context()
    first.enabled_sources = [SOURCE_SEEK]
    source_runner.run_enabled_sources(first)

    assert first.source_cache_stats[SOURCE_SEEK]["status"] == "MISS"
    signature = first.source_cache_stats[SOURCE_SEEK]["signature"]
    assert load_source_discovery_snapshot(SOURCE_SEEK, signature) is None

    second = _make_context()
    second.enabled_sources = [SOURCE_SEEK]
    source_runner.run_enabled_sources(second)
    assert second.source_cache_stats[SOURCE_SEEK]["status"] == "MISS"


def test_partial_seek_failure_does_not_replace_existing_good_snapshot(monkeypatch):
    from job_hunter_agent import source_runner
    from job_hunter_agent.source_errors import PartialSourceResultsError

    _clear_cache()
    good_records = [{"job_key": "seek:1", "title": "Policy Officer"}]

    def fake_seek_scrape_to_records_success(**kwargs):
        kwargs["discovery_capture"].extend(good_records)
        return [], [], []

    monkeypatch.setattr(
        source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records_success
    )
    first = _make_context()
    first.enabled_sources = [SOURCE_SEEK]
    source_runner.run_enabled_sources(first)
    signature = first.source_cache_stats[SOURCE_SEEK]["signature"]
    assert load_source_discovery_snapshot(SOURCE_SEEK, signature) == good_records

    def fake_seek_scrape_to_records_partial(**kwargs):
        raise PartialSourceResultsError(
            "seek", kept_records=[], audit_rows=[], skill_observations=[],
            original_error=RuntimeError("boom"),
        )

    monkeypatch.setattr(
        source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records_partial
    )
    second = _make_context()
    second.enabled_sources = [SOURCE_SEEK]
    second.force_source_refresh = True
    source_runner.run_enabled_sources(second)

    assert load_source_discovery_snapshot(SOURCE_SEEK, signature) == good_records


def test_reevaluate_stale_posting_ages_ages_forward_conservatively():
    """A record's posted_age_days was accurate at capture time only. Replaying
    it later must age it forward (never leave it looking artificially fresh),
    preferring the record's own run_started_at over the snapshot's capture
    time, and must never invent an age for a record that never had one. This
    must use the shared posting_utils.current_posted_age_days fractional-day
    contract, not a second ageing algorithm."""
    from job_hunter_agent import source_runner

    now = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)
    snapshot_captured_at = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)
    records = [
        {"posted_age_days": 1, "run_started_at": "2026-08-15T09:00:00+00:00"},
        {"posted_age_days": 3},
        {"posted_age_days": None},
    ]

    adjusted = source_runner._reevaluate_stale_posting_ages(
        records, snapshot_captured_at, now=now
    )

    assert adjusted[0]["posted_age_days"] == 3  # 1 + exactly 2 days since its own run_started_at
    assert adjusted[1]["posted_age_days"] == 4  # 3 + exactly 1 day since the snapshot's capture
    assert adjusted[2]["posted_age_days"] is None
    # Originals must not be mutated in place.
    assert records[0]["posted_age_days"] == 1


def test_reevaluate_stale_posting_ages_does_not_round_partial_days_up():
    """A record only a few hours stale must gain a few hours of age, not a
    full extra day. The old ceil(elapsed_days)-based algorithm made a job
    almost one full day older than it really is; the shared
    current_posted_age_days contract must age it forward fractionally."""
    from job_hunter_agent import source_runner

    now = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)
    snapshot_captured_at = datetime(2026, 8, 17, 7, 0, tzinfo=timezone.utc)  # 2 hours ago
    records = [{"posted_age_days": 2, "run_started_at": "2026-08-17T07:00:00+00:00"}]

    adjusted = source_runner._reevaluate_stale_posting_ages(
        records, snapshot_captured_at, now=now
    )

    aged_age_days = adjusted[0]["posted_age_days"]
    # 2 hours elapsed is 2/24 of a day (~0.083), never a full extra day.
    assert aged_age_days == pytest.approx(2 + 2 / 24, abs=1e-6)
    assert aged_age_days < 3


def test_reevaluate_stale_posting_ages_does_not_double_count_on_repeated_evaluation():
    """Materialising a current age must advance the record's reference time
    to match it. If the old reference time were left in place, a later
    current_posted_age_days() call at the same `now` would measure elapsed
    time from that stale reference using the *already aged-forward* value,
    re-applying the same elapsed interval a second time and inflating the
    age further -- exactly the double-counting bug this must prevent."""
    from job_hunter_agent import source_runner
    from job_hunter_agent.posting_utils import current_posted_age_days

    now = datetime(2026, 8, 17, 9, 0, tzinfo=timezone.utc)
    snapshot_captured_at = datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)
    records = [{"posted_age_days": 2, "run_started_at": "2026-08-15T09:00:00+00:00"}]

    adjusted = source_runner._reevaluate_stale_posting_ages(
        records, snapshot_captured_at, now=now
    )
    first_age = adjusted[0]["posted_age_days"]

    # A second, independent evaluation at the exact same instant must return
    # the same age, not a further-inflated one.
    second_age = current_posted_age_days(adjusted[0], now=now)
    assert second_age == pytest.approx(first_age, abs=1e-9)


def test_linkedin_stale_snapshot_is_served_during_active_backoff(monkeypatch):
    """A bounded, known-good LinkedIn snapshot should be served -- instead of
    an empty BACKOFF result -- when a live search is unavailable because of
    active failure backoff, with its posting ages conservatively aged forward."""
    from job_hunter_agent.scrapers import linkedin
    from job_hunter_agent import source_runner

    _clear_cache()
    calls = []

    class FakeLinkedInScraper:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self._discovery_records = kwargs["discovery_records"]
            self._discovery_capture = kwargs["discovery_capture"]
            self._discovery_status = kwargs["discovery_status"]

        def scrape(self):
            if self._discovery_records is not None:
                self._discovery_status["complete"] = True
                return list(self._discovery_records), [], []
            record = {"job_key": "linkedin:1", "title": "Policy Officer", "posted_age_days": 1}
            self._discovery_capture.append(dict(record))
            self._discovery_status["complete"] = True
            return [dict(record)], [], []

    monkeypatch.setattr(linkedin, "LinkedInScraper", FakeLinkedInScraper)

    first = _make_context()
    first.enabled_sources = [SOURCE_LINKEDIN]
    source_runner.run_enabled_sources(first)
    assert first.source_cache_stats[SOURCE_LINKEDIN]["status"] == "MISS"
    signature = first.source_cache_stats[SOURCE_LINKEDIN]["signature"]

    # Age the saved snapshot past the normal freshness TTL but still within
    # the bounded stale-fallback window, then force active failure backoff.
    stale_updated_at = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(
        timespec="seconds"
    )
    with db_conn() as conn:
        conn.execute(
            "UPDATE source_discovery_cache SET updated_at = ? WHERE source = ? AND signature = ? AND status = 'success'",
            (stale_updated_at, SOURCE_LINKEDIN, signature),
        )
    save_source_failure_state(SOURCE_LINKEDIN, signature)

    second = _make_context()
    second.enabled_sources = [SOURCE_LINKEDIN]
    kept, _audit, _skills = source_runner.run_enabled_sources(second)

    stats = second.source_cache_stats[SOURCE_LINKEDIN]
    assert stats["status"] == "STALE_FALLBACK"
    assert stats["external_source_calls_avoided"] is True
    # The first (live) call happened in `first`; active backoff must skip a
    # second live attempt entirely and go straight to the stale replay.
    assert len(calls) == 2
    assert [item["job_key"] for item in kept] == ["linkedin:1"]
    assert kept[0]["posted_age_days"] > 1

    # A stale-fallback replay must never refresh the snapshot it borrowed from.
    with db_conn() as conn:
        row = conn.execute(
            "SELECT updated_at FROM source_discovery_cache WHERE source = ? AND signature = ? AND status = 'success'",
            (SOURCE_LINKEDIN, signature),
        ).fetchone()
    assert row["updated_at"] == stale_updated_at


def test_linkedin_stale_snapshot_is_served_after_same_run_full_failure(monkeypatch):
    """When a live LinkedIn attempt fails completely this run, a bounded
    known-good snapshot should replace the empty result -- but the live
    failure must still be recorded truthfully for future backoff decisions."""
    from job_hunter_agent.scrapers import linkedin
    from job_hunter_agent import source_runner

    _clear_cache()
    calls = []

    class _ReplayOrFailLinkedInScraper:
        live_final_status = "full_failure"

        def __init__(self, **kwargs):
            calls.append(kwargs)
            self._discovery_records = kwargs["discovery_records"]
            self._discovery_capture = kwargs["discovery_capture"]
            self._discovery_status = kwargs["discovery_status"]

        def scrape(self):
            if self._discovery_records is not None:
                self._discovery_status["complete"] = True
                return list(self._discovery_records), [], []
            if self.live_final_status == "success":
                record = {"job_key": "linkedin:1", "title": "Policy Officer", "posted_age_days": 1}
                self._discovery_capture.append(dict(record))
                self._discovery_status["complete"] = True
                return [dict(record)], [], []
            self._discovery_status.update(
                {
                    "complete": False,
                    "total_targets": 3,
                    "attempted_targets": 3,
                    "succeeded_targets": 0,
                    "timed_out_targets": 3,
                    "failed_targets": 3,
                    "skipped_after_breaker": 0,
                    "circuit_breaker_tripped": False,
                    "rows_collected": 0,
                    "elapsed_seconds": 60.0,
                    "final_status": "full_failure",
                }
            )
            return [], [], []

    monkeypatch.setattr(linkedin, "LinkedInScraper", _ReplayOrFailLinkedInScraper)
    _ReplayOrFailLinkedInScraper.live_final_status = "success"

    first = _make_context()
    first.enabled_sources = [SOURCE_LINKEDIN]
    source_runner.run_enabled_sources(first)
    assert first.source_cache_stats[SOURCE_LINKEDIN]["status"] == "MISS"
    signature = first.source_cache_stats[SOURCE_LINKEDIN]["signature"]

    stale_updated_at = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(
        timespec="seconds"
    )
    with db_conn() as conn:
        conn.execute(
            "UPDATE source_discovery_cache SET updated_at = ? WHERE source = ? AND signature = ? AND status = 'success'",
            (stale_updated_at, SOURCE_LINKEDIN, signature),
        )

    _ReplayOrFailLinkedInScraper.live_final_status = "full_failure"

    second = _make_context()
    second.enabled_sources = [SOURCE_LINKEDIN]
    kept, _audit, _skills = source_runner.run_enabled_sources(second)

    stats = second.source_cache_stats[SOURCE_LINKEDIN]
    assert stats["status"] == "STALE_FALLBACK_AFTER_FAILURE"
    # A live attempt was genuinely made and failed this run, so it must not be
    # counted as an avoided external call even though it served fallback data.
    assert stats["external_source_calls_avoided"] is False
    assert [item["job_key"] for item in kept] == ["linkedin:1"]
    assert kept[0]["posted_age_days"] > 1

    # The live failure must still be recorded for future backoff decisions...
    assert load_linkedin_failure_backoff(SOURCE_LINKEDIN, signature) is True
    # ...and the borrowed snapshot itself must not have been refreshed.
    with db_conn() as conn:
        row = conn.execute(
            "SELECT updated_at FROM source_discovery_cache WHERE source = ? AND signature = ? AND status = 'success'",
            (SOURCE_LINKEDIN, signature),
        ).fetchone()
    assert row["updated_at"] == stale_updated_at


def test_linkedin_stale_fallback_does_not_exceed_configured_max_age(monkeypatch):
    """A snapshot older than linkedin_stale_fallback_max_age_minutes must not
    be served as a fallback -- active backoff must still return empty results,
    exactly as before the stale-fallback feature existed."""
    from job_hunter_agent.scrapers import linkedin
    from job_hunter_agent import source_runner
    from job_hunter_agent.global_settings import get_linkedin_stale_fallback_max_age_minutes

    _clear_cache()
    calls = []

    class FakeLinkedInScraper:
        def __init__(self, **kwargs):
            calls.append(kwargs)
            self._discovery_records = kwargs["discovery_records"]
            self._discovery_capture = kwargs["discovery_capture"]
            self._discovery_status = kwargs["discovery_status"]

        def scrape(self):
            if self._discovery_records is not None:
                self._discovery_status["complete"] = True
                return list(self._discovery_records), [], []
            record = {"job_key": "linkedin:1", "title": "Policy Officer", "posted_age_days": 1}
            self._discovery_capture.append(dict(record))
            self._discovery_status["complete"] = True
            return [dict(record)], [], []

    monkeypatch.setattr(linkedin, "LinkedInScraper", FakeLinkedInScraper)

    first = _make_context()
    first.enabled_sources = [SOURCE_LINKEDIN]
    source_runner.run_enabled_sources(first)
    signature = first.source_cache_stats[SOURCE_LINKEDIN]["signature"]

    max_age_minutes = get_linkedin_stale_fallback_max_age_minutes()
    too_old = (
        datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes + 60)
    ).isoformat(timespec="seconds")
    with db_conn() as conn:
        conn.execute(
            "UPDATE source_discovery_cache SET updated_at = ? WHERE source = ? AND signature = ? AND status = 'success'",
            (too_old, SOURCE_LINKEDIN, signature),
        )
    save_source_failure_state(SOURCE_LINKEDIN, signature)

    second = _make_context()
    second.enabled_sources = [SOURCE_LINKEDIN]
    kept, _audit, _skills = source_runner.run_enabled_sources(second)

    assert second.source_cache_stats[SOURCE_LINKEDIN]["status"] == "BACKOFF"
    assert kept == []
