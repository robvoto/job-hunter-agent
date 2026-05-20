"""
Read and normalize rows from the Google Sheet tab Job_Rejections.
Build an application history index.
Enrich workspace records with application_history metadata.

Company/role extraction is delegated to the LLM via extract_job_rejection_with_llm.
Sheet data is fetched via Google Sheets CSV export URL (no OAuth, no Google API client).
"""

import csv
import io
import json as _json
import re

import requests

from job_hunter_agent.global_settings import (
    is_candidate_application_history_enabled,
    get_candidate_application_history_spreadsheet_id,
    get_candidate_application_history_tab_name,
    get_candidate_application_history_required_headers,
)
from job_hunter_agent.llm_gate import (
    client as _llm_client,
    get_llm_model,
    _log_llm_call,
    _strip_json_fence,
)

_SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={tab_name}"


# ---------------------------------------------------------------------------
# Google Sheet CSV fetch
# ---------------------------------------------------------------------------


def fetch_job_rejection_sheet_rows(
    sheet_id: str | None = None,
    tab_name: str | None = None,
) -> list[dict]:
    """
    Fetch rows from the Job_Rejections Google Sheet tab via CSV export URL.

    sheet_id and tab_name default to the values in global settings when omitted.

    No OAuth or Google API client required — the sheet must be accessible
    to the running session (e.g. publicly readable or within a shared domain).

    Raises:
        RuntimeError: if the HTTP request fails.
        ValueError: if the sheet is missing any required headers.

    Returns a list of dicts keyed by the sheet header row.
    """
    resolved_id = sheet_id or get_candidate_application_history_spreadsheet_id()
    resolved_tab = tab_name or get_candidate_application_history_tab_name()
    required_headers = get_candidate_application_history_required_headers()

    url = _SHEET_CSV_URL.format(sheet_id=resolved_id, tab_name=resolved_tab)
    resp = requests.get(url, timeout=30)
    if not resp.ok:
        raise RuntimeError(
            f"Failed to fetch Job_Rejections sheet: HTTP {resp.status_code} from {url}"
        )

    reader = csv.DictReader(io.StringIO(resp.text))
    headers = reader.fieldnames or []
    missing = [h for h in required_headers if h not in headers]
    if missing:
        raise ValueError(
            f"Job_Rejections sheet is missing required headers: {missing}"
        )

    return list(reader)


def fetch_candidate_job_rejection_rows() -> list[dict]:
    """
    Return rows from the configured Job_Rejections sheet.

    Returns [] when candidate application history is disabled in global settings.
    All connection parameters (spreadsheet_id, tab_name, required_headers) are
    read from global settings — nothing is hardcoded.

    Raises:
        RuntimeError: if the HTTP request fails.
        ValueError: if the sheet is missing any required headers.
    """
    if not is_candidate_application_history_enabled():
        return []
    return fetch_job_rejection_sheet_rows()


_LLM_EXTRACTION_DEGRADED: dict = {
    "is_rejection": False,
    "company": None,
    "role": None,
    "application_status": "unknown",
    "confidence": "low",
    "evidence": "",
    "needs_review": True,
    "review_reason": "LLM extraction unavailable or invalid",
}


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------

def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

def _validate_llm_extraction(data: dict) -> dict:
    is_rejection = bool(data.get("is_rejection", False))
    company = data.get("company")
    role = data.get("role")
    application_status = str(data.get("application_status") or "unknown").strip().lower()
    confidence = str(data.get("confidence") or "low").strip().lower()
    evidence = str(data.get("evidence") or "").strip()
    needs_review = bool(data.get("needs_review", True))
    review_reason = data.get("review_reason")

    if application_status not in _ALLOWED_APPLICATION_STATUSES:
        raise ValueError(f"Invalid application_status: {application_status!r}")
    if confidence not in _ALLOWED_CONFIDENCES:
        raise ValueError(f"Invalid confidence: {confidence!r}")

    return {
        "is_rejection": is_rejection,
        "company": str(company).strip() or None if company else None,
        "role": str(role).strip() or None if role else None,
        "application_status": application_status,
        "confidence": confidence,
        "evidence": evidence,
        "needs_review": needs_review,
        "review_reason": str(review_reason).strip() or None if review_reason else None,
    }


def extract_job_rejection_with_llm(row: dict) -> dict:
    """
    Call the cheap LLM to extract rejection info from a normalized row.

    Accepts both raw sheet keys (Subject, Content) and pre-cleaned keys
    (subject, content) — build_job_rejection_extraction_prompt handles both.

    Returns the validated extraction dict, or the degraded fallback when
    the LLM is unavailable, errors, or returns unparseable output.
    """
    if _llm_client is None:
        return dict(_LLM_EXTRACTION_DEGRADED)

    prompt = build_job_rejection_extraction_prompt(row)

    try:
        model = get_llm_model()
        resp = _llm_client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": prompt["system"]},
                {"role": "user", "content": prompt["user"]},
            ],
            max_output_tokens=256,
        )
        _log_llm_call(resp, "rejection_email_extraction", model)
    except Exception as exc:
        print(f"[LLM][REJECTION_EMAIL_EXTRACTION][ERROR] {exc}")
        return dict(_LLM_EXTRACTION_DEGRADED)

    raw = str(getattr(resp, "output_text", "") or "").strip()
    if not raw:
        return dict(_LLM_EXTRACTION_DEGRADED)

    try:
        parsed = _json.loads(_strip_json_fence(raw))
        return _validate_llm_extraction(parsed)
    except Exception as exc:
        print(f"[LLM][REJECTION_EMAIL_EXTRACTION][PARSE_ERROR] {exc} | raw={raw[:200]}")
        return dict(_LLM_EXTRACTION_DEGRADED)


# ---------------------------------------------------------------------------
# Row normalisation
# ---------------------------------------------------------------------------


def normalize_job_rejection_row(row: dict) -> dict:
    """
    Clean a raw Job_Rejections sheet row and run LLM extraction.

    Raw sheet fields are preserved. LLM extraction results are merged
    under llm_* keys. No regex derivation, no platform/vendor lists.

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
    extraction = extract_job_rejection_with_llm(cooked)
    cooked["llm_company"] = extraction["company"]
    cooked["llm_role"] = extraction["role"]
    cooked["llm_is_rejection"] = extraction["is_rejection"]
    cooked["llm_application_status"] = extraction["application_status"]
    cooked["llm_confidence"] = extraction["confidence"]
    cooked["llm_evidence"] = extraction["evidence"]
    cooked["llm_needs_review"] = extraction["needs_review"]
    cooked["llm_review_reason"] = extraction["review_reason"]
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
        # Use LLM-extracted fields when available; fall back to raw_company.
        candidate_company = row.get("llm_company") or row.get("raw_company") or ""
        candidate_role = row.get("llm_role") or ""

        company_score = _company_match_score(job_company, candidate_company)

        # If company doesn't match at all, try a direct name scan of subject/content.
        # Subject is stronger evidence than body text, so scores differ.
        if company_score < 0.5:
            needle = _normalize_name(job_company)
            if needle:
                if needle in _normalize_name(row.get("subject", "")):
                    company_score = 0.8
                elif needle in _normalize_name(row.get("content", "")):
                    company_score = 0.75

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
