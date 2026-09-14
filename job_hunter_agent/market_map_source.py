"""Consume Job Market Map neutral jobs and run JH-owned candidate analysis."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.job_market_map_client import (
    MARKET_MAP_CONSUMER_KEY_PREFIX,
    JobMarketMapClient,
)
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.posting_utils import days_since, parse_timestamp
from job_hunter_agent.record_schema import (
    APPLY_METHOD_UNKNOWN,
    RECORD_APPLY_METHOD_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_MARKET_MAP_IDENTITY_KEY,
    RECORD_MARKET_MAP_JD_FETCHED_AT_KEY,
    RECORD_MARKET_MAP_JD_SOURCE_KEY,
    RECORD_MARKET_MAP_JOB_ID_KEY,
    RECORD_SOURCE_CANONICAL_URL_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_NAME_KEY,
    RECORD_SOURCE_PLATFORM_JOB_ID_KEY,
    RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    RECORD_WORK_MODE_SOURCE_KEY,
)
from job_hunter_agent.run_control import set_run_progress_state
from job_hunter_agent.scrapers.base import blank_source_metadata, build_initial_flat_record
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


def remove_transient_jd(record: dict[str, Any]) -> dict[str, Any]:
    """Keep JH analysis/provenance while preventing a second permanent JD copy."""
    cleaned = dict(record)
    for key in _TRANSIENT_JD_FIELDS:
        cleaned.pop(key, None)
    return cleaned


def _hydrate_jd(record: dict[str, Any], client: JobMarketMapClient) -> None:
    jd_payload = client.get_or_enrich_jd(
        jmm_job_id=int(record[RECORD_MARKET_MAP_JOB_ID_KEY])
    )
    full_description = str(jd_payload.get("full_description") or "").strip()
    if not full_description:
        raise ValueError("Job Market Map returned no current full_description")
    record[RECORD_DETAILS_TEXT_KEY] = full_description
    record[RECORD_DETAILS_STATUS_KEY] = "ok"
    record[RECORD_DESCRIPTION_SOURCE_KEY] = str(jd_payload.get("jd_source") or "job_market_map")
    record[RECORD_MARKET_MAP_JD_SOURCE_KEY] = str(jd_payload.get("jd_source") or "").strip()
    record[RECORD_MARKET_MAP_JD_FETCHED_AT_KEY] = str(jd_payload.get("jd_fetched_at") or "").strip()


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
    """Process JMM pages, checkpointing only after every page is safely analysed."""
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
    while True:
        page_number += 1
        _set_market_map_progress(
            "Reading JMM jobs",
            stage="source_collection",
            headline="Reading JMM jobs",
            detail=f"Page {page_number}",
        )
        page = client.consumer_feed_page(consumer_key=consumer_key)
        page_items = page["items"]
        page_item_total = len(page_items)
        for item_index, item in enumerate(page_items, start=1):
            title = str(item.get("title") or "").strip()
            _set_market_map_progress(
                f"Reviewing job {item_index} of page {page_number}",
                stage="relevance_analysis",
                headline=f"Reviewing job {item_index} of page {page_number}",
                detail=title,
                current=item_index,
                total=page_item_total,
            )
            record = normalize_market_job(item, run_iso=context.run_iso)
            pre_outcome, record, _, should_fetch_details = review_pre_detail_normalized_job(
                record, review_context
            )
            if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
                continue
            _set_market_map_progress(
                f"Obtaining JD for job {item_index} of page {page_number}",
                stage="job_detail",
                headline="Obtaining job description",
                detail=title,
                current=item_index,
                total=page_item_total,
            )
            _hydrate_jd(record, client)
            _set_market_map_progress(
                f"Fit review for job {item_index} of page {page_number}",
                stage="scoring",
                headline="Fit review",
                detail=title,
                current=item_index,
                total=page_item_total,
            )
            outcome, record, observations = review_post_detail_normalized_job(
                record, review_context
            )
            if outcome["decision"] == "KEEP":
                kept_records.append(remove_transient_jd(record))
                skill_observations.extend(observations)
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
