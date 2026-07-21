"""Deterministic helpers for explicit experience-duration requirements.

Purpose: parse requirements like "5+ years experience as Business Analyst" and
compare them against stored role_experience rows without changing wider scoring policy.
"""

from __future__ import annotations

import re
from typing import Any

from job_hunter_agent.onet_taxonomy_import import normalize_title as normalize_occupation_title
from job_hunter_agent.text_processing import compact_whitespace
from job_hunter_agent.title_normalization_rules import normalize_title_text

_EXPERIENCE_YEARS_PATTERNS = (
    re.compile(
        r"(?i)\b(?:minimum of\s+|minimum\s+|at least\s+)?(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years|yrs)\b"
    ),
    re.compile(
        r"(?i)\b(\d+(?:\.\d+)?)\s*(?:-|to|–|—)\s*(\d+(?:\.\d+)?)\s*(?:years|yrs)\b"
    ),
)
_EXPERIENCE_MONTHS_PATTERNS = (
    re.compile(
        r"(?i)\b(?:minimum of\s+|minimum\s+|at least\s+)?(\d+)\s*(?:\+)?\s*months?\b"
    ),
    re.compile(r"(?i)\b(\d+)\s*(?:-|to|–|—)\s*(\d+)\s*months?\b"),
)
_SUBJECT_PATTERNS = (
    re.compile(
        r"(?i)\b(?:years|yrs|months?)\s+(?:of\s+)?experience\s+as\s+(?:an?\s+)?(?P<subject>[^,.;:()]+)"
    ),
    re.compile(
        r"(?i)\b(?:years|yrs|months?)\s+(?:of\s+)?experience\s+in\s+(?P<subject>[^,.;:()]+)"
    ),
    re.compile(
        r"(?i)\bexperience\s+as\s+(?:an?\s+)?(?P<subject>[^,.;:()]+)"
    ),
    re.compile(r"(?i)\bexperience\s+in\s+(?P<subject>[^,.;:()]+)"),
)
_SUBJECT_SPLIT_PATTERN = re.compile(
    r"(?i)\b(?:in|with|across|within|for|on|using|including|required|preferred|essential)\b"
)
_ROOT_SUFFIXES = ("ation", "ition", "ment", "ance", "ence", "ing", "tion", "sion", "tor", "or", "er", "al")


def extract_required_experience_months(*texts: Any) -> int | None:
    for raw_text in texts:
        text = compact_whitespace(str(raw_text or ""))
        if not text:
            continue

        for pattern in _EXPERIENCE_MONTHS_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            return int(match.group(1))

        for pattern in _EXPERIENCE_YEARS_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            return int(float(match.group(1)) * 12)

    return None


def resolve_role_experience_requirement(
    requirement: Any,
    matched_job_text: Any,
    role_experience: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    required_months = extract_required_experience_months(requirement, matched_job_text)
    if required_months is None:
        return None

    match = _match_role_experience(requirement, matched_job_text, role_experience or [])
    result = {"required_experience_months": required_months}
    if not match:
        return result

    result.update(
        {
            "matched_role_experience_title": str(match["normalized_title"]),
            "matched_role_experience_months": int(match["total_duration_months"]),
            "matched_role_experience_end_year": int(match["most_recent_end_year"]),
            "experience_requirement_met": int(match["total_duration_months"]) >= required_months,
        }
    )
    return result


def _match_role_experience(
    requirement: Any,
    matched_job_text: Any,
    role_experience: list[dict[str, Any]],
) -> dict[str, Any] | None:
    normalized_rows = [
        {
            "normalized_title": normalize_title_text(item.get("normalized_title")),
            "occupation_title": normalize_occupation_title(item.get("normalized_title")),
            "total_duration_months": int(item.get("total_duration_months") or 0),
            "most_recent_end_year": int(item.get("most_recent_end_year") or 0),
        }
        for item in role_experience
        if isinstance(item, dict) and normalize_title_text(item.get("normalized_title"))
    ]
    if not normalized_rows:
        return None

    for subject in _candidate_subjects(requirement, matched_job_text):
        normalized_subject = normalize_title_text(subject)
        occupation_subject = normalize_occupation_title(subject)
        if not normalized_subject:
            continue

        exact = next(
            (row for row in normalized_rows if row["normalized_title"] == normalized_subject),
            None,
        )
        if exact:
            return exact

        exact_occupation = next(
            (row for row in normalized_rows if row["occupation_title"] == occupation_subject),
            None,
        )
        if exact_occupation:
            return exact_occupation

        subject_roots = _root_tokens(subject)
        if len(subject_roots) < 2:
            continue
        for row in normalized_rows:
            title_roots = _root_tokens(row["normalized_title"])
            if len(title_roots) < 2:
                continue
            if subject_roots.issubset(title_roots) or title_roots.issubset(subject_roots):
                return row

    return None


def _candidate_subjects(requirement: Any, matched_job_text: Any) -> list[str]:
    subjects: list[str] = []
    seen: set[str] = set()

    for raw_text in (requirement, matched_job_text):
        text = compact_whitespace(str(raw_text or ""))
        if not text:
            continue
        for pattern in _SUBJECT_PATTERNS:
            for match in pattern.finditer(text):
                _append_subject(subjects, seen, match.group("subject"))
        stripped = _strip_duration_prefix(text)
        if stripped:
            _append_subject(subjects, seen, stripped)

    return subjects


def _append_subject(subjects: list[str], seen: set[str], raw_subject: Any) -> None:
    subject = _clean_subject(raw_subject)
    if not subject:
        return
    key = subject.lower()
    if key in seen:
        return
    seen.add(key)
    subjects.append(subject)


def _clean_subject(value: Any) -> str:
    text = compact_whitespace(str(value or ""))
    if not text:
        return ""
    text = re.sub(r"(?i)\b(?:required|preferred|essential|mandatory)\b.*$", "", text).strip(" ,.;:-")
    parts = _SUBJECT_SPLIT_PATTERN.split(text, maxsplit=1)
    text = compact_whitespace(parts[0] if parts else text)
    text = re.sub(r"(?i)^(?:as\s+)?(?:an?\s+)?", "", text)
    text = re.sub(r"(?i)\bexperience\b$", "", text).strip(" ,.;:-")
    return compact_whitespace(text)


def _strip_duration_prefix(value: str) -> str:
    text = compact_whitespace(value)
    if not text:
        return ""
    text = re.sub(
        r"(?i)^\b(?:minimum of\s+|minimum\s+|at least\s+)?\d+(?:\.\d+)?(?:\s*(?:-|to|–|—)\s*\d+(?:\.\d+)?)?\s*(?:\+)?\s*(?:years|yrs|months?)\b",
        "",
        text,
    )
    text = re.sub(r"(?i)^\b(?:of\s+)?experience\b", "", text)
    return _clean_subject(text)


def _root_tokens(value: Any) -> set[str]:
    tokens = normalize_occupation_title(value).split()
    roots: set[str] = set()
    for token in tokens:
        root = token
        for suffix in _ROOT_SUFFIXES:
            if root.endswith(suffix) and len(root) > len(suffix) + 2:
                root = root[: -len(suffix)]
                break
        roots.add(root)
    return roots
