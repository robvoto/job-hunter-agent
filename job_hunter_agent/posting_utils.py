"""Utilities for processing and formatting job posting timestamps and age.

This module provides functions for parsing date strings, calculating the
number of days since a post was created, and generating human-readable
relative and absolute date labels for display on job cards. It centralises
date logic to ensure consistent timing and age signals across the workspace.
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import Optional, Set

from job_hunter_agent.global_settings import get_posted_age_badge_threshold_days
from job_hunter_agent.io_utils import normalize_posted_text
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EXTERNAL_APPLY,
    ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED,
    ORIGINAL_POSTED_DATE_STATUS_VERIFIED,
    RECORD_APPLY_METHOD_KEY,
    RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY,
    RECORD_ORIGINAL_POSTED_DATE_KEY,
    RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY,
)
from job_hunter_agent.text_processing import compact_whitespace

logger = logging.getLogger(__name__)

_TIMESTAMP_INPUT_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
)


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        for input_format in _TIMESTAMP_INPUT_FORMATS:
            try:
                return datetime.strptime(value, input_format)
            except (TypeError, ValueError):
                continue
    logger.warning("Failed to parse timestamp %s", value)
    return None


def days_since(value: Optional[str], reference: datetime) -> Optional[int]:
    timestamp = parse_timestamp(value)
    if not timestamp:
        return None
    try:
        return max((reference - timestamp).days, 0)
    except Exception as exc:
        logger.warning("Failed to calculate days_since: %s", exc)
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


def format_timestamp_label(value: Optional[str], *, include_time: bool = True) -> str:
    if not value:
        return "N/A"
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return value
    if not include_time:
        return f"{timestamp.day} {timestamp.strftime('%b %Y')}"
    return timestamp.strftime("%d %b %Y %I:%M %p")


def posted_datetime_from_age(
    posted_age_days: Optional[float], reference_time: Optional[datetime]
) -> Optional[datetime]:
    if posted_age_days is None or reference_time is None:
        return None
    try:
        return reference_time - timedelta(days=float(posted_age_days))
    except Exception as exc:
        logger.warning("Failed to calculate posted_datetime_from_age: %s", exc)
        return None


def parse_visible_posted_age_days(
    value: Optional[str], run_date: Optional[date] = None
) -> Optional[float]:
    text = compact_whitespace(normalize_posted_text(value)).lower()
    if not text or text == "n/a":
        return None

    if re.search(r"\b(today|just now)\b", text):
        return 0.0
    if re.search(r"\byesterday\b", text):
        return 1.0

    relative_match = re.search(
        r"\b(?:(?:posted|advertised|published)\s+(?:on\s+)?)?"
        r"(?P<amount>\d+)\s+"
        r"(?P<unit>minute|hour|day|week|month|year)s?\s+ago\b",
        text,
    )
    if relative_match:
        amount = float(relative_match.group("amount"))
        unit = relative_match.group("unit")
        multipliers = {
            "minute": 1 / 1440,
            "hour": 1 / 24,
            "day": 1.0,
            "week": 7.0,
            "month": 30.0,
            "year": 365.0,
        }
        return amount * multipliers[unit]

    if run_date is None:
        return None

    absolute_candidates = [
        r"\b(?:posted|advertised|published)?\s*(?:on\s+)?(?P<date>\d{4}-\d{2}-\d{2})\b",
        r"\b(?:posted|advertised|published)?\s*(?:on\s+)?(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4})\b",
        r"\b(?:posted|advertised|published)?\s*(?:on\s+)?(?P<date>[A-Za-z]+\s+\d{1,2},?\s+\d{4})\b",
    ]
    for pattern in absolute_candidates:
        match = re.search(pattern, text)
        if not match:
            continue
        raw_date = compact_whitespace(match.group("date"))
        for fmt in (
            "%Y-%m-%d",
            "%d %B %Y",
            "%d %b %Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%d %B, %Y",
            "%d %b, %Y",
        ):
            try:
                parsed = datetime.strptime(raw_date, fmt).date()
            except ValueError:
                continue
            return float(max((run_date - parsed).days, 0))

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
        logger.warning("Failed to format posted date label: %s", exc)
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
        logger.warning("Failed to calculate relative age label: %s", exc)
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
    posted_date_label = format_posted_date_label(
        posted_text,
        posted_age_days,
        reference_time,
    )
    if posted_age_days is not None and posted_date_label != "Unknown":
        return posted_date_label
    if posted_text in ("N/A", "") and posted_date_label != "Unknown":
        return posted_date_label
    return posted_text


def board_posted_display_label(record: dict, now: Optional[datetime] = None) -> str:
    posted_text = normalize_posted_text(record.get("posted"))
    if posted_text not in ("", "N/A"):
        return posted_text
    return posted_display_label(record, now=now)


def original_posted_display_label(record: dict) -> str:
    if str(record.get(RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY) or "").strip().lower() != (
        ORIGINAL_POSTED_DATE_STATUS_VERIFIED
    ):
        return ""
    raw_date = compact_whitespace(record.get(RECORD_ORIGINAL_POSTED_DATE_KEY))
    if raw_date:
        try:
            return date.fromisoformat(raw_date).strftime("%d %b %Y")
        except ValueError:
            pass

    original_age_days = record.get(RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY)
    reference_time = posted_reference_time(record)
    return format_posted_date_label("", original_age_days, reference_time)


def original_posted_is_unverified(record: dict) -> bool:
    return (
        str(record.get(RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY) or "").strip().lower()
        == ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED
    )


def linkedin_freshness_is_unknown(record: dict) -> bool:
    return (
        str(record.get("source") or "").strip().lower() == "linkedin"
        and record.get("posted_age_days") is None
    )


def linkedin_original_posted_is_unverified(record: dict) -> bool:
    return (
        str(record.get("source") or "").strip().lower() == "linkedin"
        and str(record.get(RECORD_APPLY_METHOD_KEY) or "").strip().lower()
        == APPLY_METHOD_EXTERNAL_APPLY
        and str(record.get(RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY) or "").strip().lower()
        != ORIGINAL_POSTED_DATE_STATUS_VERIFIED
    )


def current_posted_age_days(record: dict, now: Optional[datetime] = None) -> Optional[float]:
    posted_age_days = record.get("posted_age_days")
    if posted_age_days is None:
        return None
    try:
        raw_age_days = float(posted_age_days)
    except Exception as exc:
        logger.warning("Failed to parse posted_age_days %s: %s", posted_age_days, exc)
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
        logger.warning("Failed to calculate current_posted_age_days: %s", exc)
        return max(raw_age_days, 0.0)
    return max(age_seconds / 86400, 0.0)


def posted_age_badge_threshold(
    record: dict,
    *,
    thresholds: Optional[tuple[int, ...]] = None,
    now: Optional[datetime] = None,
) -> Optional[int]:
    age_days = current_posted_age_days(record, now=now)
    if age_days is None:
        return None
    configured = thresholds or get_posted_age_badge_threshold_days()
    matched = [int(value) for value in configured if age_days >= float(value)]
    if not matched:
        return None
    return max(matched)
