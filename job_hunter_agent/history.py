"""Helpers for history."""

import re
import sys
from datetime import datetime
from typing import Dict, List, Optional

from job_hunter_agent.company_normalization import normalize_company_name
from job_hunter_agent.global_settings import (
    get_multi_listing_red_flag_min_listings,
    get_multi_listing_red_flag_min_span_days,
    get_repeated_listing_min_span_days,
    get_repeated_listing_min_times_seen,
)
from job_hunter_agent.job_identity import RUN_IDENTITY_CLAIM_KEY
from job_hunter_agent.llm_review_state import has_complete_llm_keep_data
from job_hunter_agent.posting_utils import days_since, parse_timestamp
from job_hunter_agent.record_schema import (
    POSTING_CHANNEL_CLASSIFIER_VERSION,
    POSTING_CHANNEL_VERSION_KEY,
    RECORD_APPLY_METHOD_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_FIRST_LIKED_AT_KEY,
    RECORD_FIT_LABEL_KEY,
    RECORD_FIT_SCORE_BREAKDOWN_KEY,
    RECORD_FIT_SCORE_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FIT_TONE_CLASS_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_IS_LIKED_KEY,
    RECORD_IS_REPOSTED_KEY,
    RECORD_JOB_KEY,
    RECORD_LAST_LIKED_AT_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_ELAPSED_MS_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    RECORD_MARKET_MAP_IDENTITY_KEY,
    RECORD_MARKET_MAP_JOB_ID_KEY,
    RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY,
    RECORD_ORIGINAL_POSTED_DATE_KEY,
    RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_REQUIREMENT_COVERAGE_UNCLASSIFIED_KEY,
    RECORD_REQUIREMENT_COVERAGE_VERSION_KEY,
    RECORD_SOURCE_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_PROVENANCE_KEY,
    REQUIREMENT_COVERAGE_CONTRACT_VERSION,
    SOURCE_METADATA_SCHEMA_VERSION,
    SOURCE_METADATA_VERSION_KEY,
)
from job_hunter_agent.runtime_helpers import CLI_FLAG_RESET_NEW_TO_YOU
from job_hunter_agent.signal_detection import hard_block_reasons
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order

TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING = CLI_FLAG_RESET_NEW_TO_YOU in set(sys.argv[1:])


KEEP_SNAPSHOT_FIELDS = (
    RECORD_JOB_KEY,
    RECORD_SOURCE_KEY,
    "title",
    "company",
    "url",
    "posted",
    "posted_age_days",
    RECORD_ORIGINAL_POSTED_DATE_KEY,
    RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY,
    RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY,
    RECORD_IS_REPOSTED_KEY,
    "salary",
    "work_mode",
    "work_mode_source",
    "work_mode_evidence",
    "work_mode_needs_review",
    "location",
    "work_type",
    "teaser",
    "title_reason",
    "content_reason",
    "llm_decision",
    "llm_fit_grade",
    RECORD_LLM_ELAPSED_MS_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    "search_location",
    "search_keywords",
    "fit_source_text",
    RECORD_FIT_SCORE_KEY,
    RECORD_FIT_SCORE_BREAKDOWN_KEY,
    RECORD_FIT_LABEL_KEY,
    RECORD_FIT_TONE_CLASS_KEY,
    "full_description",
    "fit_confidence",
    "details_status",
    "description_source",
    "role_snapshot",
    "fit_highlights",
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY,
    RECORD_REQUIREMENT_COVERAGE_UNCLASSIFIED_KEY,
    RECORD_REQUIREMENT_COVERAGE_VERSION_KEY,
    "soft_risk_reasons",
    "missing_profile_support",
    "missing_clearance_support",
    "competitive_signals",
    "hard_block_reasons",
    "reviewed_signal_matches",
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_PROVENANCE_KEY,
    RECORD_MARKET_MAP_IDENTITY_KEY,
    RECORD_MARKET_MAP_JOB_ID_KEY,
)


def build_keep_snapshot(record: dict) -> dict:

    snapshot = {}

    for field in KEEP_SNAPSHOT_FIELDS:
        if field in record:
            snapshot[field] = record.get(field)

    return snapshot


# Raw detail-page evidence, distinct from KEEP_SNAPSHOT_FIELDS: a decision
# snapshot (used by can_reuse_kept_job) reuses a prior *decision*, while this
# reuses only the fetched *evidence* so a full review (deterministic filters +
# LLM) can still run against current profile/settings without reopening a
# browser page for a job whose detail page was already fetched recently.
DETAIL_EVIDENCE_FIELDS = (
    RECORD_DETAILS_TEXT_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_APPLY_METHOD_KEY,
)


def build_detail_evidence_snapshot(record: dict, run_iso: str) -> dict:
    snapshot = {field: record.get(field) for field in DETAIL_EVIDENCE_FIELDS}
    snapshot["raw_source_payload"] = record.get("_raw_source_payload")
    snapshot["fetched_at"] = run_iso
    return snapshot


def can_reuse_detail_evidence(history_entry: dict, max_age_days: int, run_iso: str) -> bool:
    """Whether a persisted detail-page fetch is fresh enough to reuse instead of
    reopening the browser. Only gates the *fetch*, not the decision: the caller
    still runs the full review pipeline against the reused evidence, so a
    profile/settings change can still change the outcome.
    """
    if not isinstance(history_entry, dict):
        return False
    evidence = history_entry.get("detail_evidence")
    if not isinstance(evidence, dict):
        return False
    if not str(evidence.get(RECORD_DETAILS_TEXT_KEY) or "").strip():
        return False
    reference = parse_timestamp(run_iso)
    if not reference:
        return False
    age_days = days_since(evidence.get("fetched_at"), reference)
    if age_days is None:
        return False
    return age_days <= max_age_days


def apply_detail_evidence_reuse(record: dict, history_entry: dict) -> dict:
    """Reuse fetched detail text without reviving obsolete source metadata."""
    evidence = history_entry.get("detail_evidence") or {}
    for field in DETAIL_EVIDENCE_FIELDS:
        if field == RECORD_SOURCE_METADATA_KEY:
            continue
        record[field] = evidence.get(field)

    cached_source_metadata = evidence.get(RECORD_SOURCE_METADATA_KEY)
    if (
        isinstance(cached_source_metadata, dict)
        and cached_source_metadata.get(SOURCE_METADATA_VERSION_KEY) == SOURCE_METADATA_SCHEMA_VERSION
    ):
        record[RECORD_SOURCE_METADATA_KEY] = cached_source_metadata

    record["_raw_source_payload"] = evidence.get("raw_source_payload")
    record["_raw_html"] = None
    return record


def can_reuse_kept_job(history_entry: dict, record: dict, profile: Optional[dict] = None) -> bool:
    """Reuse a kept snapshot only when fit and source classification are complete.

    Unclassified posting-channel state is re-reviewed rather than persisted forever.
    """

    if not isinstance(history_entry, dict):
        return False

    if int(history_entry.get("times_kept", 0) or 0) <= 0:
        return False

    snapshot = history_entry.get("last_kept_snapshot")

    if not isinstance(snapshot, dict):
        return False

    if not has_complete_llm_keep_data(snapshot):
        return False

    # Requirement coverage drives user-visible profile-learning actions. Reuse
    # only coverage produced under the current contract; otherwise a kept job
    # must receive a fresh fit review instead of preserving stale Add/No gates.
    if (
        snapshot.get(RECORD_REQUIREMENT_COVERAGE_VERSION_KEY)
        != REQUIREMENT_COVERAGE_CONTRACT_VERSION
    ):
        return False

    posting_channel = snapshot.get(RECORD_POSTING_CHANNEL_EVIDENCE_KEY)
    if not isinstance(posting_channel, dict):
        return False
    # Posting-channel output is derived data. Re-run the review whenever its
    # classifier contract changes so an old confident-but-wrong badge cannot live
    # forever in history just because the fit decision itself is reusable.
    if posting_channel.get(POSTING_CHANNEL_VERSION_KEY) != POSTING_CHANNEL_CLASSIFIER_VERSION:
        return False
    posting_channel_source = compact_whitespace(posting_channel.get("source") or "")
    if not posting_channel_source or posting_channel_source == "insufficient_evidence":
        return False

    source_metadata = snapshot.get(RECORD_SOURCE_METADATA_KEY)
    if not isinstance(source_metadata, dict):
        return False
    if source_metadata.get(SOURCE_METADATA_VERSION_KEY) != SOURCE_METADATA_SCHEMA_VERSION:
        return False

    if not record.get("job_key"):
        return False

    if hard_block_reasons(snapshot if isinstance(snapshot, dict) else {}, profile):
        return False

    return True


def apply_kept_job_reuse(record: dict, history_entry: dict) -> dict:

    snapshot = history_entry.get("last_kept_snapshot") if isinstance(history_entry, dict) else {}

    if not isinstance(snapshot, dict):
        snapshot = {}

    if record.get("posted") in {None, "", "N/A"}:
        record["posted"] = snapshot.get("posted") or "N/A"

    if record.get("posted_age_days") is None and snapshot.get("posted_age_days") is not None:
        record["posted_age_days"] = snapshot.get("posted_age_days")
    if not compact_whitespace(record.get(RECORD_ORIGINAL_POSTED_DATE_KEY) or ""):
        record[RECORD_ORIGINAL_POSTED_DATE_KEY] = snapshot.get(RECORD_ORIGINAL_POSTED_DATE_KEY) or ""
    if (
        record.get(RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY) is None
        and snapshot.get(RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY) is not None
    ):
        record[RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY] = snapshot.get(
            RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY
        )
    if not compact_whitespace(record.get(RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY) or ""):
        record[RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY] = (
            snapshot.get(RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY) or ""
        )
    if record.get(RECORD_IS_REPOSTED_KEY) is None and snapshot.get(RECORD_IS_REPOSTED_KEY) is not None:
        record[RECORD_IS_REPOSTED_KEY] = snapshot.get(RECORD_IS_REPOSTED_KEY)

    if record.get("salary") in {None, "", "N/A"}:
        record["salary"] = snapshot.get("salary") or "N/A"

    if record.get("teaser") in {None, "", "N/A"}:
        record["teaser"] = snapshot.get("teaser") or "N/A"

    if record.get("location") in {None, "", "N/A"}:
        record["location"] = snapshot.get("location") or "N/A"

    if record.get("work_mode") in {None, "", "N/A"}:
        record["work_mode"] = snapshot.get("work_mode") or "N/A"

    if record.get("work_type") in {None, "", "N/A"}:
        record["work_type"] = snapshot.get("work_type") or "N/A"

    if record.get("role_snapshot") in {None, "", "N/A"}:
        record["role_snapshot"] = snapshot.get("role_snapshot") or "N/A"

    if not compact_whitespace(record.get("fit_source_text") or ""):
        record["fit_source_text"] = snapshot.get("fit_source_text") or ""

    if not compact_whitespace(record.get("full_description") or ""):
        record["full_description"] = snapshot.get("full_description") or ""

    if not record.get("fit_confidence"):
        record["fit_confidence"] = snapshot.get("fit_confidence") or ""

    if not record.get("fit_highlights"):
        record["fit_highlights"] = snapshot.get("fit_highlights") or []

    if RECORD_FIT_SCORE_KEY in snapshot:
        record[RECORD_FIT_SCORE_KEY] = snapshot.get(RECORD_FIT_SCORE_KEY)

    if RECORD_FIT_SCORE_BREAKDOWN_KEY in snapshot:
        record[RECORD_FIT_SCORE_BREAKDOWN_KEY] = snapshot.get(RECORD_FIT_SCORE_BREAKDOWN_KEY) or []

    if RECORD_FIT_LABEL_KEY in snapshot:
        record[RECORD_FIT_LABEL_KEY] = snapshot.get(RECORD_FIT_LABEL_KEY) or ""

    if RECORD_FIT_TONE_CLASS_KEY in snapshot:
        record[RECORD_FIT_TONE_CLASS_KEY] = snapshot.get(RECORD_FIT_TONE_CLASS_KEY) or ""

    if not record.get(RECORD_LLM_ELAPSED_MS_KEY):
        record[RECORD_LLM_ELAPSED_MS_KEY] = snapshot.get(RECORD_LLM_ELAPSED_MS_KEY)

    if not record.get(RECORD_LLM_COST_USD_KEY):
        record[RECORD_LLM_COST_USD_KEY] = snapshot.get(RECORD_LLM_COST_USD_KEY)

    if not record.get(RECORD_LLM_INPUT_TOKENS_KEY):
        record[RECORD_LLM_INPUT_TOKENS_KEY] = snapshot.get(RECORD_LLM_INPUT_TOKENS_KEY)

    if not record.get(RECORD_LLM_OUTPUT_TOKENS_KEY):
        record[RECORD_LLM_OUTPUT_TOKENS_KEY] = snapshot.get(RECORD_LLM_OUTPUT_TOKENS_KEY)

    if not record.get("soft_risk_reasons"):
        record["soft_risk_reasons"] = snapshot.get("soft_risk_reasons") or []

    if not record.get("missing_profile_support"):
        record["missing_profile_support"] = snapshot.get("missing_profile_support") or []

    if not record.get("missing_clearance_support"):
        record["missing_clearance_support"] = snapshot.get("missing_clearance_support") or []

    if not record.get("competitive_signals"):
        record["competitive_signals"] = snapshot.get("competitive_signals") or []

    if not record.get("hard_block_reasons"):
        record["hard_block_reasons"] = snapshot.get("hard_block_reasons") or []

    if not record.get(RECORD_REQUIREMENT_COVERAGE_KEY):
        record[RECORD_REQUIREMENT_COVERAGE_KEY] = (
            snapshot.get(RECORD_REQUIREMENT_COVERAGE_KEY) or []
        )

    if not record.get(RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY):
        record[RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY] = (
            snapshot.get(RECORD_REQUIREMENT_COVERAGE_BEHAVIOURAL_KEY) or []
        )

    if not record.get(RECORD_REQUIREMENT_COVERAGE_UNCLASSIFIED_KEY):
        record[RECORD_REQUIREMENT_COVERAGE_UNCLASSIFIED_KEY] = (
            snapshot.get(RECORD_REQUIREMENT_COVERAGE_UNCLASSIFIED_KEY) or []
        )

    if not record.get(RECORD_POSTING_CHANNEL_EVIDENCE_KEY):
        record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] = (
            snapshot.get(RECORD_POSTING_CHANNEL_EVIDENCE_KEY) or {}
        )

    if not record.get(RECORD_SOURCE_METADATA_KEY):
        record[RECORD_SOURCE_METADATA_KEY] = snapshot.get(RECORD_SOURCE_METADATA_KEY) or {}

    if not record.get("reviewed_signal_matches"):
        record["reviewed_signal_matches"] = snapshot.get("reviewed_signal_matches") or []

    if not compact_whitespace(record.get("details_status") or ""):
        record["details_status"] = snapshot.get("details_status") or ""

    if not record.get("description_source"):
        record["description_source"] = snapshot.get("description_source") or ""

    record["content_reason"] = snapshot.get("content_reason")

    record["llm_decision"] = snapshot.get("llm_decision")

    record["llm_fit_grade"] = snapshot.get("llm_fit_grade")

    record["decision"] = "KEEP"

    record["details_length"] = 0

    record["reused_history"] = True

    return record


def viewed_by_user(record: dict) -> bool:

    if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        return False

    return int(record.get("times_viewed", 0) or 0) > 0


def is_new_to_you(record: dict, latest_run_started_at: Optional[datetime]) -> bool:
    """Return whether the vacancy was first discovered in the latest run.

    Newness is discovery history, not read/unread state. Viewing a card must not
    rewrite whether Job Hunter had already seen the vacancy before this run.
    Without a valid latest-run boundary we fail closed instead of guessing.
    """
    if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING:
        return True
    if latest_run_started_at is None:
        return False
    first_seen_at = parse_timestamp(record.get("first_seen_at"))
    return bool(first_seen_at and first_seen_at >= latest_run_started_at)


def history_cluster_key_from_parts(
    source: Optional[str], company: Optional[str], title: Optional[str]
) -> str:

    source_key = compact_whitespace(source or "").lower()

    company_key = re.sub(r"[^a-z0-9]+", " ", normalize_company_name(company or "")).strip()

    title_key = re.sub(r"[^a-z0-9]+", " ", compact_whitespace(title or "").lower()).strip()

    if not source_key or not company_key or not title_key:
        return ""

    return f"{source_key}|{company_key}|{title_key}"


def history_cluster_key(record: dict) -> str:

    source = str(record.get("source") or "").strip().lower()

    if not source:
        # Strictly extract source from the canonical job key if missing from record fields

        job_key = str(record.get("job_key") or "")

        source = job_key.split(":", 1)[0] if ":" in job_key else ""

    if not source:
        return ""

    return history_cluster_key_from_parts(source, record.get("company"), record.get("title"))


def build_history_cluster_index(history: Dict[str, dict]) -> Dict[str, dict]:

    clusters: Dict[str, dict] = {}

    for job_key, entry in history.items():
        if not isinstance(entry, dict):
            continue

        snapshot = (
            entry.get("last_kept_snapshot")
            if isinstance(entry.get("last_kept_snapshot"), dict)
            else {}
        )

        source = snapshot.get("source") or (
            str(job_key).split(":", 1)[0] if ":" in str(job_key) else ""
        )

        if not source:
            continue

        company = snapshot.get("company") or entry.get("company")

        title = snapshot.get("title") or entry.get("title")

        cluster_key = history_cluster_key_from_parts(source, company, title)

        if not cluster_key:
            continue

        stats = clusters.setdefault(
            cluster_key,
            {
                "job_keys": set(),
                "times_seen": 0,
                "first_seen_at": None,
                "last_seen_at": None,
            },
        )

        stats["job_keys"].add(str(job_key))

        stats["times_seen"] += int(entry.get("times_seen", 0) or 0)

        first_seen = parse_timestamp(entry.get("first_seen_at"))

        last_seen = parse_timestamp(entry.get("last_seen_at"))

        if first_seen and (stats["first_seen_at"] is None or first_seen < stats["first_seen_at"]):
            stats["first_seen_at"] = first_seen

        if last_seen and (stats["last_seen_at"] is None or last_seen > stats["last_seen_at"]):
            stats["last_seen_at"] = last_seen

    return clusters


def assess_history_warning_signals(
    record: dict, history_clusters: Optional[Dict[str, dict]] = None
) -> List[str]:

    warnings: List[str] = []

    times_seen = int(record.get("times_seen", 0) or 0)

    first_seen = parse_timestamp(record.get("first_seen_at"))

    last_seen = parse_timestamp(record.get("last_seen_at"))

    if first_seen and last_seen:
        span_days = max((last_seen.date() - first_seen.date()).days, 0)

        if (
            times_seen >= get_repeated_listing_min_times_seen()
            and span_days >= get_repeated_listing_min_span_days()
        ):
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

            if (
                listing_count >= get_multi_listing_red_flag_min_listings()
                and cluster_span_days >= get_multi_listing_red_flag_min_span_days()
            ):
                warnings.append(
                    f"Potential red flag: the same title from the same poster has appeared across {listing_count} separate listings over {cluster_span_days} days"
                )

    return dedupe_preserve_order(warnings)


def update_job_history(history: Dict[str, dict], record: dict, run_iso: str) -> None:

    job_key = record.get("job_key")

    if not job_key:
        record["seen_before"] = False

        record["times_kept"] = 0

        record["first_kept_at"] = None

        return

    entry = history.get(job_key, {})

    prior_kept_count = int(entry.get("times_kept", 0) or 0)

    entry["job_key"] = job_key

    entry["title"] = record.get("title")

    entry["company"] = record.get("company")

    entry["url"] = record.get("url")

    entry["last_seen_at"] = run_iso

    entry["times_seen"] = int(entry.get("times_seen", 0) or 0) + 1

    if not entry.get("first_seen_at"):
        entry["first_seen_at"] = run_iso

    record["seen_before"] = prior_kept_count > 0

    record["times_seen"] = entry["times_seen"]

    record["times_kept"] = prior_kept_count

    record["times_viewed"] = int(entry.get("times_viewed", 0) or 0)

    record["first_kept_at"] = entry.get("first_kept_at")

    record["first_seen_at"] = entry.get("first_seen_at")

    record["last_seen_at"] = entry.get("last_seen_at")

    record["first_viewed_at"] = entry.get("first_viewed_at")

    record["last_viewed_at"] = entry.get("last_viewed_at")

    # Liked is a durable user decision, so carry its canonical history state
    # onto every freshly reviewed record for the workspace renderer.
    record[RECORD_IS_LIKED_KEY] = bool(entry.get(RECORD_IS_LIKED_KEY, False))
    record[RECORD_FIRST_LIKED_AT_KEY] = entry.get(RECORD_FIRST_LIKED_AT_KEY)
    record[RECORD_LAST_LIKED_AT_KEY] = entry.get(RECORD_LAST_LIKED_AT_KEY)

    if record.get("decision") == "KEEP":
        if not entry.get("first_kept_at"):
            entry["first_kept_at"] = run_iso

        entry["last_kept_at"] = run_iso

        entry["times_kept"] = prior_kept_count + 1

        entry["last_kept_snapshot"] = build_keep_snapshot(record)

        record["times_kept"] = entry["times_kept"]

        record["first_kept_at"] = entry["first_kept_at"]

        record["last_kept_at"] = entry["last_kept_at"]

    history[job_key] = entry


def finalize_record(
    history: Dict[str, dict],
    audit_rows: List[dict],
    record: dict,
    run_iso: str,
    *,
    persist_full_description: bool = True,
) -> None:
    claim = record.pop(RUN_IDENTITY_CLAIM_KEY, None)
    persisted_record = record
    if not persist_full_description:
        persisted_record = dict(record)
        for field in (
            RECORD_FULL_DESCRIPTION_KEY,
            RECORD_DETAILS_TEXT_KEY,
            RECORD_FIT_SOURCE_TEXT_KEY,
            "description_compaction",
        ):
            persisted_record.pop(field, None)
    try:
        update_job_history(history, persisted_record, run_iso)
        audit_rows.append(persisted_record)
    except Exception:
        if isinstance(claim, tuple) and len(claim) == 2:
            registry, token = claim
            registry.release(token)
        raise
    if isinstance(claim, tuple) and len(claim) == 2:
        registry, token = claim
        registry.finish(token, persisted_record)
