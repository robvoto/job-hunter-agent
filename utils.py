# utils.py

import re
from html import escape
from typing import Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


def safe_html(text: str) -> str:
    return escape(text or "", quote=True)


def set_page_param(url: str, page_num: int) -> str:
    """
    Updates/sets page= in the URL while keeping all other filters intact.
    """
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query, keep_blank_values=True)
    query_params["page"] = [str(page_num)]
    new_query = urlencode(query_params, doseq=True)
    return urlunparse(
        (parsed_url.scheme, parsed_url.netloc, parsed_url.path, parsed_url.params, new_query, parsed_url.fragment)
    )


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
    Pull a salary-ish line from the details pane text.
    (Best-effort: SEEK formats vary)
    """
    if not details_text:
        return "N/A"

    lines = [line.strip() for line in details_text.splitlines() if line.strip()]
    for line in lines[:20]:
        line_lower = line.lower()
        if (
            "salary" in line_lower
            or "package" in line_lower
            or "$" in line
            or "k p.a." in line_lower
            or "per day" in line_lower
            or "daily rate" in line_lower
            or "incl super" in line_lower
        ):
            return line
    return "N/A"
