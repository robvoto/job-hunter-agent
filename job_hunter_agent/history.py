import re
import sys
from datetime import datetime
from typing import Dict, List, Optional

from job_hunter_agent import workspace_data
from job_hunter_agent.io_utils import normalize_posted_text
from job_hunter_agent.posting_utils import days_since, parse_timestamp
from job_hunter_agent.company_rules import normalize_company_name
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.signal_detection import hard_block_reasons
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order
from job_hunter_agent.runtime_helpers import CLI_FLAG_RESET_NEW_TO_YOU
import job_hunter_agent.record_schema
from job_hunter_agent.global_settings import (
    get_archive_stale_after_days as get_global_archive_stale_after_days,
    get_hidden_review_days as get_global_hidden_review_days,
    get_max_history_sightings as get_global_max_history_sightings,
    get_multi_listing_red_flag_min_listings as get_global_multi_listing_red_flag_min_listings,
    get_multi_listing_red_flag_min_span_days as get_global_multi_listing_red_flag_min_span_days,
    get_repeated_listing_min_span_days as get_global_repeated_listing_min_span_days,
    get_repeated_listing_min_times_seen as get_global_repeated_listing_min_times_seen,
)
TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING = CLI_FLAG_RESET_NEW_TO_YOU in set(sys.argv[1:])


def get_archive_stale_after_days() -> int:
    return get_global_archive_stale_after_days()


def get_hidden_review_days() -> int:
    return get_global_hidden_review_days()


def get_max_history_sightings() -> int:
    return get_global_max_history_sightings()


def get_repeated_listing_min_times_seen() -> int:
    return get_global_repeated_listing_min_times_seen()


def get_repeated_listing_min_span_days() -> int:
    return get_global_repeated_listing_min_span_days()


def get_multi_listing_red_flag_min_listings() -> int:
    return get_global_multi_listing_red_flag_min_listings()


def get_multi_listing_red_flag_min_span_days() -> int:
    return get_global_multi_listing_red_flag_min_span_days()

KEEP_SNAPSHOT_FIELDS = (
    job_hunter_agent.record_schema.RECORD_TITLE_KEY,
    job_hunter_agent.record_schema.RECORD_COMPANY_KEY,
    job_hunter_agent.record_schema.RECORD_URL_KEY,
    job_hunter_agent.record_schema.RECORD_POSTED_KEY,
    job_hunter_agent.record_schema.RECORD_POSTED_AGE_DAYS_KEY,
    job_hunter_agent.record_schema.RECORD_SALARY_KEY,
    job_hunter_agent.record_schema.RECORD_WORK_MODE_KEY,
    job_hunter_agent.record_schema.RECORD_WORK_MODE_SOURCE_KEY,
    job_hunter_agent.record_schema.RECORD_WORK_MODE_EVIDENCE_KEY,
    job_hunter_agent.record_schema.RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    job_hunter_agent.record_schema.RECORD_LOCATION_KEY,
    job_hunter_agent.record_schema.RECORD_WORK_TYPE_KEY,
    job_hunter_agent.record_schema.RECORD_TEASER_KEY,
    job_hunter_agent.record_schema.RECORD_TITLE_REASON_KEY,
    job_hunter_agent.record_schema.RECORD_CONTENT_REASON_KEY,
    job_hunter_agent.record_schema.RECORD_LLM_DECISION_KEY,
    job_hunter_agent.record_schema.RECORD_LLM_FIT_GRADE_KEY,
    job_hunter_agent.record_schema.RECORD_SEARCH_LOCATION_KEY,
    job_hunter_agent.record_schema.RECORD_SEARCH_KEYWORDS_KEY,
    job_hunter_agent.record_schema.RECORD_FIT_SOURCE_TEXT_KEY,
    job_hunter_agent.record_schema.RECORD_FULL_DESCRIPTION_KEY,
    job_hunter_agent.record_schema.RECORD_FIT_CONFIDENCE_KEY,
    job_hunter_agent.record_schema.RECORD_DETAILS_STATUS_KEY,
    job_hunter_agent.record_schema.RECORD_DESCRIPTION_SOURCE_KEY,
    job_hunter_agent.record_schema.RECORD_ROLE_SNAPSHOT_KEY,
    job_hunter_agent.record_schema.RECORD_FIT_HIGHLIGHTS_KEY,
    job_hunter_agent.record_schema.RECORD_SOFT_RISK_REASONS_KEY,
    job_hunter_agent.record_schema.RECORD_MISSING_EVIDENCE_KEY,
    job_hunter_agent.record_schema.RECORD_COMPETITIVE_SIGNALS_KEY,
    job_hunter_agent.record_schema.RECORD_HARD_BLOCK_REASONS_KEY,
    job_hunter_agent.record_schema.RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
)


def build_keep_snapshot(record: dict) -> dict:
    snapshot = {}
    for field in KEEP_SNAPSHOT_FIELDS:
        if field in record:
            snapshot[field] = record.get(field)
    return snapshot


def can_reuse_kept_job(history_entry: dict, record: dict, profile: Optional[dict] = None) -> bool:
    if not isinstance(history_entry, dict):
        return False
    if int(history_entry.get(job_hunter_agent.record_schema.RECORD_TIMES_KEPT_KEY, 0) or 0) <= 0:
        return False
    snapshot = history_entry.get(job_hunter_agent.record_schema.RECORD_LAST_KEPT_SNAPSHOT_KEY)
    if not isinstance(snapshot, dict):
        return False
    if not record.get(job_hunter_agent.record_schema.RECORD_JOB_KEY):
        return False
    if hard_block_reasons(snapshot if isinstance(snapshot, dict) else {}, profile):
        return False
    return True


def apply_kept_job_reuse(record: dict, history_entry: dict) -> dict:
    snapshot = history_entry.get(job_hunter_agent.record_schema.RECORD_LAST_KEPT_SNAPSHOT_KEY) if isinstance(history_entry, dict) else {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    if record.get(job_hunter_agent.record_schema.RECORD_POSTED_KEY) in {None, "", "N/A"}:
        record[job_hunter_agent.record_schema.RECORD_POSTED_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_POSTED_KEY) or "N/A"
    if record.get(job_hunter_agent.record_schema.RECORD_POSTED_AGE_DAYS_KEY) is None and snapshot.get(job_hunter_agent.record_schema.RECORD_POSTED_AGE_DAYS_KEY) is not None:
        record[job_hunter_agent.record_schema.RECORD_POSTED_AGE_DAYS_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_POSTED_AGE_DAYS_KEY)
    if record.get(job_hunter_agent.record_schema.RECORD_SALARY_KEY) in {None, "", "N/A"}:
        record[job_hunter_agent.record_schema.RECORD_SALARY_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_SALARY_KEY) or "N/A"
    if record.get(job_hunter_agent.record_schema.RECORD_TEASER_KEY) in {None, "", "N/A"}:
        record[job_hunter_agent.record_schema.RECORD_TEASER_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_TEASER_KEY) or "N/A"
    if record.get(job_hunter_agent.record_schema.RECORD_LOCATION_KEY) in {None, "", "N/A"}:
        record[job_hunter_agent.record_schema.RECORD_LOCATION_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_LOCATION_KEY) or "N/A"
    if record.get(job_hunter_agent.record_schema.RECORD_WORK_MODE_KEY) in {None, "", "N/A"}:
        record[job_hunter_agent.record_schema.RECORD_WORK_MODE_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_WORK_MODE_KEY) or "N/A"
    if record.get(job_hunter_agent.record_schema.RECORD_WORK_TYPE_KEY) in {None, "", "N/A"}:
        record[job_hunter_agent.record_schema.RECORD_WORK_TYPE_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_WORK_TYPE_KEY) or "N/A"
    if record.get(job_hunter_agent.record_schema.RECORD_ROLE_SNAPSHOT_KEY) in {None, "", "N/A"}:
        record[job_hunter_agent.record_schema.RECORD_ROLE_SNAPSHOT_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_ROLE_SNAPSHOT_KEY) or "N/A"
    if not compact_whitespace(record.get(job_hunter_agent.record_schema.RECORD_FIT_SOURCE_TEXT_KEY) or ""):
        record[job_hunter_agent.record_schema.RECORD_FIT_SOURCE_TEXT_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_FIT_SOURCE_TEXT_KEY) or ""
    if not compact_whitespace(record.get(job_hunter_agent.record_schema.RECORD_FULL_DESCRIPTION_KEY) or ""):
        record[job_hunter_agent.record_schema.RECORD_FULL_DESCRIPTION_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_FULL_DESCRIPTION_KEY) or ""
    if not record.get(job_hunter_agent.record_schema.RECORD_FIT_CONFIDENCE_KEY):
        record[job_hunter_agent.record_schema.RECORD_FIT_CONFIDENCE_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_FIT_CONFIDENCE_KEY) or ""
    if not record.get(job_hunter_agent.record_schema.RECORD_FIT_HIGHLIGHTS_KEY):
        record[job_hunter_agent.record_schema.RECORD_FIT_HIGHLIGHTS_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_FIT_HIGHLIGHTS_KEY) or []
    if not record.get(job_hunter_agent.record_schema.RECORD_SOFT_RISK_REASONS_KEY):
        record[job_hunter_agent.record_schema.RECORD_SOFT_RISK_REASONS_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_SOFT_RISK_REASONS_KEY) or []
    if not record.get(job_hunter_agent.record_schema.RECORD_MISSING_EVIDENCE_KEY):
        record[job_hunter_agent.record_schema.RECORD_MISSING_EVIDENCE_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_MISSING_EVIDENCE_KEY) or []
    if not record.get(job_hunter_agent.record_schema.RECORD_COMPETITIVE_SIGNALS_KEY):
        record[job_hunter_agent.record_schema.RECORD_COMPETITIVE_SIGNALS_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_COMPETITIVE_SIGNALS_KEY) or []
    if not record.get(job_hunter_agent.record_schema.RECORD_HARD_BLOCK_REASONS_KEY):
        record[job_hunter_agent.record_schema.RECORD_HARD_BLOCK_REASONS_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_HARD_BLOCK_REASONS_KEY) or []
    if not compact_whitespace(record.get(job_hunter_agent.record_schema.RECORD_DETAILS_STATUS_KEY) or ""):
        record[job_hunter_agent.record_schema.RECORD_DETAILS_STATUS_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_DETAILS_STATUS_KEY) or ""
    if not record.get(job_hunter_agent.record_schema.RECORD_DESCRIPTION_SOURCE_KEY):
        record[job_hunter_agent.record_schema.RECORD_DESCRIPTION_SOURCE_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_DESCRIPTION_SOURCE_KEY) or ""

    record[job_hunter_agent.record_schema.RECORD_CONTENT_REASON_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_CONTENT_REASON_KEY)
    record[job_hunter_agent.record_schema.RECORD_LLM_DECISION_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_LLM_DECISION_KEY)
    record[job_hunter_agent.record_schema.RECORD_LLM_FIT_GRADE_KEY] = snapshot.get(job_hunter_agent.record_schema.RECORD_LLM_FIT_GRADE_KEY)
    record[job_hunter_agent.record_schema.RECORD_DECISION_KEY] = "KEEP"
    record[job_hunter_agent.record_schema.RECORD_DETAILS_LENGTH_KEY] = 0
    record[job_hunter_agent.record_schema.RECORD_REUSED_HISTORY_KEY] = True
    return record


def viewed_by_user(record: dict) -> bool:
    if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        return False
    return int(record.get(job_hunter_agent.record_schema.RECORD_TIMES_VIEWED_KEY, 0) or 0) > 0


def history_cluster_key_from_parts(source: Optional[str], company: Optional[str], title: Optional[str]) -> str:
    source_key = compact_whitespace(source or "").lower()
    company_key = re.sub(r"[^a-z0-9]+", " ", normalize_company_name(company or "")).strip()
    title_key = re.sub(r"[^a-z0-9]+", " ", compact_whitespace(title or "").lower()).strip()
    if not source_key or not company_key or not title_key:
        return ""
    return f"{source_key}|{company_key}|{title_key}"


def history_cluster_key(record: dict) -> str:
    source = str(record.get(job_hunter_agent.record_schema.RECORD_SOURCE_KEY) or "").strip().lower()
    if not source:
        # Strictly extract source from the canonical job key if missing from record fields
        job_key = str(record.get(job_hunter_agent.record_schema.RECORD_JOB_KEY) or "")
        source = job_key.split(":", 1)[0] if ":" in job_key else ""
    if not source:
        return ""
    return history_cluster_key_from_parts(source, record.get(job_hunter_agent.record_schema.RECORD_COMPANY_KEY), record.get(job_hunter_agent.record_schema.RECORD_TITLE_KEY))


def build_history_sighting(record: dict, run_iso: str) -> dict:
    return {
        "seen_at": run_iso,
        job_hunter_agent.record_schema.RECORD_URL_KEY: str(record.get(job_hunter_agent.record_schema.RECORD_URL_KEY) or "").strip(),
        job_hunter_agent.record_schema.RECORD_POSTED_KEY: normalize_posted_text(record.get(job_hunter_agent.record_schema.RECORD_POSTED_KEY)),
        job_hunter_agent.record_schema.RECORD_POSTED_AGE_DAYS_KEY: record.get(job_hunter_agent.record_schema.RECORD_POSTED_AGE_DAYS_KEY),
        job_hunter_agent.record_schema.RECORD_COMPANY_KEY: str(record.get(job_hunter_agent.record_schema.RECORD_COMPANY_KEY) or "").strip(),
        job_hunter_agent.record_schema.RECORD_TITLE_KEY: str(record.get(job_hunter_agent.record_schema.RECORD_TITLE_KEY) or "").strip(),
        job_hunter_agent.record_schema.RECORD_SOURCE_KEY: str(record.get(job_hunter_agent.record_schema.RECORD_SOURCE_KEY) or "").strip().lower(),
    }


def build_history_cluster_index(history: Dict[str, dict]) -> Dict[str, dict]:
    clusters: Dict[str, dict] = {}
    for job_key, entry in history.items():
        if not isinstance(entry, dict):
            continue
        snapshot = entry.get(job_hunter_agent.record_schema.RECORD_LAST_KEPT_SNAPSHOT_KEY) if isinstance(entry.get(job_hunter_agent.record_schema.RECORD_LAST_KEPT_SNAPSHOT_KEY), dict) else {}
        source = snapshot.get(job_hunter_agent.record_schema.RECORD_SOURCE_KEY) or (str(job_key).split(":", 1)[0] if ":" in str(job_key) else "")
        if not source:
            continue
            
        company = snapshot.get(job_hunter_agent.record_schema.RECORD_COMPANY_KEY) or entry.get(job_hunter_agent.record_schema.RECORD_COMPANY_KEY)
        title = snapshot.get(job_hunter_agent.record_schema.RECORD_TITLE_KEY) or entry.get(job_hunter_agent.record_schema.RECORD_TITLE_KEY)
        cluster_key = history_cluster_key_from_parts(source, company, title)
        if not cluster_key:
            continue
        stats = clusters.setdefault(
            cluster_key,
            {
                "job_keys": set(),
                job_hunter_agent.record_schema.RECORD_TIMES_SEEN_KEY: 0,
                job_hunter_agent.record_schema.RECORD_FIRST_SEEN_AT_KEY: None,
                job_hunter_agent.record_schema.RECORD_LAST_SEEN_AT_KEY: None,
            },
        )
        stats["job_keys"].add(str(job_key))
        stats[job_hunter_agent.record_schema.RECORD_TIMES_SEEN_KEY] += int(entry.get(job_hunter_agent.record_schema.RECORD_TIMES_SEEN_KEY, 0) or 0)
        first_seen = parse_timestamp(entry.get("first_seen_at"))
        last_seen = parse_timestamp(entry.get("last_seen_at"))
        if first_seen and (stats["first_seen_at"] is None or first_seen < stats["first_seen_at"]):
            stats["first_seen_at"] = first_seen
        if last_seen and (stats["last_seen_at"] is None or last_seen > stats["last_seen_at"]):
            stats["last_seen_at"] = last_seen
    return clusters


def assess_history_warning_signals(record: dict, history_clusters: Optional[Dict[str, dict]] = None) -> List[str]:
    warnings: List[str] = []
    times_seen = int(record.get(job_hunter_agent.record_schema.RECORD_TIMES_SEEN_KEY, 0) or 0)
    first_seen = parse_timestamp(record.get(job_hunter_agent.record_schema.RECORD_FIRST_SEEN_AT_KEY))
    last_seen = parse_timestamp(record.get(job_hunter_agent.record_schema.RECORD_LAST_SEEN_AT_KEY))
    if first_seen and last_seen:
        span_days = max((last_seen.date() - first_seen.date()).days, 0)
        if times_seen >= get_repeated_listing_min_times_seen() and span_days >= get_repeated_listing_min_span_days():
            warnings.append(
                f"Potential red flag: this same listing has been seen {times_seen} times over {span_days} days"
            )

    cluster_key = history_cluster_key(record)
    cluster_stats = history_clusters.get(cluster_key) if history_clusters and cluster_key else None
    if cluster_stats:
        listing_count = len(cluster_stats.get("job_keys", set()))
        cluster_first_seen = cluster_stats.get("first_seen_at")
        cluster_last_seen = cluster_stats.get("last_seen_at")
        if cluster_first_seen and cluster_last_seen:
            cluster_span_days = max((cluster_last_seen.date() - cluster_first_seen.date()).days, 0)
            if listing_count >= get_multi_listing_red_flag_min_listings() and cluster_span_days >= get_multi_listing_red_flag_min_span_days():
                warnings.append(
                    f"Potential red flag: the same title from the same poster has appeared across {listing_count} separate listings over {cluster_span_days} days"
                )
    return dedupe_preserve_order(warnings)


def update_job_history(history: Dict[str, dict], record: dict, run_iso: str) -> None:
    job_key = record.get(job_hunter_agent.record_schema.RECORD_JOB_KEY)
    if not job_key:
        record[job_hunter_agent.record_schema.RECORD_SEEN_BEFORE_KEY] = False
        record[job_hunter_agent.record_schema.RECORD_TIMES_KEPT_KEY] = 0
        record[job_hunter_agent.record_schema.RECORD_FIRST_KEPT_AT_KEY] = None
        return

    entry = history.get(job_key, {})
    prior_kept_count = int(entry.get(job_hunter_agent.record_schema.RECORD_TIMES_KEPT_KEY, 0) or 0)

    entry[job_hunter_agent.record_schema.RECORD_JOB_KEY] = job_key
    entry[job_hunter_agent.record_schema.RECORD_TITLE_KEY] = record.get(job_hunter_agent.record_schema.RECORD_TITLE_KEY)
    entry[job_hunter_agent.record_schema.RECORD_COMPANY_KEY] = record.get(job_hunter_agent.record_schema.RECORD_COMPANY_KEY)
    entry[job_hunter_agent.record_schema.RECORD_URL_KEY] = record.get(job_hunter_agent.record_schema.RECORD_URL_KEY)
    entry[job_hunter_agent.record_schema.RECORD_LAST_SEEN_AT_KEY] = run_iso
    entry[job_hunter_agent.record_schema.RECORD_TIMES_SEEN_KEY] = int(entry.get(job_hunter_agent.record_schema.RECORD_TIMES_SEEN_KEY, 0) or 0) + 1
    if not entry.get(job_hunter_agent.record_schema.RECORD_FIRST_SEEN_AT_KEY):
        entry[job_hunter_agent.record_schema.RECORD_FIRST_SEEN_AT_KEY] = run_iso

    record[job_hunter_agent.record_schema.RECORD_SEEN_BEFORE_KEY] = prior_kept_count > 0
    record[job_hunter_agent.record_schema.RECORD_TIMES_SEEN_KEY] = entry[job_hunter_agent.record_schema.RECORD_TIMES_SEEN_KEY]
    record[job_hunter_agent.record_schema.RECORD_TIMES_KEPT_KEY] = prior_kept_count
    record[job_hunter_agent.record_schema.RECORD_TIMES_VIEWED_KEY] = int(entry.get(job_hunter_agent.record_schema.RECORD_TIMES_VIEWED_KEY, 0) or 0)
    record[job_hunter_agent.record_schema.RECORD_FIRST_KEPT_AT_KEY] = entry.get(job_hunter_agent.record_schema.RECORD_FIRST_KEPT_AT_KEY)
    record[job_hunter_agent.record_schema.RECORD_FIRST_SEEN_AT_KEY] = entry.get(job_hunter_agent.record_schema.RECORD_FIRST_SEEN_AT_KEY)
    record[job_hunter_agent.record_schema.RECORD_LAST_SEEN_AT_KEY] = entry.get(job_hunter_agent.record_schema.RECORD_LAST_SEEN_AT_KEY)
    record[job_hunter_agent.record_schema.RECORD_FIRST_VIEWED_AT_KEY] = entry.get(job_hunter_agent.record_schema.RECORD_FIRST_VIEWED_AT_KEY)
    record[job_hunter_agent.record_schema.RECORD_LAST_VIEWED_AT_KEY] = entry.get(job_hunter_agent.record_schema.RECORD_LAST_VIEWED_AT_KEY)
    sightings = entry.get(job_hunter_agent.record_schema.RECORD_SIGHTINGS_KEY) if isinstance(entry.get(job_hunter_agent.record_schema.RECORD_SIGHTINGS_KEY), list) else []
    current_sighting = build_history_sighting(record, run_iso)
    if not sightings or sightings[-1] != current_sighting:
        sightings = [*sightings, current_sighting][-get_max_history_sightings():]
    entry[job_hunter_agent.record_schema.RECORD_SIGHTINGS_KEY] = sightings
    record["history_sightings"] = sightings

    if record.get(job_hunter_agent.record_schema.RECORD_DECISION_KEY) == "KEEP":
        if not entry.get(job_hunter_agent.record_schema.RECORD_FIRST_KEPT_AT_KEY):
            entry[job_hunter_agent.record_schema.RECORD_FIRST_KEPT_AT_KEY] = run_iso
        entry[job_hunter_agent.record_schema.RECORD_LAST_KEPT_AT_KEY] = run_iso
        entry[job_hunter_agent.record_schema.RECORD_TIMES_KEPT_KEY] = prior_kept_count + 1
        entry[job_hunter_agent.record_schema.RECORD_LAST_KEPT_SNAPSHOT_KEY] = build_keep_snapshot(record)
        record[job_hunter_agent.record_schema.RECORD_TIMES_KEPT_KEY] = entry[job_hunter_agent.record_schema.RECORD_TIMES_KEPT_KEY]
        record[job_hunter_agent.record_schema.RECORD_FIRST_KEPT_AT_KEY] = entry[job_hunter_agent.record_schema.RECORD_FIRST_KEPT_AT_KEY]
        record[job_hunter_agent.record_schema.RECORD_LAST_KEPT_AT_KEY] = entry[job_hunter_agent.record_schema.RECORD_LAST_KEPT_AT_KEY]

    history[job_key] = entry


def finalize_record(history: Dict[str, dict], audit_rows: List[dict], record: dict, run_iso: str) -> None:
    update_job_history(history, record, run_iso)
    audit_rows.append(record)

