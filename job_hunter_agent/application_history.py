"""Application rejection history enrichment.

Pure functions — no Google API calls. Reads rows from the Job_Rejections Google
Sheet tab and attaches application_history metadata to matching workspace records.
Scoring, filters, and hard-rejection logic are not touched.
"""

from __future__ import annotations

import re
from typing import Optional

from job_hunter_agent.company_normalization import company_name_token_overlap_match
from job_hunter_agent.record_schema import RECORD_APPLICATION_HISTORY_KEY

_NOISE_TOKENS = frozenset(
    {
        "oraclecloud",
        "workflow",
        "workday",
        "greenhouse",
        "smartrecruiters",
        "seek",
        "pageuppeople",
        "workablemail",
        "no-reply",
        "noreply",
        "donotreply",
    }
)

# Patterns yielding (role, company) — ordered most-specific first.
# Use non-greedy role capture (.+?) and greedy company capture (.+)
# because we process one line at a time and strip trailing punctuation.
_ROLE_COMPANY_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"application\s+update\s+for\s+(.+?)\s+at\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:your\s+)?application\s+for(?:\s+the)?\s+(?:role\s+of\s+|position\s+of\s+)?(.+?)\s+(?:at|with)\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"applied\s+for(?:\s+the)?\s+(?:role\s+of\s+|position\s+of\s+)?(.+?)\s+(?:at|with)\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"position\s+of\s+(.+?)\s+with\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(.+?)\s+within\s+(.+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(.+?)\s+with\s+(.+)",
        re.IGNORECASE,
    ),
]

_ROLE_ONLY_PATTERNS: list[re.Pattern] = [
    re.compile(r"Role:\s*(.+)", re.IGNORECASE),
    re.compile(r"position:\s*(.+)", re.IGNORECASE),
]

_COMPANY_ONLY_PATTERNS: list[re.Pattern] = [
    re.compile(r"position\s+at\s+(.+)", re.IGNORECASE),
]


def is_platform_or_sender_noise(value: str) -> bool:
    """Return True if value is an ATS/platform name, email, or system sender rather than a real company."""
    if not value or not value.strip():
        return True
    v = value.strip().lower()
    if "@" in v:
        return True
    # Plain domain: word-chars/dots/hyphens followed by a 2+-char TLD
    if re.match(r"^[\w.-]+\.[a-z]{2,}$", v):
        return True
    for token in _NOISE_TOKENS:
        if token in v:
            return True
    return False


def _strip_trailing(text: str) -> str:
    return text.strip().rstrip(".,! \t")


def _try_role_company_patterns(text: str) -> Optional[tuple[str, str, str]]:
    """Search text line-by-line; return (role, company, evidence) or None."""
    lines = text.splitlines() if text else []
    if not lines:
        lines = [text]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        for pattern in _ROLE_COMPANY_PATTERNS:
            m = pattern.search(line)
            if not m:
                continue
            role = _strip_trailing(m.group(1))
            company = _strip_trailing(m.group(2))
            if role and company:
                return role, company, m.group(0).strip()
    return None


def _try_role_only_patterns(text: str) -> Optional[tuple[str, str]]:
    """Return (role, evidence) or None."""
    lines = text.splitlines() if text else [text]
    for line in lines:
        line = line.strip()
        for pattern in _ROLE_ONLY_PATTERNS:
            m = pattern.search(line)
            if m:
                role = _strip_trailing(m.group(1))
                if role:
                    return role, m.group(0).strip()
    return None


def _try_company_only_patterns(text: str) -> Optional[tuple[str, str]]:
    """Return (company, evidence) or None."""
    lines = text.splitlines() if text else [text]
    for line in lines:
        line = line.strip()
        for pattern in _COMPANY_ONLY_PATTERNS:
            m = pattern.search(line)
            if m:
                company = _strip_trailing(m.group(1))
                if company:
                    return company, m.group(0).strip()
    return None


def derive_company_and_role(subject: str, content: str, raw_company: str) -> dict:
    """Extract company and role from subject/content; fall back to raw_company only when it is not platform noise."""
    raw_noise = is_platform_or_sender_noise(raw_company)

    # Highest priority: full (role, company) from subject, then content
    for text, src in [(subject or "", "subject"), (content or "", "content")]:
        result = _try_role_company_patterns(text)
        if result:
            role, company, evidence = result
            return {
                "derived_company": company,
                "derived_role": role,
                "company_confidence": "high",
                "role_confidence": "high",
                "evidence": f"{src}: {evidence}",
            }

    # Partial extraction — collect role and company independently
    derived_role = ""
    role_confidence = "low"
    role_evidence = ""

    derived_company = "" if raw_noise else raw_company.strip()
    company_confidence = "low" if raw_noise else "medium"
    company_evidence = f"raw_company: {raw_company}" if not raw_noise else ""

    for text, src in [(subject or "", "subject"), (content or "", "content")]:
        if not derived_role:
            role_result = _try_role_only_patterns(text)
            if role_result:
                derived_role, ev = role_result
                role_confidence = "medium"
                role_evidence = f"{src}: {ev}"

        if not derived_company or company_confidence == "low":
            company_result = _try_company_only_patterns(text)
            if company_result:
                derived_company, ev = company_result
                company_confidence = "medium"
                company_evidence = f"{src}: {ev}"

    combined_evidence = (
        "; ".join(filter(None, [role_evidence, company_evidence])) or "no pattern matched"
    )

    return {
        "derived_company": derived_company,
        "derived_role": derived_role,
        "company_confidence": company_confidence,
        "role_confidence": role_confidence,
        "evidence": combined_evidence,
    }


def normalize_rejection_row(row: dict) -> dict:
    """Normalize a raw Google Sheet row into a structured rejection record."""
    raw_company = str(row.get("Company") or "").strip()
    subject = str(row.get("Subject") or "").strip()
    content = str(row.get("Content") or "").strip()

    derived = derive_company_and_role(subject, content, raw_company)

    return {
        "run_date": str(row.get("Run Date") or "").strip(),
        "raw_company": raw_company,
        "from": str(row.get("From") or "").strip(),
        "subject": subject,
        "content": content,
        "thread_id": str(row.get("Thread ID") or "").strip(),
        "message_id": str(row.get("Message ID") or "").strip(),
        "status": str(row.get("Status") or "").strip(),
        **derived,
    }


_MATCH_STOPS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "for",
        "in",
        "at",
        "with",
        "to",
        "s",
        # common business entity suffixes that add no discriminating value
        "corp",
        "corporation",
        "pty",
        "ltd",
        "limited",
        "inc",
        "llc",
        "co",
        "company",
        "group",
        "holdings",
        "services",
        "solutions",
        "australia",
        "global",
    }
)


def _normalize_tokens(text: str) -> set[str]:
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower())
    tokens = set(re.sub(r"\s+", " ", cleaned).strip().split())
    return tokens - _MATCH_STOPS


def _weakly_matches(a: str, b: str) -> bool:
    if not a or not b:
        return False
    a_tok = _normalize_tokens(a)
    b_tok = _normalize_tokens(b)
    if not a_tok or not b_tok:
        return False
    overlap = len(a_tok & b_tok)
    return overlap >= max(1, min(len(a_tok), len(b_tok)) // 2)


def match_application_history(job_record: dict, rejection_rows: list[dict]) -> dict | None:
    """Return the best matching rejection row for a job record, or None.

    A full match (company + title) is preferred over a company-only match.
    """
    job_company = str(job_record.get("company") or "").strip()
    job_title = str(job_record.get("title") or "").strip()

    best_score = 0
    best: dict | None = None

    for row in rejection_rows:
        derived_company = str(row.get("derived_company") or "").strip()
        derived_role = str(row.get("derived_role") or "").strip()

        company_match = company_name_token_overlap_match(job_company, derived_company)
        title_match = _weakly_matches(job_title, derived_role)

        score = (2 if company_match else 0) + (1 if title_match else 0)
        if score > best_score:
            best_score = score
            best = row

    # Require at least a company match
    if best_score < 2:
        return None

    return best


def enrich_records_with_application_history(
    records: list[dict], rejection_rows: list[dict]
) -> list[dict]:
    """Add application_history to matching records. Records are not removed or reordered."""
    normalized_rows = [
        row if "derived_company" in row else normalize_rejection_row(row) for row in rejection_rows
    ]

    enriched = []
    for record in records:
        match = match_application_history(record, normalized_rows)
        if match is not None:
            record = dict(record)
            record[RECORD_APPLICATION_HISTORY_KEY] = match
        enriched.append(record)

    return enriched
