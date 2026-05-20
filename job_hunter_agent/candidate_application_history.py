"""
Read and normalize rows from the Google Sheet tab Job_Rejections.
Build an application history index.
Enrich workspace records with application_history metadata.

No Google API calls in this module — pure data transformation only.
Company and role extraction is delegated to the LLM via build_job_rejection_extraction_prompt.
"""

import re


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


# ---------------------------------------------------------------------------
# Row normalisation
# ---------------------------------------------------------------------------


def normalize_job_rejection_row(row: dict) -> dict:
    """
    Prepare a single raw row from the Job_Rejections sheet for LLM extraction.

    Cleans whitespace on all text fields and embeds the LLM prompt payload.
    Company and role are not derived here — that is delegated to the LLM.

    Expected input keys: Run Date, Company, From, Subject, Content,
                         Thread ID, Message ID, Status
    """
    cooked = {
        "run_date": _clean(row.get("Run Date")),
        "raw_company": _clean(row.get("Company")),
        "from": _clean(row.get("From")),
        "subject": _clean(row.get("Subject")),
        "content": _clean(row.get("Content")),
        "thread_id": _clean(row.get("Thread ID")),
        "message_id": _clean(row.get("Message ID")),
        "status": _clean(row.get("Status")),
    }
    cooked["llm_extraction_prompt"] = build_job_rejection_extraction_prompt(cooked)
    cooked["llm_extraction_status"] = "pending"
    return cooked


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _normalize_name(value: str) -> str:
    """Lower-case, strip punctuation and common noise words for loose comparison."""
    value = value.lower()
    value = re.sub(r"[^\w\s]", " ", value)
    # Strip common legal / org suffixes that differ between job ads and emails.
    value = re.sub(
        r"\b(pty|ltd|limited|inc|co|corp|group|australia|au)\b", "", value
    )
    return re.sub(r"\s+", " ", value).strip()


def _company_match_score(job_company: str, rejection_company: str) -> float:
    """Return 0.0–1.0 how well two company names agree."""
    a = _normalize_name(job_company)
    b = _normalize_name(rejection_company)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Partial containment — shorter name appears inside longer.
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter and shorter in longer:
        return 0.8
    # Word overlap ratio.
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    return overlap / max(len(words_a), len(words_b))


def _role_match_score(job_title: str, rejection_role: str) -> float:
    """Return 0.0–1.0 how well two role strings agree."""
    a = _normalize_name(job_title)
    b = _normalize_name(rejection_role)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    overlap = len(words_a & words_b)
    return overlap / max(len(words_a), len(words_b))


def match_job_application_history(
    job_record: dict, rejection_rows: list[dict]
) -> dict | None:
    """
    Find the best-matching rejection row for a job record.

    job_record expected keys: "company" (str), "title" (str).
    rejection_rows must already be normalized via normalize_job_rejection_row().

    Returns the best-matching row dict (with added "_match_score") or None if
    no row clears the minimum threshold.
    """
    job_company = str(job_record.get("company") or "")
    job_title = str(job_record.get("title") or "")

    best_row = None
    best_score = 0.0

    for row in rejection_rows:
        # Use LLM-extracted fields when available; fall back to raw_company for pending rows.
        candidate_company = row.get("derived_company") or row.get("raw_company") or ""
        candidate_role = row.get("derived_role") or ""

        company_score = _company_match_score(job_company, candidate_company)

        # If company doesn't match at all, skip — no point checking role.
        if company_score < 0.5:
            # Try one more: scan subject/content for job_company directly.
            subject = row.get("subject", "")
            content = row.get("content", "")
            if _normalize_name(job_company) in _normalize_name(subject + " " + content):
                company_score = 0.6

        if company_score < 0.5:
            continue

        role_score = _role_match_score(job_title, candidate_role) if candidate_role else 0.0

        # Combined score: company is the stronger signal.
        combined = 0.7 * company_score + 0.3 * role_score

        if combined > best_score:
            best_score = combined
            best_row = row

    if best_row is None or best_score < 0.5:
        return None

    return {**best_row, "_match_score": round(best_score, 3)}


# ---------------------------------------------------------------------------
# LLM prompt builder
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM_PROMPT = """\
You are extracting structured data from a job-application email.

Rules:
- Use the Subject and Content fields as your primary evidence.
- Do not trust the sender email address or domain as the employer name unless
  the email body explicitly confirms it is the company.
- Do not guess. If a field is unclear, omit it (return null) and set
  confidence to "low" and needs_review to true.
- Return JSON only — no prose, no markdown fences.

Output schema (all keys required):
{
  "is_rejection": <bool>,
  "company": <string or null>,
  "role": <string or null>,
  "application_status": <"rejection" | "possible_rejection" | "not_rejection" | "unknown">,
  "confidence": <"high" | "medium" | "low">,
  "evidence": <short quote or phrase from subject/content that supports your answer>,
  "needs_review": <bool>,
  "review_reason": <string or null>
}
"""


def build_job_rejection_extraction_prompt(row: dict) -> dict:
    """
    Build the LLM prompt payload for a single rejection-sheet row.

    Returns a dict ready to pass to an LLM caller:
        {
          "system": str,
          "user": str,
          "response_format": "json",
        }

    Does not call the LLM.
    """
    subject = str(row.get("subject") or row.get("Subject") or "").strip()
    content = str(row.get("content") or row.get("Content") or "").strip()
    sender = str(row.get("from") or row.get("From") or "").strip()

    user_message = (
        f"Sender: {sender}\n"
        f"Subject: {subject}\n\n"
        f"Content:\n{content[:3000]}"
    )

    return {
        "system": _EXTRACTION_SYSTEM_PROMPT,
        "user": user_message,
        "response_format": "json",
    }


# ---------------------------------------------------------------------------
# Workspace enrichment
# ---------------------------------------------------------------------------


def enrich_records_with_application_history(
    records: list[dict], rejection_rows: list[dict]
) -> list[dict]:
    """
    Add application_history to each record that has a matching rejection row.

    Records with no match are returned unchanged (application_history absent).
    Record order is preserved. No records are removed.
    """
    enriched = []
    for record in records:
        match = match_job_application_history(record, rejection_rows)
        if match is not None:
            enriched.append({**record, "application_history": match})
        else:
            enriched.append(record)
    return enriched
