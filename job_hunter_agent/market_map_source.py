"""Consume Job Market Map neutral jobs and run JH-owned candidate analysis."""

from __future__ import annotations

import copy
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from job_hunter_agent.global_settings import get_job_market_map_parallel_workers
from job_hunter_agent.history import finalize_record
from job_hunter_agent.job_identity import RUN_IDENTITY_CLAIM_KEY, normalize_job_key
from job_hunter_agent.job_market_map_client import (
    MARKET_MAP_CONSUMER_KEY_PREFIX,
    JobMarketMapClient,
    JobMarketMapContractError,
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
from job_hunter_agent.occupation_taxonomy import RESULT_FAR
from job_hunter_agent.posting_utils import days_since, parse_timestamp
from job_hunter_agent.profile_store import KEY_EXPLORE_ADJACENT_ROLES
from job_hunter_agent.record_schema import (
    APPLY_METHOD_UNKNOWN,
    RECORD_APPLY_METHOD_KEY,
    RECORD_DECISION_EXPLANATION_KEY,
    RECORD_DECISION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_JOB_KEY,
    RECORD_MARKET_MAP_IDENTITY_KEY,
    RECORD_MARKET_MAP_JD_FETCHED_AT_KEY,
    RECORD_MARKET_MAP_JD_SOURCE_KEY,
    RECORD_MARKET_MAP_JOB_ID_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_RETRY_REASON_KEY,
    RECORD_RETRYABLE_KEY,
    RECORD_SOURCE_CANONICAL_URL_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_NAME_KEY,
    RECORD_SOURCE_PLATFORM_JOB_ID_KEY,
    RECORD_TITLE_KEY,
    RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    RECORD_WORK_MODE_SOURCE_KEY,
)
from job_hunter_agent.run_control import run_stop_requested, set_run_progress_state
from job_hunter_agent.scrapers.base import blank_source_metadata, build_initial_flat_record
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.source_learning import register_pending_learning_signals
from job_hunter_agent.source_registry import SOURCE_JOB_MARKET_MAP
from job_hunter_agent.work_mode_extraction import WORK_MODE_UNKNOWN, extract_from_linkedin


def consumer_key_for_user(user_id: str) -> str:
    """Namespace JMM's processing cursor per JH user, not as personal activity."""
    cleaned = str(user_id or "").strip()
    if not cleaned:
        raise ValueError("user_id is required for the Job Market Map consumer cursor")
    return f"{MARKET_MAP_CONSUMER_KEY_PREFIX}:{cleaned}"


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
                )
                if key in item
            },
        }
    )
    return metadata


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

    posted_at = str(item.get("posted_at") or "").strip()
    posted_age_days = days_since(posted_at, parse_timestamp(run_iso) or datetime.now(timezone.utc))
    work_mode_result = extract_from_linkedin(
        {
            "workplace_type": item.get("workplace_type"),
            "location": item.get("location"),
        }
    )
    source_metadata = _source_metadata(item, source, source_job_id)
    record = build_initial_flat_record(
        run_iso=run_iso,
        search_location=str(item.get("geography_code") or item.get("location") or ""),
        search_keywords="",
        source=source,
        job_key=job_key,
        title=str(item.get("title") or "").strip(),
        company=str(item.get("employer") or "").strip(),
        location=str(item.get("location") or "").strip(),
        posted_text=posted_at,
        posted_age_days=posted_age_days,
        work_mode=str(work_mode_result.get(RECORD_WORK_MODE_KEY) or WORK_MODE_UNKNOWN),
        work_mode_source=str(work_mode_result.get(RECORD_WORK_MODE_SOURCE_KEY) or ""),
        work_mode_evidence=list(work_mode_result.get(RECORD_WORK_MODE_EVIDENCE_KEY) or []),
        work_mode_needs_review=bool(work_mode_result.get(RECORD_WORK_MODE_NEEDS_REVIEW_KEY)),
        work_type=str(item.get("employment_type") or "").strip(),
        salary_str=str(item.get("salary_text") or "").strip(),
        url=str(item["canonical_url"]).strip(),
        teaser=str(item.get("teaser_text") or "").strip(),
        details_text="",
        details_length=0,
        source_metadata=source_metadata,
    )
    record[RECORD_SOURCE_NAME_KEY] = source
    record[RECORD_MARKET_MAP_JOB_ID_KEY] = int(item["id"])
    record[RECORD_MARKET_MAP_IDENTITY_KEY] = str(item["identity_key"]).strip()
    apply_method = str(item.get("apply_method") or APPLY_METHOD_UNKNOWN).strip().lower()
    if apply_method not in {
        APPLY_METHOD_UNKNOWN,
        "easy_apply",
        "quick_apply",
        "external_apply",
    }:
        raise ValueError(f"Job Market Map returned unsupported apply_method: {apply_method!r}")
    record[RECORD_APPLY_METHOD_KEY] = apply_method
    record[RECORD_SOURCE_METADATA_KEY][RECORD_SOURCE_PLATFORM_JOB_ID_KEY] = source_job_id
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


def _cache_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in after.items()
        if key not in before or before[key] != value
    }


def _run_parallel_stage(
    jobs: list[_IndexedJob],
    *,
    worker_limit: int,
    worker: Any,
    on_failure: Any | None = None,
    collect_failures: bool = False,
) -> tuple[dict[int, Any], bool] | tuple[dict[int, Any], bool, dict[int, Exception]]:
    """Run one bounded stage and cancel work that has not started on stop."""
    if not jobs or run_stop_requested():
        if collect_failures:
            return {}, run_stop_requested(), {}
        return {}, run_stop_requested()

    executor = ThreadPoolExecutor(max_workers=min(worker_limit, len(jobs)))
    futures = {executor.submit(worker, job): job.index for job in jobs}
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
                try:
                    results[futures[future]] = future.result()
                except Exception as exc:
                    errors[futures[future]] = exc
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
    jd_payload = client.get_or_enrich_jd(
        jmm_job_id=int(record[RECORD_MARKET_MAP_JOB_ID_KEY])
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
    record[RECORD_REJECT_REASON_KEY] = "JMM_JD_ENRICHMENT_FAILED"
    record[RECORD_DECISION_EXPLANATION_KEY] = str(error)
    record[RECORD_RETRYABLE_KEY] = True
    record[RECORD_RETRY_REASON_KEY] = "JMM_JD_ENRICHMENT_FAILED"
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
    worker_record = copy.deepcopy(job.record)
    # The coordinator owns the live identity claim. It must not cross into a
    # worker or be copied along with the mutable record.
    worker_record.pop(RUN_IDENTITY_CLAIM_KEY, None)
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
) -> None:
    """Publish JMM-owned work through the shared wait-state progress contract.

    Page item totals are authoritative only after JMM returns a page. The
    consumer therefore leaves page reads indeterminate and reports a
    determinate bar only for the current page's known item count.
    """
    set_run_progress_state(
        text,
        stage=stage,
        source=SOURCE_JOB_MARKET_MAP,
        headline=headline,
        detail=detail,
        current=current,
        total=total,
    )


def run_market_map_source(context, *, user_id: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Process JMM pages with bounded stages and an ordered coordinator merge."""
    _set_market_map_progress(
        "Starting JMM",
        stage="starting",
        headline="Starting JMM",
    )
    client = JobMarketMapClient.from_environment()
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
    consumer_key = consumer_key_for_user(user_id)
    cursor = 0
    page_number = 0
    snapshot_max_id: int | None = None
    while True:
        page_number += 1
        _set_market_map_progress(
            "Reading JMM jobs",
            stage="source_collection",
            headline="Reading JMM jobs",
            detail=f"Page {page_number}",
        )
        page = client.consumer_feed_page(
            consumer_key=consumer_key,
            through_id=snapshot_max_id,
        )
        page_snapshot_max_id = page.get("snapshot_max_id")
        if not isinstance(page_snapshot_max_id, int) or page_snapshot_max_id < 0:
            raise JobMarketMapContractError(
                "Job Market Map consumer feed snapshot_max_id is required"
            )
        if snapshot_max_id is None:
            # Run-scoped only: never persist this boundary. A later JH run starts
            # fresh from the last safely persisted JMM consumer checkpoint.
            snapshot_max_id = page_snapshot_max_id
        elif page_snapshot_max_id != snapshot_max_id:
            raise JobMarketMapContractError(
                "Job Market Map consumer feed snapshot boundary changed during the run"
            )
        page_items = page["items"]
        page_item_total = len(page_items)
        page_jobs: list[_IndexedJob] = []
        for item_index, item in enumerate(page_items):
            title = str(item.get("title") or "").strip()
            _set_market_map_progress(
                f"Reviewing job {item_index + 1} of page {page_number}",
                stage="relevance_analysis",
                headline=f"Reviewing job {item_index + 1} of page {page_number}",
                detail=title,
                current=item_index + 1,
                total=page_item_total,
            )
            record = normalize_market_job(item, run_iso=context.run_iso)
            page_jobs.append(
                _IndexedJob(
                    index=item_index,
                    record=record,
                    title_assessment=prepare_title_gate_assessment(
                        title, review_context.profile
                    ),
                )
            )

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
        title_results, stopped = _run_parallel_stage(
            title_jobs,
            worker_limit=get_job_market_map_parallel_workers(),
            worker=lambda job: _run_title_worker(
                job,
                profile=review_context.profile,
                llm_cache=review_context.llm_cache,
            ),
            on_failure=lambda: _release_unfinalized_identity_claims(page_jobs),
        )
        if stopped:
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations
        if run_stop_requested():
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations

        jobs_by_index = {job.index: job for job in page_jobs}
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
            title_result = title_results_by_cache_key[cache_key]
            if title_result.cache_value is not None:
                review_context.llm_cache[title_result.cache_key] = _thaw(
                    title_result.cache_value
                )
            jobs_by_index[job.index] = replace(
                job,
                title_assessment=replace(job.title_assessment, title_judgment=title_result),
            )
        page_jobs = [jobs_by_index[index] for index in range(page_item_total)]

        eligible_jobs: list[_IndexedJob] = []
        for job in page_jobs:
            if run_stop_requested():
                _release_unfinalized_identity_claims(page_jobs)
                return kept_records, review_context.audit_rows, skill_observations
            job_key = str(job.record.get(RECORD_JOB_KEY) or "")
            review_context.title_assessments.setdefault(job_key, []).append(
                job.title_assessment
            )
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
                "Obtaining job descriptions",
                stage="job_detail",
                headline="Obtaining job descriptions",
                detail=f"Page {page_number}",
                total=page_item_total,
            )
        jd_results, stopped, jd_failures = _run_parallel_stage(
            eligible_jobs,
            worker_limit=get_job_market_map_parallel_workers(),
            worker=lambda job: _run_jd_worker(job, client=client),
            on_failure=lambda: _release_unfinalized_identity_claims(page_jobs),
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
            _set_market_map_progress(
                f"Obtaining JD for job {index + 1} of page {page_number}",
                stage="job_detail",
                headline="Obtaining job description",
                detail=str(job.record.get("title") or ""),
                current=index + 1,
                total=page_item_total,
            )
            _apply_jd_payload(job.record, _thaw(jd_results[index].payload))

        _set_market_map_progress(
            "Fit review",
            stage="scoring",
            headline="Fit review",
            detail=f"Page {page_number}",
            total=page_item_total,
        )
        fit_base_cache = copy.deepcopy(review_context.llm_cache)
        fit_jobs = [job for job in eligible_jobs if job.index in jd_results]
        fit_results, stopped = _run_parallel_stage(
            fit_jobs,
            worker_limit=get_job_market_map_parallel_workers(),
            worker=lambda job: _run_fit_worker(
                job,
                context=context,
                llm_cache=fit_base_cache,
            ),
            on_failure=lambda: _release_unfinalized_identity_claims(page_jobs),
        )
        if stopped:
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations
        if run_stop_requested():
            _release_unfinalized_identity_claims(page_jobs)
            return kept_records, review_context.audit_rows, skill_observations

        _set_market_map_progress(
            "Finalising JMM results",
            stage="finalising",
            headline="Finalising JMM results",
            detail=f"Page {page_number}",
            total=page_item_total,
        )
        result_indexes = sorted(set(fit_results) | set(jd_failures))
        for index in result_indexes:
            if run_stop_requested():
                _release_unfinalized_identity_claims(page_jobs)
                return kept_records, review_context.audit_rows, skill_observations
            job = jobs_by_index[index]
            if index in jd_failures:
                _set_market_map_progress(
                    f"JD failed for job {index + 1} of page {page_number}",
                    stage="job_detail",
                    headline="Obtaining job description",
                    detail=str(jd_failures[index]),
                    current=index + 1,
                    total=page_item_total,
                )
                _append_retryable_jd_failure(
                    review_context,
                    job,
                    jd_failures[index],
                )
                continue
            result = fit_results[index]
            _set_market_map_progress(
                f"Finalising job {index + 1} of page {page_number}",
                stage="finalising",
                headline="Finalising JMM results",
                detail=str(job.record.get("title") or ""),
                current=index + 1,
                total=page_item_total,
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
                kept_records.append(remove_transient_jd(job.record))
                skill_observations.extend(_thaw(result.observations))

        if run_stop_requested():
            return kept_records, review_context.audit_rows, skill_observations
        if jd_failures:
            raise PartialSourceResultsError(
                SOURCE_JOB_MARKET_MAP,
                kept_records=kept_records,
                audit_rows=review_context.audit_rows,
                skill_observations=skill_observations,
                original_error=jd_failures[min(jd_failures)],
            )
        next_cursor = int(page["next_cursor"])
        if next_cursor > cursor:
            _set_market_map_progress(
                f"Checkpointing JMM through job {next_cursor}",
                stage="saving",
                headline="Checkpointing JMM progress",
                detail=f"Through job {next_cursor}",
            )
            client.checkpoint(
                consumer_key=consumer_key,
                last_job_id=next_cursor,
                note="Job Hunter completed JH-306 market analysis page",
            )
        if not page["has_more"]:
            break
        if next_cursor == cursor:
            raise ValueError("Job Market Map feed cursor did not advance")
        cursor = next_cursor
    _set_market_map_progress(
        "JMM source complete",
        stage="source_collection",
        headline="JMM source complete",
        detail="Source collection complete",
    )
    return kept_records, review_context.audit_rows, skill_observations
