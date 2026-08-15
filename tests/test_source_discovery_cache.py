"""Regression coverage for persisted source-discovery snapshots."""

from __future__ import annotations

import importlib
from datetime import datetime, timezone

from job_hunter_agent.database import db_conn
from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.source_discovery_cache import (
    build_source_search_signature,
    load_linkedin_failure_backoff,
    load_source_discovery_snapshot,
    save_source_discovery_snapshot,
    save_source_failure_state,
)
from job_hunter_agent.source_registry import SOURCE_APSJOBS, SOURCE_LINKEDIN


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


def test_all_linkedin_timeouts_enter_bounded_backoff(monkeypatch):
    from job_hunter_agent.scrapers import linkedin
    from job_hunter_agent import source_runner

    _clear_cache()
    calls = []

    class FakeLinkedInScraper:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def scrape(self):
            calls[-1]["discovery_status"]["all_targets_timed_out"] = True
            calls[-1]["discovery_status"]["complete"] = False
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
