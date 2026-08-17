"""Shared base class and helpers for all job source connectors."""

import json
import re
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Optional, Set
from urllib.parse import urlparse

from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.record_schema import (
    APPLY_METHOD_UNKNOWN,
    RECORD_APPLY_METHOD_KEY,
    RECORD_COMPANY_KEY,
    RECORD_COMPETITIVE_SIGNALS_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_DECISION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_LENGTH_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_FIT_CONFIDENCE_KEY,
    RECORD_FIT_HIGHLIGHTS_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_IS_REPOSTED_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LOCATION_KEY,
    RECORD_MISSING_PROFILE_SUPPORT_KEY,
    RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY,
    RECORD_ORIGINAL_POSTED_DATE_KEY,
    RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY,
    RECORD_PAGE_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_POSTED_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_REVIEWED_SIGNAL_MATCHES_KEY,
    RECORD_ROLE_SNAPSHOT_KEY,
    RECORD_RUN_STARTED_AT_KEY,
    RECORD_SALARY_KEY,
    RECORD_SEARCH_CLASSIFICATIONS_KEY,
    RECORD_SEARCH_KEYWORDS_KEY,
    RECORD_SEARCH_LOCATION_KEY,
    RECORD_SOFT_RISK_REASONS_KEY,
    RECORD_SOURCE_ADVERTISER_ID_KEY,
    RECORD_SOURCE_ATS_REQUISITION_ID_KEY,
    RECORD_SOURCE_CANONICAL_URL_KEY,
    RECORD_SOURCE_KEY,
    RECORD_SOURCE_METADATA_KEY,
    RECORD_SOURCE_PLATFORM_JOB_ID_KEY,
    RECORD_TEASER_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_MATCH_METADATA_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    RECORD_WORK_MODE_SOURCE_KEY,
    RECORD_WORK_TYPE_KEY,
)
from job_hunter_agent.salary import (
    KEY_CURRENCIES_WITH_DOLLAR,
    KEY_INTERVAL_DIVISOR,
    KEY_INTERVAL_SUFFIX,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
    LEARNING_CATEGORY_KEY,
    LEARNING_EVIDENCE_KEY,
    LEARNING_NEEDS_REVIEW_KEY,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SOURCE_KEY,
    LEARNING_SUGGESTED_VALUES_KEY,
)
from job_hunter_agent.job_types import load_job_type_learning_guardrails
from job_hunter_agent.work_mode_extraction import extract_from_linkedin

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


def blank_source_metadata(source: str) -> dict:
    return {
        "platform": source,
        "apply_url": "",
        "apply_domain": "",
        RECORD_SOURCE_CANONICAL_URL_KEY: "",
        "company_profile_url": "",
        "company_profile_name": "",
        RECORD_SOURCE_ADVERTISER_ID_KEY: "",
        "poster_company": "",
        "hiring_company": "",
        "ats_source": "",
        RECORD_SOURCE_ATS_REQUISITION_ID_KEY: "",
        RECORD_SOURCE_PLATFORM_JOB_ID_KEY: "",
        "raw_source_fields": {},
    }


def blank_posting_channel_evidence() -> dict:
    return {
        "kind": "unknown",
        "source": "insufficient_evidence",
        "trusted_metadata": [],
        "weak_text_matches": [],
        "text_evidence": [],
        "needs_review": False,
    }


def _build_initial_source_metadata(
    source: str,
    raw_source_fields: dict,
    apply_url: str = "",
    canonical_url: str = "",
    company_profile_url: str = "",
    company_profile_name: str = "",
    advertiser_id: str = "",
    poster_company: str = "",
    hiring_company: str = "",
    platform_job_id: str = "",
    ats_requisition_id: str = "",
    ats_source: str | None = None,
) -> dict:
    metadata = blank_source_metadata(source)
    metadata.update(
        {
            "apply_url": apply_url,
            "apply_domain": _url_domain(apply_url),
            RECORD_SOURCE_CANONICAL_URL_KEY: canonical_url,
            "company_profile_url": company_profile_url,
            "company_profile_name": company_profile_name,
            RECORD_SOURCE_ADVERTISER_ID_KEY: advertiser_id,
            "poster_company": poster_company or company_profile_name,
            "hiring_company": hiring_company or company_profile_name,
            "ats_source": _url_domain(apply_url) if ats_source is None else ats_source,
            RECORD_SOURCE_PLATFORM_JOB_ID_KEY: platform_job_id,
            "raw_source_fields": raw_source_fields,
        }
    )
    if ats_requisition_id:
        metadata[RECORD_SOURCE_ATS_REQUISITION_ID_KEY] = ats_requisition_id
    else:
        metadata.pop(RECORD_SOURCE_ATS_REQUISITION_ID_KEY, None)
    return metadata


def _build_initial_review_state() -> dict:
    return {
        RECORD_REVIEWED_SIGNAL_MATCHES_KEY: {
            "matched": [],
            "evidence_only": [],
            "ignored": [],
            "unresolved": [],
        },
        RECORD_POSTING_CHANNEL_EVIDENCE_KEY: blank_posting_channel_evidence(),
        RECORD_ORIGINAL_POSTED_DATE_KEY: "",
        RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY: None,
        RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY: "",
        RECORD_IS_REPOSTED_KEY: None,
    }


def _build_initial_scoring_state() -> dict:
    return {
        RECORD_DETAILS_STATUS_KEY: "",
        RECORD_DESCRIPTION_SOURCE_KEY: "",
        RECORD_FIT_CONFIDENCE_KEY: "",
        RECORD_FIT_SOURCE_TEXT_KEY: "",
        RECORD_FULL_DESCRIPTION_KEY: "",
        RECORD_HARD_BLOCK_REASONS_KEY: [],
    }


def _build_initial_llm_state() -> dict:
    return {
        RECORD_LLM_DECISION_KEY: None,
        RECORD_LLM_FIT_GRADE_KEY: None,
        RECORD_ROLE_SNAPSHOT_KEY: "",
        RECORD_FIT_HIGHLIGHTS_KEY: [],
        RECORD_COMPETITIVE_SIGNALS_KEY: [],
        RECORD_SOFT_RISK_REASONS_KEY: [],
        RECORD_MISSING_PROFILE_SUPPORT_KEY: [],
    }


def _build_initial_decision_state() -> dict:
    return {
        RECORD_DECISION_KEY: None,
        RECORD_REJECT_REASON_KEY: None,
        RECORD_TITLE_REASON_KEY: None,
        RECORD_TITLE_MATCH_METADATA_KEY: {},
        RECORD_CONTENT_REASON_KEY: None,
    }


def build_initial_flat_record(
    *,
    run_iso: str,
    search_location: str,
    search_keywords: str,
    source: str,
    job_key: str | None,
    title: str,
    company: str,
    location: str,
    posted_text: str,
    posted_age_days: Optional[float],
    work_mode: str,
    work_mode_source: str,
    work_mode_evidence: list,
    work_mode_needs_review: bool,
    work_type: str,
    salary_str: str,
    url: str,
    teaser: str,
    details_text: str,
    details_length: int,
    source_metadata: dict | None = None,
) -> dict:
    # Transitional flat schema: these grouped defaults will later become nested state.
    record = _build_ingestion_record(
        run_iso=run_iso,
        search_location=search_location,
        search_keywords=search_keywords,
        source=source,
        job_key=job_key,
        title=title,
        company=company,
        location=location,
        posted_text=posted_text,
        posted_age_days=posted_age_days,
        work_mode=work_mode,
        work_mode_source=work_mode_source,
        work_mode_evidence=work_mode_evidence,
        work_mode_needs_review=work_mode_needs_review,
        work_type=work_type,
        salary_str=salary_str,
        url=url,
        teaser=teaser,
        details_text=details_text,
        details_length=details_length,
    )
    record.update(_build_initial_decision_state())
    record.update(_build_initial_llm_state())
    record.update(_build_initial_review_state())
    record.update(_build_initial_scoring_state())
    record[RECORD_SOURCE_METADATA_KEY] = (
        source_metadata if source_metadata is not None else blank_source_metadata(source)
    )
    return record


def _build_ingestion_record(
    *,
    run_iso: str,
    search_location: str,
    search_keywords: str,
    source: str,
    job_key: str | None,
    title: str,
    company: str,
    location: str,
    posted_text: str,
    posted_age_days: Optional[float],
    work_mode: str,
    work_mode_source: str,
    work_mode_evidence: list,
    work_mode_needs_review: bool,
    work_type: str,
    salary_str: str,
    url: str,
    teaser: str,
    details_text: str,
    details_length: int,
) -> dict:
    # Transitional flat schema: these fields are grouped by concern here for readability.
    # The final record stays flat until consumers are migrated to nested decision_state,
    # llm_state, and review_state blocks.
    return {
        RECORD_RUN_STARTED_AT_KEY: run_iso,
        RECORD_SEARCH_LOCATION_KEY: search_location,
        RECORD_SEARCH_KEYWORDS_KEY: search_keywords,
        RECORD_SEARCH_CLASSIFICATIONS_KEY: "",
        RECORD_PAGE_KEY: 1,
        RECORD_SOURCE_KEY: source,
        RECORD_JOB_KEY: job_key,
        RECORD_TITLE_KEY: title,
        RECORD_COMPANY_KEY: company,
        RECORD_LOCATION_KEY: location,
        RECORD_POSTED_KEY: posted_text,
        RECORD_POSTED_AGE_DAYS_KEY: posted_age_days,
        RECORD_WORK_MODE_KEY: work_mode,
        RECORD_WORK_MODE_SOURCE_KEY: work_mode_source,
        RECORD_WORK_MODE_EVIDENCE_KEY: work_mode_evidence,
        RECORD_WORK_MODE_NEEDS_REVIEW_KEY: work_mode_needs_review,
        RECORD_WORK_TYPE_KEY: work_type,
        RECORD_SALARY_KEY: salary_str,
        RECORD_URL_KEY: url,
        RECORD_TEASER_KEY: teaser,
        RECORD_DETAILS_TEXT_KEY: details_text,
        RECORD_DETAILS_LENGTH_KEY: details_length,
        RECORD_APPLY_METHOD_KEY: APPLY_METHOD_UNKNOWN,
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
        discovery_records: list[dict] | None = None,
        discovery_capture: list[dict] | None = None,
        discovery_status: dict[str, bool] | None = None,
    ):
        self.profile = profile
        self.llm_cache = llm_cache
        self.job_history = job_history
        self.applied_job_keys = applied_job_keys
        self.hidden_job_keys = hidden_job_keys
        self.run_iso = run_iso
        self.discovery_records = discovery_records
        self.discovery_capture = discovery_capture
        self.discovery_status = discovery_status if discovery_status is not None else {}

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
    salary_str = _build_salary_string(
        min_amt,
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
    canonical_url = _safe_str(_get(JOBSPY_JOB_URL_KEY))
    company_profile_url = _first_non_empty(_get("company_url_direct"), _get("company_url"))
    company_profile_name = _first_non_empty(_get("company_name"), _get(JOBSPY_COMPANY_KEY))
    raw_source_fields = _json_safe_value(_safe_row_dict(row))
    source_metadata = _build_initial_source_metadata(
        source=source,
        raw_source_fields=raw_source_fields,
        apply_url=apply_url,
        canonical_url=canonical_url,
        company_profile_url=company_profile_url,
        company_profile_name=company_profile_name,
        poster_company=company_profile_name,
        hiring_company=company_profile_name,
        platform_job_id=raw_id,
        ats_requisition_id=_safe_str(_get(RECORD_SOURCE_ATS_REQUISITION_ID_KEY), ""),
    )
    return build_initial_flat_record(
        run_iso=run_iso,
        search_location=search_location,
        search_keywords=search_keywords,
        source=source,
        job_key=job_key,
        title=_safe_str(_get(JOBSPY_TITLE_KEY)),
        company=_safe_str(_get(JOBSPY_COMPANY_KEY)),
        location=_safe_str(_get(JOBSPY_LOCATION_KEY)),
        posted_text=posted_text,
        posted_age_days=posted_age_days,
        work_mode=wm["work_mode"],
        work_mode_source=wm["work_mode_source"],
        work_mode_evidence=wm["work_mode_evidence"],
        work_mode_needs_review=wm["work_mode_needs_review"],
        work_type=work_type,
        salary_str=salary_str,
        url=_safe_str(_get(JOBSPY_JOB_URL_KEY)),
        teaser=description[:240].strip(),
        details_text=description,
        details_length=len(description),
        source_metadata=source_metadata,
    )


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

    cleaned_raw = str(raw or "").strip()
    key = cleaned_raw.lower().replace(" ", "")
    mapped = mapping.get(key, "")
    if mapped:
        return mapped
    _register_unknown_job_type(cleaned_raw)
    return ""


map_job_type = _map_job_type


_JOB_TYPE_PAGE_STRUCTURE_PATTERNS = (
    re.compile(r"<[^>]+>", flags=re.IGNORECASE),
    re.compile(r"\b(?:window|document|navigator)\s*\.\s*[A-Za-z_$]", flags=re.IGNORECASE),
    re.compile(r"\b(?:function|const|let|var)\s+[A-Za-z_$]", flags=re.IGNORECASE),
    re.compile(r"[{}]"),
)


def _is_valid_job_type_learning_candidate(value: str) -> bool:
    """Allow scalar unknown types while blocking captured page or script structure."""
    if not value:
        return False
    guardrails = load_job_type_learning_guardrails()
    normalized = str(value or "").strip()
    if not normalized:
        return False

    non_learnable_values = {
        str(entry).strip().lower()
        for entry in guardrails.get("non_learnable_values", [])
        if str(entry).strip()
    }
    if normalized.lower() in non_learnable_values:
        return False
    if len(normalized) > int(guardrails["max_chars"]):
        return False
    if len(normalized.split()) > int(guardrails["max_words"]):
        return False
    if normalized.count("\n") + 1 > int(guardrails["max_lines"]):
        return False
    return not any(pattern.search(normalized) for pattern in _JOB_TYPE_PAGE_STRUCTURE_PATTERNS)


def _register_unknown_job_type(raw_value: str) -> None:
    cleaned_raw = str(raw_value or "").strip()
    if not _is_valid_job_type_learning_candidate(cleaned_raw):
        return
    from job_hunter_agent.signal_registry import register_signals

    register_signals(
        [
            {
                LEARNING_SIGNAL_KEY: cleaned_raw,
                LEARNING_CATEGORY_KEY: CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
                LEARNING_SOURCE_KEY: "job parsing",
                LEARNING_EVIDENCE_KEY: [cleaned_raw],
                LEARNING_ORIGINAL_TEXTS_KEY: [cleaned_raw],
                LEARNING_SUGGESTED_VALUES_KEY: [cleaned_raw],
                LEARNING_NEEDS_REVIEW_KEY: True,
            }
        ],
        category=CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
    )
