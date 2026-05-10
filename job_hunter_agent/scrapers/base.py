"""Shared base class and helpers for all job source connectors."""

import json
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Optional, Set
from urllib.parse import urlparse

from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_COMPETITIVE_SIGNALS_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_DECISION_KEY,
    RECORD_DETAILS_LENGTH_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_FIT_HIGHLIGHTS_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LOCATION_KEY,
    RECORD_MISSING_EVIDENCE_KEY,
    RECORD_PAGE_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_POSTED_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_SALARY_KEY,
    RECORD_SEARCH_KEYWORDS_KEY,
    RECORD_SEARCH_CLASSIFICATIONS_KEY,
    RECORD_SEARCH_LOCATION_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOFT_RISK_REASONS_KEY,
    RECORD_SOURCE_KEY,
    RECORD_RUN_STARTED_AT_KEY,
    RECORD_ROLE_SNAPSHOT_KEY,
    RECORD_TITLE_MATCH_METADATA_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_TEASER_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_MODE_SOURCE_KEY,
    RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    RECORD_WORK_TYPE_KEY,
)
from job_hunter_agent.work_mode_extraction import extract_from_linkedin
from job_hunter_agent.salary import (
    KEY_CURRENCIES_WITH_DOLLAR,
    KEY_INTERVAL_DIVISOR,
    KEY_INTERVAL_SUFFIX,
)

JOBSPY_DATE_POSTED_KEY = "date_posted"
JOBSPY_MIN_AMOUNT_KEY = "min_amount"
JOBSPY_MAX_AMOUNT_KEY = "max_amount"
JOBSPY_INTERVAL_KEY = "interval"
JOBSPY_CURRENCY_KEY = "currency"
JOBSPY_JOB_TYPE_KEY = "job_type"
JOBSPY_DESCRIPTION_KEY = "description"
JOBSPY_ID_KEY = "id"
JOBSPY_TITLE_KEY = "title"
JOBSPY_COMPANY_KEY = "company"
JOBSPY_LOCATION_KEY = "location"
JOBSPY_JOB_URL_KEY = "job_url"

def keywords_to_search_string(keywords: str) -> str:
    """Convert comma-separated keywords stored in profile to a boolean OR search string.

    "Senior Business Analyst, Scrum Master" -> "Senior Business Analyst OR Scrum Master"
    Already-OR-joined strings are returned unchanged.
    """
    raw = str(keywords or "").strip()
    if not raw:
        return raw
    parts = [p.strip() for p in re.split(r",\s*", raw) if p.strip()]
    if len(parts) <= 1:
        return raw
    return " OR ".join(parts)


def blank_source_metadata(source: str) -> dict:
    return {
        "platform": source,
        "apply_url": "",
        "apply_domain": "",
        "company_profile_url": "",
        "company_profile_name": "",
        "poster_company": "",
        "hiring_company": "",
        "ats_source": "",
        "raw_source_fields": {},
    }


def blank_posting_channel_evidence() -> dict:
    return {
        "trusted_metadata": [],
        "weak_text_matches": [],
        "needs_review": False,
    }


class BaseJobScraper(ABC):
    """Abstract base for all job source connectors."""

    source_name: str = "unknown"

    def __init__(
        self,
        profile: dict,
        llm_cache: dict,
        job_history: dict,
        applied_job_keys: Set[str],
        hidden_job_keys: Set[str],
        run_iso: str,
    ):
        self.profile = profile
        self.llm_cache = llm_cache
        self.job_history = job_history
        self.applied_job_keys = applied_job_keys
        self.hidden_job_keys = hidden_job_keys
        self.run_iso = run_iso

    @abstractmethod
    def scrape(self) -> tuple:
        """Run the scraper.

        Returns:
            (kept_records, audit_rows, skill_observations) - three lists of dicts.
        """
        ...

def _safe_row_dict(row: Any) -> dict:
    if hasattr(row, "to_dict"):
        try:
            payload = row.to_dict()
            if isinstance(payload, dict):
                return dict(payload)
        except Exception:
            pass
    if hasattr(row, "items"):
        try:
            return {str(key): value for key, value in row.items()}
        except Exception:
            pass
    return dict(getattr(row, "__dict__", {}) or {})


def _url_domain(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    return parsed.netloc.lower().strip() if parsed.netloc else ""


def _json_safe_value(value: Any):
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def normalize_jobspy_record(
    row: Any,
    source: str,
    search_keywords: str,
    search_location: str,
    run_iso: str,
    salary_rules: dict,
    job_type_rules: dict,
) -> dict:
    """Map a python-jobspy DataFrame row to the project's normalized record shape."""
    try:
        import pandas as pd  # noqa: F401 - only used for pd.isna
        _pd = pd
    except ImportError:
        _pd = None

    def _safe_str(val, default: str = "") -> str:
        if _pd is not None:
            try:
                if _pd.isna(val):
                    return default
            except Exception:
                pass
        if val is None:
            return default
        return str(val).strip() or default

    def _safe_float(val) -> Optional[float]:
        if _pd is not None:
            try:
                if _pd.isna(val):
                    return None
            except Exception:
                pass
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    def _get(attr: str):
        if hasattr(row, "get"):
            return row.get(attr)
        return getattr(row, attr, None)

    def _first_non_empty(*values: Any) -> str:
        for value in values:
            text = _safe_str(value)
            if text:
                return text
        return ""

    # Posted date -> age in days
    raw_date = _get(JOBSPY_DATE_POSTED_KEY)
    posted_age_days: Optional[float] = None
    posted_text = ""
    try:
        if raw_date is not None:
            if isinstance(raw_date, str):
                raw_date = date.fromisoformat(raw_date)
            elif isinstance(raw_date, datetime):
                raw_date = raw_date.date()
            if isinstance(raw_date, date):
                today = datetime.fromisoformat(run_iso).date()
                delta = (today - raw_date).days
                posted_age_days = float(max(delta, 0))
                posted_text = "today" if delta == 0 else f"{delta}d ago"
    except Exception:
        pass

    # Salary
    min_amt = _safe_float(_get(JOBSPY_MIN_AMOUNT_KEY))
    max_amt = _safe_float(_get(JOBSPY_MAX_AMOUNT_KEY))
    interval_raw = _safe_str(_get(JOBSPY_INTERVAL_KEY), "")
    currency_raw = _safe_str(_get(JOBSPY_CURRENCY_KEY), "")
    salary_str = _build_salary_string(min_amt,
        max_amt,
        interval_raw,
        currency_raw,
        salary_rules,
    )
    # Work mode — metadata-first from structured jobspy fields.
    # Text fallback happens later in the scraper once the description is available.
    wm = extract_from_linkedin(_json_safe_value(_safe_row_dict(row)))

    # Work type
    work_type = _map_job_type(
        _safe_str(_get(JOBSPY_JOB_TYPE_KEY), ""),
        job_type_rules,
    )

    # Description
    description = _safe_str(_get(JOBSPY_DESCRIPTION_KEY), "")
    # Stable job key (namespaced)
    raw_id = _safe_str(_get(JOBSPY_ID_KEY), "")
    job_key = normalize_job_key(raw_id, source=source) if raw_id else None
    apply_url = _first_non_empty(_get("job_url_direct"), _get(JOBSPY_JOB_URL_KEY))
    company_profile_url = _first_non_empty(_get("company_url_direct"), _get("company_url"))
    company_profile_name = _first_non_empty(_get("company_name"), _get(JOBSPY_COMPANY_KEY))
    source_metadata = blank_source_metadata(source)
    source_metadata.update(
        {
            "apply_url": apply_url,
            "apply_domain": _url_domain(apply_url),
            "company_profile_url": company_profile_url,
            "company_profile_name": company_profile_name,
            "poster_company": company_profile_name,
            "hiring_company": company_profile_name,
            "ats_source": _url_domain(apply_url),
            "raw_source_fields": _json_safe_value(_safe_row_dict(row)),
        }
    )
    return {
        RECORD_RUN_STARTED_AT_KEY: run_iso,
        RECORD_SEARCH_LOCATION_KEY: search_location,
        RECORD_SEARCH_KEYWORDS_KEY: search_keywords,
        RECORD_SEARCH_CLASSIFICATIONS_KEY: "",
        RECORD_PAGE_KEY: 1,
        RECORD_SOURCE_KEY: source,
        RECORD_JOB_KEY: job_key,
        RECORD_TITLE_KEY: _safe_str(_get(JOBSPY_TITLE_KEY)),
        RECORD_COMPANY_KEY: _safe_str(_get(JOBSPY_COMPANY_KEY)),
        RECORD_LOCATION_KEY: _safe_str(_get(JOBSPY_LOCATION_KEY)),
        RECORD_POSTED_KEY: posted_text,
        RECORD_POSTED_AGE_DAYS_KEY: posted_age_days,
        RECORD_WORK_MODE_KEY: wm["work_mode"],
        RECORD_WORK_MODE_SOURCE_KEY: wm["work_mode_source"],
        RECORD_WORK_MODE_EVIDENCE_KEY: wm["work_mode_evidence"],
        RECORD_WORK_MODE_NEEDS_REVIEW_KEY: wm["work_mode_needs_review"],
        RECORD_WORK_TYPE_KEY: work_type,
        RECORD_SALARY_KEY: salary_str,
        RECORD_URL_KEY: _safe_str(_get(JOBSPY_JOB_URL_KEY)),
        RECORD_TEASER_KEY: description[:240].strip(),
        RECORD_DETAILS_TEXT_KEY: description,
        RECORD_DETAILS_LENGTH_KEY: len(description),
        RECORD_DECISION_KEY: None,
        RECORD_REJECT_REASON_KEY: None,
        RECORD_TITLE_REASON_KEY: None,
        RECORD_TITLE_MATCH_METADATA_KEY: {},
        RECORD_CONTENT_REASON_KEY: None,
        RECORD_LLM_DECISION_KEY: None,
        RECORD_LLM_FIT_GRADE_KEY: None,
        RECORD_ROLE_SNAPSHOT_KEY: "",
        RECORD_FIT_HIGHLIGHTS_KEY: [],
        RECORD_COMPETITIVE_SIGNALS_KEY: [],
        RECORD_SOFT_RISK_REASONS_KEY: [],
        RECORD_MISSING_EVIDENCE_KEY: [],
        RECORD_REVIEWED_SIGNAL_MATCHES_KEY: {
            "matched": [],
            "evidence_only": [],
            "ignored": [],
            "unresolved": [],
        },
        RECORD_SOURCE_METADATA_KEY: source_metadata,
        RECORD_POSTING_CHANNEL_EVIDENCE_KEY: blank_posting_channel_evidence(),
    }


def _build_salary_string(
    min_amt: Optional[float],
    max_amt: Optional[float],
    interval: str,
    currency: str,
    rules: dict,
) -> str:
    """
    Format salary information using externally supplied salary rules.

    This function contains no hard-coded salary knowledge.
    All formatting behaviour is driven by the provided rules dictionary.
    """

    if min_amt is None and max_amt is None:
        return ""

    interval_suffix = rules[KEY_INTERVAL_SUFFIX]
    interval_divisor = rules[KEY_INTERVAL_DIVISOR]
    currencies_with_dollar = set(rules[KEY_CURRENCIES_WITH_DOLLAR])

    prefix = "$" if currency in currencies_with_dollar else (f"{currency} " if currency else "")
    normalized_interval = interval.lower()

    divisor = interval_divisor.get(normalized_interval, 1)
    suffix = interval_suffix.get(normalized_interval, "")

    try:
        if min_amt is not None and max_amt is not None:
            result = (
                f"{prefix}{int(min_amt / divisor)}k–{int(max_amt / divisor)}k"
                if divisor == 1000
                else f"{prefix}{int(min_amt)}–{int(max_amt)}"
            )
        elif min_amt is not None:
            result = (
                f"{prefix}{int(min_amt / divisor)}k+"
                if divisor == 1000
                else f"{prefix}{int(min_amt)}+"
            )
        else:
            result = (
                f"{prefix}{int(max_amt / divisor)}k"
                if divisor == 1000
                else f"{prefix}{int(max_amt)}"
            )

        return f"{result} {suffix}".strip() if suffix else result

    except Exception:
        return ""

def _map_job_type(raw: str, mapping: dict) -> str:
    """
    Normalize a raw job type label from a job source into a standard internal value.

    `raw`:
        The original job type string as provided by the external job source
        (e.g. "Full Time", "FULL-TIME", "Contractor", "Permanent", etc.).
        This value is untrusted, inconsistent, and outside our control.

    `mapping`:
        A dictionary owned by this project that maps normalized raw values
        (e.g. "fulltime", "part_time", "contract") to approved, human-readable
        job type labels used internally (e.g. "Full time", "Part time", "Contract").

    Behavior:
        - If `raw` is empty or missing, return ""
        - The raw value is normalized (lowercased, spaces removed)
        - The normalized value is looked up in the provided mapping
        - If no mapping exists, return ""

    This function deliberately contains no hard-coded knowledge.
    All job type knowledge lives in the supplied `mapping`, not in this function.
    """
    if not raw:
        return ""

    key = raw.lower().replace(" ", "")
    return mapping.get(key, "")
