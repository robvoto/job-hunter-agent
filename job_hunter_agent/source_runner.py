"""Helpers for source runner."""

from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.run_control import run_stop_requested, set_run_progress
from job_hunter_agent.profile_store import GovPref, KEY_PREFER_SECTOR, normalize_sector_preference_values
from job_hunter_agent.global_settings import get_seek_assisted_verification_enabled
from job_hunter_agent.scrapers.apsjobs import APSJobsScraper
from job_hunter_agent.scrapers.seek import build_seek_search_targets
from job_hunter_agent.scrapers.seek_runner import (
    BotChallengeDetected,
    SEEK_ASSISTED_VISIBILITY_WARNING,
    SEEK_BOT_CHALLENGE,
    SEEK_HUMAN_VERIFICATION,
    seek_scrape_to_records,
)
from job_hunter_agent.source_registry import SOURCE_APSJOBS, SOURCE_LINKEDIN, SOURCE_SEEK

logger = logging.getLogger(__name__)


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
            logger.warning("[SEEK] %s", SEEK_ASSISTED_VISIBILITY_WARNING)
            set_run_progress(SEEK_ASSISTED_VISIBILITY_WARNING)
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
            logger.warning(
                "[SEEK] Headless SEEK run hit %s; retrying with headless=False",
                failure_class,
            )
            set_run_progress("SEEK retrying with visible browser after a SEEK challenge")
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
    except Exception as exc:
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
    except Exception as exc:
        print(f"[LinkedIn] Scraping failed: {type(exc).__name__}: {exc}")
        return SourceRunResult(
            source=SOURCE_LINKEDIN,
            error=exc,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )


def _government_sector_selected(profile: dict) -> bool:
    preferences = profile.get("match_preferences", {})
    selected = normalize_sector_preference_values(
        preferences.get(KEY_PREFER_SECTOR) if isinstance(preferences, dict) else []
    )
    return GovPref.GOVERNMENT in selected


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
    except Exception as exc:
        print(f"[APSJobs] Scraping failed: {type(exc).__name__}: {exc}")
        return SourceRunResult(
            source=SOURCE_APSJOBS,
            error=exc,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )


def run_enabled_sources(context: ScrapeRunContext) -> tuple[list[dict], list[dict], list[dict]]:
    """Run all enabled sources and return merged (kept_records, audit_rows, skill_observations).

    When both SEEK and LinkedIn are enabled they run concurrently via a two-worker
    thread pool. Results are always merged in deterministic order: SEEK first,
    LinkedIn second, and APSJobs last if government jobs are enabled, regardless
    of which source finishes first.

    Mutable shared state (job_history, llm_cache) is isolated per source during
    execution and merged back into context after all sources complete.
    """
    kept_records: list[dict] = []
    audit_rows: list[dict] = []
    skill_observations: list[dict] = []

    seek_enabled = SOURCE_SEEK in context.enabled_sources
    li_enabled = SOURCE_LINKEDIN in context.enabled_sources
    apsjobs_enabled = _government_sector_selected(context.profile)

    print("[Seek] enabled" if seek_enabled else "[Seek] disabled in enabled_sources; skipping")
    print(
        "[LinkedIn] enabled" if li_enabled else "[LinkedIn] disabled in enabled_sources; skipping"
    )
    print("[APSJobs] enabled" if apsjobs_enabled else "[APSJobs] disabled; government not selected")

    if run_stop_requested():
        return kept_records, audit_rows, skill_observations

    results: list[SourceRunResult] = []

    if seek_enabled and li_enabled:
        set_run_progress("SEEK + LinkedIn running in parallel")
        ctx_seek = contextvars.copy_context()
        ctx_li = contextvars.copy_context()
        with ThreadPoolExecutor(max_workers=2) as pool:
            seek_future = pool.submit(ctx_seek.run, _run_seek_source, context)
            li_future = pool.submit(ctx_li.run, _run_linkedin_source, context)
            seek_result = seek_future.result()
            li_result = li_future.result()
        results = [seek_result, li_result]  # deterministic order: SEEK first
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

    # Collect outputs, skipping errored sources (LinkedIn errors already printed).
    for result in results:
        if result.error is not None:
            continue
        kept_records.extend(result.kept_records)
        audit_rows.extend(result.audit_rows)
        skill_observations.extend(result.skill_observations)

    return kept_records, audit_rows, skill_observations
