"""Helpers for workspace data."""



from __future__ import annotations



import logging

from datetime import datetime

from typing import Callable, Optional



logger = logging.getLogger(__name__)



from job_hunter_agent.record_schema import (

    RECORD_JOB_KEY, RECORD_SOURCE_KEY, RECORD_TITLE_KEY, RECORD_COMPANY_KEY,

    RECORD_URL_KEY, RECORD_POSTED_KEY, RECORD_POSTED_AGE_DAYS_KEY, RECORD_SALARY_KEY,

    RECORD_LOCATION_KEY, RECORD_WORK_MODE_KEY, RECORD_WORK_TYPE_KEY, RECORD_TEASER_KEY,

    RECORD_TITLE_REASON_KEY, RECORD_CONTENT_REASON_KEY, RECORD_LLM_DECISION_KEY,

    RECORD_LLM_FIT_GRADE_KEY, RECORD_SEARCH_LOCATION_KEY, RECORD_SEARCH_KEYWORDS_KEY,

    RECORD_ROLE_SNAPSHOT_KEY, RECORD_TIMES_VIEWED_KEY, RECORD_TIMES_KEPT_KEY,

    RECORD_TIMES_SEEN_KEY, RECORD_FIRST_KEPT_AT_KEY, RECORD_LAST_KEPT_AT_KEY,

    RECORD_FIRST_SEEN_AT_KEY, RECORD_LAST_SEEN_AT_KEY, RECORD_FIRST_VIEWED_AT_KEY,

    RECORD_LAST_VIEWED_AT_KEY, RECORD_SEEN_BEFORE_KEY,

    RECORD_JOB_REQUIREMENTS_KEY,

)



def _record_source(entry: dict, job_key: str) -> str:

    source = str(entry.get(RECORD_SOURCE_KEY) or entry.get("source") or "").strip().lower()

    if source:

        return source

    return str(job_key).split(":", 1)[0].strip().lower() if ":" in str(job_key) else "unknown"





def build_history_workspace_record(

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

        RECORD_JOB_KEY: job_key,

        RECORD_SOURCE_KEY: _record_source(snapshot or entry, job_key),

        RECORD_TITLE_KEY: snapshot.get(RECORD_TITLE_KEY) or entry.get(RECORD_TITLE_KEY) or "Untitled",

        RECORD_COMPANY_KEY: snapshot.get(RECORD_COMPANY_KEY) or entry.get(RECORD_COMPANY_KEY) or "N/A",

        RECORD_URL_KEY: snapshot.get(RECORD_URL_KEY) or entry.get(RECORD_URL_KEY) or "#",

        RECORD_POSTED_KEY: snapshot.get(RECORD_POSTED_KEY) or "N/A",

        RECORD_POSTED_AGE_DAYS_KEY: snapshot.get(RECORD_POSTED_AGE_DAYS_KEY),

        RECORD_SALARY_KEY: snapshot.get(RECORD_SALARY_KEY) or "N/A",

        RECORD_LOCATION_KEY: snapshot.get(RECORD_LOCATION_KEY) or "N/A",

        RECORD_WORK_MODE_KEY: snapshot.get(RECORD_WORK_MODE_KEY) or "N/A",

        RECORD_WORK_TYPE_KEY: snapshot.get(RECORD_WORK_TYPE_KEY) or "N/A",

        RECORD_TEASER_KEY: snapshot.get(RECORD_TEASER_KEY) or "N/A",

        RECORD_TITLE_REASON_KEY: snapshot.get(RECORD_TITLE_REASON_KEY),

        RECORD_CONTENT_REASON_KEY: snapshot.get(RECORD_CONTENT_REASON_KEY),

        RECORD_LLM_DECISION_KEY: snapshot.get(RECORD_LLM_DECISION_KEY),

        RECORD_LLM_FIT_GRADE_KEY: snapshot.get(RECORD_LLM_FIT_GRADE_KEY),

        RECORD_SEARCH_LOCATION_KEY: snapshot.get(RECORD_SEARCH_LOCATION_KEY) or "N/A",

        RECORD_SEARCH_KEYWORDS_KEY: snapshot.get(RECORD_SEARCH_KEYWORDS_KEY) or "",

        "fit_source_text": snapshot.get("fit_source_text") or "",

        "full_description": snapshot.get("full_description") or "",

        "fit_confidence": snapshot.get("fit_confidence") or "",

        "details_status": snapshot.get("details_status") or "",

        "description_source": snapshot.get("description_source") or "",

        RECORD_ROLE_SNAPSHOT_KEY: snapshot.get(RECORD_ROLE_SNAPSHOT_KEY) or "N/A",

        "fit_highlights": snapshot.get("fit_highlights") or [],

        RECORD_JOB_REQUIREMENTS_KEY: snapshot.get(RECORD_JOB_REQUIREMENTS_KEY) or [],

        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],

        "missing_profile_support": snapshot.get("missing_profile_support") or [],

        "competitive_signals": snapshot.get("competitive_signals") or [],

        "hard_block_reasons": snapshot.get("hard_block_reasons") or [],

        RECORD_SEEN_BEFORE_KEY: True,

        RECORD_TIMES_VIEWED_KEY: int(entry.get(RECORD_TIMES_VIEWED_KEY, 0) or 0),

        RECORD_TIMES_KEPT_KEY: int(entry.get(RECORD_TIMES_KEPT_KEY, 0) or 0),

        RECORD_TIMES_SEEN_KEY: int(entry.get(RECORD_TIMES_SEEN_KEY, 0) or 0),

        RECORD_FIRST_KEPT_AT_KEY: entry.get(RECORD_FIRST_KEPT_AT_KEY),

        RECORD_LAST_KEPT_AT_KEY: entry.get(RECORD_LAST_KEPT_AT_KEY),

        RECORD_FIRST_SEEN_AT_KEY: entry.get(RECORD_FIRST_SEEN_AT_KEY),

        RECORD_LAST_SEEN_AT_KEY: entry.get(RECORD_LAST_SEEN_AT_KEY),

        RECORD_FIRST_VIEWED_AT_KEY: entry.get(RECORD_FIRST_VIEWED_AT_KEY),

        RECORD_LAST_VIEWED_AT_KEY: entry.get(RECORD_LAST_VIEWED_AT_KEY),

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

    build_history_workspace_record_fn: Callable[[str, dict, datetime], Optional[dict]],

) -> list[dict]:

    records: list[dict] = []

    blocked_keys = applied_job_keys | hidden_job_keys



    for job_key, entry in history.items():

        normalized_key = normalize_job_key_fn(str(job_key))

        if not normalized_key or normalized_key in current_run_keys or normalized_key in blocked_keys:

            continue

        record = build_history_workspace_record_fn(normalized_key, entry, run_started_at)

        if record:

            records.append(record)



    records.sort(

        key=lambda item: parse_timestamp_fn(item.get("last_kept_at")) or datetime.min,

        reverse=True,

    )

    return records





def build_hidden_workspace_record(

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

        RECORD_JOB_KEY: job_key,

        RECORD_SOURCE_KEY: _record_source(snapshot or entry, job_key),

        RECORD_TITLE_KEY: snapshot.get(RECORD_TITLE_KEY) or entry.get(RECORD_TITLE_KEY) or f"Hidden job {job_key}",

        RECORD_COMPANY_KEY: snapshot.get(RECORD_COMPANY_KEY) or entry.get(RECORD_COMPANY_KEY) or "N/A",

        RECORD_URL_KEY: snapshot.get(RECORD_URL_KEY) or entry.get(RECORD_URL_KEY) or "#",

        RECORD_POSTED_KEY: snapshot.get(RECORD_POSTED_KEY) or "N/A",

        RECORD_POSTED_AGE_DAYS_KEY: snapshot.get(RECORD_POSTED_AGE_DAYS_KEY),

        RECORD_SALARY_KEY: snapshot.get(RECORD_SALARY_KEY) or "N/A",

        RECORD_LOCATION_KEY: snapshot.get(RECORD_LOCATION_KEY) or "N/A",

        RECORD_WORK_MODE_KEY: snapshot.get(RECORD_WORK_MODE_KEY) or "N/A",

        RECORD_WORK_TYPE_KEY: snapshot.get(RECORD_WORK_TYPE_KEY) or "N/A",

        RECORD_TEASER_KEY: snapshot.get(RECORD_TEASER_KEY) or "N/A",

        RECORD_ROLE_SNAPSHOT_KEY: snapshot.get(RECORD_ROLE_SNAPSHOT_KEY) or "N/A",

        RECORD_TITLE_REASON_KEY: snapshot.get(RECORD_TITLE_REASON_KEY),

        RECORD_CONTENT_REASON_KEY: snapshot.get(RECORD_CONTENT_REASON_KEY),

        RECORD_LLM_DECISION_KEY: snapshot.get(RECORD_LLM_DECISION_KEY),

        RECORD_LLM_FIT_GRADE_KEY: snapshot.get(RECORD_LLM_FIT_GRADE_KEY),

        "fit_source_text": snapshot.get("fit_source_text") or "",

        "full_description": snapshot.get("full_description") or "",

        "fit_confidence": snapshot.get("fit_confidence") or "",

        "details_status": snapshot.get("details_status") or "",

        "description_source": snapshot.get("description_source") or "",

        "fit_highlights": snapshot.get("fit_highlights") or [],

        RECORD_JOB_REQUIREMENTS_KEY: snapshot.get(RECORD_JOB_REQUIREMENTS_KEY) or [],

        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],

        "missing_profile_support": snapshot.get("missing_profile_support") or [],

        "competitive_signals": snapshot.get("competitive_signals") or [],

        "hard_block_reasons": snapshot.get("hard_block_reasons") or [],

        RECORD_SEARCH_LOCATION_KEY: snapshot.get(RECORD_SEARCH_LOCATION_KEY) or "N/A",

        RECORD_SEARCH_KEYWORDS_KEY: snapshot.get(RECORD_SEARCH_KEYWORDS_KEY) or "",

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

    build_hidden_workspace_record_fn: Callable[[str, dict, datetime], dict],

) -> list[dict]:

    records: list[dict] = []

    for job_key in hidden_job_keys:

        entry = history.get(job_key, {})

        hidden_at = entry.get("last_hidden_at") or entry.get("first_hidden_at")

        hidden_age_days = days_since_fn(hidden_at, run_started_at) if hidden_at else None

        if hidden_age_days is not None and hidden_age_days > hidden_review_days:

            continue

        records.append(build_hidden_workspace_record_fn(job_key, entry, run_started_at))



    records.sort(

        key=lambda item: (

            parse_timestamp_fn(item.get("last_hidden_at")) or datetime.min,

            parse_timestamp_fn(item.get("last_seen_at")) or datetime.min,

        ),

        reverse=True,

    )

    return records





def build_applied_workspace_record(

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

        "source": _record_source(snapshot or entry, job_key),

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

        RECORD_JOB_REQUIREMENTS_KEY: snapshot.get(RECORD_JOB_REQUIREMENTS_KEY) or [],

        "soft_risk_reasons": snapshot.get("soft_risk_reasons") or [],

        "missing_profile_support": snapshot.get("missing_profile_support") or [],

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

    build_applied_workspace_record_fn: Callable[[str, dict, datetime], dict],

) -> list[dict]:

    records = [

        build_applied_workspace_record_fn(job_key, history.get(job_key, {}), run_started_at)

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





def build_workspace_record_sets(

    kept_records: list[dict],

    job_history: dict[str, dict],

    applied_job_keys: set[str],

    hidden_job_keys: set[str],

    reference_time: datetime,

    *,

    profile: dict,

    is_workspace_eligible_fn: Callable[[dict, Optional[dict]], bool],

    fit_score_fn: Callable[[dict, Optional[dict]], int],

    viewed_by_user_fn: Callable[[dict], bool],

    normalize_job_key_fn: Callable[[str], str],

    parse_timestamp_fn: Callable[[Optional[str]], Optional[datetime]],

    build_archive_records_fn: Callable[[dict[str, dict], set[str], set[str], set[str], datetime], list[dict]],

    build_applied_records_fn: Callable[[set[str], dict[str, dict], datetime], list[dict]],

    build_hidden_records_fn: Callable[[set[str], dict[str, dict], datetime], list[dict]],

    debug_mode: bool = False,

    audit_rows: list[dict] | None = None,

) -> dict[str, list[dict]]:

    _score_cache: dict[str, int] = {}



    def _cached_score(record: dict) -> int:

        key = str(record.get("job_key") or id(record))

        if key not in _score_cache:

            try:

                _score_cache[key] = fit_score_fn(record, profile)

            except RuntimeError as exc:

                logger.error(

                    "[WORKSPACE_DATA][SCORING_ERROR] job=%s title=%r — score set to 0: %s",

                    record.get("job_key", "<unknown>"),

                    str(record.get("title") or "").strip(),

                    exc,

                )

                _score_cache[key] = 0

        return _score_cache[key]



    def _is_eligible(record: dict) -> bool:

        return is_workspace_eligible_fn(record, profile)



    curated_kept_records = [record for record in kept_records if _is_eligible(record)]



    def _rank_by_fit(record: dict) -> tuple:

        timestamp = parse_timestamp_fn(record.get("last_kept_at") or record.get("last_seen_at"))

        return (

            -_cached_score(record),

            -(1 if not viewed_by_user_fn(record) else 0),

            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,

            -(timestamp or datetime.min).timestamp() if timestamp else float("-inf"),

        )



    def _rank_archive_by_fit(record: dict) -> tuple:

        timestamp = parse_timestamp_fn(record.get("last_kept_at"))

        return (

            -_cached_score(record),

            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,

            -(timestamp or datetime.min).timestamp() if timestamp else float("-inf"),

        )



    current_records = sorted(curated_kept_records, key=_rank_by_fit)

    if debug_mode and audit_rows:

        current_keys = {

            normalize_job_key_fn(str(record.get("job_key") or ""))

            for record in current_records

            if normalize_job_key_fn(str(record.get("job_key") or ""))

        }

        debug_records: list[dict] = []

        for row in audit_rows:

            if str(row.get("decision") or "").upper() != "REJECT":

                continue

            job_key = normalize_job_key_fn(str(row.get("job_key") or ""))

            if not job_key or job_key in current_keys:

                continue

            debug_records.append(dict(row))

            current_keys.add(job_key)

        current_records = sorted([*current_records, *debug_records], key=_rank_by_fit)



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

        [record for record in archive_records if not record.get("is_stale") and _is_eligible(record)],

        key=_rank_archive_by_fit,

    )

    stale_archive_records = sorted(

        [record for record in archive_records if record.get("is_stale") and _is_eligible(record)],

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

    seek_max_pages: int,

) -> dict:

    search_targets: dict[str, set[int]] = {}

    page_visits: set[tuple[str, str, int]] = set()

    reject_counts: dict[str, int] = {}

    skip_counts: dict[str, int] = {}

    flag_counts: dict[str, int] = {}



    def _add_flag(key: str) -> None:

        if not key:

            return

        flag_counts[key] = flag_counts.get(key, 0) + 1



    for row in audit_rows:

        source_name = str(row.get("source") or "Unknown")

        search_location = str(row.get("search_location") or "Unknown")

        page_num = row.get("page")

        if page_num is not None:

            page_visits.add((source_name, search_location, int(page_num)))

            search_targets.setdefault(search_location, set()).add(int(page_num))



        reason = row.get("reject_reason") or "UNKNOWN"

        decision = row.get("decision")

        if decision == "SKIP":

            skip_counts[reason] = skip_counts.get(reason, 0) + 1

        elif decision != "KEEP":

            reject_counts[reason] = reject_counts.get(reason, 0) + 1



        if row.get("job_quality_signals"):

            _add_flag("quality_signals")

            for signal in row.get("job_quality_signals") or []:

                if isinstance(signal, dict):

                    kind = str(signal.get("kind") or signal.get("label") or "quality_signal").strip()

                    _add_flag(f"quality:{kind.lower()}")

                else:

                    _add_flag("quality:signal")

        if row.get("hard_block_reasons"):

            _add_flag("hard_block_reasons")

        if row.get("soft_risk_reasons"):

            _add_flag("soft_risk_reasons")

        if row.get("missing_profile_support"):

            _add_flag("missing_profile_support")

        if row.get("reviewed_signal_matches"):

            _add_flag("reviewed_signal_matches")

    onet_match_count = sum(
        1
        for row in audit_rows
        if str((row.get("onet_classification") or {}).get("result") or "").strip().lower() == "near"
    )



    top_reject_reasons = [

        {"reason": reason, "count": count}

        for reason, count in sorted(reject_counts.items(), key=lambda item: (-item[1], item[0]))[:8]

    ]

    issue_flag_summary = [

        {"flag": flag, "count": count}

        for flag, count in sorted(flag_counts.items(), key=lambda item: (-item[1], item[0]))[:8]

    ]



    detail_fetches = sum(1 for row in audit_rows if int(row.get("details_length") or 0) > 0)

    cards_seen = len(audit_rows)

    kept_count = len(kept_records)

    rejected_count = sum(1 for row in audit_rows if str(row.get("decision") or "").upper() == "REJECT")

    cards_with_flags_count = sum(

        1

        for row in audit_rows

        if row.get("job_quality_signals")

        or row.get("hard_block_reasons")

        or row.get("soft_risk_reasons")

        or row.get("missing_profile_support")

        or row.get("reviewed_signal_matches")

    )



    return {

        "run_started_at": run_started_at.isoformat(timespec="seconds"),

        "run_finished_at": run_finished_at.isoformat(timespec="seconds"),

        "search_window_days": date_range_days,

        "sort_newest_first": sort_newest_first,

        "seek_max_pages": seek_max_pages,

        "search_targets": {

            location: sorted(pages)

            for location, pages in sorted(search_targets.items())

        },

        "page_count": len(page_visits),

        "cards_seen": cards_seen,

        "cards_read": detail_fetches,

        "detail_fetches": detail_fetches,

        "kept_count": kept_count,

        "rejected_count": rejected_count,

        "cards_with_flags_count": cards_with_flags_count,

        "issue_flag_summary": issue_flag_summary,

        "onet_match_count": onet_match_count,

        "keep_rate": round((kept_count / cards_seen), 4) if cards_seen else 0.0,

        "top_reject_reasons": top_reject_reasons,

        "skip_counts": skip_counts,

    }

