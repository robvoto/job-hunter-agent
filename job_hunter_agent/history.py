import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from job_hunter_agent import dashboard_data
from job_hunter_agent.io_utils import normalize_posted_text
from job_hunter_agent.posting_utils import days_since, parse_timestamp
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.signal_detection import hard_block_reasons
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order
from job_hunter_agent.runtime_helpers import CLI_FLAG_RESET_NEW_TO_YOU
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_COMPETITIVE_SIGNALS_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_DECISION_KEY,
    RECORD_DETAILS_LENGTH_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_FIT_HIGHLIGHTS_KEY,
    RECORD_FIT_CONFIDENCE_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_LOCATION_KEY,
    RECORD_MISSING_EVIDENCE_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_POSTED_KEY,
    RECORD_SOFT_RISK_REASONS_KEY,
    RECORD_SOURCE_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_MODE_SOURCE_KEY,
    RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    RECORD_WORK_TYPE_KEY,
    RECORD_TEASER_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_ROLE_SNAPSHOT_KEY,
    RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
    RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_TIMES_KEPT_KEY,
    RECORD_FIRST_KEPT_AT_KEY,
    RECORD_LAST_KEPT_AT_KEY,
    RECORD_TIMES_SEEN_KEY,
    RECORD_FIRST_SEEN_AT_KEY,
    RECORD_LAST_SEEN_AT_KEY,
    RECORD_TIMES_VIEWED_KEY,
    RECORD_FIRST_VIEWED_AT_KEY,
    RECORD_LAST_VIEWED_AT_KEY,
    RECORD_SIGHTINGS_KEY,
    RECORD_SEEN_BEFORE_KEY,
    RECORD_REUSED_HISTORY_KEY,
    RECORD_SALARY_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_SEARCH_LOCATION_KEY,
    RECORD_SEARCH_KEYWORDS_KEY
)
from job_hunter_agent.advance_settings import (
    KEY_ARCHIVE_STALE_AFTER_DAYS,
    KEY_HISTORY_SETTINGS,
    KEY_HIDDEN_REVIEW_DAYS,
    load_advance_settings,
)
MAX_HISTORY_SIGHTINGS = 24
REPEATED_LISTING_MIN_TIMES_SEEN = 4
REPEATED_LISTING_MIN_SPAN_DAYS = 21
MULTI_LISTING_RED_FLAG_MIN_LISTINGS = 3
MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS = 30
TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING = CLI_FLAG_RESET_NEW_TO_YOU in set(sys.argv[1:])


def get_archive_stale_after_days() -> int:
    return int(load_advance_settings()[KEY_HISTORY_SETTINGS][KEY_ARCHIVE_STALE_AFTER_DAYS])


def get_hidden_review_days() -> int:
    return int(load_advance_settings()[KEY_HISTORY_SETTINGS][KEY_HIDDEN_REVIEW_DAYS])

KEEP_SNAPSHOT_FIELDS = (
    RECORD_TITLE_KEY,
    RECORD_COMPANY_KEY,
    RECORD_URL_KEY,
    RECORD_POSTED_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_SALARY_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_MODE_SOURCE_KEY,
    RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    RECORD_LOCATION_KEY,
    RECORD_WORK_TYPE_KEY,
    RECORD_TEASER_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_SEARCH_LOCATION_KEY,
    RECORD_SEARCH_KEYWORDS_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_FIT_CONFIDENCE_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_ROLE_SNAPSHOT_KEY,
    RECORD_FIT_HIGHLIGHTS_KEY,
    RECORD_SOFT_RISK_REASONS_KEY,
    RECORD_MISSING_EVIDENCE_KEY,
    RECORD_COMPETITIVE_SIGNALS_KEY,
    RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
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
    if int(history_entry.get(RECORD_TIMES_KEPT_KEY, 0) or 0) <= 0:
        return False
    snapshot = history_entry.get(RECORD_LAST_KEPT_SNAPSHOT_KEY)
    if not isinstance(snapshot, dict):
        return False
    if not record.get(RECORD_JOB_KEY):
        return False
    if hard_block_reasons(snapshot if isinstance(snapshot, dict) else {}, profile):
        return False
    return True


def apply_kept_job_reuse(record: dict, history_entry: dict) -> dict:
    snapshot = history_entry.get(RECORD_LAST_KEPT_SNAPSHOT_KEY) if isinstance(history_entry, dict) else {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    if record.get(RECORD_POSTED_KEY) in {None, "", "N/A"}:
        record[RECORD_POSTED_KEY] = snapshot.get(RECORD_POSTED_KEY) or "N/A"
    if record.get(RECORD_POSTED_AGE_DAYS_KEY) is None and snapshot.get(RECORD_POSTED_AGE_DAYS_KEY) is not None:
        record[RECORD_POSTED_AGE_DAYS_KEY] = snapshot.get(RECORD_POSTED_AGE_DAYS_KEY)
    if record.get(RECORD_SALARY_KEY) in {None, "", "N/A"}:
        record[RECORD_SALARY_KEY] = snapshot.get(RECORD_SALARY_KEY) or "N/A"
    if record.get(RECORD_TEASER_KEY) in {None, "", "N/A"}:
        record[RECORD_TEASER_KEY] = snapshot.get(RECORD_TEASER_KEY) or "N/A"
    if record.get(RECORD_LOCATION_KEY) in {None, "", "N/A"}:
        record[RECORD_LOCATION_KEY] = snapshot.get(RECORD_LOCATION_KEY) or "N/A"
    if record.get(RECORD_WORK_MODE_KEY) in {None, "", "N/A"}:
        record[RECORD_WORK_MODE_KEY] = snapshot.get(RECORD_WORK_MODE_KEY) or "N/A"
    if record.get(RECORD_WORK_TYPE_KEY) in {None, "", "N/A"}:
        record[RECORD_WORK_TYPE_KEY] = snapshot.get(RECORD_WORK_TYPE_KEY) or "N/A"
    if record.get(RECORD_ROLE_SNAPSHOT_KEY) in {None, "", "N/A"}:
        record[RECORD_ROLE_SNAPSHOT_KEY] = snapshot.get(RECORD_ROLE_SNAPSHOT_KEY) or "N/A"
    if not compact_whitespace(record.get(RECORD_FIT_SOURCE_TEXT_KEY) or ""):
        record[RECORD_FIT_SOURCE_TEXT_KEY] = snapshot.get(RECORD_FIT_SOURCE_TEXT_KEY) or ""
    if not compact_whitespace(record.get(RECORD_FULL_DESCRIPTION_KEY) or ""):
        record[RECORD_FULL_DESCRIPTION_KEY] = snapshot.get(RECORD_FULL_DESCRIPTION_KEY) or ""
    if not record.get(RECORD_FIT_CONFIDENCE_KEY):
        record[RECORD_FIT_CONFIDENCE_KEY] = snapshot.get(RECORD_FIT_CONFIDENCE_KEY) or ""
    if not record.get(RECORD_FIT_HIGHLIGHTS_KEY):
        record[RECORD_FIT_HIGHLIGHTS_KEY] = snapshot.get(RECORD_FIT_HIGHLIGHTS_KEY) or []
    if not record.get(RECORD_SOFT_RISK_REASONS_KEY):
        record[RECORD_SOFT_RISK_REASONS_KEY] = snapshot.get(RECORD_SOFT_RISK_REASONS_KEY) or []
    if not record.get(RECORD_MISSING_EVIDENCE_KEY):
        record[RECORD_MISSING_EVIDENCE_KEY] = snapshot.get(RECORD_MISSING_EVIDENCE_KEY) or []
    if not record.get(RECORD_COMPETITIVE_SIGNALS_KEY):
        record[RECORD_COMPETITIVE_SIGNALS_KEY] = snapshot.get(RECORD_COMPETITIVE_SIGNALS_KEY) or []
    if not record.get(RECORD_HARD_BLOCK_REASONS_KEY):
        record[RECORD_HARD_BLOCK_REASONS_KEY] = snapshot.get(RECORD_HARD_BLOCK_REASONS_KEY) or []
    if not compact_whitespace(record.get(RECORD_DETAILS_STATUS_KEY) or ""):
        record[RECORD_DETAILS_STATUS_KEY] = snapshot.get(RECORD_DETAILS_STATUS_KEY) or ""
    if not record.get(RECORD_DESCRIPTION_SOURCE_KEY):
        record[RECORD_DESCRIPTION_SOURCE_KEY] = snapshot.get(RECORD_DESCRIPTION_SOURCE_KEY) or ""

    record[RECORD_CONTENT_REASON_KEY] = snapshot.get(RECORD_CONTENT_REASON_KEY)
    record[RECORD_LLM_DECISION_KEY] = snapshot.get(RECORD_LLM_DECISION_KEY)
    record[RECORD_LLM_FIT_GRADE_KEY] = snapshot.get(RECORD_LLM_FIT_GRADE_KEY)
    record[RECORD_DECISION_KEY] = "KEEP"
    record[RECORD_DETAILS_LENGTH_KEY] = 0
    record[RECORD_REUSED_HISTORY_KEY] = True
    return record


def viewed_by_user(record: dict) -> bool:
    if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        return False
    return int(record.get(RECORD_TIMES_VIEWED_KEY, 0) or 0) > 0


def history_cluster_key_from_parts(source: Optional[str], company: Optional[str], title: Optional[str]) -> str:
    source_key = compact_whitespace(source or "").lower()
    company_key = re.sub(r"[^a-z0-9]+", " ", compact_whitespace(company or "").lower()).strip()
    title_key = re.sub(r"[^a-z0-9]+", " ", compact_whitespace(title or "").lower()).strip()
    if not source_key or not company_key or not title_key:
        return ""
    return f"{source_key}|{company_key}|{title_key}"


def history_cluster_key(record: dict) -> str:
    source = str(record.get(RECORD_SOURCE_KEY) or "").strip().lower()
    if not source:
        # Strictly extract source from the canonical job key if missing from record fields
        job_key = str(record.get(RECORD_JOB_KEY) or "")
        source = job_key.split(":", 1)[0] if ":" in job_key else ""
    if not source:
        return ""
    return history_cluster_key_from_parts(source, record.get(RECORD_COMPANY_KEY), record.get(RECORD_TITLE_KEY))


def build_history_sighting(record: dict, run_iso: str) -> dict:
    return {
        "seen_at": run_iso,
        RECORD_URL_KEY: str(record.get(RECORD_URL_KEY) or "").strip(),
        RECORD_POSTED_KEY: normalize_posted_text(record.get(RECORD_POSTED_KEY)),
        RECORD_POSTED_AGE_DAYS_KEY: record.get(RECORD_POSTED_AGE_DAYS_KEY),
        RECORD_COMPANY_KEY: str(record.get(RECORD_COMPANY_KEY) or "").strip(),
        RECORD_TITLE_KEY: str(record.get(RECORD_TITLE_KEY) or "").strip(),
        RECORD_SOURCE_KEY: str(record.get(RECORD_SOURCE_KEY) or "").strip().lower(),
    }


def build_history_cluster_index(history: Dict[str, dict]) -> Dict[str, dict]:
    clusters: Dict[str, dict] = {}
    for job_key, entry in history.items():
        if not isinstance(entry, dict):
            continue
        snapshot = entry.get(RECORD_LAST_KEPT_SNAPSHOT_KEY) if isinstance(entry.get(RECORD_LAST_KEPT_SNAPSHOT_KEY), dict) else {}
        source = snapshot.get(RECORD_SOURCE_KEY) or (str(job_key).split(":", 1)[0] if ":" in str(job_key) else "")
        if not source:
            continue
            
        company = snapshot.get(RECORD_COMPANY_KEY) or entry.get(RECORD_COMPANY_KEY)
        title = snapshot.get(RECORD_TITLE_KEY) or entry.get(RECORD_TITLE_KEY)
        cluster_key = history_cluster_key_from_parts(source, company, title)
        if not cluster_key:
            continue
        stats = clusters.setdefault(
            cluster_key,
            {
                "job_keys": set(),
                RECORD_TIMES_SEEN_KEY: 0,
                RECORD_FIRST_SEEN_AT_KEY: None,
                RECORD_LAST_SEEN_AT_KEY: None,
            },
        )
        stats["job_keys"].add(str(job_key))
        stats[RECORD_TIMES_SEEN_KEY] += int(entry.get(RECORD_TIMES_SEEN_KEY, 0) or 0)
        first_seen = parse_timestamp(entry.get("first_seen_at"))
        last_seen = parse_timestamp(entry.get("last_seen_at"))
        if first_seen and (stats["first_seen_at"] is None or first_seen < stats["first_seen_at"]):
            stats["first_seen_at"] = first_seen
        if last_seen and (stats["last_seen_at"] is None or last_seen > stats["last_seen_at"]):
            stats["last_seen_at"] = last_seen
    return clusters


def assess_history_warning_signals(record: dict, history_clusters: Optional[Dict[str, dict]] = None) -> List[str]:
    warnings: List[str] = []
    times_seen = int(record.get(RECORD_TIMES_SEEN_KEY, 0) or 0)
    first_seen = parse_timestamp(record.get(RECORD_FIRST_SEEN_AT_KEY))
    last_seen = parse_timestamp(record.get(RECORD_LAST_SEEN_AT_KEY))
    if first_seen and last_seen:
        span_days = max((last_seen.date() - first_seen.date()).days, 0)
        if times_seen >= REPEATED_LISTING_MIN_TIMES_SEEN and span_days >= REPEATED_LISTING_MIN_SPAN_DAYS:
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
            if listing_count >= MULTI_LISTING_RED_FLAG_MIN_LISTINGS and cluster_span_days >= MULTI_LISTING_RED_FLAG_MIN_SPAN_DAYS:
                warnings.append(
                    f"Potential red flag: the same title from the same poster has appeared across {listing_count} separate listings over {cluster_span_days} days"
                )
    return dedupe_preserve_order(warnings)


def update_job_history(history: Dict[str, dict], record: dict, run_iso: str) -> None:
    job_key = record.get(RECORD_JOB_KEY)
    if not job_key:
        record[RECORD_SEEN_BEFORE_KEY] = False
        record[RECORD_TIMES_KEPT_KEY] = 0
        record[RECORD_FIRST_KEPT_AT_KEY] = None
        return

    entry = history.get(job_key, {})
    prior_kept_count = int(entry.get(RECORD_TIMES_KEPT_KEY, 0) or 0)

    entry[RECORD_JOB_KEY] = job_key
    entry[RECORD_TITLE_KEY] = record.get(RECORD_TITLE_KEY)
    entry[RECORD_COMPANY_KEY] = record.get(RECORD_COMPANY_KEY)
    entry[RECORD_URL_KEY] = record.get(RECORD_URL_KEY)
    entry[RECORD_LAST_SEEN_AT_KEY] = run_iso
    entry[RECORD_TIMES_SEEN_KEY] = int(entry.get(RECORD_TIMES_SEEN_KEY, 0) or 0) + 1
    if not entry.get(RECORD_FIRST_SEEN_AT_KEY):
        entry[RECORD_FIRST_SEEN_AT_KEY] = run_iso

    record[RECORD_SEEN_BEFORE_KEY] = prior_kept_count > 0
    record[RECORD_TIMES_SEEN_KEY] = entry[RECORD_TIMES_SEEN_KEY]
    record[RECORD_TIMES_KEPT_KEY] = prior_kept_count
    record[RECORD_TIMES_VIEWED_KEY] = int(entry.get(RECORD_TIMES_VIEWED_KEY, 0) or 0)
    record[RECORD_FIRST_KEPT_AT_KEY] = entry.get(RECORD_FIRST_KEPT_AT_KEY)
    record[RECORD_FIRST_SEEN_AT_KEY] = entry.get(RECORD_FIRST_SEEN_AT_KEY)
    record[RECORD_LAST_SEEN_AT_KEY] = entry.get(RECORD_LAST_SEEN_AT_KEY)
    record[RECORD_FIRST_VIEWED_AT_KEY] = entry.get(RECORD_FIRST_VIEWED_AT_KEY)
    record[RECORD_LAST_VIEWED_AT_KEY] = entry.get(RECORD_LAST_VIEWED_AT_KEY)
    sightings = entry.get(RECORD_SIGHTINGS_KEY) if isinstance(entry.get(RECORD_SIGHTINGS_KEY), list) else []
    current_sighting = build_history_sighting(record, run_iso)
    if not sightings or sightings[-1] != current_sighting:
        sightings = [*sightings, current_sighting][-MAX_HISTORY_SIGHTINGS:]
    entry[RECORD_SIGHTINGS_KEY] = sightings
    record["history_sightings"] = sightings

    if record.get(RECORD_DECISION_KEY) == "KEEP":
        if not entry.get(RECORD_FIRST_KEPT_AT_KEY):
            entry[RECORD_FIRST_KEPT_AT_KEY] = run_iso
        entry[RECORD_LAST_KEPT_AT_KEY] = run_iso
        entry[RECORD_TIMES_KEPT_KEY] = prior_kept_count + 1
        entry[RECORD_LAST_KEPT_SNAPSHOT_KEY] = build_keep_snapshot(record)
        record[RECORD_TIMES_KEPT_KEY] = entry[RECORD_TIMES_KEPT_KEY]
        record[RECORD_FIRST_KEPT_AT_KEY] = entry[RECORD_FIRST_KEPT_AT_KEY]
        record[RECORD_LAST_KEPT_AT_KEY] = entry[RECORD_LAST_KEPT_AT_KEY]

    history[job_key] = entry


def finalize_record(history: Dict[str, dict], audit_rows: List[dict], record: dict, run_iso: str) -> None:
    update_job_history(history, record, run_iso)
    audit_rows.append(record)
