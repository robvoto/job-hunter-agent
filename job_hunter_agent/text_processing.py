"""Helpers for text processing."""

import re
from typing import Dict, List, Optional, Set


def _generic_summary_phrases() -> set[str]:
    from job_hunter_agent.profile_learning import get_parsing_rule_set

    return get_parsing_rule_set("generic_summary_phrases")


def dedupe_preserve_order(values: List[str]) -> List[str]:

    seen: Set[str] = set()

    result: List[str] = []

    for value in values:
        normalized = value.strip()

        if not normalized or normalized in seen:
            continue

        seen.add(normalized)

        result.append(normalized)

    return result


def compact_whitespace(value: Optional[str]) -> str:

    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_text_snippets(text: str) -> List[str]:

    snippets: List[str] = []

    for raw_line in re.split(r"[\r\n]+", text or ""):
        cleaned = compact_whitespace(raw_line.strip(" -•\t"))

        if len(cleaned) >= 24:
            snippets.append(cleaned)

    if snippets:
        return dedupe_preserve_order(snippets)

    compact = compact_whitespace(text)

    if not compact:
        return []

    sentence_like = [
        compact_whitespace(part)
        for part in re.split(r"(?<=[.!?])\s+", compact)
        if len(compact_whitespace(part)) >= 24
    ]

    return dedupe_preserve_order(sentence_like)


def list_to_phrase(items: List[str]) -> str:

    cleaned = [compact_whitespace(item) for item in items if compact_whitespace(item)]

    if not cleaned:
        return ""

    if len(cleaned) == 1:
        return cleaned[0]

    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"

    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def summarize_snippet(snippet: str, max_length: int = 180) -> str:

    cleaned = compact_whitespace(snippet)

    cleaned = re.sub(r"^([A-Z][a-z]{3,30})(?=[A-Z][a-z])", r"\1 ", cleaned)

    if len(cleaned) <= max_length:
        return cleaned

    return cleaned[: max_length - 3].rstrip() + "..."


def synthesize_role_snapshot(record: dict) -> str:

    title = compact_whitespace(record.get("title") or "")

    location = compact_whitespace(record.get("location") or "")

    if location.endswith(", Australia"):
        location = location[:-11].strip()

    work_type = compact_whitespace(record.get("work_type") or "")

    teaser = compact_whitespace(record.get("teaser") or "")

    domain_focus = ""

    if " - " in title:
        domain_focus = compact_whitespace(title.split(" - ", 1)[1])

    elif "(" in title and ")" in title:
        domain_focus = compact_whitespace(re.sub(r"^[^(]*\((.*?)\).*$", r"\1", title))

    summary = ""

    if (
        title
        and domain_focus
        and work_type
        and location
        and work_type != "N/A"
        and location != "N/A"
    ):
        summary = f"{title} role focused on {domain_focus.lower()} work in {location} on a {work_type.lower()} basis."

    elif title and location and location != "N/A":
        summary = f"{title} role based in {location}."

    elif title:
        summary = f"{title} role."

    if teaser and teaser != "N/A" and not _is_generic_summary_text(teaser):
        summary = f"{summary} {teaser}".strip()

    return summarize_snippet(summary, max_length=220) if summary else "Role summary not available."


def description_summary_snippet(record: dict, details_text: str) -> str:

    title = compact_whitespace(record.get("title") or "")

    company = compact_whitespace(record.get("company") or "")

    snippets = [_clean_summary_candidate(snippet) for snippet in split_text_snippets(details_text)]

    for snippet in snippets:
        if _is_summary_heading(snippet):
            continue

        if _looks_like_generic_job_summary(snippet, title, company):
            continue

        return summarize_snippet(snippet, max_length=220)

    return ""


def _is_generic_summary_text(text: str) -> bool:

    lowered = compact_whitespace(text).lower()

    phrases = _generic_summary_phrases()

    return any(phrase in lowered for phrase in phrases)


def _clean_summary_candidate(text: str) -> str:

    cleaned = compact_whitespace(text)

    if not cleaned:
        return ""

    if ":" in cleaned[:40]:
        prefix, _, remainder = cleaned.partition(":")

        if 0 < len(prefix.split()) <= 4 and remainder.strip():
            cleaned = compact_whitespace(remainder)

    cleaned = re.sub(r"^[•\-–—]+\s*", "", cleaned).strip()

    return cleaned


def _is_summary_heading(text: str) -> bool:

    cleaned = compact_whitespace(text)

    if not cleaned:
        return True

    if len(cleaned) <= 24 and cleaned.endswith(":"):
        return True

    tokens = cleaned.split()

    if len(tokens) <= 5 and cleaned == cleaned.upper():
        return True

    return False


def _looks_like_generic_job_summary(text: str, title: str, company: str) -> bool:

    cleaned = compact_whitespace(text)

    lowered = cleaned.lower()

    title_lower = compact_whitespace(title).lower()

    company_lower = compact_whitespace(company).lower()

    if not cleaned or len(cleaned) < 45:
        return True

    if cleaned.endswith(":"):
        return True

    if title_lower and lowered == title_lower:
        return True

    if company_lower and lowered == company_lower:
        return True

    if lowered.startswith("about the role") and len(cleaned.split()) <= 4:
        return True

    return False


def build_role_summary(record: dict, details_text: str, profile: Optional[dict] = None) -> str:

    teaser = compact_whitespace(record.get("teaser") or "")

    title = compact_whitespace(record.get("title") or "")

    location = compact_whitespace(record.get("location") or "")

    work_type = compact_whitespace(record.get("work_type") or "")

    detail_summary = description_summary_snippet(record, details_text)

    if detail_summary:
        return detail_summary

    if teaser and teaser != "N/A" and not _is_generic_summary_text(teaser):
        return summarize_snippet(teaser, max_length=220)

    domain_focus = ""

    if " - " in title:
        domain_focus = compact_whitespace(title.split(" - ", 1)[1])

    elif "(" in title and ")" in title:
        domain_focus = compact_whitespace(re.sub(r"^[^(]*\((.*?)\).*$", r"\1", title))

    base_role = title.split(" - ")[0].split("(")[0].strip() if domain_focus else title

    if title and location and location != "N/A" and work_type and work_type != "N/A":
        intro = f"{base_role} role in {location} ({work_type.lower()})"

    elif title and location and location != "N/A":
        intro = f"{base_role} role in {location}"

    else:
        intro = f"{base_role} role" if base_role else "Role"

    if domain_focus:
        summary = f"{intro} focused on {domain_focus}."

    else:
        summary = f"{intro}."

    return summarize_snippet(summary, max_length=180)
