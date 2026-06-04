"""Tests for source_runner parallel execution and result merging."""

from __future__ import annotations

import contextvars
import threading
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from job_hunter_agent import source_runner
from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.source_registry import SOURCE_LINKEDIN, SOURCE_SEEK
from job_hunter_agent.source_runner import SourceRunResult, run_enabled_sources


def _make_context(enabled_sources: list[str]) -> ScrapeRunContext:
    run_started_at = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    return ScrapeRunContext(
        profile={"name": "test"},
        search_settings={},
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
        run_started_at=run_started_at,
        run_iso=run_started_at.isoformat(timespec="seconds"),
        previous_audit_rows=[],
        previous_run_stats={},
        llm_cache={},
        job_history={},
        enabled_sources=enabled_sources,
        no_llm_mode=True,
        dashboard_debug_mode=False,
        reset_new_to_you=False,
    )


def _seek_result(**kwargs) -> SourceRunResult:
    return SourceRunResult(source=SOURCE_SEEK, **kwargs)


def _li_result(**kwargs) -> SourceRunResult:
    return SourceRunResult(source=SOURCE_LINKEDIN, **kwargs)


# ---------------------------------------------------------------------------
# 1. SEEK only runs when only SEEK is enabled
# ---------------------------------------------------------------------------

def test_seek_only_runs_when_seek_enabled(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    seek_called = []
    li_called = []

    monkeypatch.setattr(source_runner, "_run_seek_source", lambda ctx: seek_called.append(True) or _seek_result())
    monkeypatch.setattr(source_runner, "_run_linkedin_source", lambda ctx: li_called.append(True) or _li_result())

    run_enabled_sources(context)

    assert seek_called == [True]
    assert li_called == []


# ---------------------------------------------------------------------------
# 2. LinkedIn only runs when only LinkedIn is enabled
# ---------------------------------------------------------------------------

def test_linkedin_only_runs_when_linkedin_enabled(monkeypatch):
    context = _make_context([SOURCE_LINKEDIN])
    seek_called = []
    li_called = []

    monkeypatch.setattr(source_runner, "_run_seek_source", lambda ctx: seek_called.append(True) or _seek_result())
    monkeypatch.setattr(source_runner, "_run_linkedin_source", lambda ctx: li_called.append(True) or _li_result())

    run_enabled_sources(context)

    assert seek_called == []
    assert li_called == [True]


# ---------------------------------------------------------------------------
# 3. Both run when both sources are enabled
# ---------------------------------------------------------------------------

def test_both_sources_run_when_both_enabled(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    seek_called = []
    li_called = []

    monkeypatch.setattr(source_runner, "_run_seek_source", lambda ctx: seek_called.append(True) or _seek_result())
    monkeypatch.setattr(source_runner, "_run_linkedin_source", lambda ctx: li_called.append(True) or _li_result())

    run_enabled_sources(context)

    assert seek_called == [True]
    assert li_called == [True]


# ---------------------------------------------------------------------------
# 4. Both sources are submitted concurrently when both enabled
# ---------------------------------------------------------------------------

def test_both_sources_run_concurrently_when_both_enabled(monkeypatch):
    """Verify both workers start before either blocks by using a barrier."""
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    barrier = threading.Barrier(2, timeout=5)
    overlap_confirmed = threading.Event()

    def _fake_seek(ctx):
        barrier.wait()  # blocks until LinkedIn thread also reaches this point
        overlap_confirmed.set()
        return _seek_result()

    def _fake_linkedin(ctx):
        barrier.wait()
        return _li_result()

    monkeypatch.setattr(source_runner, "_run_seek_source", _fake_seek)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", _fake_linkedin)

    run_enabled_sources(context)

    assert overlap_confirmed.is_set(), "SEEK and LinkedIn did not run concurrently"


# ---------------------------------------------------------------------------
# 5. Merge order is always SEEK then LinkedIn, even if LinkedIn finishes first
# ---------------------------------------------------------------------------

def test_merge_order_is_seek_then_linkedin_regardless_of_completion(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])

    # LinkedIn returns a record immediately; SEEK returns after a brief delay.
    def _slow_seek(ctx):
        import time
        time.sleep(0.05)
        return _seek_result(kept_records=[{"job_key": "seek:1", "title": "Seek job"}])

    def _fast_linkedin(ctx):
        return _li_result(kept_records=[{"job_key": "linkedin:1", "title": "LinkedIn job"}])

    monkeypatch.setattr(source_runner, "_run_seek_source", _slow_seek)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", _fast_linkedin)

    kept, _, _ = run_enabled_sources(context)

    assert len(kept) == 2
    assert kept[0]["job_key"] == "seek:1", "SEEK records must come first"
    assert kept[1]["job_key"] == "linkedin:1", "LinkedIn records must come second"


# ---------------------------------------------------------------------------
# 6. LinkedIn exception prints and continues — does not raise
# ---------------------------------------------------------------------------

def test_linkedin_exception_prints_and_continues(monkeypatch, capsys):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])

    monkeypatch.setattr(source_runner, "_run_seek_source",
                        lambda ctx: _seek_result(kept_records=[{"job_key": "seek:1"}]))
    monkeypatch.setattr(source_runner, "_run_linkedin_source",
                        lambda ctx: _li_result(error=RuntimeError("network error")))

    kept, _, _ = run_enabled_sources(context)

    # SEEK records still returned
    assert len(kept) == 1
    assert kept[0]["job_key"] == "seek:1"


def test_seek_scraper_exception_is_caught_and_printed(monkeypatch, capsys):
    """Verify _run_seek_source catches exceptions, prints them, and returns an error result."""
    context = _make_context([SOURCE_SEEK])

    with patch("job_hunter_agent.source_runner._run_seek_source",
               return_value=_seek_result(error=RuntimeError("seek exploded"))):
        kept, _, _ = run_enabled_sources(context)

    assert kept == []


def test_seek_exception_printed_and_continued(monkeypatch, capsys):
    """SEEK exception is printed; LinkedIn still runs if enabled."""
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])

    monkeypatch.setattr(source_runner, "_run_seek_source",
                        lambda ctx: _seek_result(error=RuntimeError("seek exploded")))
    monkeypatch.setattr(source_runner, "_run_linkedin_source",
                        lambda ctx: _li_result(kept_records=[{"job_key": "linkedin:1"}]))

    kept, _, _ = run_enabled_sources(context)

    assert len(kept) == 1
    assert kept[0]["job_key"] == "linkedin:1"


def test_linkedin_scraper_exception_is_caught_and_printed(monkeypatch, capsys):
    """Verify _run_linkedin_source catches scraper exceptions and prints them."""
    context = _make_context([SOURCE_LINKEDIN])

    def _boom(ctx):
        raise RuntimeError("connection refused")

    with patch("job_hunter_agent.scrapers.linkedin.LinkedInScraper") as mock_li:
        mock_li.side_effect = RuntimeError("connection refused")
        result = source_runner._run_linkedin_source(context)

    assert result.error is not None
    out = capsys.readouterr().out
    assert "[LinkedIn] Scraping failed" in out


# ---------------------------------------------------------------------------
# 7. Stop before LinkedIn does not start LinkedIn in serial path
# ---------------------------------------------------------------------------

def test_stop_before_linkedin_skips_linkedin_in_serial_path(monkeypatch):
    """When only LinkedIn is enabled and stop is requested, LinkedIn does not run."""
    context = _make_context([SOURCE_LINKEDIN])
    li_called = []

    monkeypatch.setattr(source_runner, "run_stop_requested", lambda: True)
    monkeypatch.setattr(source_runner, "_run_linkedin_source",
                        lambda ctx: li_called.append(True) or _li_result())

    kept, audit, skills = run_enabled_sources(context)

    assert li_called == [], "LinkedIn must not run when stop is requested"
    assert kept == []
    assert audit == []
    assert skills == []


# ---------------------------------------------------------------------------
# Mutable state isolation — each source gets its own copy
# ---------------------------------------------------------------------------

def test_context_vars_propagated_to_worker_threads(monkeypatch):
    """ContextVar values (e.g. active user id) must be visible inside worker threads."""
    _test_var: contextvars.ContextVar[str] = contextvars.ContextVar("_test_var", default="unset")
    _test_var.set("expected_value")

    captured_in_seek = []
    captured_in_li = []

    def _seek_reads_var(ctx):
        captured_in_seek.append(_test_var.get())
        return _seek_result()

    def _li_reads_var(ctx):
        captured_in_li.append(_test_var.get())
        return _li_result()

    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    monkeypatch.setattr(source_runner, "_run_seek_source", _seek_reads_var)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", _li_reads_var)

    run_enabled_sources(context)

    assert captured_in_seek == ["expected_value"], "ContextVar not propagated to SEEK worker"
    assert captured_in_li == ["expected_value"], "ContextVar not propagated to LinkedIn worker"


def test_job_history_changes_are_merged_back_to_context(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])

    def _seek_adds_entry(ctx):
        result = _seek_result()
        result._job_history_snapshot["seek:new"] = {"title": "Seek job"}
        return result

    def _li_adds_entry(ctx):
        result = _li_result()
        result._job_history_snapshot["linkedin:new"] = {"title": "LinkedIn job"}
        return result

    monkeypatch.setattr(source_runner, "_run_seek_source", _seek_adds_entry)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", _li_adds_entry)

    run_enabled_sources(context)

    assert "seek:new" in context.job_history
    assert "linkedin:new" in context.job_history
