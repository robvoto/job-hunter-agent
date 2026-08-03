"""Helpers for source runner."""

from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.run_control import (
    get_run_progress,
    request_run_stop,
    run_stop_requested,
    set_run_progress,
    set_run_progress_state,
    step_through_enabled,
)
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.global_settings import get_seek_assisted_verification_enabled
from job_hunter_agent.scrapers.apsjobs import APSJobsScraper
from job_hunter_agent.scrapers.seek import build_seek_search_targets
from job_hunter_agent.scrapers.seek_runner import (
    BotChallengeDetected,
    SEEK_ASSISTED_BROWSER_SESSION_ENABLED,
    SEEK_BOT_CHALLENGE,
    SEEK_HUMAN_VERIFICATION,
    SEEK_TIMEOUT_NO_CARDS,
    seek_scrape_to_records,
)
from job_hunter_agent.source_registry import SOURCE_APSJOBS, SOURCE_LINKEDIN, SOURCE_SEEK
from job_hunter_agent.source_registry import get_source_display_label
from job_hunter_agent.text_processing import list_to_phrase
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)
from job_hunter_agent.logging_utils import format_log_block
from job_hunter_agent.logging_utils import reset_log_source_scope, set_log_source_scope

logger = logging.getLogger(__name__)

SEEK_SOURCE_TIMEOUT_SECONDS = 90
LINKEDIN_SOURCE_TIMEOUT_SECONDS = 180
APSJOBS_SOURCE_TIMEOUT_SECONDS = 120
DEFAULT_SOURCE_TIMEOUT_SECONDS = 120
SOURCE_HEARTBEAT_SECONDS = 15
SOURCE_TIMEOUT_GRACE_MIN_SECONDS = 0.25
SOURCE_TIMEOUT_GRACE_MAX_SECONDS = 10.0
SOURCE_TIMEOUT_GRACE_FRACTION = 0.1
SEEK_SOURCE_TIMEOUT_MESSAGE = "SEEK is taking longer than expected; waiting for it to finish."
LINKEDIN_SOURCE_TIMEOUT_MESSAGE = "LinkedIn is taking longer than expected; waiting for it to finish."
APSJOBS_SOURCE_TIMEOUT_MESSAGE = "APSJobs is taking longer than expected; waiting for it to finish."


def _exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or type(exc).__name__

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

    Takes shallow copies of job_history and llm_cache so enabled source workers
    cannot corrupt each other's in-flight state when running concurrently.
    The mutated copies are returned for deterministic merge.
    """
    job_history: dict[str, Any] = dict(context.job_history)
    llm_cache: dict[str, Any] = dict(context.llm_cache)
    try:
        set_run_progress_state(
            "Starting SEEK",
            stage="starting",
            source="seek",
            headline="Starting SEEK",
            determinate=False,
        )
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
            if failure_class not in {
                SEEK_HUMAN_VERIFICATION,
                SEEK_BOT_CHALLENGE,
                SEEK_TIMEOUT_NO_CARDS,
            } or not headless:
                set_run_progress(_exception_message(exc))
                _record_source_warning(
                    source=SOURCE_SEEK,
                    severity="warning",
                    category="source_failure",
                    message=_exception_message(exc),
                    run_id=context.run_iso,
                    context={
                        "failure_class": failure_class,
                        "headless": headless,
                        "assisted_verification_enabled": assisted_verification_enabled,
                    },
                    fingerprint_parts=(
                        "source_failure",
                        SOURCE_SEEK,
                        failure_class,
                        _exception_message(exc),
                    ),
                )
                raise
            if not assisted_verification_enabled:
                logger.warning(
                    "[SEEK] Headless SEEK run hit %s but AWS browser session mode is disabled",
                    failure_class,
                )
                set_run_progress(_exception_message(exc))
                _record_source_warning(
                    source=SOURCE_SEEK,
                    severity="warning",
                    category="source_failure",
                    message=_exception_message(exc),
                    run_id=context.run_iso,
                    context={
                        "failure_class": failure_class,
                        "headless": headless,
                        "assisted_verification_enabled": assisted_verification_enabled,
                    },
                    fingerprint_parts=(
                        "source_failure",
                        SOURCE_SEEK,
                        failure_class,
                        _exception_message(exc),
                    ),
                )
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
                if retry_failure_class not in {
                    SEEK_HUMAN_VERIFICATION,
                    SEEK_BOT_CHALLENGE,
                    SEEK_TIMEOUT_NO_CARDS,
                }:
                    set_run_progress(str(retry_exc))
                    raise
                logger.warning(
                    "[SEEK] Visible SEEK retry was still blocked (%s); continuing without SEEK results: %s",
                    retry_failure_class,
                    retry_exc,
                )
                set_run_progress(_exception_message(retry_exc))
                _record_source_warning(
                    source=SOURCE_SEEK,
                    severity="warning",
                    category="source_failure",
                    message=_exception_message(retry_exc),
                    run_id=context.run_iso,
                    context={
                        "failure_class": retry_failure_class,
                        "headless": False,
                        "assisted_verification_enabled": assisted_verification_enabled,
                    },
                    fingerprint_parts=(
                        "source_failure",
                        SOURCE_SEEK,
                        retry_failure_class,
                        _exception_message(retry_exc),
                    ),
                )
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
        print(
            f"[SEEK] Scraping failed: {type(exc.original_error).__name__}: "
            f"{_exception_message(exc.original_error)}"
        )
        _record_source_warning(
            source=SOURCE_SEEK,
            severity="warning",
            category="source_failure",
            message=_exception_message(exc.original_error),
            run_id=context.run_iso,
            context={
                "error_type": type(exc.original_error).__name__,
                "partial_results": True,
                "kept_records": len(exc.kept_records),
                "audit_rows": len(exc.audit_rows),
            },
            fingerprint_parts=(
                "source_failure",
                SOURCE_SEEK,
                type(exc.original_error).__name__,
                _exception_message(exc.original_error),
            ),
        )
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
        print(f"[SEEK] Scraping failed: {type(exc).__name__}: {_exception_message(exc)}")
        _record_source_warning(
            source=SOURCE_SEEK,
            severity="error",
            category="source_failure",
            message=_exception_message(exc),
            run_id=context.run_iso,
            context={
                "error_type": type(exc).__name__,
                "headless": headless,
            },
            fingerprint_parts=(
                "source_failure",
                SOURCE_SEEK,
                type(exc).__name__,
                _exception_message(exc),
            ),
        )
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
        set_run_progress_state(
            "Starting LinkedIn",
            stage="starting",
            source="linkedin",
            headline="Starting LinkedIn",
            determinate=False,
        )
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
            f"[LinkedIn] Scraping failed: {type(exc.original_error).__name__}: "
            f"{_exception_message(exc.original_error)}"
        )
        _record_source_warning(
            source=SOURCE_LINKEDIN,
            severity="warning",
            category="source_failure",
            message=_exception_message(exc.original_error),
            run_id=context.run_iso,
            context={
                "error_type": type(exc.original_error).__name__,
                "partial_results": True,
                "kept_records": len(exc.kept_records),
                "audit_rows": len(exc.audit_rows),
            },
            fingerprint_parts=(
                "source_failure",
                SOURCE_LINKEDIN,
                type(exc.original_error).__name__,
                _exception_message(exc.original_error),
            ),
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
        print(f"[LinkedIn] Scraping failed: {type(exc).__name__}: {_exception_message(exc)}")
        _record_source_warning(
            source=SOURCE_LINKEDIN,
            severity="error",
            category="source_failure",
            message=_exception_message(exc),
            run_id=context.run_iso,
            context={
                "error_type": type(exc).__name__,
            },
            fingerprint_parts=(
                "source_failure",
                SOURCE_LINKEDIN,
                type(exc).__name__,
                _exception_message(exc),
            ),
        )
        return SourceRunResult(
            source=SOURCE_LINKEDIN,
            error=exc,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )


def _run_apsjobs_source(context: ScrapeRunContext) -> SourceRunResult:
    """Run APS Jobs with isolated mutable state for safe parallel collection."""
    job_history: dict[str, Any] = dict(context.job_history)
    llm_cache: dict[str, Any] = dict(context.llm_cache)
    try:
        set_run_progress_state(
            "Starting APSJobs",
            stage="starting",
            source="apsjobs",
            headline="Starting APS Jobs",
            determinate=False,
        )
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
        _record_source_warning(
            source=SOURCE_APSJOBS,
            severity="warning",
            category="source_failure",
            message=str(exc.original_error),
            run_id=context.run_iso,
            context={
                "error_type": type(exc.original_error).__name__,
                "partial_results": True,
                "kept_records": len(exc.kept_records),
                "audit_rows": len(exc.audit_rows),
            },
            fingerprint_parts=(
                "source_failure",
                SOURCE_APSJOBS,
                type(exc.original_error).__name__,
                str(exc.original_error),
            ),
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
        _record_source_warning(
            source=SOURCE_APSJOBS,
            severity="error",
            category="source_failure",
            message=str(exc),
            run_id=context.run_iso,
            context={
                "error_type": type(exc).__name__,
            },
            fingerprint_parts=("source_failure", SOURCE_APSJOBS, type(exc).__name__, str(exc)),
        )
        return SourceRunResult(
            source=SOURCE_APSJOBS,
            error=exc,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
        )


SOURCE_RUNNER_NAMES: dict[str, str] = {
    SOURCE_SEEK: "_run_seek_source",
    SOURCE_LINKEDIN: "_run_linkedin_source",
    SOURCE_APSJOBS: "_run_apsjobs_source",
}


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
    record_system_warning(
        severity="warning",
        category="source_timeout",
        source=source,
        message=message,
        fingerprint=make_system_warning_fingerprint(
            "source_timeout",
            source,
            message,
        ),
        context={
            "elapsed_s": int(elapsed_s) if elapsed_s is not None else None,
            "progress": get_run_progress() or "",
        },
    )


def _record_source_warning(
    *,
    source: str,
    severity: str,
    category: str,
    message: str,
    run_id: str,
    context: dict[str, Any],
    fingerprint_parts: tuple[Any, ...],
) -> None:
    record_system_warning(
        severity=severity,
        category=category,
        source=source,
        message=message,
        fingerprint=make_system_warning_fingerprint(*fingerprint_parts),
        run_id=run_id,
        context=context,
    )


def _source_timeout_seconds(source: str) -> int:
    if source == SOURCE_SEEK:
        return int(SEEK_SOURCE_TIMEOUT_SECONDS)
    if source == SOURCE_LINKEDIN:
        return int(LINKEDIN_SOURCE_TIMEOUT_SECONDS)
    if source == SOURCE_APSJOBS:
        return int(APSJOBS_SOURCE_TIMEOUT_SECONDS)
    return int(DEFAULT_SOURCE_TIMEOUT_SECONDS)


def _source_timeout_message(source: str) -> str:
    if source == SOURCE_SEEK:
        return SEEK_SOURCE_TIMEOUT_MESSAGE
    if source == SOURCE_LINKEDIN:
        return LINKEDIN_SOURCE_TIMEOUT_MESSAGE
    if source == SOURCE_APSJOBS:
        return APSJOBS_SOURCE_TIMEOUT_MESSAGE
    return f"{get_source_display_label(source)} is taking longer than expected; waiting for it to finish."


def _source_stop_cleanup_seconds(source: str) -> float:
    """Return the bounded cleanup window after a stop request reaches a source."""
    soft_timeout = float(_source_timeout_seconds(source))
    return min(
        SOURCE_TIMEOUT_GRACE_MAX_SECONDS,
        max(SOURCE_TIMEOUT_GRACE_MIN_SECONDS, soft_timeout * SOURCE_TIMEOUT_GRACE_FRACTION),
    )


def _source_hard_timeout_seconds(source: str) -> float:
    """Return the absolute source deadline including its cooperative cleanup window."""
    return float(_source_timeout_seconds(source)) + _source_stop_cleanup_seconds(source)


def _log_source_start(source: str, *, execution_mode: str) -> None:
    logger.info(
        format_log_block(
            f"{source.upper()}][SOURCE_START",
            {
                "source": get_source_display_label(source),
                "execution_mode": execution_mode,
                "timeout_seconds": _source_timeout_seconds(source),
            },
        )
    )


def _log_source_complete(result: SourceRunResult, *, elapsed_s: float) -> None:
    log = logger.warning if result.error is not None else logger.info
    log(
        format_log_block(
            f"{result.source.upper()}][SOURCE_COMPLETE",
            {
                "source": get_source_display_label(result.source),
                "elapsed_seconds": int(elapsed_s),
                "kept": len(result.kept_records),
                "audit": len(result.audit_rows),
                "skills": len(result.skill_observations),
                "error": type(result.error).__name__ if result.error is not None else "none",
            },
        )
    )


def _parallel_completion_progress(completed_source: str, pending_sources: Sequence[str]) -> str:
    completed_label = get_source_display_label(completed_source)
    if not pending_sources:
        return f"{completed_label} complete"
    waiting_labels = [get_source_display_label(source) for source in pending_sources]
    return (
        f"Waiting for {list_to_phrase(waiting_labels)}\n"
        f"{completed_label} complete"
    )


def _enabled_source_order(context: ScrapeRunContext) -> list[str]:
    enabled_sources: list[str] = []
    for source in context.enabled_sources:
        source_key = str(source or "").strip().lower()
        if not source_key:
            continue
        if source_key not in SOURCE_RUNNER_NAMES:
            raise RuntimeError(f"No source runner registered for enabled source {source_key!r}")
        if source_key not in enabled_sources:
            enabled_sources.append(source_key)
    return enabled_sources


def _get_source_runner(source: str) -> Callable[[ScrapeRunContext], SourceRunResult]:
    runner_name = SOURCE_RUNNER_NAMES.get(source)
    if not runner_name:
        raise RuntimeError(f"No source runner registered for source {source!r}")
    runner = globals().get(runner_name)
    if not callable(runner):
        raise RuntimeError(f"Source runner {runner_name!r} is not available")
    return runner


def _run_source_with_scope(
    source: str,
    runner: Callable[[ScrapeRunContext], SourceRunResult],
    context: ScrapeRunContext,
) -> SourceRunResult:
    token = set_log_source_scope(source)
    try:
        return runner(context)
    finally:
        reset_log_source_scope(token)


def _run_sources_in_parallel(
    context: ScrapeRunContext, source_order: Sequence[str]
) -> list[SourceRunResult]:
    if not source_order:
        return []

    executor = ThreadPoolExecutor(max_workers=len(source_order))
    started_at: dict[str, float] = {source: time.monotonic() for source in source_order}
    futures = {}
    for source in source_order:
        _log_source_start(source, execution_mode="parallel")
        runner = _get_source_runner(source)
        worker_context = contextvars.copy_context()
        futures[executor.submit(worker_context.run, _run_source_with_scope, source, runner, context)] = source

    warn_deadlines = {
        future: started_at[source] + _source_timeout_seconds(source)
        for future, source in futures.items()
    }
    hard_deadlines = {
        future: started_at[source] + _source_hard_timeout_seconds(source)
        for future, source in futures.items()
    }
    timeout_messages = {future: _source_timeout_message(source) for future, source in futures.items()}
    timeout_warned: set[Any] = set()
    next_heartbeat_at = {
        source: started_at[source] + SOURCE_HEARTBEAT_SECONDS for source in source_order
    }
    pending = set(futures)
    results_by_source: dict[str, SourceRunResult] = {}
    hard_timeout_stop_requested: set[Any] = set()
    stop_deadlines: dict[Any, float] = {}

    try:
        while pending:
            now = time.monotonic()

            # A user stop gets a short, source-sized cleanup window. Running
            # Python threads cannot be killed safely, so late returns are ignored
            # after this boundary instead of blocking the active run forever.
            if run_stop_requested():
                for future in pending:
                    source = futures[future]
                    stop_deadlines.setdefault(
                        future,
                        now + _source_stop_cleanup_seconds(source),
                    )

            newly_timed_out = [
                future
                for future in list(pending)
                if now >= warn_deadlines[future] and future not in timeout_warned
            ]
            for future in newly_timed_out:
                source = futures[future]
                elapsed_s = now - started_at[source]
                _log_source_timeout_warning(
                    source,
                    timeout_messages[future],
                    elapsed_s=elapsed_s,
                )
                timeout_warned.add(future)

            hard_timed_out = [
                future
                for future in list(pending)
                if now >= hard_deadlines[future] and future not in hard_timeout_stop_requested
            ]
            for future in hard_timed_out:
                source = futures[future]
                elapsed_s = now - started_at[source]
                logger.warning(
                    "[%s][SOURCE_TIMEOUT_STOP_REQUESTED] elapsed_s=%s progress=%r message=%s",
                    source.upper(),
                    int(elapsed_s),
                    get_run_progress() or "(none)",
                    timeout_messages[future],
                )
                request_run_stop()
                hard_timeout_stop_requested.add(future)
                # Give the timed-out worker one final bounded chance to return
                # partial results before it is detached from the active run.
                stop_deadlines[future] = now + _source_stop_cleanup_seconds(source)

            if run_stop_requested():
                for future in pending:
                    source = futures[future]
                    stop_deadlines.setdefault(
                        future,
                        now + _source_stop_cleanup_seconds(source),
                    )

            expired_futures = [
                future
                for future in list(pending)
                if not future.done()
                and future in stop_deadlines
                and now >= stop_deadlines[future]
            ]
            for future in expired_futures:
                pending.remove(future)
                source = futures[future]
                cleanup_seconds = _source_stop_cleanup_seconds(source)
                source_label = get_source_display_label(source)
                message = (
                    f"{source_label} did not stop within {cleanup_seconds:g}s; "
                    "continuing with results already collected."
                )
                future.cancel()
                logger.error(
                    "[%s][SOURCE_STOP_BOUNDED] elapsed_s=%d cleanup_seconds=%s message=%s",
                    source.upper(),
                    int(now - started_at[source]),
                    cleanup_seconds,
                    message,
                )
                _record_source_warning(
                    source=source,
                    severity="warning",
                    category="source_timeout",
                    message=message,
                    run_id=context.run_iso,
                    context={
                        "elapsed_s": int(now - started_at[source]),
                        "cleanup_seconds": cleanup_seconds,
                        "stop_requested": True,
                    },
                    fingerprint_parts=("source_stop_bounded", source, message),
                )
                results_by_source[source] = SourceRunResult(
                    source=source,
                    error=TimeoutError(message),
                )
                set_run_progress_state(
                    message,
                    stage="error",
                    source=source,
                    headline=f"{source_label} stopped after timeout",
                    detail="Continuing with results collected so far.",
                    determinate=False,
                )

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

            next_deadline_candidates: list[float] = []
            for future in pending:
                if future not in timeout_warned:
                    next_deadline_candidates.append(warn_deadlines[future])
                if future not in hard_timeout_stop_requested:
                    next_deadline_candidates.append(hard_deadlines[future])
                if future in stop_deadlines:
                    next_deadline_candidates.append(stop_deadlines[future])
            if next_deadline_candidates:
                next_deadline = min(next_deadline_candidates)
                wait_timeout = max(0.0, min(0.1, next_deadline - time.monotonic()))
            else:
                wait_timeout = 0.1
            done, _ = wait(pending, timeout=wait_timeout, return_when=FIRST_COMPLETED)
            for future in done:
                pending.remove(future)
                source = futures[future]
                try:
                    result = future.result()
                    results_by_source[source] = result
                    elapsed_s = time.monotonic() - started_at[source]
                    _log_source_complete(result, elapsed_s=elapsed_s)
                    pending_source_set = {futures[pending_future] for pending_future in pending}
                    remaining_sources = [
                        pending_source
                        for pending_source in source_order
                        if pending_source in pending_source_set
                    ]
                    if pending:
                        progress_text = _parallel_completion_progress(source, remaining_sources)
                        set_run_progress_state(
                            progress_text,
                            stage="source_collection",
                            source="generic",
                            headline=progress_text,
                            determinate=False,
                        )
                except Exception as exc:
                    logger.exception(
                        "[%s] source worker failed after %ds",
                        source.upper(),
                        int(time.monotonic() - started_at[source]),
                    )
                    results_by_source[source] = SourceRunResult(source=source, error=exc)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    missing_sources = [source for source in source_order if source not in results_by_source]
    if missing_sources:
        raise RuntimeError(
            "Source runner did not produce results before parallel runner exit: "
            + ", ".join(missing_sources)
        )
    return [results_by_source[source] for source in source_order]


def run_enabled_sources(context: ScrapeRunContext) -> tuple[list[dict], list[dict], list[dict]]:
    """Run all enabled sources and return merged (kept_records, audit_rows, skill_observations).

    When more than one source is enabled they run concurrently, unless step-through is
    active, in which case the run stays serial so manual pausing can actually halt progress.
    Each source has a hard timeout so a stuck job board cannot block the whole run.

    Mutable shared state (job_history, llm_cache) is isolated per source during
    execution and merged back into context after all sources complete.
    """
    kept_records: list[dict] = []
    audit_rows: list[dict] = []
    skill_observations: list[dict] = []

    enabled_source_order = _enabled_source_order(context)

    if not enabled_source_order:
        raise RuntimeError(
            "No search sources are enabled for this run. Enable at least one source in Settings or Global Settings."
        )

    for source in SOURCE_RUNNER_NAMES:
        label = get_source_display_label(source)
        print(
            f"[{label}] enabled"
            if source in enabled_source_order
            else f"[{label}] disabled in enabled_sources; skipping"
        )

    if run_stop_requested():
        return kept_records, audit_rows, skill_observations

    results: list[SourceRunResult] = []

    if step_through_enabled():
        # Step-through is a manual inspection aid, so keep the whole run serial.
        # Parallel sources would continue advancing while another worker is paused.
        for source in enabled_source_order:
            if run_stop_requested():
                break
            results.append(_run_source_with_scope(source, _get_source_runner(source), context))
    elif len(enabled_source_order) > 1:
        parallel_labels = list_to_phrase(
            [get_source_display_label(source) for source in enabled_source_order]
        )
        progress_text = f"{parallel_labels} running in parallel"
        set_run_progress_state(
            progress_text,
            stage="starting",
            source="generic",
            headline=progress_text,
            determinate=False,
        )
        results = _run_sources_in_parallel(context, enabled_source_order)
    elif enabled_source_order:
        source = enabled_source_order[0]
        results = [_run_source_with_scope(source, _get_source_runner(source), context)]

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
