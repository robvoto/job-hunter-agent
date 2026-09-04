"""Helpers for source runner."""

from __future__ import annotations

import contextvars
import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Sequence, cast

from job_hunter_agent.posting_utils import current_posted_age_days
from job_hunter_agent.record_schema import (
    RECORD_JOB_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_RUN_STARTED_AT_KEY,
)
from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.run_control import (
    get_run_progress_for_source,
    request_run_stop,
    run_stop_requested,
    run_shutdown_requested,
    set_run_progress_state,
    step_through_enabled,
)
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_APSJOBS_RESULTS_PER_SEARCH,
    KEY_DATE_RANGE_DAYS,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_SEEK_MAX_PAGES,
    KEY_SORT_NEWEST_FIRST,
    get_linkedin_stale_fallback_max_age_minutes,
    get_search_plan_max_age_minutes,
    get_search_plan_min_corroboration_samples,
    get_seek_assisted_verification_enabled,
)
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
from job_hunter_agent.source_discovery_cache import (
    build_source_search_signature,
    load_linkedin_failure_backoff,
    load_source_discovery_snapshot,
    load_source_discovery_stale_snapshot,
    save_source_discovery_snapshot,
    save_source_failure_state,
)
from job_hunter_agent.incremental_search import (
    IncrementalSearchPlan,
    plan_incremental_search,
    save_incremental_checkpoints,
)
from job_hunter_agent.search_plan_state import load_search_plan_state, planned_search_terms

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


def _set_seek_source_progress(text: str, *, stage: str) -> None:
    message = str(text or "").strip()
    set_run_progress_state(
        message,
        stage=stage,
        source=SOURCE_SEEK,
        headline=message,
        determinate=False,
    )


def _exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or type(exc).__name__


def _merge_partial_rows(*groups: list[dict]) -> list[dict]:
    """Keep one copy of each explicitly identified row across retry attempts."""
    merged: list[dict] = []
    seen_keys: set[str] = set()
    for group in groups:
        for row in group:
            job_key = str(row.get(RECORD_JOB_KEY) or "").strip()
            if job_key and job_key in seen_keys:
                continue
            if job_key:
                seen_keys.add(job_key)
            merged.append(row)
    return merged

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
    discovery_records: list[dict] = field(default_factory=list)
    source_cache_status: str = "MISS"
    source_cache_signature: str = ""
    source_failure_backoff: bool = False
    source_collection_complete: bool = True


def _incremental_search_plan(
    context: ScrapeRunContext, source: str, signature: str
) -> IncrementalSearchPlan:
    """Plan a bounded source window from the unchanged full-search signature."""
    if source == SOURCE_SEEK:
        targets = build_seek_search_targets(
            context.profile, context.configured_date_range, context.sort_newest_first
        )
        configured_days = context.configured_date_range
        configured_hours_old = None
    elif source == SOURCE_LINKEDIN:
        from job_hunter_agent.scrapers.linkedin import build_linkedin_search_targets

        targets = build_linkedin_search_targets(context.search_settings, context.profile)
        configured_hours_old = int(
            context.search_settings.get(
                KEY_LINKEDIN_HOURS_OLD,
                DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD],
            )
            or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
        )
        configured_days = max(1, (configured_hours_old + 23) // 24)
    elif source == SOURCE_APSJOBS:
        from job_hunter_agent.scrapers.apsjobs import build_apsjobs_search_targets

        targets = build_apsjobs_search_targets(context.search_settings, context.profile)[1]
        configured_days = context.configured_date_range
        configured_hours_old = None
    else:
        raise ValueError(f"Unsupported incremental source: {source}")
    return plan_incremental_search(
        source=source,
        signature=signature,
        targets=targets,
        configured_window_days=configured_days,
        configured_hours_old=configured_hours_old,
        force_refresh=context.force_source_refresh,
    )


def _log_incremental_plan(plan: IncrementalSearchPlan) -> None:
    logger.info(
        format_log_block(
            f"{plan.source.upper()}][INCREMENTAL_SEARCH",
            plan.as_log_fields(),
        )
    )


def _source_health(result: SourceRunResult) -> str:
    """Classify collection health separately from whether the worker returned."""
    if result.error is None and result.source_collection_complete:
        return "healthy"
    if result.kept_records or result.audit_rows:
        return "partial_failure"
    return "full_failure"


def _request_fail_fast_for_source_failure(
    context: ScrapeRunContext, result: SourceRunResult
) -> bool:
    """Stop the rest of a run when one enabled source has actually failed.

    Timeout warnings alone are not failures. A user-requested stop also retains
    its own cancellation semantics and is never relabelled as a source failure.
    """
    if result.error is None or run_stop_requested() or context.source_failure_message:
        return False

    source_label = get_source_display_label(result.source)
    error_message = _exception_message(result.error)
    failure_message = f"{source_label} failed: {error_message}"
    context.source_failure_message = failure_message
    logger.error(
        "[%s][RUN_FAIL_FAST] %s; stopping remaining enabled sources.",
        result.source.upper(),
        failure_message,
    )
    set_run_progress_state(
        failure_message,
        stage="error",
        source=result.source,
        headline=f"{source_label} failed",
        detail="Stopping the remaining enabled sources.",
        determinate=False,
    )
    request_run_stop()
    return True


def _source_search_signature(context: ScrapeRunContext, source: str) -> str:
    """Build a signature from source inputs, excluding downstream fit preferences."""
    inputs: dict[str, Any] = {
        "date_range_days": context.configured_date_range,
        "sort_newest_first": context.sort_newest_first,
    }
    if source == SOURCE_SEEK:
        inputs.update(
            {
                "search_settings": {
                    "keywords": context.search_settings.get("keywords"),
                    "locations": context.search_settings.get("locations"),
                    "classification_ids": context.search_settings.get("classification_ids"),
                    KEY_DATE_RANGE_DAYS: context.search_settings.get(KEY_DATE_RANGE_DAYS),
                    KEY_SEEK_MAX_PAGES: context.search_settings.get(KEY_SEEK_MAX_PAGES),
                    KEY_SORT_NEWEST_FIRST: context.search_settings.get(KEY_SORT_NEWEST_FIRST),
                },
                "search_targets": build_seek_search_targets(
                    context.profile, context.configured_date_range, context.sort_newest_first
                ),
                "max_pages": context.configured_seek_max_pages,
            }
        )
    elif source == SOURCE_LINKEDIN:
        from job_hunter_agent.scrapers.linkedin import build_linkedin_search_targets

        inputs["search_settings"] = {
            "keywords": context.search_settings.get("keywords"),
            "locations": context.search_settings.get("locations"),
            KEY_DATE_RANGE_DAYS: context.search_settings.get(KEY_DATE_RANGE_DAYS),
            KEY_LINKEDIN_HOURS_OLD: context.search_settings.get(KEY_LINKEDIN_HOURS_OLD),
            KEY_LINKEDIN_RESULTS_PER_SEARCH: context.search_settings.get(
                KEY_LINKEDIN_RESULTS_PER_SEARCH
            ),
            KEY_LINKEDIN_EASY_APPLY_ONLY: context.search_settings.get(
                KEY_LINKEDIN_EASY_APPLY_ONLY
            ),
            KEY_SORT_NEWEST_FIRST: context.search_settings.get(KEY_SORT_NEWEST_FIRST),
        }
        inputs["search_targets"] = build_linkedin_search_targets(
            context.search_settings, context.profile
        )
    elif source == SOURCE_APSJOBS:
        from job_hunter_agent.scrapers.apsjobs import build_apsjobs_search_targets

        inputs["search_settings"] = {
            "keywords": context.search_settings.get("keywords"),
            "locations": context.search_settings.get("locations"),
            KEY_DATE_RANGE_DAYS: context.search_settings.get(KEY_DATE_RANGE_DAYS),
            KEY_APSJOBS_RESULTS_PER_SEARCH: context.search_settings.get(
                KEY_APSJOBS_RESULTS_PER_SEARCH
            ),
        }
        inputs["search_targets"] = build_apsjobs_search_targets(
            context.search_settings, context.profile
        )[1]
    return build_source_search_signature(source, inputs)


def _reevaluate_stale_posting_ages(
    records: list[dict], captured_at: datetime, *, now: datetime | None = None
) -> list[dict]:
    """Return copies of stale-fallback records with posting age aged forward.

    Each record's ``posted_age_days`` was accurate at capture time, not now.
    Before these records are replayed through the shared ``POSTED_TOO_OLD``
    date-range filter, their age must be brought up to date using the same
    fractional-day contract the rest of the product uses for a record's
    current age (``posting_utils.current_posted_age_days``), rather than a
    second, coarser ageing calculation. A record without its own capture
    timestamp falls back to the snapshot's own capture time.

    The record's reference time is advanced to this evaluation instant
    together with the materialised age, so the two stay self-consistent.
    Otherwise a later call to ``current_posted_age_days`` would measure
    elapsed time from the old reference time using the *already aged-forward*
    ``posted_age_days``, re-applying the same elapsed interval a second time
    and inflating the age further.
    """
    evaluated_at = now or datetime.now().astimezone()
    adjusted: list[dict] = []
    for record in records:
        record = dict(record)
        if record.get(RECORD_POSTED_AGE_DAYS_KEY) is not None:
            if not record.get(RECORD_RUN_STARTED_AT_KEY):
                record[RECORD_RUN_STARTED_AT_KEY] = captured_at.isoformat()
            aged_age_days = current_posted_age_days(record, now=evaluated_at)
            if aged_age_days is not None:
                record[RECORD_POSTED_AGE_DAYS_KEY] = aged_age_days
                record[RECORD_RUN_STARTED_AT_KEY] = evaluated_at.isoformat()
        adjusted.append(record)
    return adjusted


def _search_plan_requires_probe(
    context: ScrapeRunContext, source: str, signature: str
) -> bool:
    """Return whether an existing learned plan has expired before cache reuse."""
    if source == SOURCE_SEEK:
        targets = build_seek_search_targets(
            context.profile, context.configured_date_range, context.sort_newest_first
        )
        term_key = "keywords"
    elif source == SOURCE_LINKEDIN:
        from job_hunter_agent.scrapers.linkedin import build_linkedin_search_targets

        targets = build_linkedin_search_targets(context.search_settings, context.profile)
        term_key = "search_term"
    elif source == SOURCE_APSJOBS:
        from job_hunter_agent.scrapers.apsjobs import build_apsjobs_search_targets

        targets = build_apsjobs_search_targets(context.search_settings, context.profile)[1]
        term_key = "search_term"
    else:
        return False

    terms_by_location: dict[str, list[str]] = {}
    for target in targets:
        location = str(target.get("location") or "")
        term = str(target.get(term_key) or "").strip()
        if term:
            terms_by_location.setdefault(location, []).append(term)

    for location, probe_terms in terms_by_location.items():
        state = load_search_plan_state(source=source.lower(), signature=signature, location=location)
        if not state:
            continue
        _, plan_source = planned_search_terms(
            state,
            probe_terms,
            min_corroboration_samples=get_search_plan_min_corroboration_samples(),
            max_age_minutes=get_search_plan_max_age_minutes(),
        )
        if plan_source != "remembered":
            logger.info(
                "[%s][SEARCH_PLAN] bypassing source-result cache; existing plan requires a bounded probe location=%r",
                source.upper(),
                location or "(all)",
            )
            return True
    return False


def _source_cache_lookup(context: ScrapeRunContext, source: str) -> tuple[str, str, list[dict] | None]:
    signature = _source_search_signature(context, source)
    if context.force_source_refresh:
        logger.info("[%s][SOURCE_CACHE] MISS reason=force_refresh", source.upper())
        return signature, "MISS", None
    if _search_plan_requires_probe(context, source, signature):
        logger.info("[%s][SOURCE_CACHE] MISS reason=search_plan_probe_required", source.upper())
        return signature, "MISS", None
    snapshot = load_source_discovery_snapshot(source, signature)
    if snapshot is not None:
        logger.info(
            "[%s][SOURCE_CACHE] HIT records=%d signature=%s",
            source.upper(), len(snapshot), signature[:12]
        )
        return signature, "HIT", snapshot
    if source == SOURCE_LINKEDIN and load_linkedin_failure_backoff(source, signature):
        stale = load_source_discovery_stale_snapshot(
            source, signature, get_linkedin_stale_fallback_max_age_minutes()
        )
        if stale is not None:
            stale_records = _reevaluate_stale_posting_ages(stale["records"], stale["updated_at"])
            logger.warning(
                "[%s][SOURCE_CACHE] STALE_FALLBACK records=%d captured_at=%s signature=%s",
                source.upper(), len(stale_records), stale["updated_at"].isoformat(), signature[:12],
            )
            return signature, "STALE_FALLBACK", stale_records
        logger.warning(
            "[%s][SOURCE_CACHE] BACKOFF identical timed-out search signature=%s",
            source.upper(), signature[:12]
        )
        return signature, "BACKOFF", []
    logger.info("[%s][SOURCE_CACHE] MISS signature=%s", source.upper(), signature[:12])
    return signature, "MISS", None


def _run_seek_source(context: ScrapeRunContext) -> SourceRunResult:
    """Run SEEK with isolated mutable state.

    Takes shallow copies of job_history and llm_cache so enabled source workers
    cannot corrupt each other's in-flight state when running concurrently.
    The mutated copies are returned for deterministic merge.
    """
    job_history: dict[str, Any] = dict(context.job_history)
    llm_cache: dict[str, Any] = dict(context.llm_cache)
    signature = ""
    cache_status = "MISS"
    cached_records = None
    captured_records: list[dict] = []
    failure_state: dict[str, Any] = {"complete": True}
    headless = bool(getattr(context, "headless", False))
    try:
        signature, cache_status, cached_records = _source_cache_lookup(context, SOURCE_SEEK)
        incremental_plan = _incremental_search_plan(context, SOURCE_SEEK, signature)
        _log_incremental_plan(incremental_plan)
        set_run_progress_state(
            "Starting SEEK",
            stage="starting",
            source="seek",
            headline="Starting SEEK",
            determinate=False,
        )
        search_targets = build_seek_search_targets(
            context.profile,
            context.configured_date_range,
            context.sort_newest_first,
            effective_date_range=incremental_plan.effective_window_days,
        )
        assisted_verification_enabled = (
            get_seek_assisted_verification_enabled() or context.dashboard_debug_mode
        )
        if assisted_verification_enabled:
            logger.warning("[SEEK] %s", SEEK_ASSISTED_BROWSER_SESSION_ENABLED)
            _set_seek_source_progress(SEEK_ASSISTED_BROWSER_SESSION_ENABLED, stage="verification")
        _seek_kwargs: dict[str, Any] = dict(
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
            discovery_records=cached_records,
            discovery_capture=captured_records,
            discovery_status=failure_state,
            search_plan_signature=signature,
            identity_registry=context.identity_registry,
            incremental_known_job_keys=set(incremental_plan.known_job_keys),
        )
        try:
            kept, audit, skills = seek_scrape_to_records(**_seek_kwargs, headless=headless)
        except BotChallengeDetected as exc:
            partial_kept = list(exc.kept_records)
            partial_audit = list(exc.audit_rows)
            partial_skills = list(exc.skill_observations)
            failure_class = getattr(exc, "failure_class", "SEEK_UNKNOWN_FAILURE")
            if failure_class not in {
                SEEK_HUMAN_VERIFICATION,
                SEEK_BOT_CHALLENGE,
                SEEK_TIMEOUT_NO_CARDS,
            }:
                _set_seek_source_progress(_exception_message(exc), stage="error")
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
            if not headless:
                _set_seek_source_progress(_exception_message(exc), stage="error")
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
                    kept_records=partial_kept,
                    audit_rows=partial_audit,
                    skill_observations=partial_skills,
                    error=exc,
                    _job_history_snapshot=job_history,
                    _llm_cache_snapshot=llm_cache,
                    discovery_records=(cached_records if cached_records is not None else captured_records),
                    source_cache_status=cache_status,
                    source_cache_signature=signature,
                    source_collection_complete=False,
                )
            if not assisted_verification_enabled:
                logger.warning(
                    "[SEEK] Headless SEEK run hit %s but AWS browser session mode is disabled",
                    failure_class,
                )
                _set_seek_source_progress(_exception_message(exc), stage="error")
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
                    kept_records=partial_kept,
                    audit_rows=partial_audit,
                    skill_observations=partial_skills,
                    error=exc,
                    _job_history_snapshot=job_history,
                    _llm_cache_snapshot=llm_cache,
                    discovery_records=(cached_records if cached_records is not None else captured_records),
                    source_cache_status=cache_status,
                    source_cache_signature=signature,
                    source_collection_complete=False,
                )
            logger.warning(
                "[SEEK] Headless SEEK run hit %s; retrying with AWS browser session",
                failure_class,
            )
            _set_seek_source_progress("SEEK needs human verification. Open the AWS browser session and complete the check.", stage="verification")
            try:
                kept, audit, skills = seek_scrape_to_records(**_seek_kwargs, headless=False)
            except BotChallengeDetected as retry_exc:
                retry_kept = list(retry_exc.kept_records)
                retry_audit = list(retry_exc.audit_rows)
                retry_skills = list(retry_exc.skill_observations)
                retry_failure_class = getattr(retry_exc, "failure_class", "SEEK_UNKNOWN_FAILURE")
                if retry_failure_class not in {
                    SEEK_HUMAN_VERIFICATION,
                    SEEK_BOT_CHALLENGE,
                    SEEK_TIMEOUT_NO_CARDS,
                }:
                    _set_seek_source_progress(str(retry_exc), stage="error")
                    raise
                logger.warning(
                    "[SEEK] Visible SEEK retry was still blocked (%s); continuing without SEEK results: %s",
                    retry_failure_class,
                    retry_exc,
                )
                _set_seek_source_progress(_exception_message(retry_exc), stage="error")
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
                    kept_records=_merge_partial_rows(partial_kept, retry_kept),
                    audit_rows=_merge_partial_rows(partial_audit, retry_audit),
                    skill_observations=[*partial_skills, *retry_skills],
                    error=retry_exc,
                    _job_history_snapshot=job_history,
                    _llm_cache_snapshot=llm_cache,
                    discovery_records=(cached_records if cached_records is not None else captured_records),
                    source_cache_status=cache_status,
                    source_cache_signature=signature,
                    source_collection_complete=False,
                )
        return SourceRunResult(
            source=SOURCE_SEEK,
            kept_records=kept,
            audit_rows=audit,
            skill_observations=skills,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_collection_complete=failure_state.get("complete", True),
        )
    except PartialSourceResultsError as exc:
        logger.exception("[SEEK] scraping failed after partial results")
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
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_collection_complete=False,
        )
    except Exception as exc:
        logger.exception("[SEEK] scraping failed")
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
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_collection_complete=False,
        )


def _run_linkedin_source(context: ScrapeRunContext) -> SourceRunResult:
    """Run LinkedIn with isolated mutable state.

    Mirrors _run_seek_source isolation pattern.
    LinkedIn failures print and return an error result rather than raising,
    matching the existing behaviour.
    """
    job_history: dict[str, Any] = dict(context.job_history)
    llm_cache: dict[str, Any] = dict(context.llm_cache)
    signature = ""
    cache_status = "MISS"
    cached_records = None
    captured_records: list[dict] = []
    failure_state: dict[str, Any] = {"complete": True}
    try:
        signature, cache_status, cached_records = _source_cache_lookup(context, SOURCE_LINKEDIN)
        incremental_plan = _incremental_search_plan(context, SOURCE_LINKEDIN, signature)
        _log_incremental_plan(incremental_plan)
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
            discovery_records=cached_records,
            discovery_capture=captured_records,
            discovery_status=failure_state,
            search_plan_signature=signature,
            identity_registry=context.identity_registry,
            incremental_known_job_keys=set(incremental_plan.known_job_keys),
            incremental_hours_old=incremental_plan.effective_hours_old,
        )
        kept, audit, skills = li.scrape()

        final_status = str(failure_state.get("final_status", "healthy"))
        total_targets = int(failure_state.get("total_targets", 0))
        attempted = int(failure_state.get("attempted_targets", 0))
        succeeded = int(failure_state.get("succeeded_targets", 0))
        timed_out = int(failure_state.get("timed_out_targets", 0))
        failed = int(failure_state.get("failed_targets", 0))
        skipped = int(failure_state.get("skipped_after_breaker", 0))
        breaker_tripped = bool(failure_state.get("circuit_breaker_tripped", False))
        full_failure = final_status == "full_failure"
        error: Exception | None = None

        if full_failure:
            reason = "consecutive_timeouts" if failed > 0 and timed_out == failed else "consecutive_failures"
            message = (
                f"LinkedIn source failed: {attempted}/{total_targets} targets attempted, "
                f"{timed_out} timed out, {failed} failed, {skipped} skipped after "
                f"{'circuit breaker' if breaker_tripped else 'run end'}."
            )
            logger.error(
                format_log_block(
                    "LINKEDIN][SOURCE_FAILED",
                    {
                        "attempted": attempted,
                        "timed_out": timed_out,
                        "failed": failed,
                        "remaining_skipped": skipped,
                        "reason": reason,
                    },
                )
            )
            _record_source_warning(
                source=SOURCE_LINKEDIN,
                severity="error",
                category="source_failure",
                message=message,
                run_id=context.run_iso,
                context={
                    "attempted": attempted,
                    "timed_out": timed_out,
                    "failed": failed,
                    "skipped_after_breaker": skipped,
                    "circuit_breaker_tripped": breaker_tripped,
                    "reason": reason,
                },
                fingerprint_parts=("source_failure", SOURCE_LINKEDIN, reason),
            )
            error = RuntimeError(message)

            stale = load_source_discovery_stale_snapshot(
                SOURCE_LINKEDIN, signature, get_linkedin_stale_fallback_max_age_minutes()
            )
            if stale is not None:
                stale_records = _reevaluate_stale_posting_ages(stale["records"], stale["updated_at"])
                fallback_scraper = LinkedInScraper(
                    profile=context.profile,
                    llm_cache=llm_cache,
                    job_history=job_history,
                    applied_job_keys=context.applied_job_keys,
                    hidden_job_keys=context.hidden_job_keys,
                    run_iso=context.run_iso,
                    discovery_records=stale_records,
                    discovery_capture=None,
                    discovery_status={},
                    identity_registry=context.identity_registry,
                )
                kept, audit, skills = fallback_scraper.scrape()
                cached_records = stale_records
                cache_status = "STALE_FALLBACK_AFTER_FAILURE"
                logger.warning(
                    "[LINKEDIN][SOURCE_CACHE] STALE_FALLBACK_AFTER_FAILURE records=%d "
                    "captured_at=%s signature=%s",
                    len(stale_records), stale["updated_at"].isoformat(), signature[:12],
                )
        elif final_status == "partial_failure":
            message = (
                f"LinkedIn source partially collected: {succeeded}/{attempted} attempted "
                f"targets succeeded"
                + (f", {skipped} skipped after circuit breaker" if breaker_tripped else "")
                + "."
            )
            logger.warning(format_log_block("LINKEDIN][SOURCE_PARTIAL", {"message": message}))
            _record_source_warning(
                source=SOURCE_LINKEDIN,
                severity="warning",
                category="source_failure",
                message=message,
                run_id=context.run_iso,
                context={
                    "attempted": attempted,
                    "succeeded": succeeded,
                    "timed_out": timed_out,
                    "failed": failed,
                    "skipped_after_breaker": skipped,
                    "circuit_breaker_tripped": breaker_tripped,
                },
                fingerprint_parts=("source_partial", SOURCE_LINKEDIN, "partial_collection"),
            )

        return SourceRunResult(
            source=SOURCE_LINKEDIN,
            kept_records=kept,
            audit_rows=audit,
            skill_observations=skills,
            error=error,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_failure_backoff=full_failure,
            source_collection_complete=failure_state.get("complete", True),
        )
    except PartialSourceResultsError as exc:
        logger.exception("[LinkedIn] scraping failed after partial results")
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
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_collection_complete=False,
        )
    except Exception as exc:
        logger.exception("[LinkedIn] scraping failed")
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
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_collection_complete=False,
        )


def _run_apsjobs_source(context: ScrapeRunContext) -> SourceRunResult:
    """Run APS Jobs with isolated mutable state for safe parallel collection."""
    job_history: dict[str, Any] = dict(context.job_history)
    llm_cache: dict[str, Any] = dict(context.llm_cache)
    signature = ""
    cache_status = "MISS"
    cached_records = None
    captured_records: list[dict] = []
    failure_state: dict[str, Any] = {"complete": True}
    try:
        signature, cache_status, cached_records = _source_cache_lookup(context, SOURCE_APSJOBS)
        incremental_plan = _incremental_search_plan(context, SOURCE_APSJOBS, signature)
        _log_incremental_plan(incremental_plan)
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
            discovery_records=cached_records,
            discovery_capture=captured_records,
            discovery_status=failure_state,
            search_plan_signature=signature,
            identity_registry=context.identity_registry,
            incremental_known_job_keys=set(incremental_plan.known_job_keys),
        )
        kept, audit, skills = scraper.scrape()
        return SourceRunResult(
            source=SOURCE_APSJOBS,
            kept_records=kept,
            audit_rows=audit,
            skill_observations=skills,
            _job_history_snapshot=job_history,
            _llm_cache_snapshot=llm_cache,
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_collection_complete=failure_state.get("complete", True),
        )
    except PartialSourceResultsError as exc:
        logger.warning(
            "[APSJobs] scraping failed after partial results: %s: %s",
            type(exc.original_error).__name__,
            exc.original_error,
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
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_collection_complete=False,
        )
    except Exception as exc:
        logger.exception("[APSJobs] scraping failed")
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
            discovery_records=(cached_records if cached_records is not None else captured_records),
            source_cache_status=cache_status,
            source_cache_signature=signature,
            source_collection_complete=False,
        )


SOURCE_RUNNER_NAMES: dict[str, str] = {
    SOURCE_SEEK: "_run_seek_source",
    SOURCE_LINKEDIN: "_run_linkedin_source",
    SOURCE_APSJOBS: "_run_apsjobs_source",
}


def _log_source_timeout_warning(
    source: str, message: str, *, elapsed_s: float | None = None
) -> None:
    source_progress = get_run_progress_for_source(source)
    logger.warning(
        "[%s][SOURCE_TIMEOUT] elapsed_s=%s progress=%r message=%s",
        source.upper(),
        int(elapsed_s) if elapsed_s is not None else -1,
        source_progress or "(none)",
        message,
    )
    source_label = get_source_display_label(source)
    set_run_progress_state(
        message,
        stage="error",
        source=source,
        headline=f"{source_label} timed out",
        detail="Stopping the source and preserving completed results.",
        determinate=False,
    )
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
            "progress": source_progress,
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
    if result.error is None and result.source_collection_complete:
        marker = "SOURCE_COMPLETE"
        log = logger.info
    elif result.kept_records or result.audit_rows or (
        result.error is None and not result.source_collection_complete
    ):
        marker = "SOURCE_PARTIAL"
        log = logger.warning
    else:
        marker = "SOURCE_FAILED"
        log = logger.error
    log(
        format_log_block(
            f"{result.source.upper()}][{marker}",
            {
                "source": get_source_display_label(result.source),
                "elapsed_seconds": int(elapsed_s),
                "kept": len(result.kept_records),
                "audit": len(result.audit_rows),
                "skills": len(result.skill_observations),
                "error": type(result.error).__name__ if result.error is not None else "none",
                "collection_complete": result.source_collection_complete,
                "source_cache": result.source_cache_status,
                "source_cache_signature": result.source_cache_signature[:12],
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
    return cast(Callable[[ScrapeRunContext], SourceRunResult], runner)


def _run_source_with_scope(
    source: str,
    runner: Callable[[ScrapeRunContext], SourceRunResult],
    context: ScrapeRunContext,
) -> SourceRunResult:
    log_token = set_log_source_scope(source)
    try:
        return runner(context)
    finally:
        reset_log_source_scope(log_token)


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
        future = executor.submit(
            worker_context.run,
            _run_source_with_scope,
            source,
            runner,
            context,
        )
        futures[future] = source

    warn_deadlines = {
        future: started_at[source] + _source_timeout_seconds(source)
        for future, source in futures.items()
    }
    timeout_messages = {future: _source_timeout_message(source) for future, source in futures.items()}
    timeout_warned: set[Any] = set()
    next_heartbeat_at = {
        source: started_at[source] + SOURCE_HEARTBEAT_SECONDS for source in source_order
    }
    pending = set(futures)
    results_by_source: dict[str, SourceRunResult] = {}
    stop_deadlines: dict[Any, float] = {}

    try:
        while pending:
            now = time.monotonic()

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
                        "stop_requested": run_stop_requested(),
                    },
                    fingerprint_parts=("source_stop_bounded", source, message),
                )
                results_by_source[source] = SourceRunResult(
                    source=source,
                    error=TimeoutError(message),
                    source_collection_complete=False,
                )
                if not context.source_failure_message:
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
                    get_run_progress_for_source(source) or "(none)",
                )
                while next_heartbeat_at[source] <= now:
                    next_heartbeat_at[source] += SOURCE_HEARTBEAT_SECONDS

            if not pending:
                break

            next_deadline_candidates: list[float] = []
            for future in pending:
                if future not in timeout_warned:
                    next_deadline_candidates.append(warn_deadlines[future])
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
                    failure_triggered = _request_fail_fast_for_source_failure(context, result)
                    pending_source_set = {futures[pending_future] for pending_future in pending}
                    remaining_sources = [
                        pending_source
                        for pending_source in source_order
                        if pending_source in pending_source_set
                    ]
                    if pending and not failure_triggered and not context.source_failure_message:
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
                    result = SourceRunResult(
                        source=source, error=exc, source_collection_complete=False
                    )
                    results_by_source[source] = result
                    _request_fail_fast_for_source_failure(context, result)
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
    Each source has a configurable warning threshold; only an explicit user stop
    bounds cleanup for a source that does not return.

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
        logger.info(
            "[%s] %s",
            label,
            "enabled" if source in enabled_source_order else "disabled in enabled_sources; skipping",
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
            result = _run_source_with_scope(source, _get_source_runner(source), context)
            results.append(result)
            if _request_fail_fast_for_source_failure(context, result):
                break
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
        # Use the same monitored worker path for a single source so its timeout
        # and cooperative cancellation contract matches parallel runs.
        results = _run_sources_in_parallel(context, enabled_source_order)

    # Merge mutable state back into context in deterministic order.
    for result in results:
        context.job_history.update(result._job_history_snapshot)
        context.llm_cache.update(result._llm_cache_snapshot)

    context.source_cache_stats = {
        result.source: {
            "status": result.source_cache_status,
            "signature": result.source_cache_signature,
            "records": len(result.discovery_records),
            "error": _exception_message(result.error) if result.error is not None else "",
            "external_source_calls_avoided": result.source_cache_status
            in {"HIT", "BACKOFF", "STALE_FALLBACK"},
            "health": _source_health(result),
            "collection_complete": bool(result.source_collection_complete),
            "error": _exception_message(result.error) if result.error is not None else "",
        }
        for result in results
    }

    # A server shutdown invalidates the whole in-flight run. Do not commit any
    # source result gathered by that run, even if a worker returned a result
    # while its cooperative stop was being processed.
    if run_shutdown_requested():
        logger.warning(
            "[RUN_INTERRUPTED] Skipping source-discovery snapshot commits after server shutdown."
        )
    # Commit only complete source snapshots after all source workers return. A
    # source exception, stop, or partial-result path therefore cannot replace a
    # known-good snapshot.
    if not run_shutdown_requested():
        for result in results:
            incremental_stats: dict[str, Any] = {}
            if result.source_cache_signature:
                incremental_plan = _incremental_search_plan(
                    context, result.source, result.source_cache_signature
                )
                if (
                    result.error is None
                    and result.source_collection_complete
                    and result.source_cache_status in {"MISS", "HIT"}
                ):
                    incremental_stats = save_incremental_checkpoints(
                        incremental_plan,
                        targets=list(incremental_plan.targets),
                        discovery_records=result.discovery_records,
                        completed=True,
                    )
                    logger.info(
                        format_log_block(
                            f"{result.source.upper()}][INCREMENTAL_CHECKPOINT",
                            incremental_stats,
                        )
                    )
                else:
                    incremental_stats = {
                        "advanced": False,
                        "reason": "source_not_healthy",
                    }
            if result.source in context.source_cache_stats:
                context.source_cache_stats[result.source]["incremental_search"] = incremental_stats
            if (
                result.source_cache_status not in {"MISS", "STALE_FALLBACK", "STALE_FALLBACK_AFTER_FAILURE"}
                or not result.source_cache_signature
            ):
                continue
            if result.source_failure_backoff:
                # A same-run stale-fallback replay still reflects a live failure this run
                # observed, so the failure/backoff state must still be recorded even
                # though the served results came from the fallback snapshot.
                save_source_failure_state(result.source, result.source_cache_signature)
            elif (
                result.source_cache_status == "MISS"
                and result.error is None
                and result.source_collection_complete
                and incremental_plan.mode == "full"
            ):
                # Only a fresh live MISS may write a new success snapshot. A
                # stale-fallback replay must never refresh or overwrite the
                # existing snapshot it borrowed from.
                save_source_discovery_snapshot(
                    result.source,
                    result.source_cache_signature,
                    result.discovery_records,
                )

    # Collect outputs even from errored sources so partial current-run audit data survives.
    for result in results:
        kept_records.extend(result.kept_records)
        audit_rows.extend(result.audit_rows)
        skill_observations.extend(result.skill_observations)

    return kept_records, audit_rows, skill_observations
