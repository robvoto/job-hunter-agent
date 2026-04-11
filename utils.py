# utils.py

import re
from html import escape
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def safe_html(text: str) -> str:
    return escape(text or "", quote=True)


def set_query_param(url: str, key: str, value: str | int) -> str:
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query, keep_blank_values=True)
    query_params[key] = [str(value)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment)
    )


def set_page_param(url: str, page_num: int) -> str:
    """
    Updates/sets page= in the URL while keeping all other filters intact.
    """
    return set_query_param(url, "page", page_num)


def extract_job_id_from_relative_url(relative_url: str) -> Optional[str]:
    match = re.search(r"/job/(\d+)", relative_url or "")
    return match.group(1) if match else None


def fingerprint_text(text: str) -> str:
    """
    A simple fingerprint so we can detect when the right-side details pane changes.
    """
    if not text:
        return ""
    snippet_start = text[:120]
    snippet_end = text[-120:] if len(text) > 120 else text
    return f"{len(text)}::{snippet_start}::{snippet_end}"


def extract_salary(details_text: str) -> str:
    """
    Pull a salary-ish snippet from the job text.
    (Best-effort: SEEK formats vary)
    """
    if not details_text:
        return "N/A"

    regex_patterns = [
        r"\$\s?\d[\d,]*(?:\s*-\s*\$?\s?\d[\d,]*)?(?:\s*(?:\+?\s*super|incl\.?\s*super|package|p\.a\.|per annum|per day|daily rate))?",
        r"\b\d{2,3}k(?:\s*-\s*\d{2,3}k)?(?:\s*(?:\+?\s*super|incl\.?\s*super|package|p\.a\.|per annum))?",
    ]
    for pattern in regex_patterns:
        match = re.search(pattern, details_text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()

    lines = [line.strip() for line in details_text.splitlines() if line.strip()]
    for line in lines[:20]:
        line_lower = line.lower()
        if (
            len(line) <= 120
            and (
                "salary" in line_lower
                or "package" in line_lower
                or "$" in line
                or "k p.a." in line_lower
                or "per day" in line_lower
                or "daily rate" in line_lower
                or "incl super" in line_lower
            )
        ):
            return line
    return "N/A"


def parse_seek_posted_age_days(posted_text: str) -> Optional[float]:
    if not posted_text:
        return None

    value = posted_text.strip().lower()
    if value == "today":
        return 0.0

    match = re.search(r"(\d+)\s*([mhdy])", value)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "m":
        return amount / (24 * 60)
    if unit == "h":
        return amount / 24
    if unit == "d":
        return float(amount)
    if unit == "y":
        return float(amount * 365)
    return None
