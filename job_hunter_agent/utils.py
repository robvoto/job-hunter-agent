"""Common utility functions for the job hunter agent.

This module provides shared helper functions for recursive dictionary
merging, safe type coercion, and URL parameter manipulation. It also
includes best-effort logic for extracting salary info and age data from
scraped job text based on parsing rules.
"""

import copy
import re
from datetime import date
from html import escape
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from job_hunter_agent.io_utils import load_parsing_rules


def safe_html(text: str) -> str:
    return escape(text or "", quote=True)


def deep_merge(base: Any, patch: Any) -> Any:
    """Recursively merge two dictionaries, deep-copying values from the patch."""
    if isinstance(base, dict) and isinstance(patch, dict):
        merged = dict(base)
        for key, value in patch.items():
            merged[key] = deep_merge(merged.get(key), value)
        return merged
    return copy.deepcopy(patch)


def coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Safe integer coercion with clamping."""
    try:
        resolved = int(value)
    except Exception as exc:
        resolved = default
        print(f"[UTILS][WARN] Failed to coerce {value!r} to int, using default {default}: {exc}")
    return max(minimum, min(maximum, resolved))


def set_query_param(url: str, key: str, value: str | int) -> str:
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query, keep_blank_values=True)
    query_params[key] = [str(value)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment,
        )
    )


def set_page_param(url: str, page_num: int) -> str:
    """
    Updates/sets page= in the URL while keeping all other filters intact.
    """
    return set_query_param(url, "page", page_num)


def extract_salary(details_text: str) -> str:
    """
    Pull a salary-ish snippet from the job text.
    (Best-effort: SEEK formats vary)
    """
    if not details_text:
        return ""

    rules = load_parsing_rules()
    regex_patterns = rules.get("salary_extraction_patterns", [])
    for pattern in regex_patterns:
        match = re.search(pattern, details_text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()

    lines = [line.strip() for line in details_text.splitlines() if line.strip()]
    for line in lines[:20]:
        line_lower = line.lower()
        if len(line) <= 120 and (
            "salary" in line_lower
            or "package" in line_lower
            or "$" in line
            or "k p.a." in line_lower
            or "per day" in line_lower
            or "daily rate" in line_lower
            or "incl super" in line_lower
        ):
            return line
    return ""


_ABSOLUTE_DATE_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ABSOLUTE_DATE_RE = re.compile(
    r"(?:(\d{1,2})\s+([a-z]{3})\s+(\d{4})|([a-z]{3})\s+(\d{1,2}),?\s+(\d{4})|(\d{4})-(\d{2})-(\d{2}))",
    re.IGNORECASE,
)


def _parse_absolute_posted_date(text: str, today: Optional[date] = None) -> Optional[float]:
    m = _ABSOLUTE_DATE_RE.search(text.strip())
    if not m:
        return None
    try:
        if m.group(1):  # day month year: "5 Jun 2026"
            d = date(int(m.group(3)), _ABSOLUTE_DATE_MONTHS[m.group(2).lower()[:3]], int(m.group(1)))
        elif m.group(4):  # month day year: "Jun 5, 2026"
            d = date(int(m.group(6)), _ABSOLUTE_DATE_MONTHS[m.group(4).lower()[:3]], int(m.group(5)))
        else:  # ISO: "2026-06-05"
            d = date(int(m.group(7)), int(m.group(8)), int(m.group(9)))
        ref = today or date.today()
        return float(max(0, (ref - d).days))
    except (KeyError, ValueError):
        return None


def parse_seek_posted_age_days(
    posted_text: str, today: Optional[date] = None
) -> Optional[float]:
    if not posted_text:
        return None

    rules = load_parsing_rules().get("seek_posted_age_rules", {})
    if not isinstance(rules, dict):
        return None

    value = posted_text.strip().lower()
    explicit_labels = rules.get("explicit_labels", {})
    if isinstance(explicit_labels, dict):
        for label, days in explicit_labels.items():
            if value == str(label).strip().lower():
                try:
                    return float(days)
                except Exception as exc:
                    print(
                        f"[UTILS][WARN] Failed to parse seek age days from label '{label}': {exc}"
                    )
                    return None

    pattern = str(rules.get("relative_text_pattern") or "").strip()
    unit_days = rules.get("unit_days", {})
    if not pattern or not isinstance(unit_days, dict):
        return None

    match = re.fullmatch(pattern, value)
    if match:
        amount = int(match.group("amount"))
        unit = match.group("unit").lower()
        if unit not in unit_days:
            return None
        try:
            return float(amount) * float(unit_days[unit])
        except Exception as exc:
            print(
                f"[UTILS][WARN] Failed to calculate seek age days from relative text '{posted_text}': {exc}"
            )
            return None

    return _parse_absolute_posted_date(posted_text, today)
