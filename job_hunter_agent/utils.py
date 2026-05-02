# utils.py

import re
import sys
from html import escape
from typing import Optional, Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def safe_html(text: str) -> str:
    return escape(text or "", quote=True)


def repair_text(text: str) -> str:
    """Fix common encoding mojibake and normalize special characters for clean dashboard rendering."""
    if not text:
        return ""

    # 1. Normalize line endings and common high-unicode whitespace/dashes
    repaired = str(text).replace("\r\n", "\n").replace("\r", "\n")
    
    replacements = {
        "\u00a0": " ",      # Non-breaking space
        "\u2013": "-",      # En dash
        "\u2014": "-",      # Em dash
        "\u2011": "-",      # Non-breaking hyphen
        "\u2018": "'",      # Left single quote
        "\u2019": "'",      # Right single quote
        "\u201c": '"',      # Left double quote
        "\u201d": '"',      # Right double quote
        "\u2022": "*",      # Bullet point
        "\u2026": "...",    # Ellipsis
        "\u2192": "->",     # Right arrow
    }
    for old, new in replacements.items():
        repaired = repaired.replace(old, new)

    # 2. Fix Mojibake: UTF-8 bytes accidentally interpreted as Latin-1/CP1252
    # Patterns like "Ã¢" or "â€" (typical of double-encoding or bad decoding)
    if "Ã¢" in repaired or "Ãƒ" in repaired or "â€" in repaired:
        try:
            # Attempt to re-encode the mangled string back to bytes as latin1
            # (which recovers the original raw UTF-8 bytes) then decode as utf-8.
            # This fixes "â€™" becoming "'" and similar.
            candidate = repaired.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
            # Only apply if we actually reduced the count of suspicious 'Ã' characters
            # or if the length changed significantly (indicating multi-byte recovery).
            if candidate.count("Ã") < repaired.count("Ã") or len(candidate) < len(repaired):
                repaired = candidate
        except Exception:
            pass

    # 3. Strip any remaining non-printable control chars except \n and \t
    # (Avoids weird glyphs in some browsers)
    repaired = "".join(ch for ch in repaired if ch.isprintable() or ch in "\n\t")

    return repaired.strip()


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


def extract_work_mode(text: str) -> str:
    if not text:
        return "N/A"

    lowered = text.lower()
    strict_onsite_tokens = [
        "5 days in office",
        "five days in office",
        "must be in office",
        "must work from the office",
        "100% office based",
        "100% office-based",
        "fully office based",
        "fully office-based",
    ]
    if any(token in lowered for token in strict_onsite_tokens):
        return "On-site"
    if any(token in lowered for token in ["hybrid", "split between home and office", "mix of home and office"]):
        return "Hybrid"
    if any(
        token in lowered
        for token in [
            "work from home",
            "wfh",
            "remote",
            "fully remote",
            "100% remote",
        ]
    ):
        return "Remote"
    if any(
        token in lowered
        for token in [
            "on site",
            "onsite",
            "office based",
            "office-based",
            "must be in office",
            "5 days in office",
        ]
    ):
        return "On-site"
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
