from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional


def build_history_dashboard_record(
    job_key: str,
    entry: dict,
    run_started_at: datetime,
    *,
    days_since_fn: Callable[[Optional[str], datetime], Optional[int]],
    archive_stale_after_days: int,
) -> Optional[dict]:
    if int(entry.get("times_kept", 0) or 0) <= 0:
        return None

    snapshot = entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    archived_age_days = days_since_fn(entry.get("last_kept_at"), run_started_at)
    return {
        "job_key": job_key,
        "source": "linkedin" if str(job_key).startswith("linkedin:") else "seek",
        "title": snapshot.get("title") or entry.get("title") or "Untitled",
        "company": snapshot.get("company") or entry.get("company") or "N/A",
        "url": snapshot.get("url") or entry.get("url") or "#",
        "posted": snapshot.get("posted") or "N/A",
        "posted_age_days": snapshot.get("posted_age_days"),
        "salary": snapshot.get("salary") or "N/A",
        "location": snapshot.get("location") or "N/A",
        "work_mode": snapshot.get("work_mode") or "N/A",
        "work_type": snapshot.get("work_type") or "N/A",
        "teaser": snapshot.get("teaser") or "N/A",
        "title_reason": snapshot.get("title_reason"),
        "content_reason": snapshot.get("content_reason"),
        "llm_decision": snapshot.get("llm_decision"),
        "llm_fit_grade": snapshot.get("llm_fit_grade"),
        "search_location": snapshot.get("search_location") or "N/A",
        "search_keywords": snapshot.get("search_keywords") or "",
        "fit_source_text": snapshot.get("fit_source_text") or "",
        "full_description": snapshot.get("full_description") or "",
        "fit_confidence": snapshot.get("fit_confidence") or "",
        "details_status": snapshot.get("details_status") or "",
        "description_source": snapshot.get("description_source") or "",
        "role_snapshot": snapshot.get("role_snapshot") or "N/A",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],
        "missing_evidence": snapshot.get("missing_evidence") or [],
        "competitive_signals": snapshot.get("competitive_signals") or [],
        "hard_block_reasons": snapshot.get("hard_block_reasons") or [],
        "seen_before": True,
        "times_viewed": int(entry.get("times_viewed", 0) or 0),
        "times_kept": int(entry.get("times_kept", 0) or 0),
        "times_seen": int(entry.get("times_seen", 0) or 0),
        "first_kept_at": entry.get("first_kept_at"),
        "last_kept_at": entry.get("last_kept_at"),
        "first_seen_at": entry.get("first_seen_at"),
        "last_seen_at": entry.get("last_seen_at"),
        "first_viewed_at": entry.get("first_viewed_at"),
        "last_viewed_at": entry.get("last_viewed_at"),
        "history_sightings": entry.get("sightings") if isinstance(entry.get("sightings"), list) else [],
        "archived": True,
        "archived_age_days": archived_age_days,
        "is_stale": archived_age_days is not None and archived_age_days > archive_stale_after_days,
    }


def build_archive_records(
    history: dict[str, dict],
    current_run_keys: set[str],
    applied_job_keys: set[str],
    hidden_job_keys: set[str],
    run_started_at: datetime,
    *,
    normalize_job_key_fn: Callable[[str], str],
    parse_timestamp_fn: Callable[[Optional[str]], Optional[datetime]],
    build_history_dashboard_record_fn: Callable[[str, dict, datetime], Optional[dict]],
) -> list[dict]:
    records: list[dict] = []
    blocked_keys = applied_job_keys | hidden_job_keys

    for job_key, entry in history.items():
        normalized_key = normalize_job_key_fn(str(job_key))
        if not normalized_key or normalized_key in current_run_keys or normalized_key in blocked_keys:
            continue
        record = build_history_dashboard_record_fn(normalized_key, entry, run_started_at)
        if record:
            records.append(record)

    records.sort(
        key=lambda item: parse_timestamp_fn(item.get("last_kept_at")) or datetime.min,
        reverse=True,
    )
    return records


def build_hidden_dashboard_record(
    job_key: str,
    entry: dict,
    run_started_at: datetime,
    *,
    days_since_fn: Callable[[Optional[str], datetime], Optional[int]],
) -> dict:
    snapshot = entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    hidden_at = entry.get("last_hidden_at") or entry.get("first_hidden_at")
    hidden_age_days = days_since_fn(hidden_at, run_started_at) if hidden_at else None
    return {
        "job_key": job_key,
        "source": "linkedin" if str(job_key).startswith("linkedin:") else "seek",
        "title": snapshot.get("title") or entry.get("title") or f"Hidden job {job_key}",
        "company": snapshot.get("company") or entry.get("company") or "N/A",
        "url": snapshot.get("url") or entry.get("url") or "#",
        "posted": snapshot.get("posted") or "N/A",
        "posted_age_days": snapshot.get("posted_age_days"),
        "salary": snapshot.get("salary") or "N/A",
        "location": snapshot.get("location") or "N/A",
        "work_mode": snapshot.get("work_mode") or "N/A",
        "work_type": snapshot.get("work_type") or "N/A",
        "teaser": snapshot.get("teaser") or "N/A",
        "role_snapshot": snapshot.get("role_snapshot") or "N/A",
        "title_reason": snapshot.get("title_reason"),
        "content_reason": snapshot.get("content_reason"),
        "llm_decision": snapshot.get("llm_decision"),
        "llm_fit_grade": snapshot.get("llm_fit_grade"),
        "fit_source_text": snapshot.get("fit_source_text") or "",
        "full_description": snapshot.get("full_description") or "",
        "fit_confidence": snapshot.get("fit_confidence") or "",
        "details_status": snapshot.get("details_status") or "",
        "description_source": snapshot.get("description_source") or "",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],
        "missing_evidence": snapshot.get("missing_evidence") or [],
        "competitive_signals": snapshot.get("competitive_signals") or [],
        "hard_block_reasons": snapshot.get("hard_block_reasons") or [],
        "search_location": snapshot.get("search_location") or "N/A",
        "search_keywords": snapshot.get("search_keywords") or "",
        "times_viewed": int(entry.get("times_viewed", 0) or 0),
        "first_seen_at": entry.get("first_seen_at"),
        "last_seen_at": entry.get("last_seen_at"),
        "first_viewed_at": entry.get("first_viewed_at"),
        "last_viewed_at": entry.get("last_viewed_at"),
        "first_hidden_at": entry.get("first_hidden_at"),
        "last_hidden_at": entry.get("last_hidden_at"),
        "hidden_age_days": hidden_age_days,
        "hidden": True,
    }


def build_hidden_records(
    hidden_job_keys: set[str],
    history: dict[str, dict],
    run_started_at: datetime,
    *,
    parse_timestamp_fn: Callable[[Optional[str]], Optional[datetime]],
    days_since_fn: Callable[[Optional[str], datetime], Optional[int]],
    hidden_review_days: int,
    build_hidden_dashboard_record_fn: Callable[[str, dict, datetime], dict],
) -> list[dict]:
    records: list[dict] = []
    for job_key in hidden_job_keys:
        entry = history.get(job_key, {})
        hidden_at = entry.get("last_hidden_at") or entry.get("first_hidden_at")
        hidden_age_days = days_since_fn(hidden_at, run_started_at) if hidden_at else None
        if hidden_age_days is not None and hidden_age_days > hidden_review_days:
            continue
        records.append(build_hidden_dashboard_record_fn(job_key, entry, run_started_at))

    records.sort(
        key=lambda item: (
            parse_timestamp_fn(item.get("last_hidden_at")) or datetime.min,
            parse_timestamp_fn(item.get("last_seen_at")) or datetime.min,
        ),
        reverse=True,
    )
    return records


def build_applied_dashboard_record(
    job_key: str,
    entry: dict,
    run_started_at: datetime,
    *,
    days_since_fn: Callable[[Optional[str], datetime], Optional[int]],
) -> dict:
    snapshot = entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    applied_at = entry.get("last_applied_at") or entry.get("first_applied_at")
    applied_age_days = days_since_fn(applied_at, run_started_at) if applied_at else None
    return {
        "job_key": job_key,
        "title": snapshot.get("title") or entry.get("title") or f"Applied job {job_key}",
        "company": snapshot.get("company") or entry.get("company") or "N/A",
        "url": snapshot.get("url") or entry.get("url") or "#",
        "posted": snapshot.get("posted") or "N/A",
        "posted_age_days": snapshot.get("posted_age_days"),
        "salary": snapshot.get("salary") or "N/A",
        "location": snapshot.get("location") or "N/A",
        "work_mode": snapshot.get("work_mode") or "N/A",
        "work_type": snapshot.get("work_type") or "N/A",
        "teaser": snapshot.get("teaser") or "N/A",
        "role_snapshot": snapshot.get("role_snapshot") or "N/A",
        "title_reason": snapshot.get("title_reason"),
        "content_reason": snapshot.get("content_reason"),
        "llm_decision": snapshot.get("llm_decision"),
        "llm_fit_grade": snapshot.get("llm_fit_grade"),
        "fit_source_text": snapshot.get("fit_source_text") or "",
        "full_description": snapshot.get("full_description") or "",
        "fit_confidence": snapshot.get("fit_confidence") or "",
        "details_status": snapshot.get("details_status") or "",
        "description_source": snapshot.get("description_source") or "",
        "fit_highlights": snapshot.get("fit_highlights") or [],
        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],
        "missing_evidence": snapshot.get("missing_evidence") or [],
        "competitive_signals": snapshot.get("competitive_signals") or [],
        "hard_block_reasons": snapshot.get("hard_block_reasons") or [],
        "search_location": snapshot.get("search_location") or "N/A",
        "search_keywords": snapshot.get("search_keywords") or "",
        "times_viewed": int(entry.get("times_viewed", 0) or 0),
        "first_seen_at": entry.get("first_seen_at"),
        "last_seen_at": entry.get("last_seen_at"),
        "first_viewed_at": entry.get("first_viewed_at"),
        "last_viewed_at": entry.get("last_viewed_at"),
        "first_applied_at": entry.get("first_applied_at"),
        "last_applied_at": entry.get("last_applied_at"),
        "applied_age_days": applied_age_days,
        "applied": True,
    }


def build_applied_records(
    applied_job_keys: set[str],
    history: dict[str, dict],
    run_started_at: datetime,
    *,
    parse_timestamp_fn: Callable[[Optional[str]], Optional[datetime]],
    build_applied_dashboard_record_fn: Callable[[str, dict, datetime], dict],
) -> list[dict]:
    records = [
        build_applied_dashboard_record_fn(job_key, history.get(job_key, {}), run_started_at)
        for job_key in applied_job_keys
    ]
    records.sort(
        key=lambda item: (
            parse_timestamp_fn(item.get("last_applied_at")) or datetime.min,
            parse_timestamp_fn(item.get("last_seen_at")) or datetime.min,
        ),
        reverse=True,
    )
    return records


def build_dashboard_record_sets(
    kept_records: list[dict],
    job_history: dict[str, dict],
    applied_job_keys: set[str],
    hidden_job_keys: set[str],
    reference_time: datetime,
    *,
    profile: dict,
    is_dashboard_eligible_fn: Callable[[dict, Optional[dict]], bool],
    fit_score_fn: Callable[[dict, Optional[dict]], int],
    viewed_by_user_fn: Callable[[dict], bool],
    normalize_job_key_fn: Callable[[str], str],
    parse_timestamp_fn: Callable[[Optional[str]], Optional[datetime]],
    build_archive_records_fn: Callable[[dict[str, dict], set[str], set[str], set[str], datetime], list[dict]],
    build_applied_records_fn: Callable[[set[str], dict[str, dict], datetime], list[dict]],
    build_hidden_records_fn: Callable[[set[str], dict[str, dict], datetime], list[dict]],
) -> dict[str, list[dict]]:
    curated_kept_records = [record for record in kept_records if is_dashboard_eligible_fn(record, profile)]

    def _rank_by_fit(record: dict) -> tuple:
        timestamp = parse_timestamp_fn(record.get("last_kept_at") or record.get("last_seen_at"))
        return (
            -fit_score_fn(record, profile),
            -(1 if not viewed_by_user_fn(record) else 0),
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -(timestamp or datetime.min).timestamp() if timestamp else float("-inf"),
        )

    def _rank_archive_by_fit(record: dict) -> tuple:
        timestamp = parse_timestamp_fn(record.get("last_kept_at"))
        return (
            -fit_score_fn(record, profile),
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -(timestamp or datetime.min).timestamp() if timestamp else float("-inf"),
        )

    current_records = sorted(curated_kept_records, key=_rank_by_fit)
    current_run_keys = {
        normalize_job_key_fn(str(record.get("job_key") or ""))
        for record in curated_kept_records
        if normalize_job_key_fn(str(record.get("job_key") or ""))
    }
    archive_records = build_archive_records_fn(
        job_history,
        current_run_keys,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    )
    applied_records = build_applied_records_fn(applied_job_keys, job_history, reference_time)
    hidden_records = build_hidden_records_fn(hidden_job_keys, job_history, reference_time)
    recent_archive_records = sorted(
        [record for record in archive_records if not record.get("is_stale") and is_dashboard_eligible_fn(record, profile)],
        key=_rank_archive_by_fit,
    )
    stale_archive_records = sorted(
        [record for record in archive_records if record.get("is_stale") and is_dashboard_eligible_fn(record, profile)],
        key=_rank_archive_by_fit,
    )
    shortlist_records = sorted(
        [*current_records, *recent_archive_records, *stale_archive_records],
        key=_rank_by_fit,
    )
    return {
        "shortlist_records": shortlist_records,
        "current_records": current_records,
        "archive_records": archive_records,
        "recent_archive_records": recent_archive_records,
        "stale_archive_records": stale_archive_records,
        "applied_records": applied_records,
        "hidden_records": hidden_records,
    }


def load_last_kept_records(audit_rows: list[dict], *, deduplicate_across_sources_fn: Callable[[list[dict]], list[dict]]) -> list[dict]:
    if not audit_rows:
        return []

    latest_run_started_at = max(
        (str(row.get("run_started_at") or "") for row in audit_rows if row.get("run_started_at")),
        default="",
    )
    if not latest_run_started_at:
        return []

    records = [
        row
        for row in audit_rows
        if row.get("decision") == "KEEP" and str(row.get("run_started_at") or "") == latest_run_started_at
    ]
    return deduplicate_across_sources_fn(records)


def build_run_stats(
    audit_rows: list[dict],
    kept_records: list[dict],
    run_started_at: datetime,
    run_finished_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    max_pages_cap: int,
) -> dict:
    search_targets: dict[str, set[int]] = {}
    reject_counts: dict[str, int] = {}
    skip_counts: dict[str, int] = {}

    for row in audit_rows:
        search_location = str(row.get("search_location") or "Unknown")
        page_num = row.get("page")
        if page_num is not None:
            search_targets.setdefault(search_location, set()).add(int(page_num))

        reason = row.get("reject_reason") or "UNKNOWN"
        decision = row.get("decision")
        if decision == "SKIP":
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
        elif decision != "KEEP":
            reject_counts[reason] = reject_counts.get(reason, 0) + 1

    top_reject_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(reject_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]

    detail_fetches = sum(1 for row in audit_rows if int(row.get("details_length") or 0) > 0)
    cards_seen = len(audit_rows)
    kept_count = len(kept_records)

    return {
        "run_started_at": run_started_at.isoformat(timespec="seconds"),
        "run_finished_at": run_finished_at.isoformat(timespec="seconds"),
        "search_window_days": date_range_days,
        "sort_newest_first": sort_newest_first,
        "max_pages_cap": max_pages_cap,
        "search_targets": {
            location: sorted(pages)
            for location, pages in sorted(search_targets.items())
        },
        "page_count": sum(len(pages) for pages in search_targets.values()),
        "cards_seen": cards_seen,
        "detail_fetches": detail_fetches,
        "kept_count": kept_count,
        "keep_rate": round((kept_count / cards_seen), 4) if cards_seen else 0.0,
        "top_reject_reasons": top_reject_reasons,
        "skip_counts": skip_counts,
    }
