"""Utilities for processing and formatting job posting timestamps and age.

This module provides functions for parsing date strings, calculating the
number of days since a post was created, and generating human-readable
relative and absolute date labels for display on job cards. It centralises
date logic to ensure consistent timing and age signals across the workspace.
"""

import re
from datetime import datetime, timedelta
from typing import Optional, Set

from job_hunter_agent.io_utils import normalize_posted_text
from job_hunter_agent.job_identity import normalize_job_key


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception as exc:
        print(f"[POSTING_UTILS][WARN] Failed to parse timestamp {value}: {exc}")
        return None


def days_since(value: Optional[str], reference: datetime) -> Optional[int]:
    timestamp = parse_timestamp(value)
    if not timestamp:
        return None
    try:
        return max((reference - timestamp).days, 0)
    except Exception as exc:
        print(f"[POSTING_UTILS][WARN] Failed to calculate days_since: {exc}")
        return None


def get_manual_skip_sets(profile: dict) -> tuple[Set[str], Set[str]]:
    review_controls = profile.get("review_controls", {})
    applied = {
        normalize_job_key(value)
        for value in review_controls.get("applied_job_keys", [])
        if normalize_job_key(value)
    }
    hidden = {
        normalize_job_key(value)
        for value in review_controls.get("hidden_job_keys", [])
        if normalize_job_key(value)
    }
    return applied, hidden


def format_timestamp_label(value: Optional[str]) -> str:
    if not value:
        return "N/A"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y %I:%M %p")
    except Exception as exc:
        print(f"[POSTING_UTILS][WARN] Failed to format timestamp {value}: {exc}")
        return value


def posted_datetime_from_age(
    posted_age_days: Optional[float], reference_time: Optional[datetime]
) -> Optional[datetime]:
    if posted_age_days is None or reference_time is None:
        return None
    try:
        return reference_time - timedelta(days=float(posted_age_days))
    except Exception as exc:
        print(f"[POSTING_UTILS][WARN] Failed to calculate posted_datetime_from_age: {exc}")
        return None


def format_posted_date_label(
    posted_text: Optional[str], posted_age_days: Optional[float], reference_time: Optional[datetime]
) -> str:
    normalized_posted = normalize_posted_text(posted_text)
    if normalized_posted.lower() == "today" and reference_time is None:
        return "Today"
    posted_at = posted_datetime_from_age(posted_age_days, reference_time)
    if posted_at is None:
        return "Unknown"
    try:
        return posted_at.strftime("%d %b %Y")
    except Exception as exc:
        print(f"[POSTING_UTILS][WARN] Failed to format posted date label: {exc}")
        return "Unknown"


def relative_posted_age_label(posted_at: Optional[datetime], now: Optional[datetime] = None) -> str:
    if posted_at is None:
        return ""
    current = now or datetime.now().astimezone()
    try:
        local_posted = (
            posted_at.astimezone(current.tzinfo)
            if posted_at.tzinfo and current.tzinfo
            else posted_at
        )
        days_old = max((current.date() - local_posted.date()).days, 0)
    except Exception as exc:
        print(f"[POSTING_UTILS][WARN] Failed to calculate relative age label: {exc}")
        return ""
    if days_old == 0:
        return "today"
    if days_old == 1:
        return "yesterday"
    return f"{days_old} days ago"


def posted_reference_time(record: dict) -> Optional[datetime]:
    for key in ("run_started_at", "last_seen_at", "last_kept_at", "first_seen_at"):
        timestamp = parse_timestamp(record.get(key))
        if timestamp:
            return timestamp
    return None


def is_relative_posted_text(value: Optional[str]) -> bool:
    text = normalize_posted_text(value).lower()
    if text in {"today", "yesterday"}:
        return True
    return re.fullmatch(r"\d+\s*[mhdy](?:\s*ago)?", text) is not None


def posted_display_label(record: dict, now: Optional[datetime] = None) -> str:
    posted_text = normalize_posted_text(record.get("posted"))
    posted_age_days = record.get("posted_age_days")
    reference_time = posted_reference_time(record)
    posted_at = posted_datetime_from_age(posted_age_days, reference_time)
    relative_label = relative_posted_age_label(posted_at, now) if posted_at else ""
    posted_date_label = format_posted_date_label(
        posted_text,
        posted_age_days,
        reference_time,
    )

    if (
        posted_date_label != "Unknown"
        and posted_age_days is not None
        and is_relative_posted_text(posted_text)
    ):
        return f"{posted_date_label} ({relative_label})" if relative_label else posted_date_label
    if posted_age_days is not None and posted_age_days >= 1 and posted_text not in ("N/A", ""):
        if posted_date_label != "Unknown" and posted_date_label != posted_text:
            if relative_label:
                return f"{posted_date_label} ({relative_label})"
            return posted_date_label
    if posted_text in ("N/A", "") and posted_date_label != "Unknown":
        return f"{posted_date_label} ({relative_label})" if relative_label else posted_date_label
    return posted_text


def current_posted_age_days(record: dict, now: Optional[datetime] = None) -> Optional[float]:
    posted_age_days = record.get("posted_age_days")
    if posted_age_days is None:
        return None
    try:
        raw_age_days = float(posted_age_days)
    except Exception as exc:
        print(f"[POSTING_UTILS][WARN] Failed to parse posted_age_days {posted_age_days}: {exc}")
        return None

    reference_time = posted_reference_time(record)
    if reference_time is None:
        return max(raw_age_days, 0.0)

    posted_at = posted_datetime_from_age(raw_age_days, reference_time)
    if posted_at is None:
        return max(raw_age_days, 0.0)

    current = now or datetime.now().astimezone()
    try:
        age_seconds = (current - posted_at).total_seconds()
    except Exception as exc:
        print(f"[POSTING_UTILS][WARN] Failed to calculate current_posted_age_days: {exc}")
        return max(raw_age_days, 0.0)
    return max(age_seconds / 86400, 0.0)
