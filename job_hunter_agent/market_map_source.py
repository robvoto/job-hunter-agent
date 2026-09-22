"""Consume Job Market Map neutral jobs and run JH-owned candidate analysis."""

from __future__ import annotations

import contextvars
import copy
import logging
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any

from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_SEEK_QUICK_APPLY_ONLY,
    get_job_market_map_parallel_workers,
)
from job_hunter_agent.history import finalize_record
from job_hunter_agent.io_utils import load_parsing_rules, save_llm_cache
from job_hunter_agent.job_identity import RUN_IDENTITY_CLAIM_KEY, normalize_job_key
from job_hunter_agent.job_market_map_client import (
    JMM_FIELD_STATE_KNOWN,
    JobMarketMapClient,
    JobMarketMapContractError,
    JobMarketMapJDNotCached,
    JobMarketMapJDUnavailable,
    validate_market_job_field_states,
    validate_market_job_salary_normalized,
)
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    TitleGateAssessment,
    TitleJudgmentResult,
    prepare_title_gate_assessment,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
    review_title_judgment,
)
from job_hunter_agent.job_types import load_job_type_filter_groups
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.occupation_taxonomy import RESULT_FAR
from job_hunter_agent.posting_utils import days_since, parse_timestamp
from job_hunter_agent.profile_store import (
    ENGAGEMENT_TYPE_DEFAULT_VALUES,
    KEY_EXPLORE_ADJACENT_ROLES,
    KEY_WORK_MODE_PREFERENCE,
    WORK_MODE_PREFERENCE_DEFAULT_VALUES,
    normalize_engagement_type_preferences,
    normalize_work_mode_preferences,
)
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EASY_APPLY,
    APPLY_METHOD_EXTERNAL_APPLY,
    APPLY_METHOD_QUICK_APPLY,
    APPLY_METHOD_UNKNOWN,
    RECORD_APPLY_METHOD_KEY,
    RECORD_DECISION_EXPLANATION_KEY,
    RECORD_DECISION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_DUPLICATE_LINKS_KEY,
    RECORD_JOB_KEY,
    RECORD_MARKET_MAP_FIELD_STATES_KEY,
    RECORD_MARKET_MAP_IDENTITY_KEY,
    RECORD_MARKET_MAP_JD_FETCHED_AT_KEY,
    RECORD_MARKET_MAP_JD_SOURCE_KEY,
    RECORD_MARKET_MAP_JOB_ID_KEY,
    RECORD_MARKET_MAP_SALARY_NORMALIZED_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_RETRY_REASON_KEY,
    RECORD_RETRYABLE_KEY,
    RECORD_SECTOR_KEY,
    RECORD_SOURCE_CANONICAL_URL_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_NAME_KEY,
    RECORD_SOURCE_PLATFORM_JOB_ID_KEY,
    RECORD_SOURCE_PROVENANCE_KEY,
    RECORD_TITLE_KEY,
    REJECT_REASON_JMM_JD_ENRICHMENT_FAILED,
    REJECT_REASON_JMM_JD_NOT_CACHED,
    REJECT_REASON_JMM_JD_UNAVAILABLE,
)
from job_hunter_agent.run_control import run_stop_requested, set_run_progress_state
from job_hunter_agent.scrapers.base import blank_source_metadata, build_initial_flat_record
from job_hunter_agent.search_terms import ordered_profile_search_terms
from job_hunter_agent.sector_utils import classify_market_sector
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.source_learning import register_pending_learning_signals
from job_hunter_agent.source_registry import (
    SOURCE_JOB_MARKET_MAP,
    SOURCE_LINKEDIN,
    SOURCE_SEEK,
)
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)
from job_hunter_agent.work_mode_extraction import (
    WORK_MODE_UNKNOWN,
    canonical_work_mode_value,
)

logger = logging.getLogger(__name__)


def _jmm_readiness_degraded_sources(readiness: dict[str, Any]) -> list[str]:
    degraded: list[str] = []
    source_runs = readiness.get("source_runs") or {}
    for source in ("seek", "linkedin"):
        run = source_runs.get(source) if isinstance(source_runs, dict) else None
        status = str((run or {}).get("status") or "NOT_RUN").strip().upper()
        if (
            status == "NOT_RUN"
            or status in {"STOPPED", "FAILED", "ERROR"}
            or "FAIL" in status
            or status.startswith("PARTIAL_")
            or status.startswith("INCOMPLETE")
        ):
            degraded.append(f"{source}:{status}")
    return degraded


def _record_jmm_readiness(readiness: dict[str, Any], *, run_id: str) -> None:
    source_runs = readiness.get("source_runs") or {}
    coverage = readiness.get("jd_coverage") or {}
    seek_status = str((source_runs.get("seek") or {}).get("status") or "NOT_RUN")
    linkedin_status = str((source_runs.get("linkedin") or {}).get("status") or "NOT_RUN")
    logger.info(
        "[JMM][READINESS] seek_status=%s linkedin_status=%s jd_available=%s jd_missing_not_cached=%s jd_failed=%s",
        seek_status,
        linkedin_status,
        coverage.get("available", 0),
        coverage.get("missing_not_cached", 0),
        coverage.get("failed", 0),
    )
    degraded = _jmm_readiness_degraded_sources(readiness)
    if degraded:
        message = "Job Market Map source readiness is degraded: " + ", ".join(degraded)
        record_system_warning(
            severity="warning",
            category="jmm_readiness",
            source=SOURCE_JOB_MARKET_MAP,
            message=message,
            fingerprint=make_system_warning_fingerprint("jmm_readiness", *degraded),
            run_id=run_id,
            context=readiness,
        )


def _source_metadata(item: dict[str, Any], source: str, source_job_id: str) -> dict[str, Any]:
    metadata = blank_source_metadata(source)
    metadata.update(
        {
            RECORD_SOURCE_CANONICAL_URL_KEY: str(item["canonical_url"]).strip(),
            RECORD_SOURCE_PLATFORM_JOB_ID_KEY: source_job_id,
            "apply_url": "",
            "raw_source_fields": {
                key: item.get(key)
                for key in (
                    "source",
                    "source_job_id",
                    "identity_key",
                    "canonical_url",
                    "title",
                    "employer",
                    "location",
                    "geography_code",
                    "salary_text",
                    "employment_type",
                    "workplace_type",
                    "posted_at",
                    "apply_method",
                    "teaser_text",
                    "sector",
                    "classification_text",
                    "subclassification_text",
                    "field_states",
                    "salary_normalized",
                )
                if key in item
            },
        }
    )
    return metadata


_JMM_FIELD_VALUE_KEYS = {
    "title": "title",
    "company": "employer",
    "location": "location",
    "geography_code": "geography_code",
    "posted_at": "posted_at",
    "classification": "classification_text",
    "subclassification": "subclassification_text",
    "employment_type": "employment_type",
    "workplace_type": "workplace_type",
    "apply_method": "apply_method",
    "salary": "salary_text",
    "description": "full_description",
}


def _known_market_value(
    item: dict[str, Any], field_states: dict[str, str], field: str
) -> Any:
    """Return a JMM fact only when JMM explicitly marks that field as current/known."""
    if field_states[field] != JMM_FIELD_STATE_KNOWN:
        return ""
    value_key = _JMM_FIELD_VALUE_KEYS[field]
    value = item.get(value_key)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise JobMarketMapContractError(
            f"Job Market Map marked {field!r} known but returned no current value"
        )
    return value


def _trusted_market_item(item: dict[str, Any], field_states: dict[str, str]) -> dict[str, Any]:
    """Build a view that cannot accidentally treat stale non-known values as current truth."""
    trusted = dict(item)
    for field, value_key in _JMM_FIELD_VALUE_KEYS.items():
        if field_states[field] != JMM_FIELD_STATE_KNOWN:
            trusted[value_key] = ""
    return trusted


def _matched_source_entries(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw = item.get("matched_sources")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise JobMarketMapContractError("Job Market Map matched_sources must be a list")

    entries: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int | None]] = set()
    for matched in raw:
        if not isinstance(matched, dict):
            raise JobMarketMapContractError("Job Market Map matched_sources entries must be objects")
        source = str(matched.get("source") or "").strip().lower()
        if not source:
            raise JobMarketMapContractError("Job Market Map matched source is missing source")
        source_job_id = str(matched.get("source_job_id") or "").strip()
        matched_job_id = matched.get("id")
        if matched_job_id is not None and (not isinstance(matched_job_id, int) or matched_job_id < 0):
            raise JobMarketMapContractError("Job Market Map matched source id is invalid")
        key = (source, source_job_id, matched_job_id)
        if key in seen:
            continue
        seen.add(key)
        entries.append(dict(matched))
    return entries


def _merge_jmm_matched_sources(record: dict[str, Any], item: dict[str, Any]) -> None:
    """Preserve JMM's confirmed same-vacancy source evidence on the JH record."""
    matched_sources = _matched_source_entries(item)
    if not matched_sources:
        return

    canonical_source = str(record.get("source") or "").strip().lower()
    canonical_job_key = str(record.get(RECORD_JOB_KEY) or "").strip()
    canonical_source_job_id = str(
        (record.get(RECORD_SOURCE_METADATA_KEY) or {}).get(RECORD_SOURCE_PLATFORM_JOB_ID_KEY) or ""
    ).strip()

    provenance = record.get(RECORD_SOURCE_PROVENANCE_KEY)
    provenance = [dict(entry) for entry in provenance if isinstance(entry, dict)] if isinstance(provenance, list) else []
    if not provenance:
        provenance.append(
            {
                "source": canonical_source,
                RECORD_SOURCE_NAME_KEY: canonical_source,
                RECORD_JOB_KEY: canonical_job_key,
                "url": str(record.get("url") or "").strip(),
                "title": str(record.get("title") or "").strip(),
                "company": str(record.get("company") or "").strip(),
                "location": str(record.get("location") or "").strip(),
                RECORD_SOURCE_METADATA_KEY: copy.deepcopy(record.get(RECORD_SOURCE_METADATA_KEY) or {}),
            }
        )

    duplicate_links = record.get(RECORD_DUPLICATE_LINKS_KEY)
    duplicate_links = [dict(link) for link in duplicate_links if isinstance(link, dict)] if isinstance(duplicate_links, list) else []

    provenance_keys = {
        (
            str(entry.get("source") or entry.get(RECORD_SOURCE_NAME_KEY) or "").strip().lower(),
            str((entry.get(RECORD_SOURCE_METADATA_KEY) or {}).get(RECORD_SOURCE_PLATFORM_JOB_ID_KEY) or "").strip(),
        )
        for entry in provenance
    }
    duplicate_keys = {
        (
            str(link.get("source") or "").strip().lower(),
            str((link.get("source_metadata") or {}).get(RECORD_SOURCE_PLATFORM_JOB_ID_KEY) or link.get("job_key") or "").strip(),
        )
        for link in duplicate_links
    }

    for matched in matched_sources:
        source = str(matched.get("source") or "").strip().lower()
        source_job_id = str(matched.get("source_job_id") or "").strip()
        is_canonical = source == canonical_source and (
            not source_job_id or source_job_id == canonical_source_job_id
        )
        if is_canonical:
            continue

        source_metadata = blank_source_metadata(source)
        source_metadata[RECORD_SOURCE_PLATFORM_JOB_ID_KEY] = source_job_id
        matched_url = str(matched.get("canonical_url") or matched.get("url") or "").strip()
        if matched_url:
            source_metadata[RECORD_SOURCE_CANONICAL_URL_KEY] = matched_url
        source_metadata["raw_source_fields"] = {"jmm_matched_source": copy.deepcopy(matched)}
        job_key = normalize_job_key(source_job_id, source=source) if source_job_id else ""
        provenance_key = (source, source_job_id)
        if provenance_key not in provenance_keys:
            provenance.append(
                {
                    "source": source,
                    RECORD_SOURCE_NAME_KEY: source,
                    RECORD_JOB_KEY: job_key,
                    "title": str(record.get("title") or "").strip(),
                    "company": str(record.get("company") or "").strip(),
                    "location": str(record.get("location") or "").strip(),
                    "url": matched_url,
                    RECORD_SOURCE_METADATA_KEY: source_metadata,
                }
            )
            provenance_keys.add(provenance_key)

        duplicate_key = (source, source_job_id or job_key)
        if duplicate_key not in duplicate_keys:
            duplicate_links.append(
                {
                    "kind": "confirmed_duplicate",
                    "matched_on": "jmm_same_vacancy",
                    "matched_value": str(item.get("id") or ""),
                    "source": source,
                    "title": str(record.get("title") or "").strip(),
                    "company": str(record.get("company") or "").strip(),
                    "job_key": job_key,
                    "url": matched_url,
                    "source_metadata": copy.deepcopy(source_metadata),
                    "source_provenance": provenance[-1] if provenance else {},
                }
            )
            duplicate_keys.add(duplicate_key)

    record[RECORD_SOURCE_PROVENANCE_KEY] = provenance
    if duplicate_links:
        record[RECORD_DUPLICATE_LINKS_KEY] = duplicate_links


def normalize_market_job(item: dict[str, Any], *, run_iso: str) -> dict[str, Any]:
    """Adapt JMM facts to JH's analysis input; the adapter does not persist market truth."""
    required = ("id", "identity_key", "source", "canonical_url")
    missing = [key for key in required if not str(item.get(key) or "").strip()]
    if missing:
        raise ValueError(f"Job Market Map item missing required fields: {', '.join(missing)}")
    source = str(item["source"]).strip().lower()
    source_job_id = str(item.get("source_job_id") or "").strip()
    job_key = (
        normalize_job_key(source_job_id, source=source)
        if source_job_id
        else str(item["identity_key"])
    )
    if not job_key:
        raise ValueError("Job Market Map item has no usable JH job identity")

    field_states = validate_market_job_field_states(item)
    salary_normalized = validate_market_job_salary_normalized(item, field_states)
    title = str(_known_market_value(item, field_states, "title") or "").strip()
    company = str(_known_market_value(item, field_states, "company") or "").strip()
    location = str(_known_market_value(item, field_states, "location") or "").strip()
    geography_code = str(
        _known_market_value(item, field_states, "geography_code") or ""
    ).strip()
    posted_at = str(_known_market_value(item, field_states, "posted_at") or "").strip()
    employment_type = str(
        _known_market_value(item, field_states, "employment_type") or ""
    ).strip()
    workplace_type = str(
        _known_market_value(item, field_states, "workplace_type") or ""
    ).strip()
    salary_text = str(_known_market_value(item, field_states, "salary") or "").strip()
    posted_age_days = days_since(posted_at, parse_timestamp(run_iso) or datetime.now(timezone.utc))
    workplace_state = field_states["workplace_type"]
    work_mode = (
        canonical_work_mode_value(workplace_type)
        if workplace_state == JMM_FIELD_STATE_KNOWN
        else WORK_MODE_UNKNOWN
    )
    work_mode_needs_review = workplace_state == "unknown" or (
        workplace_state == JMM_FIELD_STATE_KNOWN and work_mode == WORK_MODE_UNKNOWN
    )
    source_metadata = _source_metadata(item, source, source_job_id)
    record = build_initial_flat_record(
        run_iso=run_iso,
        search_location=geography_code or location,
        search_keywords="",
        source=source,
        job_key=job_key,
        title=title,
        company=company,
        location=location,
        posted_text=posted_at,
        posted_age_days=posted_age_days,
        work_mode=work_mode,
        work_mode_source="job_market_map",
        work_mode_evidence=[workplace_type] if workplace_type else [],
        work_mode_needs_review=work_mode_needs_review,
        work_type=employment_type,
        salary_str=salary_text,
        url=str(item["canonical_url"]).strip(),
        teaser=str(item.get("teaser_text") or "").strip(),
        details_text="",
        details_length=0,
        source_metadata=source_metadata,
    )
    record[RECORD_SOURCE_NAME_KEY] = source
    parsing_rules = load_parsing_rules()
    government_config = parsing_rules.get("government_discovery_config")
    government_terms = (
        government_config.get("government_terms", [])
        if isinstance(government_config, dict)
        else []
    )
    record[RECORD_SECTOR_KEY] = classify_market_sector(
        _trusted_market_item(item, field_states), government_terms
    )
    record[RECORD_MARKET_MAP_JOB_ID_KEY] = int(item["id"])
    record[RECORD_MARKET_MAP_IDENTITY_KEY] = str(item["identity_key"]).strip()
    record[RECORD_MARKET_MAP_FIELD_STATES_KEY] = copy.deepcopy(field_states)
    record[RECORD_MARKET_MAP_SALARY_NORMALIZED_KEY] = copy.deepcopy(salary_normalized)
    apply_method = (
        str(_known_market_value(item, field_states, "apply_method") or "").strip().lower()
        if field_states["apply_method"] == JMM_FIELD_STATE_KNOWN
        else APPLY_METHOD_UNKNOWN
    )
    if apply_method not in {
        APPLY_METHOD_UNKNOWN,
        APPLY_METHOD_EASY_APPLY,
        APPLY_METHOD_QUICK_APPLY,
        APPLY_METHOD_EXTERNAL_APPLY,
    }:
        raise JobMarketMapContractError(
            f"Job Market Map returned unsupported known apply_method: {apply_method!r}"
        )
    record[RECORD_APPLY_METHOD_KEY] = apply_method
    record[RECORD_SOURCE_METADATA_KEY][RECORD_SOURCE_PLATFORM_JOB_ID_KEY] = source_job_id
    _merge_jmm_matched_sources(record, item)
    return record


_TRANSIENT_JD_FIELDS = frozenset(
    {
        "full_description",
        "details_text",
        "fit_source_text",
        "description_compaction",
    }
)


@dataclass(frozen=True, slots=True)
class _IndexedJob:
    index: int
    record: dict[str, Any]
    title_assessment: TitleGateAssessment


@dataclass(frozen=True, slots=True)
class _JdOutcome:
    index: int
    payload: Any


@dataclass(frozen=True, slots=True)
class _FitOutcome:
    index: int
    record: Any
    outcome: Any
    observations: tuple[Any, ...]
    cache_updates: Any
    pending_learning_signals: tuple[Any, ...]


def _freeze(value: Any) -> Any:
    """Deep-freeze a worker result before handing it to the coordinator."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, MappingProxyType):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, frozenset)):
        return [_thaw(item) for item in value]
    return copy.deepcopy(value)


def _thaw_title_judgment_result(result: TitleJudgmentResult) -> TitleJudgmentResult:
    """Return ordinary coordinator-owned data after a frozen worker hand-off."""
    return TitleJudgmentResult(
        cache_key=result.cache_key,
        judgment=_thaw(result.judgment),
        cache_value=_thaw(result.cache_value),
        cache_hit=result.cache_hit,
    )


def _cache_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in after.items()
        if key not in before or before[key] != value
    }


def _merge_completed_title_cache(
    review_context: ReviewPipelineContext,
    title_results: dict[int, Any],
) -> None:
    """Keep cache values from title workers that finished before a stop."""
    for result in title_results.values():
        if not isinstance(result, tuple) or len(result) != 2:
            continue
        title_result = result[1]
        if isinstance(title_result, TitleJudgmentResult) and title_result.cache_value is not None:
            review_context.llm_cache[title_result.cache_key] = _thaw(title_result.cache_value)


def _merge_completed_fit_cache(
    review_context: ReviewPipelineContext,
    fit_results: dict[int, Any],
) -> None:
    """Keep cache deltas from fit workers that finished before a stop."""
    for result in fit_results.values():
        cache_updates = getattr(result, "cache_updates", None)
        if cache_updates:
            review_context.llm_cache.update(_thaw(cache_updates))


def _run_parallel_stage(
    jobs: list[_IndexedJob],
    *,
    worker_limit: int,
    worker: Any,
    on_failure: Any | None = None,
    on_progress: Any | None = None,
    collect_failures: bool = False,
) -> tuple[dict[int, Any], bool] | tuple[dict[int, Any], bool, dict[int, Exception]]:
    """Run one bounded stage and cancel work that has not started on stop."""
    if not jobs or run_stop_requested():
        if collect_failures:
            return {}, run_stop_requested(), {}
        return {}, run_stop_requested()

    executor = ThreadPoolExecutor(max_workers=min(worker_limit, len(jobs)))
    # ContextVars do not cross ThreadPoolExecutor boundaries on their own.
    # Each job needs an independent snapshot so user-scoped JH helpers keep
    # the caller's identity without workers sharing one Context instance.
    futures = {
        executor.submit(contextvars.copy_context().run, worker, job): job.index for job in jobs
    }
    pending = set(futures)
    results: dict[int, Any] = {}
    errors: dict[int, Exception] = {}
    stopped = False
    try:
        while pending:
            if run_stop_requested():
                stopped = True
                for future in pending:
                    future.cancel()
            done, pending = wait(
                pending,
                timeout=0.05,
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                if future.cancelled():
                    continue
                job_index = futures[future]
                error: Exception | None = None
                try:
                    results[job_index] = future.result()
                except Exception as exc:
                    errors[job_index] = exc
                    error = exc
                if on_progress is not None:
                    on_progress(job_index, len(results) + len(errors), len(jobs), error)
            if stopped:
                for future in pending:
                    future.cancel()
        if errors and not stopped and collect_failures:
            return results, stopped, errors
        if errors and not stopped:
            if on_failure is not None:
                on_failure()
            raise next(iter(errors.values()))
        if collect_failures:
            return results, stopped, errors
        return results, stopped
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def remove_transient_jd(record: dict[str, Any]) -> dict[str, Any]:
    """Keep JH analysis/provenance while preventing a second permanent JD copy."""
    cleaned = dict(record)
    for key in _TRANSIENT_JD_FIELDS:
        cleaned.pop(key, None)
    return cleaned


def _fetch_jd_payload(record: dict[str, Any], client: JobMarketMapClient) -> dict[str, Any]:
    jd_payload = client.get_cached_jd(
        jmm_job_id=int(record[RECORD_MARKET_MAP_JOB_ID_KEY]),
        identity_key=str(record[RECORD_MARKET_MAP_IDENTITY_KEY]),
    )
    full_description = str(jd_payload.get("full_description") or "").strip()
    if not full_description:
        raise ValueError("Job Market Map returned no current full_description")
    return dict(jd_payload)


def _hydrate_jd(record: dict[str, Any], client: JobMarketMapClient) -> None:
    jd_payload = _fetch_jd_payload(record, client)
    _apply_jd_payload(record, jd_payload)


def _apply_jd_payload(record: dict[str, Any], jd_payload: dict[str, Any]) -> None:
    full_description = str(jd_payload.get("full_description") or "").strip()
    record[RECORD_DETAILS_TEXT_KEY] = full_description
    record[RECORD_DETAILS_STATUS_KEY] = "ok"
    record[RECORD_DESCRIPTION_SOURCE_KEY] = str(jd_payload.get("jd_source") or "job_market_map")
    record[RECORD_MARKET_MAP_JD_SOURCE_KEY] = str(jd_payload.get("jd_source") or "").strip()
    record[RECORD_MARKET_MAP_JD_FETCHED_AT_KEY] = str(jd_payload.get("jd_fetched_at") or "").strip()


def _build_worker_context(context, *, llm_cache: dict[str, Any]) -> ReviewPipelineContext:
    """Give a fit worker private snapshots of every mutable review container."""
    return ReviewPipelineContext(
        profile=copy.deepcopy(context.profile),
        job_history=copy.deepcopy(context.job_history),
        audit_rows=[],
        llm_cache=copy.deepcopy(llm_cache),
        applied_job_keys=set(context.applied_job_keys),
        hidden_job_keys=set(context.hidden_job_keys),
        run_iso=context.run_iso,
        date_range_days=context.configured_date_range,
        source_name="Job Market Map",
        identity_registry=None,
        market_map_mode=True,
        defer_finalization=True,
        defer_learning_signals=True,
    )


def _release_unfinalized_identity_claims(jobs: list[_IndexedJob]) -> None:
    """Release coordinator claims when a page is stopped or fails mid-stage."""
    for job in jobs:
        claim = job.record.pop(RUN_IDENTITY_CLAIM_KEY, None)
        if isinstance(claim, tuple) and len(claim) == 2:
            registry, token = claim
            registry.release(token)


def _append_retryable_jd_failure(
    review_context: ReviewPipelineContext,
    job: _IndexedJob,
    error: Exception,
) -> None:
    """Record a failed JMM JD request without completing its identity claim."""
    record = job.record
    claim = record.pop(RUN_IDENTITY_CLAIM_KEY, None)
    record[RECORD_DECISION_KEY] = "REJECT"
    record[RECORD_REJECT_REASON_KEY] = REJECT_REASON_JMM_JD_ENRICHMENT_FAILED
    record[RECORD_DECISION_EXPLANATION_KEY] = str(error)
    record[RECORD_RETRYABLE_KEY] = True
    record[RECORD_RETRY_REASON_KEY] = REJECT_REASON_JMM_JD_ENRICHMENT_FAILED
    try:
        finalize_record(
            review_context.job_history,
            review_context.audit_rows,
            record,
            review_context.run_iso,
            persist_full_description=False,
            update_history=False,
        )
    finally:
        if isinstance(claim, tuple) and len(claim) == 2:
            registry, token = claim
            registry.release(token)


def _append_jd_not_cached(
    review_context: ReviewPipelineContext,
    job: _IndexedJob,
    error: JobMarketMapJDNotCached,
) -> None:
    """Audit a per-job JMM cache miss without treating it as source failure."""
    record = job.record
    claim = record.pop(RUN_IDENTITY_CLAIM_KEY, None)
    record[RECORD_DECISION_KEY] = "REJECT"
    record[RECORD_REJECT_REASON_KEY] = REJECT_REASON_JMM_JD_NOT_CACHED
    record[RECORD_DECISION_EXPLANATION_KEY] = str(error)
    record[RECORD_RETRYABLE_KEY] = True
    record[RECORD_RETRY_REASON_KEY] = REJECT_REASON_JMM_JD_NOT_CACHED
    try:
        finalize_record(
            review_context.job_history,
            review_context.audit_rows,
            record,
            review_context.run_iso,
            persist_full_description=False,
            update_history=False,
        )
    finally:
        if isinstance(claim, tuple) and len(claim) == 2:
            registry, token = claim
            registry.release(token)


def _append_terminal_jd_unavailable(
    review_context: ReviewPipelineContext,
    job: _IndexedJob,
    error: JobMarketMapJDUnavailable,
) -> None:
    """Audit a terminal JMM JD disappearance and allow the page to complete."""
    record = job.record
    claim = record.pop(RUN_IDENTITY_CLAIM_KEY, None)
    record[RECORD_DECISION_KEY] = "REJECT"
    record[RECORD_REJECT_REASON_KEY] = REJECT_REASON_JMM_JD_UNAVAILABLE
    record[RECORD_DECISION_EXPLANATION_KEY] = str(error)
    record[RECORD_RETRYABLE_KEY] = False
    record.pop(RECORD_RETRY_REASON_KEY, None)
    try:
        finalize_record(
            review_context.job_history,
            review_context.audit_rows,
            record,
            review_context.run_iso,
            persist_full_description=False,
            update_history=False,
        )
    finally:
        if isinstance(claim, tuple) and len(claim) == 2:
            registry, token = claim
            registry.release(token)


def _run_title_worker(
    job: _IndexedJob,
    *,
    profile: dict[str, Any],
    llm_cache: dict[str, Any],
) -> tuple[int, TitleJudgmentResult]:
    result = review_title_judgment(
        str(job.record.get(RECORD_TITLE_KEY) or ""),
        copy.deepcopy(profile),
        copy.deepcopy(llm_cache),
    )
    return job.index, TitleJudgmentResult(
        cache_key=result.cache_key,
        judgment=_freeze(result.judgment),
        cache_value=_freeze(result.cache_value),
        cache_hit=result.cache_hit,
    )


def _run_jd_worker(job: _IndexedJob, *, client: JobMarketMapClient) -> _JdOutcome:
    return _JdOutcome(
        index=job.index,
        payload=_freeze(_fetch_jd_payload(job.record, client)),
    )


def _run_fit_worker(
    job: _IndexedJob,
    *,
    context,
    llm_cache: dict[str, Any],
) -> _FitOutcome:
    worker_context = _build_worker_context(context, llm_cache=llm_cache)
    # The coordinator owns the live identity claim. Its registry contains a
    # thread lock, so remove it before making the worker's isolated deep copy.
    # The original record keeps the claim for the ordered coordinator merge.
    claim_free_record = {
        key: value for key, value in job.record.items() if key != RUN_IDENTITY_CLAIM_KEY
    }
    worker_record = copy.deepcopy(claim_free_record)
    outcome, reviewed_record, observations = review_post_detail_normalized_job(
        worker_record,
        worker_context,
    )
    return _FitOutcome(
        index=job.index,
        record=_freeze(reviewed_record),
        outcome=_freeze(outcome),
        observations=tuple(_freeze(observation) for observation in observations),
        cache_updates=_freeze(_cache_delta(llm_cache, worker_context.llm_cache)),
        pending_learning_signals=tuple(
            _freeze(signal) for signal in worker_context.deferred_learning_signals
        ),
    )


def _set_market_map_progress(
    text: str,
    *,
    stage: str,
    headline: str,
    detail: str = "",
    current: int | None = None,
    total: int | None = None,
    determinate: bool | None = None,
) -> None:
    """Publish JMM-owned work through the shared wait-state progress contract.

    Filtered search pages provide a matching canonical-vacancy total, which JH
    uses transiently to keep the existing stage/headline progress contract
    determinate without persisting JMM search state.
    """
    set_run_progress_state(
        text,
        stage=stage,
        source=SOURCE_JOB_MARKET_MAP,
        headline=headline,
        detail=detail,
        current=current,
        total=total,
        determinate=determinate,
    )


def _posted_after_for_source(context, source: str) -> str:
    run_at = parse_timestamp(context.run_iso)
    if run_at is None:
        raise ValueError("JMM search requires a valid JH run timestamp")
    if source == SOURCE_LINKEDIN:
        hours_old = int(
            context.search_settings.get(
                KEY_LINKEDIN_HOURS_OLD,
                DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD],
            )
            or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
        )
        return (run_at - timedelta(hours=max(1, hours_old))).isoformat()
    return (run_at - timedelta(days=max(1, context.configured_date_range))).isoformat()


def _setting_values(settings: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        raw = settings.get(key)
        if raw in (None, "", []):
            continue
        values = raw if isinstance(raw, (list, tuple, set)) else [raw]
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value).strip()
            marker = text.casefold()
            if text and marker not in seen:
                seen.add(marker)
                cleaned.append(text)
        return cleaned
    return []


def _employment_type_filters(profile: dict[str, Any]) -> list[str]:
    preferences = profile.get("match_preferences") or {}
    selected = normalize_engagement_type_preferences(preferences.get("engagement_type"))
    if set(selected) == set(ENGAGEMENT_TYPE_DEFAULT_VALUES):
        return []

    group_labels: set[str] = set()
    if "permanent" in selected:
        group_labels.add("permanent")
    if "contract" in selected:
        group_labels.add("contract / temp")
    if "full_time_contract" in selected:
        group_labels.add("full time contract")

    values: list[str] = []
    seen: set[str] = set()
    for group in load_job_type_filter_groups():
        if str(group.get("label") or "").strip().casefold() not in group_labels:
            continue
        for value in group.get("values") or []:
            text = str(value).strip()
            marker = text.casefold()
            if text and marker not in seen:
                seen.add(marker)
                values.append(text)
    return values


def _workplace_type_filters(profile: dict[str, Any]) -> list[str]:
    preferences = profile.get("match_preferences") or {}
    selected = normalize_work_mode_preferences(preferences.get(KEY_WORK_MODE_PREFERENCE))
    if set(selected) == set(WORK_MODE_PREFERENCE_DEFAULT_VALUES):
        return []
    values: list[str] = []
    for mode in selected:
        if mode == "onsite":
            values.extend(["On-site", "On site", "Onsite"])
        elif mode:
            values.append(mode.title())
    return values


def _salary_search_filters(profile: dict[str, Any]) -> list[dict[str, Any]]:
    salary_preferences = profile.get("salary_preferences") or {}
    yearly = int(salary_preferences.get("minimum_salary_yearly") or 0)
    daily = int(salary_preferences.get("minimum_daily_rate") or 0)
    annual_filter = {
        "salary_min": yearly,
        "salary_period": "year",
        "salary_currency": "AUD",
    }
    daily_filter = {
        "salary_min": daily,
        "salary_period": "day",
        "salary_currency": "AUD",
    }
    if yearly <= 0 and daily <= 0:
        return [{}]
    if yearly > 0 and daily <= 0:
        return [annual_filter]
    if daily > 0 and yearly <= 0:
        return [daily_filter]

    selected = set(
        normalize_engagement_type_preferences(
            (profile.get("match_preferences") or {}).get("engagement_type")
        )
    )
    if selected and selected <= {"permanent"}:
        return [annual_filter]
    if selected and selected <= {"contract", "full_time_contract"}:
        return [daily_filter]

    # JMM accepts one salary period/currency per search. When JH has both an
    # annual and a daily floor, query both neutral scopes and union them by JMM
    # canonical id. JMM deliberately preserves period-incomparable/uncertain
    # salaries; the existing JH preference gate remains the final authority.
    return [annual_filter, daily_filter]


def _apply_method_filters(search_settings: dict[str, Any], source: str) -> list[str]:
    if source == SOURCE_SEEK:
        setting = search_settings.get(KEY_SEEK_QUICK_APPLY_ONLY)
        if setting is None:
            return []
        return [APPLY_METHOD_QUICK_APPLY if bool(setting) else APPLY_METHOD_EXTERNAL_APPLY]
    if source == SOURCE_LINKEDIN:
        setting = search_settings.get(KEY_LINKEDIN_EASY_APPLY_ONLY)
        if setting is None:
            return []
        return [APPLY_METHOD_EASY_APPLY if bool(setting) else APPLY_METHOD_EXTERNAL_APPLY]
    return []


def _location_search_scopes(search_settings: dict[str, Any]) -> list[tuple[list[str], list[str]]]:
    raw_locations = _setting_values(search_settings, "locations")
    if not raw_locations:
        return [([], [])]
    scopes: list[tuple[list[str], list[str]]] = []
    for value in raw_locations:
        resolved = resolve_location(value)
        geography = str(
            resolved.get("market_map_geography_code") or resolved.get("code") or ""
        ).strip().upper()
        location_values: list[str] = []
        if str(resolved.get("kind") or "").strip().casefold() == "city":
            location_name = str(resolved.get("name") or resolved.get("code") or value).strip()
            if location_name:
                location_values.append(location_name)
        scopes.append(([geography] if geography else [], location_values))
    return scopes


def _build_market_search_scopes(context) -> list[dict[str, Any]]:
    search_settings = context.search_settings
    role_terms = ordered_profile_search_terms(search_settings, context.profile)
    if not role_terms:
        raise ValueError(
            "No preferred role is configured. Please complete onboarding and add a preferred role before running."
        )
    selected_sources: list[str] = []
    for source in context.enabled_sources:
        source_key = str(source).strip().lower()
        if not source_key or source_key == SOURCE_JOB_MARKET_MAP or source_key in selected_sources:
            continue
        selected_sources.append(source_key)
    if not selected_sources:
        raise ValueError("No market source is selected for the JMM search")

    # JMM's `classification` filter is textual (`classification_text`). Existing
    # JH `classification_ids` are source-native board IDs, so forwarding them as
    # names can falsely exclude valid jobs. Only explicit text classifications
    # are safe to send until JMM exposes a source-native classification-id field.
    classifications = _setting_values(search_settings, "classification", "classifications")
    subclassifications = _setting_values(
        search_settings, "subclassification", "subclassifications"
    )
    companies = _setting_values(search_settings, "company", "companies", "employers")
    employment_types = _employment_type_filters(context.profile)
    workplace_types = _workplace_type_filters(context.profile)
    salary_filters = _salary_search_filters(context.profile)

    scopes: list[dict[str, Any]] = []
    for source in selected_sources:
        for geography_codes, locations in _location_search_scopes(search_settings):
            for salary_filter in salary_filters:
                scopes.append(
                    {
                        "role_terms": role_terms,
                        "sources": [source],
                        "geography_codes": geography_codes,
                        "locations": locations,
                        # Forward configured classification values verbatim. JH must
                        # not translate/recreate SEEK, LinkedIn or APS taxonomies.
                        "classifications": classifications,
                        "subclassifications": subclassifications,
                        "employment_types": employment_types,
                        "workplace_types": workplace_types,
                        "apply_methods": _apply_method_filters(search_settings, source),
                        "companies": companies,
                        "posted_after": _posted_after_for_source(context, source),
                        **salary_filter,
                    }
                )
    return scopes


def _iter_filtered_market_pages(context, client: JobMarketMapClient):
    """Yield progressive pages inside one fixed market boundary for the whole run."""
    run_snapshot_max_id: int | None = None
    for scope in _build_market_search_scopes(context):
        cursor = 0
        scope_total: int | None = None
        while True:
            page = client.search_page(
                **scope,
                after_id=cursor,
                through_id=run_snapshot_max_id,
            )
            page_snapshot_max_id = page.get("snapshot_max_id")
            if not isinstance(page_snapshot_max_id, int) or page_snapshot_max_id < 0:
                raise JobMarketMapContractError(
                    "Job Market Map search snapshot_max_id is required"
                )
            if run_snapshot_max_id is None:
                run_snapshot_max_id = page_snapshot_max_id
            elif page_snapshot_max_id != run_snapshot_max_id:
                raise JobMarketMapContractError(
                    "Job Market Map search snapshot boundary changed during the run"
                )

            page_total = page.get("total")
            if not isinstance(page_total, int) or page_total < 0:
                raise JobMarketMapContractError("Job Market Map search total is required")
            if scope_total is None:
                scope_total = page_total
            elif page_total != scope_total:
                raise JobMarketMapContractError(
                    "Job Market Map search total changed within a fixed search scope"
                )

            yield page
            if not page["has_more"]:
                break
            next_cursor = int(page["next_cursor"])
            if next_cursor == cursor:
                raise JobMarketMapContractError("Job Market Map search cursor did not advance")
            cursor = next_cursor


def run_market_map_source(context) -> tuple[list[dict], list[dict], list[dict]]:
    """Search JMM within JH's selected scope, then run the existing JH pipeline."""
    _set_market_map_progress(
        "Finding matching jobs",
        stage="starting",
        headline="Finding matching jobs",
    )
    client = JobMarketMapClient.from_environment()
    readiness_reader = getattr(client, "get_readiness", None)
    if callable(readiness_reader):
        _record_jmm_readiness(readiness_reader(), run_id=context.run_iso)
    review_context = ReviewPipelineContext(
        profile=context.profile,
        job_history=context.job_history,
        audit_rows=[],
        llm_cache=context.llm_cache,
        applied_job_keys=context.applied_job_keys,
        hidden_job_keys=context.hidden_job_keys,
        seen_job_keys=set(),
        seen_urls=set(),
        run_iso=context.run_iso,
        date_range_days=context.configured_date_range,
        source_name="Job Market Map",
        identity_registry=context.identity_registry,
        market_map_mode=True,
    )
    kept_records: list[dict] = []
    skill_observations: list[dict] = []
    worker_limit = get_job_market_map_parallel_workers()
    analysed_count = 0
    jd_cache_miss_count = 0
    _set_market_map_progress(
        "Loading matching jobs",
        stage="source_collection",
        headline="Loading matching jobs",
        detail="Loading the bounded Job Market Map result set",
        current=0,
        total=None,
        determinate=False,
    )
    seen_market_ids: set[int] = set()
    records_by_market_id: dict[int, dict[str, Any]] = {}
    for page in _iter_filtered_market_pages(context, client):
        page_items: list[dict] = []
        for item in page["items"]:
            item_id = item.get("id")
            if not isinstance(item_id, int) or item_id < 0:
                raise JobMarketMapContractError("Job Market Map search item id is invalid")
            if item_id in seen_market_ids:
                existing_record = records_by_market_id.get(item_id)
                if existing_record is not None:
                    _merge_jmm_matched_sources(existing_record, item)
                continue
            seen_market_ids.add(item_id)
            page_items.append(item)
        if not page_items:
            continue

        # Process this bounded page before requesting the next cursor page. For
        # overlapping source/location scopes the JMM total is informational; JH
        # de-duplicates canonical vacancy ids as pages arrive.
        search_total = max(int(page["total"]), analysed_count + len(page_items))
        _set_market_map_progress(
            "Loading matching jobs",
            stage="source_collection",
            headline="Loading matching jobs",
            detail=f"Processing {len(page_items)} matching jobs from the current page",
            current=analysed_count,
            total=search_total,
            determinate=True,
        )
        page_item_total = len(page_items)
        page_jobs: list[_IndexedJob] = []
        for item_index, item in enumerate(page_items):
            title = str(item.get("title") or "").strip()
            progress_current = analysed_count + item_index + 1
            progress_headline = f"Checking job titles — {progress_current} of {search_total}"
            _set_market_map_progress(
                progress_headline,
                stage="relevance_analysis",
                headline=progress_headline,
                detail=title,
                current=progress_current,
                total=search_total,
                determinate=True,
            )
            record = normalize_market_job(item, run_iso=context.run_iso)
            records_by_market_id[int(item["id"])] = record
            page_jobs.append(
                _IndexedJob(
                    index=item_index,
                    record=record,
                    title_assessment=prepare_title_gate_assessment(title, review_context.profile),
                )
            )

        jobs_by_index = {job.index: job for job in page_jobs}
        title_jobs: list[_IndexedJob] = []
        title_jobs_by_cache_key: dict[str, _IndexedJob] = {}
        for job in page_jobs:
            assessment = job.title_assessment
            if (
                bool(assessment.title_analysis.get("ok"))
                or str(assessment.title_analysis.get("reason") or "") != "TITLE_NOT_TARGET"
                or assessment.onet is None
                or (
                    assessment.onet.result == RESULT_FAR
                    and not bool(review_context.profile.get(KEY_EXPLORE_ADJACENT_ROLES, False))
                )
            ):
                continue
            cache_key = assessment.title_judgment_cache_key
            if cache_key is None:
                raise ValueError("JMM title assessment did not provide its cache key")
            if cache_key not in title_jobs_by_cache_key:
                title_jobs_by_cache_key[cache_key] = job
                title_jobs.append(job)
        if title_jobs:
            _set_market_map_progress(
                f"Resolving title matches — 0 of {len(title_jobs)}",
                stage="relevance_analysis",
                headline=f"Resolving title matches — 0 of {len(title_jobs)}",
                detail="Checking uncertain job titles against your target roles",
                current=0,
                total=len(title_jobs),
                determinate=True,
            )
        title_results, stopped = _run_parallel_stage(
            title_jobs,
            worker_limit=worker_limit,
            worker=lambda job: _run_title_worker(
                job,
                profile=review_context.profile,
                llm_cache=review_context.llm_cache,
            ),
            on_failure=lambda: _release_unfinalized_identity_claims(page_jobs),
            on_progress=lambda index, completed, total, error: _set_market_map_progress(
                f"Resolving title matches — {completed} of {total}",
                stage="relevance_analysis",
                headline=f"Resolving title matches — {completed} of {total}",
                detail=str(jobs_by_index[index].record.get("title") or ""),
                current=completed,
                total=total,
                determinate=True,
            ),
        )
        if stopped:
            _merge_completed_title_cache(review_context, title_results)
            save_llm_cache(review_context.llm_cache)
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations
        if run_stop_requested():
            _merge_completed_title_cache(review_context, title_results)
            save_llm_cache(review_context.llm_cache)
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations

        title_results_by_cache_key: dict[str, TitleJudgmentResult] = {}
        for job in title_jobs:
            if job.index not in title_results:
                continue
            cache_key = job.title_assessment.title_judgment_cache_key
            if cache_key is None:
                raise ValueError("JMM title result did not have a cache key")
            title_results_by_cache_key[cache_key] = title_results[job.index][1]
        for job in page_jobs:
            cache_key = job.title_assessment.title_judgment_cache_key
            if cache_key is None or cache_key not in title_results_by_cache_key:
                continue
            title_result = _thaw_title_judgment_result(title_results_by_cache_key[cache_key])
            if title_result.cache_value is not None:
                review_context.llm_cache[title_result.cache_key] = _thaw(title_result.cache_value)
            jobs_by_index[job.index] = replace(
                job,
                title_assessment=replace(job.title_assessment, title_judgment=title_result),
            )
        # Persist completed title judgements before detail/fit work. A server
        # stop later in this page must not discard valid cache entries, while
        # job results remain uncommitted until the page
        # is finalized.
        save_llm_cache(review_context.llm_cache)
        page_jobs = [jobs_by_index[index] for index in range(page_item_total)]

        eligible_jobs: list[_IndexedJob] = []
        for job in page_jobs:
            if run_stop_requested():
                _release_unfinalized_identity_claims(page_jobs)
                return kept_records, review_context.audit_rows, skill_observations
            job_key = str(job.record.get(RECORD_JOB_KEY) or "")
            review_context.title_assessments.setdefault(job_key, []).append(job.title_assessment)
            try:
                pre_outcome, _, _, should_fetch_details = review_pre_detail_normalized_job(
                    job.record, review_context
                )
            except Exception:
                _release_unfinalized_identity_claims(page_jobs)
                raise
            if pre_outcome["decision"] == "KEEP" and should_fetch_details:
                eligible_jobs.append(job)

        if eligible_jobs:
            _set_market_map_progress(
                f"Getting job descriptions — 0 of {len(eligible_jobs)}",
                stage="job_detail",
                headline=f"Getting job descriptions — 0 of {len(eligible_jobs)}",
                detail="Reading full descriptions for jobs that passed the title checks",
                current=0,
                total=len(eligible_jobs),
                determinate=True,
            )
        jd_results, stopped, jd_failures = _run_parallel_stage(
            eligible_jobs,
            worker_limit=worker_limit,
            worker=lambda job: _run_jd_worker(job, client=client),
            on_failure=lambda: _release_unfinalized_identity_claims(page_jobs),
            on_progress=lambda index, completed, total, error: _set_market_map_progress(
                f"Getting job descriptions — {completed} of {total}",
                stage="job_detail",
                headline=f"Getting job descriptions — {completed} of {total}",
                detail=str(jobs_by_index[index].record.get("title") or ""),
                current=completed,
                total=total,
                determinate=True,
            ),
            collect_failures=True,
        )
        if stopped:
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations
        if run_stop_requested():
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations

        for index in sorted(jd_results):
            job = jobs_by_index[index]
            _apply_jd_payload(job.record, _thaw(jd_results[index].payload))

        fit_base_cache = copy.deepcopy(review_context.llm_cache)
        fit_jobs = [job for job in eligible_jobs if job.index in jd_results]
        if fit_jobs:
            _set_market_map_progress(
                f"Reviewing job fit — 0 of {len(fit_jobs)}",
                stage="scoring",
                headline=f"Reviewing job fit — 0 of {len(fit_jobs)}",
                detail="Comparing job requirements with your profile",
                current=0,
                total=len(fit_jobs),
                determinate=True,
            )
        fit_results, stopped = _run_parallel_stage(
            fit_jobs,
            worker_limit=worker_limit,
            worker=lambda job: _run_fit_worker(
                job,
                context=context,
                llm_cache=fit_base_cache,
            ),
            on_failure=lambda: _release_unfinalized_identity_claims(page_jobs),
            on_progress=lambda index, completed, total, error: _set_market_map_progress(
                f"Reviewing job fit — {completed} of {total}",
                stage="scoring",
                headline=f"Reviewing job fit — {completed} of {total}",
                detail=str(jobs_by_index[index].record.get("title") or ""),
                current=completed,
                total=total,
                determinate=True,
            ),
        )
        if stopped:
            _merge_completed_fit_cache(review_context, fit_results)
            save_llm_cache(review_context.llm_cache)
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations
        if run_stop_requested():
            _merge_completed_fit_cache(review_context, fit_results)
            save_llm_cache(review_context.llm_cache)
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations

        retryable_jd_failures = {
            index: error
            for index, error in jd_failures.items()
            if not isinstance(error, (JobMarketMapJDUnavailable, JobMarketMapJDNotCached))
        }
        result_indexes = sorted(set(fit_results) | set(jd_failures))
        for completed_results, index in enumerate(result_indexes, start=1):
            if run_stop_requested():
                _release_unfinalized_identity_claims(page_jobs)
                return kept_records, review_context.audit_rows, skill_observations
            job = jobs_by_index[index]
            if index in jd_failures:
                error = jd_failures[index]
                if isinstance(error, JobMarketMapJDNotCached):
                    jd_cache_miss_count += 1
                    _append_jd_not_cached(review_context, job, error)
                elif isinstance(error, JobMarketMapJDUnavailable):
                    _append_terminal_jd_unavailable(review_context, job, error)
                else:
                    _append_retryable_jd_failure(review_context, job, error)
                continue
            result = fit_results[index]
            _set_market_map_progress(
                f"Finalising results — {completed_results} of {len(result_indexes)}",
                stage="finalising",
                headline=f"Finalising results — {completed_results} of {len(result_indexes)}",
                detail=str(job.record.get("title") or ""),
                current=completed_results,
                total=len(result_indexes),
                determinate=True,
            )
            claim = job.record.get(RUN_IDENTITY_CLAIM_KEY)
            merged_record = _thaw(result.record)
            job.record.clear()
            job.record.update(merged_record)
            if claim is not None:
                job.record[RUN_IDENTITY_CLAIM_KEY] = claim
            review_context.llm_cache.update(_thaw(result.cache_updates))
            pending_signals = _thaw(result.pending_learning_signals)
            if pending_signals:
                register_pending_learning_signals(pending_signals)
            finalize_record(
                review_context.job_history,
                review_context.audit_rows,
                job.record,
                review_context.run_iso,
                persist_full_description=False,
                update_history=False,
            )
            outcome = _thaw(result.outcome)
            if outcome["decision"] == "KEEP":
                kept_record = remove_transient_jd(job.record)
                kept_records.append(kept_record)
                records_by_market_id[int(job.record[RECORD_MARKET_MAP_JOB_ID_KEY])] = kept_record
                skill_observations.extend(_thaw(result.observations))

        # Fit workers return immutable cache deltas; save only after the
        # coordinator merges them in deterministic input order.
        save_llm_cache(review_context.llm_cache)

        if run_stop_requested():
            return kept_records, review_context.audit_rows, skill_observations
        if retryable_jd_failures:
            raise PartialSourceResultsError(
                SOURCE_JOB_MARKET_MAP,
                kept_records=kept_records,
                audit_rows=review_context.audit_rows,
                skill_observations=skill_observations,
                original_error=retryable_jd_failures[min(retryable_jd_failures)],
            )
        analysed_count += page_item_total

    logger.info(
        "[JMM][JD_CACHE] available_fit_jobs=%d not_cached=%d",
        len(kept_records),
        jd_cache_miss_count,
    )
    _set_market_map_progress(
        "Search review complete",
        stage="source_collection",
        headline="Search review complete",
        detail=f"{analysed_count:,} jobs analysed; {jd_cache_miss_count:,} JDs not cached",
        current=analysed_count,
        total=analysed_count,
        determinate=True,
    )
    return kept_records, review_context.audit_rows, skill_observations
