"""Helpers for source runner."""

from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any

from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.run_control import get_run_progress, run_stop_requested, set_run_progress
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.global_settings import get_seek_assisted_verification_enabled
from job_hunter_agent.scrapers.apsjobs import APSJobsScraper
from job_hunter_agent.scrapers.seek import build_seek_search_targets
from job_hunter_agent.scrapers.seek_runner import (
    BotChallengeDetected,
    SEEK_ASSISTED_BROWSER_SESSION_ENABLED,
    SEEK_BOT_CHALLENGE,
    SEEK_HUMAN_VERIFICATION,
    seek_scrape_to_records,
)
from job_hunter_agent.source_registry import SOURCE_APSJOBS, SOURCE_LINKEDIN, SOURCE_SEEK

logger = logging.getLogger(__name__)

SEEK_SOURCE_TIMEOUT_SECONDS = 90
LINKEDIN_SOURCE_TIMEOUT_SECONDS = 180
SOURCE_HEARTBEAT_SECONDS = 15
SEEK_SOURCE_TIMEOUT_MESSAGE = "SEEK is taking longer than expected; waiting for it to finish."
LINKEDIN_SOURCE_TIMEOUT_MESSAGE = "LinkedIn is taking longer than expected; waiting for it to finish."


@dataclass
class SourceRunResult:
    source: str
    kept_records: list[dict] = field(default_factory=list)
    audit_rows: list[dict] = field(default_factory=list)
    skill_observations: list[dict] = field(default_factory=list)
    error: Exception | None = None
    # Isolated copies mutated by the scraper — merged back into context after both sources finish.
    _job_history_snapshot: dict[str, Any] = field(default_factory=dict)
    _llm_cache_snapshot: dict[str, Any] = field(default_factory=dict)


def _run_seek_source(context: ScrapeRunContext) -> SourceRunResult:
    """Run SEEK with isolated mutable state.

    Takes shallow copies of job_history and llm_cache so SEEK and LinkedIn
    cannot corrupt each other's in-flight state when running concurrently.
    The mutated copies are returned for deterministic merge.
    """
    job_history: dict[str, Any] = dict(context.job_history)
    llm_cache: dict[str, Any] = dict(context.llm_cache)
    try:
        set_run_progress("Starting SEEK")
        search_targets = build_seek_search_targets(
            context.profile, context.configured_date_range, context.sort_newest_first
        )
        headless = bool(getattr(context, "headless", False))
        assisted_verification_enabled = (
            get_seek_assisted_verification_enabled() or context.dashboard_debug_mode
        )
        if assisted_verification_enabled:
            logger.warning("[SEEK] %s", SEEK_ASSISTED_BROWSER_SESSION_ENABLED)
            set_run_progress(SEEK_ASSISTED_BROWSER_SESSION_ENABLED)
        _seek_kwargs = dict(
            profile=context.profile,
            search_targets=search_targets,
            job_history=job_history,
            llm_cache=llm_cache,
            applied_job_keys=context.applied_job_keys,
            hidden_job_keys=context.hidden_job_keys,
            run_iso=context.run_iso,
            configured_date_range=context.configured_date_range,
            configured_seek_max_pages=context.configured_seek_max_pages,
            playwright_viewport_width=context.playwright_viewport_width,
            playwright_viewport_height=context.playwright_viewport_height,
            playwright_selector_timeout=context.playwright_selector_timeout,
            seek_parallel_detail_workers=context.seek_parallel_detail_workers,
            assisted_verification_enabled=assisted_verification_enabled,
        )
        try:
            kept, audit, skills = seek_scrape_to_records(**_seek_kwargs, headless=headless)
        except BotChallengeDetected as exc:
            failure_class = getattr(exc, "failure_class", "SEEK_UNKNOWN_FAILURE")
            if failure_class not in {SEEK_HUMAN_VERIFICATION, SEEK_BOT_CHALLENGE} or not headless:
                set_run_progress(str(exc))
                raise
            if not assisted_verification_enabled:
                logger.warning(
                    "[SEEK] Headless SEEK run hit %s but AWS browser session mode is disabled",
                    failure_class,
                )
                set_run_progress(str(exc))
                return SourceRunResult(
                    source=SOURCE_SEEK,
                    error=exc,
                    _job_history_snapshot=job_history,
                    _llm_cache_snapshot=llm_cache,
                )
            logger.warning(
                "[SEEK] Headless SEEK run hit %s; retrying with AWS browser session",
                failure_class,
            )
            set_run_progress("SEEK needs human verification. Open the AWS browser session and complete the check.")
            try:
                kept, audit, skills = seek_scrape_to_records(**_seek_kwargs, headless=False)
            except BotChallengeDetected as retry_exc:
                retry_failure_class = getattr(retry_exc, "failure_class", "SEEK_UNKNOWN_FAILURE")
                if retry_failure_class not in {SEEK_HUMAN_VERIFICATION, SEEK_BOT_CHALLENGE}:
                    set_run_progress(str(retry_exc))
                    raise
                logger.warning(
                    "[SEEK] Visible SEEK retry was still blocked (%s); continuing without SEEK results: %s",
                    retry_failure_class,
                    retry_exc,
                )
                set_run_progress(str(retry_exc))
                return SourceRunResult(
                    source=SOURCE_SEEK,
                    error=retry_exc,
                    _job_history_snapshot=job_history,
                    _llm_cache_snapshot=llm_cache,
                )
        return SourceRunResult(
            source=SOURCE_SEEK,
            kept_records=kept,
            audit_rows=audit,
            skill_observations=skills,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )
    except PartialSourceResultsError as exc:
        logger.exception("[SEEK] scraping failed after partial results")
        print(f"[SEEK] Scraping failed: {type(exc.original_error).__name__}: {exc.original_error}")
        return SourceRunResult(
            source=SOURCE_SEEK,
            kept_records=exc.kept_records,
            audit_rows=exc.audit_rows,
            skill_observations=exc.skill_observations,
            error=exc.original_error,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )
    except Exception as exc:
        logger.exception("[SEEK] scraping failed")
        print(f"[SEEK] Scraping failed: {type(exc).__name__}: {exc}")
        return SourceRunResult(
            source=SOURCE_SEEK,
            error=exc,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )


def _run_linkedin_source(context: ScrapeRunContext) -> SourceRunResult:
    """Run LinkedIn with isolated mutable state.

    Mirrors _run_seek_source isolation pattern.
    LinkedIn failures print and return an error result rather than raising,
    matching the existing behaviour.
    """
    job_history: dict[str, Any] = dict(context.job_history)
    llm_cache: dict[str, Any] = dict(context.llm_cache)
    try:
        set_run_progress("Starting LinkedIn")
        from job_hunter_agent.scrapers.linkedin import LinkedInScraper  # noqa: PLC0415

        li = LinkedInScraper(
            profile=context.profile,
            llm_cache=llm_cache,
            job_history=job_history,
            applied_job_keys=context.applied_job_keys,
            hidden_job_keys=context.hidden_job_keys,
            run_iso=context.run_iso,
        )
        kept, audit, skills = li.scrape()
        return SourceRunResult(
            source=SOURCE_LINKEDIN,
            kept_records=kept,
            audit_rows=audit,
            skill_observations=skills,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )
    except PartialSourceResultsError as exc:
        logger.exception("[LinkedIn] scraping failed after partial results")
        print(
            f"[LinkedIn] Scraping failed: {type(exc.original_error).__name__}: {exc.original_error}"
        )
        return SourceRunResult(
            source=SOURCE_LINKEDIN,
            kept_records=exc.kept_records,
            audit_rows=exc.audit_rows,
            skill_observations=exc.skill_observations,
            error=exc.original_error,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )
    except Exception as exc:
        logger.exception("[LinkedIn] scraping failed")
        print(f"[LinkedIn] Scraping failed: {type(exc).__name__}: {exc}")
        return SourceRunResult(
            source=SOURCE_LINKEDIN,
            error=exc,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )


def _run_apsjobs_source(context: ScrapeRunContext) -> SourceRunResult:
    job_history: dict[str, Any] = dict(context.job_history)
    llm_cache: dict[str, Any] = dict(context.llm_cache)
    try:
        set_run_progress("Starting APSJobs")
        scraper = APSJobsScraper(
            profile=context.profile,
            llm_cache=llm_cache,
            job_history=job_history,
            applied_job_keys=context.applied_job_keys,
            hidden_job_keys=context.hidden_job_keys,
            run_iso=context.run_iso,
        )
        kept, audit, skills = scraper.scrape()
        return SourceRunResult(
            source=SOURCE_APSJOBS,
            kept_records=kept,
            audit_rows=audit,
            skill_observations=skills,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )
    except PartialSourceResultsError as exc:
        print(
            f"[APSJobs] Scraping failed: {type(exc.original_error).__name__}: {exc.original_error}"
        )
        return SourceRunResult(
            source=SOURCE_APSJOBS,
            kept_records=exc.kept_records,
            audit_rows=exc.audit_rows,
            skill_observations=exc.skill_observations,
            error=exc.original_error,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )
    except Exception as exc:
        print(f"[APSJobs] Scraping failed: {type(exc).__name__}: {exc}")
        return SourceRunResult(
            source=SOURCE_APSJOBS,
            error=exc,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )


def _log_source_timeout_warning(
    source: str, message: str, *, elapsed_s: float | None = None
) -> None:
    logger.warning(
        "[%s][SOURCE_TIMEOUT] elapsed_s=%s progress=%r message=%s",
        source.upper(),
        int(elapsed_s) if elapsed_s is not None else -1,
        get_run_progress() or "(none)",
        message,
    )
    set_run_progress(message)


def _run_seek_and_linkedin_in_parallel(context: ScrapeRunContext) -> list[SourceRunResult]:
    """Run SEEK and LinkedIn without letting either source block the whole run."""
    executor = ThreadPoolExecutor(max_workers=2)
    ctx_seek = contextvars.copy_context()
    ctx_li = contextvars.copy_context()
    started_at: dict[str, float] = {
        SOURCE_SEEK: time.monotonic(),
        SOURCE_LINKEDIN: time.monotonic(),
    }
    seek_future = executor.submit(ctx_seek.run, _run_seek_source, context)
    li_future = executor.submit(ctx_li.run, _run_linkedin_source, context)
    futures = {seek_future: SOURCE_SEEK, li_future: SOURCE_LINKEDIN}
    deadlines = {
        seek_future: time.monotonic() + SEEK_SOURCE_TIMEOUT_SECONDS,
        li_future: time.monotonic() + LINKEDIN_SOURCE_TIMEOUT_SECONDS,
    }
    timeout_messages = {
        seek_future: SEEK_SOURCE_TIMEOUT_MESSAGE,
        li_future: LINKEDIN_SOURCE_TIMEOUT_MESSAGE,
    }
    timeout_warned: set[Any] = set()
    next_heartbeat_at = {
        SOURCE_SEEK: started_at[SOURCE_SEEK] + SOURCE_HEARTBEAT_SECONDS,
        SOURCE_LINKEDIN: started_at[SOURCE_LINKEDIN] + SOURCE_HEARTBEAT_SECONDS,
    }
    pending = set(futures)
    results_by_source: dict[str, SourceRunResult] = {}

    try:
        while pending:
            now = time.monotonic()
            timed_out = [
                future
                for future in list(pending)
                if now >= deadlines[future] and future not in timeout_warned
            ]
            for future in timed_out:
                source = futures[future]
                elapsed_s = now - started_at[source]
                _log_source_timeout_warning(
                    source,
                    timeout_messages[future],
                    elapsed_s=elapsed_s,
                )
                timeout_warned.add(future)

            for future in list(pending):
                source = futures[future]
                if now < next_heartbeat_at[source]:
                    continue
                elapsed_s = now - started_at[source]
                logger.info(
                    "[%s][SOURCE_RUNNING] elapsed_s=%d progress=%r",
                    source.upper(),
                    int(elapsed_s),
                    get_run_progress() or "(none)",
                )
                while next_heartbeat_at[source] <= now:
                    next_heartbeat_at[source] += SOURCE_HEARTBEAT_SECONDS

            if not pending:
                break

            next_deadline = min(deadlines[future] for future in pending)
            wait_timeout = max(0.1, min(1.0, next_deadline - time.monotonic()))
            done, _ = wait(pending, timeout=wait_timeout, return_when=FIRST_COMPLETED)
            for future in done:
                pending.remove(future)
                source = futures[future]
                try:
                    result = future.result()
                    results_by_source[source] = result
                    elapsed_s = time.monotonic() - started_at[source]
                    log = logger.warning if result.error is not None else logger.info
                    log(
                        "[%s][SOURCE_COMPLETE] elapsed_s=%d kept=%d audit=%d skills=%d error=%s",
                        source.upper(),
                        int(elapsed_s),
                        len(result.kept_records),
                        len(result.audit_rows),
                        len(result.skill_observations),
                        type(result.error).__name__ if result.error is not None else "none",
                    )
                except Exception as exc:
                    logger.exception(
                        "[%s] source worker failed after %ds",
                        source.upper(),
                        int(time.monotonic() - started_at[source]),
                    )
                    results_by_source[source] = SourceRunResult(source=source, error=exc)
    finally:
        executor.shutdown(wait=True, cancel_futures=False)

    if SOURCE_SEEK not in results_by_source:
        raise RuntimeError("SEEK source did not produce a result before parallel runner exit.")
    if SOURCE_LINKEDIN not in results_by_source:
        raise RuntimeError("LinkedIn source did not produce a result before parallel runner exit.")
    return [results_by_source[SOURCE_SEEK], results_by_source[SOURCE_LINKEDIN]]


def run_enabled_sources(context: ScrapeRunContext) -> tuple[list[dict], list[dict], list[dict]]:
    """Run all enabled sources and return merged (kept_records, audit_rows, skill_observations).

    When both SEEK and LinkedIn are enabled they run concurrently. Each source has a hard
    timeout so a stuck job board cannot block the whole run.

    Mutable shared state (job_history, llm_cache) is isolated per source during
    execution and merged back into context after all sources complete.
    """
    kept_records: list[dict] = []
    audit_rows: list[dict] = []
    skill_observations: list[dict] = []

    seek_enabled = SOURCE_SEEK in context.enabled_sources
    li_enabled = SOURCE_LINKEDIN in context.enabled_sources
    apsjobs_enabled = SOURCE_APSJOBS in context.enabled_sources

    print("[Seek] enabled" if seek_enabled else "[Seek] disabled in enabled_sources; skipping")
    print(
        "[LinkedIn] enabled" if li_enabled else "[LinkedIn] disabled in enabled_sources; skipping"
    )
    print(
        "[APSJobs] enabled" if apsjobs_enabled else "[APSJobs] disabled in enabled_sources; skipping"
    )

    if run_stop_requested():
        return kept_records, audit_rows, skill_observations

    results: list[SourceRunResult] = []

    if seek_enabled and li_enabled:
        set_run_progress("SEEK + LinkedIn running in parallel")
        results = _run_seek_and_linkedin_in_parallel(context)
    elif seek_enabled:
        results = [_run_seek_source(context)]
    elif li_enabled:
        if not run_stop_requested():
            results = [_run_linkedin_source(context)]

    if apsjobs_enabled and not run_stop_requested():
        results.append(_run_apsjobs_source(context))

    # Merge mutable state back into context in deterministic order.
    for result in results:
        context.job_history.update(result._job_history_snapshot)
        context.llm_cache.update(result._llm_cache_snapshot)

    # Collect outputs even from errored sources so partial current-run audit data survives.
    for result in results:
        kept_records.extend(result.kept_records)
        audit_rows.extend(result.audit_rows)
        skill_observations.extend(result.skill_observations)

    return kept_records, audit_rows, skill_observations
