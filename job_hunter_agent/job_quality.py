"""Job quality signal detection - evidence collection only.

This module focuses on detecting signals related to job quality, such as
CV-farming patterns, job closure indicators, and date mismatches. It uses
managed knowledge files to identify suspicious job postings and provides
functions to fetch external HTML for deeper analysis. The module collects
evidence for review signals but does not make final decisions on job rejection.

CV-farming language is learned through managed knowledge in `data/cv_farming_rules.json`
and approved through the signal registry. Closed-job and date-mismatch checks stay
in `data/dodgy_job_rules.json`.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from job_hunter_agent.paths import (
    CV_FARMING_RULES_DESCRIPTION,
    CV_FARMING_RULES_NAME,
    CV_FARMING_RULES_VERSION,
)
from job_hunter_agent.signal_schema import CATEGORY_CV_FARMING_PATTERN
from job_hunter_agent.text_processing import compact_whitespace

SIGNAL_KIND_DATE_MISMATCH = "date_mismatch"
SIGNAL_KIND_JOB_CLOSED = "job_closed"
SIGNAL_KIND_CV_FARMING = "cv_farming"
SIGNAL_KIND_BROAD_ENGAGEMENT = "broad_engagement"

_MONTH_NAMES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _clean_text(value: object) -> str:
    """Normalize whitespace and coerce any value to a trimmed string."""
    return compact_whitespace(value)


def _clean_aliases(values: object, *, canonical: str = "") -> list[str]:
    """Normalize alias lists while keeping the canonical value out of the result."""
    if isinstance(values, str):
        raw_values = re.split(r"[\n,]", values)
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []

    canonical_key = _clean_text(canonical).lower()
    aliases: list[str] = []
    seen: set[str] = {canonical_key} if canonical_key else set()
    for value in raw_values:
        alias = _clean_text(value)
        alias_key = alias.lower()
        if not alias or alias_key in seen:
            continue
        seen.add(alias_key)
        aliases.append(alias)
    return aliases


def _normalize_entry(entry: object) -> dict[str, object] | None:
    """Validate and normalize a single managed-knowledge entry."""
    if not isinstance(entry, dict):
        return None
    value = _clean_text(entry.get("value"))
    if not value:
        return None
    return {
        "value": value,
        "aliases": _clean_aliases(entry.get("aliases"), canonical=value),
    }


def _merge_entries(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Merge duplicate entries while preserving order and alias coverage."""
    merged: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for entry in entries:
        normalized = _normalize_entry(entry)
        if normalized is None:
            continue
        value_key = str(normalized["value"]).lower()
        bucket = merged.get(value_key)
        if bucket is None:
            bucket = {
                "value": normalized["value"],
                "aliases": [],
            }
            merged[value_key] = bucket
            order.append(value_key)
        seen_aliases = {
            str(bucket["value"]).lower(),
            *(str(alias).lower() for alias in bucket["aliases"]),
        }
        for alias in normalized["aliases"]:
            alias_key = str(alias).lower()
            if alias_key in seen_aliases:
                continue
            seen_aliases.add(alias_key)
            bucket["aliases"].append(alias)
    return [merged[key] for key in order]


def load_cv_farming_rules() -> list[dict[str, object]]:
    """Load approved CV-farming patterns from managed knowledge."""
    from job_hunter_agent.knowledge_store import get_knowledge

    payload = get_knowledge("cv_farming_rules") or {}
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    return _merge_entries(entries)


def save_cv_farming_rules(entries: list[dict[str, object]]) -> dict[str, object]:
    """Persist the CV-farming knowledge store using the shared managed-knowledge schema."""
    payload = {
        "kind": "managed_knowledge",
        "name": CV_FARMING_RULES_NAME,
        "version": CV_FARMING_RULES_VERSION,
        "description": CV_FARMING_RULES_DESCRIPTION,
        "entries": _merge_entries(entries),
    }
    from job_hunter_agent.knowledge_store import set_knowledge

    set_knowledge("cv_farming_rules", payload)
    return payload


def upsert_cv_farming_rule(value: str, aliases: list[str] | None = None) -> dict[str, object]:
    """Insert or update a CV-farming pattern in the shared knowledge store."""
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        raise ValueError("value is required")

    entries = list(load_cv_farming_rules())
    incoming_aliases = _clean_aliases(aliases or [], canonical=cleaned_value)
    for entry in entries:
        if _clean_text(entry.get("value")).lower() != cleaned_value.lower():
            continue
        existing_aliases = _clean_aliases(entry.get("aliases"), canonical=cleaned_value)
        merged: list[str] = []
        seen: set[str] = {cleaned_value.lower()}
        for alias in [*existing_aliases, *incoming_aliases]:
            alias_key = alias.lower()
            if alias_key in seen:
                continue
            seen.add(alias_key)
            merged.append(alias)
        entry["value"] = cleaned_value
        entry["aliases"] = merged
        return save_cv_farming_rules(entries)

    entries.append(
        {
            "value": cleaned_value,
            "aliases": incoming_aliases,
        }
    )
    return save_cv_farming_rules(entries)


def load_dodgy_job_rules() -> dict:
    """Load the quality rules used for closed-job and CV-farming detection."""
    from job_hunter_agent.knowledge_store import get_knowledge

    base_rules = get_knowledge("dodgy_job_rules") or {}
    if "external_date_mismatch_flag_days" not in base_rules:
        raise ValueError("dodgy_job_rules.json must define external_date_mismatch_flag_days")
    try:
        flag_days = int(base_rules["external_date_mismatch_flag_days"])
    except Exception as exc:
        raise ValueError(
            "dodgy_job_rules.json must define a whole-number external_date_mismatch_flag_days"
        ) from exc
    if flag_days <= 0:
        raise ValueError(
            "dodgy_job_rules.json must define a positive external_date_mismatch_flag_days"
        )

    return {
        "cv_farming_patterns": [
            str(entry.get("value") or "")
            for entry in load_cv_farming_rules()
            if _clean_text(entry.get("value"))
        ],
        "job_closed_indicators": [
            _clean_text(value)
            for value in base_rules.get("job_closed_indicators", [])
            if _clean_text(value)
        ],
        "external_date_mismatch_flag_days": flag_days,
    }


def fetch_external_html(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    req = Request(raw, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"[JOB_QUALITY][WARN] Failed to fetch external HTML from {url}: {exc}")
        return ""


def _approx_age_days_from_html(html: str) -> Optional[int]:
    m = re.search(r"\bposted\s+(\d+)\s+(day|week|month)s?\s+ago\b", html, re.IGNORECASE)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "day":
        return n
    if unit == "week":
        return n * 7
    if unit == "month":
        return n * 30
    return None


def _absolute_date_from_html(html: str) -> Optional[date]:
    month_pat = "|".join(_MONTH_NAMES.keys())

    m = re.search(r"\bposted[:\s]+(\d{4}-\d{2}-\d{2})\b", html, re.IGNORECASE)
    if m:
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            pass

    m = re.search(
        rf"\bposted[:\s]+({month_pat})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",
        html,
        re.IGNORECASE,
    )
    if m:
        try:
            return date(int(m.group(3)), _MONTH_NAMES[m.group(1).lower()], int(m.group(2)))
        except (ValueError, KeyError):
            pass

    m = re.search(
        rf"\bposted\s+(?:on\s+)?(\d{{1,2}})\s+({month_pat})\s+(\d{{4}})\b",
        html,
        re.IGNORECASE,
    )
    if m:
        try:
            return date(int(m.group(3)), _MONTH_NAMES[m.group(2).lower()], int(m.group(1)))
        except (ValueError, KeyError):
            print(f"[JOB_QUALITY][WARN] Failed to parse date from HTML (format 3): {m.group(0)}")
            pass

    return None


def detect_external_date_signals(
    html: str,
    linkedin_age_days: Optional[float],
    rules: dict,
    run_date: date,
) -> list:
    if not html:
        return []

    signals = []
    flag_days = int(rules.get("external_date_mismatch_flag_days", 14))

    for pat in rules.get("job_closed_indicators", []):
        if re.search(pat, html, re.IGNORECASE):
            signals.append(
                {
                    "kind": SIGNAL_KIND_JOB_CLOSED,
                    "label": "Job Closed",
                    "evidence": "External page indicates this role is no longer available.",
                    "needs_review": True,
                }
            )
            return signals

    external_age = _approx_age_days_from_html(html)
    if external_age is None:
        ext_date = _absolute_date_from_html(html)
        if ext_date is not None:
            external_age = max((run_date - ext_date).days, 0)

    if external_age is not None and linkedin_age_days is not None:
        diff = external_age - float(linkedin_age_days)
        if diff >= flag_days:
            signals.append(
                {
                    "kind": SIGNAL_KIND_DATE_MISMATCH,
                    "label": "Date Mismatch",
                    "evidence": (
                        f"LinkedIn shows ~{int(linkedin_age_days)}d old; "
                        f"external page suggests ~{external_age}d old "
                        f"({int(diff)}d discrepancy)."
                    ),
                    "needs_review": True,
                    "linkedin_age_days": int(linkedin_age_days),
                    "external_age_days": external_age,
                    "mismatch_days": int(diff),
                }
            )

    return signals


def detect_broad_engagement_signal(record: dict) -> list:
    """Flag jobs that advertise for both permanent and contract — may indicate a broad talent-pool search."""
    work_type = _clean_text(record.get("work_type") or "").lower()
    if not work_type:
        return []
    perm_keywords = ("full time", "permanent", "full-time")
    contract_keywords = ("contract",)
    is_perm = any(k in work_type for k in perm_keywords)
    is_contract = any(k in work_type for k in contract_keywords)
    if is_perm and is_contract:
        return [
            {
                "kind": SIGNAL_KIND_BROAD_ENGAGEMENT,
                "label": "Broad Ad",
                "evidence": f'Ad lists both permanent and contract work types ("{work_type}") — may be a wide talent-pool search rather than a specific vacancy.',
                "needs_review": False,
            }
        ]
    return []


def detect_cv_farming_signals(description_text: str, rules: dict) -> list:
    """Return a single review signal when the description matches a learned CV-farming pattern."""
    patterns = rules.get("cv_farming_patterns", [])
    if not patterns:
        return []

    for pat in patterns:
        m = re.search(pat, description_text, re.IGNORECASE)
        if m:
            match_text = _clean_text(m.group(0))[:80]
            return [
                {
                    "kind": SIGNAL_KIND_CV_FARMING,
                    "label": "CV Farming",
                    "signal": pat,
                    "suggested_category": CATEGORY_CV_FARMING_PATTERN,
                    "original_texts": [match_text],
                    "evidence": f'Description matches talent-pool pattern: "{match_text}"',
                    "needs_review": True,
                }
            ]
    return []
