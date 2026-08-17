"""Helpers for text processing."""

import re
from functools import lru_cache
from typing import List, Optional, Set

_ESCAPED_LIST_MARKER_RE = re.compile(r"(?<!\S)\\\*(?=\s+\S)")
_STRUCTURED_SUMMARY_PREFIXES = (
    "role:",
    "location:",
    "location of work:",
    "length of contract:",
    "contract extension:",
    "contract extensions:",
    "security clearance:",
    "work mode:",
    "work type:",
    "contract term:",
    "salary:",
    "rate:",
)


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


@lru_cache(maxsize=8192)
def _compact_whitespace_cached(text: str) -> str:

    return re.sub(r"\s+", " ", text).strip()


def compact_whitespace(value: Optional[str]) -> str:
    # Per-term capability/eligibility/signal matching re-checks the same
    # normalized description text many times per job record (profiling a
    # 247-record cached-SEEK repeat search: ~175k calls, ~4s of redundant
    # re.sub work). str() always yields a hashable key, so caching here is
    # safe and pure -- no invalidation needed.
    return _compact_whitespace_cached(str(value or ""))


def _normalize_escaped_list_markers(text: str, replacement: str) -> str:

    return _ESCAPED_LIST_MARKER_RE.sub(replacement, text)


def clean_display_text(text: Optional[str]) -> str:

    cleaned = compact_whitespace(text)
    cleaned = _normalize_escaped_list_markers(cleaned, " | ")
    cleaned = re.sub(r"\s*\|\s*", " | ", cleaned)
    cleaned = re.sub(r"^\|\s*", "", cleaned.strip())
    cleaned = re.sub(r"\s*\|$", "", cleaned).strip()

    cleaned = _strip_markdown_emphasis(cleaned)

    return re.sub(r"^([A-Z][a-z]{3,30})(?=[A-Z][a-z])", r"\1 ", cleaned)


def clean_display_text_preserving_blocks(text: Optional[str]) -> str:

    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    raw = _normalize_escaped_list_markers(raw, "\n* ").lstrip("\n")
    lines: List[str] = []
    blank_run = 0

    for raw_line in raw.split("\n"):
        cleaned = re.sub(r"[ \t\f\v]+", " ", raw_line).strip()
        cleaned = _strip_markdown_emphasis(cleaned)
        cleaned = re.sub(r"^([A-Z][a-z]{3,30})(?=[A-Z][a-z])", r"\1 ", cleaned)
        if cleaned:
            lines.append(cleaned)
            blank_run = 0
            continue
        if blank_run == 0:
            lines.append("")
        blank_run += 1

    return "\n".join(lines).strip()


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


def _strip_markdown_emphasis(text: str) -> str:
    """Remove literal Markdown emphasis markers and escape backslashes left over from scraped source text.

    Source text sometimes has an odd number of ``*`` markers on a line (e.g. a
    stray bullet marker consumed one side of a pair), which would otherwise
    make paired matching skip misaligned and leave real ``**bold**`` markers
    behind later in the string. Strip bold/italic pairs first, then sweep up
    any markers left over from unbalanced input so none are ever shown.
    """

    cleaned = re.sub(r"\*\*([^*\n]+?)\*\*", r"\1", text)

    cleaned = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"\1", cleaned)

    cleaned = re.sub(r"\*+", "", cleaned)

    cleaned = re.sub(r"(?<!\w)_{1,3}([^_\n]+?)_{1,3}(?!\w)", r"\1", cleaned)

    cleaned = re.sub(r"\\([\\`*_{}\[\]()#+\-.!|=])", r"\1", cleaned)

    return cleaned


def summarize_snippet(snippet: str, max_length: int = 180) -> str:

    cleaned = clean_display_text(snippet)

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

    snippets = []
    for raw_snippet in split_text_snippets(details_text):
        if _is_structured_summary_snippet(raw_snippet):
            continue
        snippets.append(_clean_summary_candidate(raw_snippet))

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


def _is_structured_summary_snippet(text: str) -> bool:

    cleaned = clean_display_text(text)

    if not cleaned:
        return True

    lowered = cleaned.lower()

    return any(lowered.startswith(prefix) for prefix in _STRUCTURED_SUMMARY_PREFIXES)


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

    if (
        teaser
        and teaser != "N/A"
        and not _is_generic_summary_text(teaser)
        and not _is_structured_summary_snippet(teaser)
    ):
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
