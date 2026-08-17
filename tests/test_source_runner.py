"""Tests for source_runner parallel execution and result merging."""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from datetime import datetime, timezone
from unittest.mock import patch

from job_hunter_agent import source_runner
from job_hunter_agent.logging_utils import get_log_source_scope
from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.source_registry import SOURCE_APSJOBS, SOURCE_LINKEDIN, SOURCE_SEEK
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


def _aps_result(**kwargs) -> SourceRunResult:
    return SourceRunResult(source=SOURCE_APSJOBS, **kwargs)


# ---------------------------------------------------------------------------
# 1. SEEK only runs when only SEEK is enabled
# ---------------------------------------------------------------------------


def test_seek_only_runs_when_seek_enabled(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    seek_called = []
    li_called = []

    monkeypatch.setattr(
        source_runner, "_run_seek_source", lambda ctx: seek_called.append(True) or _seek_result()
    )
    monkeypatch.setattr(
        source_runner, "_run_linkedin_source", lambda ctx: li_called.append(True) or _li_result()
    )

    run_enabled_sources(context)

    assert seek_called == [True]
    assert li_called == []


def test_shutdown_does_not_commit_incomplete_source_snapshot(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    committed: list[str] = []

    monkeypatch.setattr(source_runner, "run_stop_requested", lambda: False)
    monkeypatch.setattr(source_runner, "run_shutdown_requested", lambda: True)
    monkeypatch.setattr(source_runner, "step_through_enabled", lambda: True)
    monkeypatch.setattr(
        source_runner,
        "_run_seek_source",
        lambda ctx: _seek_result(
            discovery_records=[{"job_key": "seek:1"}],
            source_cache_status="MISS",
            source_cache_signature="signature",
        ),
    )
    monkeypatch.setattr(
        source_runner,
        "save_source_discovery_snapshot",
        lambda *args: committed.append("snapshot"),
    )
    monkeypatch.setattr(
        source_runner,
        "save_source_failure_state",
        lambda *args: committed.append("failure"),
    )

    run_enabled_sources(context)

    assert committed == []


# ---------------------------------------------------------------------------
# 2. LinkedIn only runs when only LinkedIn is enabled
# ---------------------------------------------------------------------------


def test_linkedin_only_runs_when_linkedin_enabled(monkeypatch):
    context = _make_context([SOURCE_LINKEDIN])
    seek_called = []
    li_called = []

    monkeypatch.setattr(
        source_runner, "_run_seek_source", lambda ctx: seek_called.append(True) or _seek_result()
    )
    monkeypatch.setattr(
        source_runner, "_run_linkedin_source", lambda ctx: li_called.append(True) or _li_result()
    )

    run_enabled_sources(context)

    assert seek_called == []
    assert li_called == [True]


# ---------------------------------------------------------------------------
# 3. All enabled sources run when enabled
# ---------------------------------------------------------------------------


def test_all_enabled_sources_run_when_enabled(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN, SOURCE_APSJOBS])
    seek_called = []
    li_called = []
    aps_called = []

    monkeypatch.setattr(
        source_runner, "_run_seek_source", lambda ctx: seek_called.append(True) or _seek_result()
    )
    monkeypatch.setattr(
        source_runner, "_run_linkedin_source", lambda ctx: li_called.append(True) or _li_result()
    )
    monkeypatch.setattr(
        source_runner, "_run_apsjobs_source", lambda ctx: aps_called.append(True) or _aps_result()
    )

    run_enabled_sources(context)

    assert seek_called == [True]
    assert li_called == [True]
    assert aps_called == [True]


# ---------------------------------------------------------------------------
# 4. All enabled sources are submitted concurrently when multiple enabled
# ---------------------------------------------------------------------------


def test_all_enabled_sources_run_concurrently_when_multiple_enabled(monkeypatch):
    """Verify all workers start before any one blocks by using a barrier."""
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN, SOURCE_APSJOBS])
    barrier = threading.Barrier(3, timeout=5)
    overlap_confirmed = threading.Event()

    def _fake_seek(ctx):
        barrier.wait()  # blocks until the other source threads also reach this point
        overlap_confirmed.set()
        return _seek_result()

    def _fake_linkedin(ctx):
        barrier.wait()
        return _li_result()

    def _fake_apsjobs(ctx):
        barrier.wait()
        return _aps_result()

    monkeypatch.setattr(source_runner, "_run_seek_source", _fake_seek)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", _fake_linkedin)
    monkeypatch.setattr(source_runner, "_run_apsjobs_source", _fake_apsjobs)

    run_enabled_sources(context)

    assert overlap_confirmed.is_set(), "enabled sources did not run concurrently"


def test_step_through_runs_sources_serially(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN, SOURCE_APSJOBS])
    call_order: list[str] = []

    monkeypatch.setattr(source_runner, "step_through_enabled", lambda: True)
    monkeypatch.setattr(
        source_runner,
        "_run_seek_source",
        lambda ctx: call_order.append("seek") or _seek_result(),
    )
    monkeypatch.setattr(
        source_runner,
        "_run_linkedin_source",
        lambda ctx: call_order.append("linkedin") or _li_result(),
    )
    monkeypatch.setattr(
        source_runner,
        "_run_apsjobs_source",
        lambda ctx: call_order.append("apsjobs") or _aps_result(),
    )

    run_enabled_sources(context)

    assert call_order == ["seek", "linkedin", "apsjobs"]


# ---------------------------------------------------------------------------
# 5. Merge order follows enabled-source order, even if completion order differs
# ---------------------------------------------------------------------------


def test_merge_order_follows_enabled_sources_regardless_of_completion(monkeypatch):
    context = _make_context([SOURCE_APSJOBS, SOURCE_LINKEDIN, SOURCE_SEEK])

    # SEEK returns immediately; APSJobs returns after a brief delay.
    def _slow_apsjobs(ctx):
        import time

        time.sleep(0.05)
        return _aps_result(kept_records=[{"job_key": "apsjobs:1", "title": "APSJobs job"}])

    def _fast_linkedin(ctx):
        return _li_result(kept_records=[{"job_key": "linkedin:1", "title": "LinkedIn job"}])

    def _fast_seek(ctx):
        return _seek_result(kept_records=[{"job_key": "seek:1", "title": "Seek job"}])

    monkeypatch.setattr(source_runner, "_run_seek_source", _fast_seek)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", _fast_linkedin)
    monkeypatch.setattr(source_runner, "_run_apsjobs_source", _slow_apsjobs)

    kept, _, _ = run_enabled_sources(context)

    assert len(kept) == 3
    assert kept[0]["job_key"] == "apsjobs:1", "APSJobs records must follow enabled-source order"
    assert kept[1]["job_key"] == "linkedin:1", "LinkedIn records must follow enabled-source order"
    assert kept[2]["job_key"] == "seek:1", "SEEK records must follow enabled-source order"


# ---------------------------------------------------------------------------
# 6. LinkedIn exception prints and continues — does not raise
# ---------------------------------------------------------------------------


def test_linkedin_exception_prints_and_continues(monkeypatch, capsys):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])

    monkeypatch.setattr(
        source_runner,
        "_run_seek_source",
        lambda ctx: _seek_result(kept_records=[{"job_key": "seek:1"}]),
    )
    monkeypatch.setattr(
        source_runner,
        "_run_linkedin_source",
        lambda ctx: _li_result(error=RuntimeError("network error")),
    )

    kept, _, _ = run_enabled_sources(context)

    # SEEK records still returned
    assert len(kept) == 1
    assert kept[0]["job_key"] == "seek:1"


def test_seek_scraper_exception_is_caught_and_printed(monkeypatch, capsys):
    """Verify _run_seek_source catches exceptions, prints them, and returns an error result."""
    context = _make_context([SOURCE_SEEK])

    with patch(
        "job_hunter_agent.source_runner._run_seek_source",
        return_value=_seek_result(error=RuntimeError("seek exploded")),
    ):
        kept, _, _ = run_enabled_sources(context)

    assert kept == []


def test_seek_exception_printed_and_continued(monkeypatch, capsys):
    """SEEK exception is printed; LinkedIn still runs if enabled."""
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])

    monkeypatch.setattr(
        source_runner,
        "_run_seek_source",
        lambda ctx: _seek_result(error=RuntimeError("seek exploded")),
    )
    monkeypatch.setattr(
        source_runner,
        "_run_linkedin_source",
        lambda ctx: _li_result(kept_records=[{"job_key": "linkedin:1"}]),
    )

    kept, _, _ = run_enabled_sources(context)

    assert len(kept) == 1
    assert kept[0]["job_key"] == "linkedin:1"


def test_seek_headless_bot_challenge_retries_aws_browser_session(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = True
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}
    calls: list[bool] = []

    def fake_seek_scrape_to_records(*, headless, **kwargs):
        calls.append(headless)
        if headless:
            raise source_runner.BotChallengeDetected(
                "SEEK is showing a bot challenge page and did not reach job cards.",
                failure_class=source_runner.SEEK_BOT_CHALLENGE,
            )
        return ([{"job_key": "seek:1"}], [], [])

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)
    monkeypatch.setattr(source_runner, "get_seek_assisted_verification_enabled", lambda: True)

    result = source_runner._run_seek_source(context)

    assert calls == [True, False]
    assert result.error is None
    assert result.kept_records == [{"job_key": "seek:1"}]


def test_seek_headless_timeout_no_cards_retries_aws_browser_session(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = True
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}
    calls: list[bool] = []

    def fake_seek_scrape_to_records(*, headless, **kwargs):
        calls.append(headless)
        if headless:
            raise source_runner.BotChallengeDetected(
                "SEEK timed out before any job cards appeared.",
                failure_class=source_runner.SEEK_TIMEOUT_NO_CARDS,
            )
        return ([{"job_key": "seek:1"}], [], [])

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)
    monkeypatch.setattr(source_runner, "get_seek_assisted_verification_enabled", lambda: True)

    result = source_runner._run_seek_source(context)

    assert calls == [True, False]
    assert result.error is None
    assert result.kept_records == [{"job_key": "seek:1"}]


def test_seek_visible_timeout_no_cards_returns_error_result(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = True
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}
    calls: list[bool] = []

    def fake_seek_scrape_to_records(*, headless, **kwargs):
        calls.append(headless)
        raise source_runner.BotChallengeDetected(
            f"timeout-no-cards (headless={headless})",
            failure_class=source_runner.SEEK_TIMEOUT_NO_CARDS,
        )

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)
    monkeypatch.setattr(source_runner, "get_seek_assisted_verification_enabled", lambda: True)

    result = source_runner._run_seek_source(context)

    assert calls == [True, False]
    assert result.error is not None
    assert result.kept_records == []


def test_seek_headless_bot_challenge_without_assisted_mode_does_not_retry(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = True
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}
    calls: list[bool] = []

    def fake_seek_scrape_to_records(*, headless, **kwargs):
        calls.append(headless)
        raise source_runner.BotChallengeDetected(
            "SEEK is showing a bot challenge page and did not reach job cards.",
            failure_class=source_runner.SEEK_BOT_CHALLENGE,
        )

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)
    monkeypatch.setattr(source_runner, "get_seek_assisted_verification_enabled", lambda: False)

    result = source_runner._run_seek_source(context)

    assert calls == [True]
    assert result.error is not None
    assert result.kept_records == []


def test_apsjobs_runs_when_enabled_in_sources(monkeypatch):
    context = _make_context([SOURCE_APSJOBS])
    aps_called = []

    monkeypatch.setattr(source_runner, "_run_seek_source", lambda ctx: _seek_result())
    monkeypatch.setattr(source_runner, "_run_linkedin_source", lambda ctx: _li_result())
    monkeypatch.setattr(
        source_runner, "_run_apsjobs_source", lambda ctx: aps_called.append(True) or _aps_result()
    )

    run_enabled_sources(context)

    assert aps_called == [True]


def test_apsjobs_skips_when_not_enabled_in_sources(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    aps_called = []

    monkeypatch.setattr(source_runner, "_run_seek_source", lambda ctx: _seek_result())
    monkeypatch.setattr(source_runner, "_run_linkedin_source", lambda ctx: _li_result())
    monkeypatch.setattr(
        source_runner, "_run_apsjobs_source", lambda ctx: aps_called.append(True) or _aps_result()
    )

    run_enabled_sources(context)

    assert aps_called == []


def test_seek_visible_bot_challenge_returns_error_result(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = True
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}
    calls: list[bool] = []

    def fake_seek_scrape_to_records(*, headless, **kwargs):
        calls.append(headless)
        raise source_runner.BotChallengeDetected(
            f"challenge (headless={headless})",
            failure_class=source_runner.SEEK_BOT_CHALLENGE,
        )

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)
    monkeypatch.setattr(source_runner, "get_seek_assisted_verification_enabled", lambda: True)

    result = source_runner._run_seek_source(context)

    assert calls == [True, False]
    assert result.error is not None
    assert result.kept_records == []


def test_seek_human_verification_sets_user_facing_progress(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = False
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}
    messages: list[str] = []

    def fake_progress(message: str) -> None:
        messages.append(message)

    def fake_seek_scrape_to_records(*, headless, **kwargs):
        raise source_runner.BotChallengeDetected(
            "SEEK needs human verification. Open the AWS browser session and complete the check.",
            failure_class=source_runner.SEEK_HUMAN_VERIFICATION,
        )

    monkeypatch.setattr(source_runner, "set_run_progress", fake_progress)
    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)

    result = source_runner._run_seek_source(context)

    assert messages[-1].startswith("SEEK needs human verification")
    assert result.error is not None
    assert result.kept_records == []


def test_seek_assisted_verification_sets_browser_session_enabled_message(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = False
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}
    messages: list[str] = []

    def fake_progress(message: str) -> None:
        messages.append(message)

    def fake_seek_scrape_to_records(**kwargs):
        return ([{"job_key": "seek:1"}], [], [])

    monkeypatch.setattr(source_runner, "get_seek_assisted_verification_enabled", lambda: True)
    monkeypatch.setattr(source_runner, "set_run_progress", fake_progress)
    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)

    result = source_runner._run_seek_source(context)

    assert any(message == "AWS-assisted SEEK browser session is enabled." for message in messages)
    assert result.error is None
    assert result.kept_records == [{"job_key": "seek:1"}]


def test_linkedin_scraper_exception_is_caught_and_logged(monkeypatch, caplog):
    """Verify _run_linkedin_source catches scraper exceptions and logs them."""
    context = _make_context([SOURCE_LINKEDIN])

    def _boom(ctx):
        raise RuntimeError("connection refused")

    with caplog.at_level("ERROR"):
        with patch("job_hunter_agent.scrapers.linkedin.LinkedInScraper") as mock_li:
            mock_li.side_effect = RuntimeError("connection refused")
            result = source_runner._run_linkedin_source(context)

    assert result.error is not None
    assert "[LinkedIn] scraping failed" in caplog.text


# ---------------------------------------------------------------------------
# 7. Stop before LinkedIn does not start LinkedIn in serial path
# ---------------------------------------------------------------------------


def test_stop_before_linkedin_skips_linkedin_in_serial_path(monkeypatch):
    """When only LinkedIn is enabled and stop is requested, LinkedIn does not run."""
    context = _make_context([SOURCE_LINKEDIN])
    li_called = []

    monkeypatch.setattr(source_runner, "run_stop_requested", lambda: True)
    monkeypatch.setattr(
        source_runner, "_run_linkedin_source", lambda ctx: li_called.append(True) or _li_result()
    )

    kept, audit, skills = run_enabled_sources(context)

    assert li_called == [], "LinkedIn must not run when stop is requested"
    assert kept == []
    assert audit == []
    assert skills == []


# ---------------------------------------------------------------------------
# Mutable state isolation — each source gets its own copy
# ---------------------------------------------------------------------------


def test_context_vars_propagated_to_worker_threads(monkeypatch):
    """ContextVar values (e.g. active account id) must be visible inside worker threads."""
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


def test_parallel_runner_logs_source_start_and_complete_blocks(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="job_hunter_agent.source_runner")
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])

    monkeypatch.setattr(source_runner, "_run_seek_source", lambda ctx: _seek_result())
    monkeypatch.setattr(source_runner, "_run_linkedin_source", lambda ctx: _li_result())

    run_enabled_sources(context)

    assert "[SEEK][SOURCE_START]" in caplog.text
    assert "[LINKEDIN][SOURCE_START]" in caplog.text
    assert "[SEEK][SOURCE_COMPLETE]" in caplog.text
    assert "[LINKEDIN][SOURCE_COMPLETE]" in caplog.text


def test_run_enabled_sources_binds_source_scope_per_runner(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    captured_scopes: list[str] = []

    def _seek_with_scope(ctx):
        captured_scopes.append(get_log_source_scope())
        return _seek_result()

    def _linkedin_with_scope(ctx):
        captured_scopes.append(get_log_source_scope())
        return _li_result()

    monkeypatch.setattr(source_runner, "step_through_enabled", lambda: True)
    monkeypatch.setattr(source_runner, "_run_seek_source", _seek_with_scope)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", _linkedin_with_scope)

    run_enabled_sources(context)

    assert captured_scopes == ["SEEK", "LINKEDIN"]


def test_parallel_runner_keeps_results_after_timeout_warning(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="job_hunter_agent.source_runner")
    warnings = []
    monkeypatch.setattr(
        source_runner,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )

    def slow_seek(ctx):
        time.sleep(0.03)
        return _seek_result(kept_records=[{"job_key": "seek:1"}], audit_rows=[{"job_key": "seek:1"}])

    def slow_linkedin(ctx):
        time.sleep(0.03)
        return _li_result(
            kept_records=[{"job_key": "linkedin:1"}], audit_rows=[{"job_key": "linkedin:1"}]
        )

    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    monkeypatch.setattr(source_runner, "_run_seek_source", slow_seek)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", slow_linkedin)
    monkeypatch.setattr(source_runner, "SEEK_SOURCE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(source_runner, "LINKEDIN_SOURCE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(source_runner, "SOURCE_HEARTBEAT_SECONDS", 60)

    kept, audit, skills = run_enabled_sources(context)

    assert [record["job_key"] for record in kept] == ["seek:1", "linkedin:1"]
    assert [row["job_key"] for row in audit] == ["seek:1", "linkedin:1"]
    assert skills == []
    assert "[SOURCE_TIMEOUT]" in caplog.text
    assert "was skipped" not in caplog.text
    assert warnings
    assert warnings[0]["category"] == "source_timeout"


def test_parallel_runner_does_not_kill_active_source_after_timeout_warning(monkeypatch, caplog):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    def slow_seek(ctx):
        time.sleep(0.05)
        return _seek_result(
            kept_records=[{"job_key": "seek:late"}],
            audit_rows=[{"job_key": "seek:late"}],
        )

    def fast_linkedin(ctx):
        return _li_result(
            kept_records=[{"job_key": "linkedin:1"}],
            audit_rows=[{"job_key": "linkedin:1"}],
        )

    monkeypatch.setattr(source_runner, "_run_seek_source", slow_seek)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", fast_linkedin)
    monkeypatch.setattr(source_runner, "SEEK_SOURCE_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(source_runner, "SOURCE_HEARTBEAT_SECONDS", 60)
    kept, audit, skills = run_enabled_sources(context)

    assert [record["job_key"] for record in kept] == ["seek:late", "linkedin:1"]
    assert [row["job_key"] for row in audit] == ["seek:late", "linkedin:1"]
    assert skills == []
    assert "[SOURCE_TIMEOUT]" in caplog.text


def test_parallel_runner_detaches_unresponsive_source_after_stop_cleanup(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    stop_requested = threading.Event()
    hung_started = threading.Event()
    release_hung_worker = threading.Event()
    warnings: list[dict] = []
    result_holder: dict[str, tuple[list[dict], list[dict], list[dict]]] = {}

    def unresponsive_seek(ctx):
        hung_started.set()
        release_hung_worker.wait(timeout=2)
        return _seek_result(kept_records=[{"job_key": "seek:too-late"}])

    def fast_linkedin(ctx):
        return _li_result(
            kept_records=[{"job_key": "linkedin:1"}],
            audit_rows=[{"job_key": "linkedin:1"}],
        )

    monkeypatch.setattr(source_runner, "_run_seek_source", unresponsive_seek)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", fast_linkedin)
    monkeypatch.setattr(source_runner, "run_stop_requested", stop_requested.is_set)
    monkeypatch.setattr(source_runner, "SEEK_SOURCE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(source_runner, "LINKEDIN_SOURCE_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(source_runner, "SOURCE_TIMEOUT_GRACE_MIN_SECONDS", 0.02)
    monkeypatch.setattr(source_runner, "SOURCE_TIMEOUT_GRACE_MAX_SECONDS", 0.02)
    monkeypatch.setattr(source_runner, "SOURCE_TIMEOUT_GRACE_FRACTION", 0.0)
    monkeypatch.setattr(
        source_runner,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )

    runner = threading.Thread(
        target=lambda: result_holder.setdefault("result", run_enabled_sources(context)),
        daemon=True,
    )
    runner.start()
    assert hung_started.wait(timeout=1)

    started = time.monotonic()
    stop_requested.set()
    runner.join(timeout=0.5)
    elapsed = time.monotonic() - started
    release_hung_worker.set()

    assert not runner.is_alive()
    assert elapsed < 0.5
    kept, audit, skills = result_holder["result"]
    assert [record["job_key"] for record in kept] == ["linkedin:1"]
    assert [row["job_key"] for row in audit] == ["linkedin:1"]
    assert skills == []
    assert any(warning["category"] == "source_timeout" for warning in warnings)


def test_run_enabled_sources_fails_clearly_when_no_sources_are_enabled():
    context = _make_context([])

    with patch.object(source_runner, "SOURCE_RUNNER_NAMES", dict(source_runner.SOURCE_RUNNER_NAMES)):
        try:
            run_enabled_sources(context)
            raise AssertionError("expected clear no-sources error")
        except RuntimeError as exc:
            assert "No search sources are enabled for this run." in str(exc)


def test_parallel_runner_updates_progress_to_wait_for_pending_source(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])
    progress_states: list[tuple[str, dict]] = []
    seek_release = threading.Event()

    def fake_progress_state(message: str, **detail) -> None:
        progress_states.append((message, detail))

    def slow_seek(ctx):
        seek_release.wait(timeout=2)
        return _seek_result(kept_records=[{"job_key": "seek:1"}])

    def fast_linkedin(ctx):
        return _li_result(kept_records=[{"job_key": "linkedin:1"}])

    monkeypatch.setattr(source_runner, "set_run_progress_state", fake_progress_state)
    monkeypatch.setattr(source_runner, "_run_seek_source", slow_seek)
    monkeypatch.setattr(source_runner, "_run_linkedin_source", fast_linkedin)

    runner = threading.Thread(target=run_enabled_sources, args=(context,))
    runner.start()

    deadline = time.time() + 2
    while time.time() < deadline:
        if any(message == "Waiting for SEEK\nLinkedIn complete" for message, _ in progress_states):
            break
        time.sleep(0.01)
    seek_release.set()
    runner.join(timeout=2)

    waiting_states = [
        detail
        for message, detail in progress_states
        if message == "Waiting for SEEK\nLinkedIn complete"
    ]
    assert waiting_states
    assert waiting_states[-1]["stage"] == "source_collection"
    assert waiting_states[-1]["source"] == "generic"
    assert waiting_states[-1]["determinate"] is False


def test_run_seek_source_records_warning_on_failure(monkeypatch):
    warnings = []
    monkeypatch.setattr(
        source_runner,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    monkeypatch.setattr(source_runner, "build_seek_search_targets", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        source_runner,
        "seek_scrape_to_records",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("seek failed")),
    )

    result = source_runner._run_seek_source(_make_context([SOURCE_SEEK]))

    assert result.error is not None
    assert warnings
    assert warnings[0]["category"] == "source_failure"


def test_run_enabled_sources_keeps_partial_audit_rows_from_errored_source(monkeypatch):
    context = _make_context([SOURCE_SEEK, SOURCE_LINKEDIN])

    monkeypatch.setattr(
        source_runner,
        "_run_seek_source",
        lambda ctx: _seek_result(
            kept_records=[{"job_key": "seek:1"}],
            audit_rows=[{"job_key": "seek:1", "reject_reason": "ONET_FAR_OCCUPATION"}],
            error=RuntimeError("seek ended late"),
        ),
    )
    monkeypatch.setattr(
        source_runner,
        "_run_linkedin_source",
        lambda ctx: _li_result(
            kept_records=[{"job_key": "linkedin:1"}],
            audit_rows=[{"job_key": "linkedin:1", "reject_reason": "LLM_REJECT"}],
        ),
    )

    kept, audit, skills = run_enabled_sources(context)

    assert [record["job_key"] for record in kept] == ["seek:1", "linkedin:1"]
    assert [row["job_key"] for row in audit] == ["seek:1", "linkedin:1"]
    assert skills == []


def test_run_linkedin_source_preserves_partial_results_on_late_failure(monkeypatch):
    context = _make_context([SOURCE_LINKEDIN])

    class FakeLinkedInScraper:
        def __init__(self, **kwargs):
            pass

        def scrape(self):
            raise PartialSourceResultsError(
                SOURCE_LINKEDIN,
                kept_records=[{"job_key": "linkedin:1"}],
                audit_rows=[{"job_key": "linkedin:1", "reject_reason": "ONET_FAR_OCCUPATION"}],
                skill_observations=[{"kind": "note"}],
                original_error=RuntimeError("late linkedin failure"),
            )

    monkeypatch.setattr(
        source_runner,
        "LinkedInScraper",
        FakeLinkedInScraper,
        raising=False,
    )
    monkeypatch.setattr(
        __import__("job_hunter_agent.scrapers.linkedin", fromlist=["LinkedInScraper"]),
        "LinkedInScraper",
        FakeLinkedInScraper,
    )

    result = source_runner._run_linkedin_source(context)

    assert isinstance(result.error, RuntimeError)
    assert [record["job_key"] for record in result.kept_records] == ["linkedin:1"]
    assert [row["job_key"] for row in result.audit_rows] == ["linkedin:1"]
    assert result.skill_observations == [{"kind": "note"}]


def test_run_seek_source_preserves_partial_results_on_late_failure(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = True
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}

    def fake_seek_scrape_to_records(**kwargs):
        raise PartialSourceResultsError(
            SOURCE_SEEK,
            kept_records=[{"job_key": "seek:1"}],
            audit_rows=[{"job_key": "seek:1", "reject_reason": "ONET_FAR_OCCUPATION"}],
            skill_observations=[{"kind": "note"}],
            original_error=RuntimeError("late seek failure"),
        )

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)

    result = source_runner._run_seek_source(context)

    assert isinstance(result.error, RuntimeError)
    assert [record["job_key"] for record in result.kept_records] == ["seek:1"]
    assert [row["job_key"] for row in result.audit_rows] == ["seek:1"]
    assert result.skill_observations == [{"kind": "note"}]


def test_run_seek_source_uses_non_empty_warning_message_for_blank_exception(monkeypatch):
    context = _make_context([SOURCE_SEEK])
    context.headless = True
    context.profile = {"search_settings": {"keywords": "Business Analyst", "locations": ["Sydney"]}}
    recorded: list[dict] = []

    def fake_seek_scrape_to_records(**kwargs):
        raise PartialSourceResultsError(
            SOURCE_SEEK,
            kept_records=[],
            audit_rows=[],
            skill_observations=[],
            original_error=TimeoutError(),
        )

    monkeypatch.setattr(source_runner, "seek_scrape_to_records", fake_seek_scrape_to_records)
    monkeypatch.setattr(
        source_runner,
        "record_system_warning",
        lambda **kwargs: recorded.append(kwargs),
    )

    result = source_runner._run_seek_source(context)

    assert isinstance(result.error, TimeoutError)
    assert recorded
    assert recorded[0]["message"] == "TimeoutError"


# ---------------------------------------------------------------------------
# LinkedIn circuit-breaker: truthful reporting + backoff-decoupling regressions
# ---------------------------------------------------------------------------


def _install_fake_linkedin_scraper(monkeypatch, discovery_status_updates: dict, kept=None, audit=None, skills=None):
    class FakeLinkedInScraper:
        def __init__(self, **kwargs):
            self._discovery_status = kwargs["discovery_status"]

        def scrape(self):
            self._discovery_status.update(discovery_status_updates)
            return kept or [], audit or [], skills or []

    monkeypatch.setattr(source_runner, "LinkedInScraper", FakeLinkedInScraper, raising=False)
    monkeypatch.setattr(
        __import__("job_hunter_agent.scrapers.linkedin", fromlist=["LinkedInScraper"]),
        "LinkedInScraper",
        FakeLinkedInScraper,
    )


def test_run_linkedin_source_full_failure_reports_error_and_backoff(monkeypatch):
    context = _make_context([SOURCE_LINKEDIN])
    warnings: list[dict] = []
    monkeypatch.setattr(
        source_runner,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    _install_fake_linkedin_scraper(
        monkeypatch,
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
            "elapsed_seconds": 45.0,
            "final_status": "full_failure",
        },
    )

    result = source_runner._run_linkedin_source(context)

    assert result.error is not None
    assert result.source_failure_backoff is True
    assert warnings
    assert warnings[0]["category"] == "source_failure"


def test_run_linkedin_source_healthy_zero_rows_reports_no_error(monkeypatch):
    context = _make_context([SOURCE_LINKEDIN])
    warnings: list[dict] = []
    monkeypatch.setattr(
        source_runner,
        "record_system_warning",
        lambda **kwargs: warnings.append(kwargs) or kwargs,
    )
    _install_fake_linkedin_scraper(
        monkeypatch,
        {
            "complete": True,
            "total_targets": 3,
            "attempted_targets": 3,
            "succeeded_targets": 3,
            "timed_out_targets": 0,
            "failed_targets": 0,
            "skipped_after_breaker": 0,
            "circuit_breaker_tripped": False,
            "rows_collected": 0,
            "elapsed_seconds": 5.0,
            "final_status": "healthy",
        },
    )

    result = source_runner._run_linkedin_source(context)

    assert result.error is None
    assert result.source_failure_backoff is False
    assert warnings == []


def test_run_enabled_sources_writes_backoff_state_despite_error(monkeypatch):
    """Regression test: an errored LinkedIn result must still trigger
    save_source_failure_state when source_failure_backoff is set, even though
    result.error is not None. This is the exact bug that previously caused the
    commit loop to silently skip persisting backoff state on full failure."""
    context = _make_context([SOURCE_LINKEDIN])
    committed: list[tuple] = []

    monkeypatch.setattr(
        source_runner,
        "_run_linkedin_source",
        lambda ctx: _li_result(
            error=RuntimeError("LinkedIn source failed"),
            source_failure_backoff=True,
            source_cache_status="MISS",
            source_cache_signature="sig",
            discovery_records=[],
        ),
    )
    monkeypatch.setattr(
        source_runner,
        "save_source_failure_state",
        lambda source, signature: committed.append(("failure", source, signature)),
    )
    monkeypatch.setattr(
        source_runner,
        "save_source_discovery_snapshot",
        lambda *args: committed.append(("snapshot",) + args),
    )

    run_enabled_sources(context)

    assert committed == [("failure", SOURCE_LINKEDIN, "sig")]


def test_run_enabled_sources_skips_snapshot_for_non_backoff_error(monkeypatch):
    """A generic (non-LinkedIn-breaker-style) error must not write a success
    snapshot, and must not write backoff state either since source_failure_backoff
    is False."""
    context = _make_context([SOURCE_LINKEDIN])
    committed: list[tuple] = []

    monkeypatch.setattr(
        source_runner,
        "_run_linkedin_source",
        lambda ctx: _li_result(
            error=RuntimeError("some unrelated failure"),
            source_failure_backoff=False,
            source_cache_status="MISS",
            source_cache_signature="sig",
            discovery_records=[],
        ),
    )
    monkeypatch.setattr(
        source_runner,
        "save_source_failure_state",
        lambda source, signature: committed.append(("failure", source, signature)),
    )
    monkeypatch.setattr(
        source_runner,
        "save_source_discovery_snapshot",
        lambda *args: committed.append(("snapshot",) + args),
    )

    run_enabled_sources(context)

    assert committed == []
