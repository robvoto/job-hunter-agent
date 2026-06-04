"""Helpers for source runner."""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.run_control import run_stop_requested, set_run_progress
from job_hunter_agent.source_registry import SOURCE_LINKEDIN, SOURCE_SEEK
from job_hunter_agent.scrapers.seek import build_seek_search_targets
from job_hunter_agent.scrapers.seek_runner import seek_scrape_to_records


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
        kept, audit, skills = seek_scrape_to_records(
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
            headless=bool(getattr(context, "headless", False)),
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


def run_enabled_sources(context: ScrapeRunContext) -> tuple[list[dict], list[dict], list[dict]]:
    """Run all enabled sources and return merged (kept_records, audit_rows, skill_observations).

    When both SEEK and LinkedIn are enabled they run concurrently via a two-worker
    thread pool. Results are always merged in deterministic order: SEEK first,
    LinkedIn second, regardless of which source finishes first.

    Mutable shared state (job_history, llm_cache) is isolated per source during
    execution and merged back into context after all sources complete.
    """
    kept_records: list[dict] = []
    audit_rows: list[dict] = []
    skill_observations: list[dict] = []

    seek_enabled = SOURCE_SEEK in context.enabled_sources
    li_enabled = SOURCE_LINKEDIN in context.enabled_sources

    print("[Seek] enabled" if seek_enabled else "[Seek] disabled in enabled_sources; skipping")
    print("[LinkedIn] enabled" if li_enabled else "[LinkedIn] disabled in enabled_sources; skipping")

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
