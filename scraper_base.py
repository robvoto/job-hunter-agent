"""Shared base class and helpers for all job source connectors."""

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Optional, Set


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
            (kept_records, audit_rows, skill_observations) – three lists of dicts.
        """
        ...


def make_namespaced_key(source: str, raw_id: str) -> str:
    """Return 'source:raw_id', e.g. 'linkedin:4056789012'."""
    return f"{source}:{raw_id}"


def normalize_jobspy_record(row: Any, search_keywords: str, search_location: str, run_iso: str) -> dict:
    """Map a python-jobspy DataFrame row to the project's normalized record shape."""
    try:
        import pandas as pd  # noqa: F401 – only used for pd.isna
        _pd = pd
    except ImportError:
        _pd = None

    def _safe_str(val, default: str = "N/A") -> str:
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

    # Posted date → age in days
    raw_date = _get("date_posted")
    posted_age_days: Optional[float] = None
    posted_text = "N/A"
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
    min_amt = _safe_float(_get("min_amount"))
    max_amt = _safe_float(_get("max_amount"))
    interval_raw = _safe_str(_get("interval"), "")
    currency_raw = _safe_str(_get("currency"), "AUD")
    salary_str = _build_salary_string(min_amt, max_amt, interval_raw, currency_raw)

    # Work mode
    is_remote = _get("is_remote")
    if is_remote is True or (isinstance(is_remote, str) and is_remote.lower() == "true"):
        work_mode = "Remote"
    else:
        work_mode = "N/A"

    # Work type
    work_type = _map_job_type(_safe_str(_get("job_type"), ""))

    # Description
    description = _safe_str(_get("description"), "")

    # Stable job key (namespaced)
    raw_id = _safe_str(_get("id"), "")
    job_key = make_namespaced_key("linkedin", raw_id) if raw_id and raw_id != "N/A" else None

    return {
        "run_started_at": run_iso,
        "search_location": search_location,
        "search_keywords": search_keywords,
        "search_classifications": "",
        "page": 1,
        "source": "linkedin",
        "job_key": job_key,
        "title": _safe_str(_get("title")),
        "company": _safe_str(_get("company")),
        "location": _safe_str(_get("location")),
        "posted": posted_text,
        "posted_age_days": posted_age_days,
        "work_mode": work_mode,
        "work_type": work_type,
        "salary": salary_str,
        "url": _safe_str(_get("job_url")),
        "teaser": description[:240].strip() or "N/A",
        "details_text": description,
        "details_length": len(description),
        "decision": "REJECT",
        "reject_reason": None,
        "title_reason": None,
        "content_reason": None,
        "llm_decision": None,
        "llm_fit_grade": None,
        "role_snapshot": "N/A",
        "fit_highlights": [],
        "competitive_signals": [],
    }


def _build_salary_string(
    min_amt: Optional[float],
    max_amt: Optional[float],
    interval: str,
    currency: str,
) -> str:
    if min_amt is None and max_amt is None:
        return "N/A"
    prefix = "$" if currency in ("AUD", "USD", "N/A", "") else f"{currency} "
    interval_map = {"yearly": "p.a.", "monthly": "/mo", "hourly": "/hr"}
    suffix = interval_map.get(interval.lower(), "")
    try:
        if min_amt is not None and max_amt is not None:
            result = f"{prefix}{int(min_amt / 1000)}k\u2013{int(max_amt / 1000)}k"
        elif min_amt is not None:
            result = f"{prefix}{int(min_amt / 1000)}k+"
        else:
            result = f"{prefix}{int(max_amt / 1000)}k"  # type: ignore[arg-type]
        return f"{result} {suffix}".strip() if suffix else result
    except Exception:
        return "N/A"


def _map_job_type(raw: str) -> str:
    mapping = {
        "fulltime": "Full time",
        "full-time": "Full time",
        "full_time": "Full time",
        "parttime": "Part time",
        "part-time": "Part time",
        "part_time": "Part time",
        "contract": "Contract",
        "contractor": "Contract",
        "temporary": "Temporary",
        "internship": "Internship",
        "casual": "Casual",
    }
    return mapping.get(raw.lower().replace(" ", ""), "N/A") if raw else "N/A"
