"""
Maintain the local candidate application history store.
The runtime workspace reads from the local JSON file only.
Google Sheet access exists only as an explicit import utility.

Use `python -m job_hunter_agent.candidate_application_history import-from-sheet`
to refresh the local store from the configured Job_Rejections sheet.

Company/role extraction is delegated to the LLM via extract_job_rejection_with_llm.
Sheet data is fetched via Google Sheets CSV export URL (no OAuth, no Google API client).
"""

import argparse
import csv
import hashlib
import io
import json as _json
import re
from datetime import datetime, timezone

import requests

from job_hunter_agent.global_settings import (
    get_candidate_application_history_required_headers,
    get_candidate_application_history_spreadsheet_id,
    get_candidate_application_history_tab_name,
    is_candidate_application_history_enabled,
)
from job_hunter_agent.io_utils import load_json_list, save_json
from job_hunter_agent.llm_gate import (
    _log_llm_call,
    _strip_json_fence,
    get_llm_model,
)
from job_hunter_agent.llm_gate import (
    client as _llm_client,
)
from job_hunter_agent.paths import (
    CANDIDATE_APPLICATION_HISTORY_CACHE_PATH,
    get_candidate_application_history_path,
)
from job_hunter_agent.text_processing import compact_whitespace

_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={tab_name}"
)
_CANDIDATE_APPLICATION_HISTORY_PATH = get_candidate_application_history_path()
_CANDIDATE_HISTORY_STATUS_REJECTION = "rejection"
_CANDIDATE_HISTORY_SOURCE_MANUAL = "manual"
_CANDIDATE_HISTORY_SOURCE_SHEET_IMPORT = "sheet_import"
_CLI_COMMAND_IMPORT_FROM_SHEET = "import-from-sheet"
_CLI_COMMAND_STATUS = "status"
_OUTPUT_PREFIX = "[candidate_application_history]"
_SUMMARY_FIELD_ORDER = (
    "rows_fetched",
    "rows_loaded_from_cache",
    "rows_sent_to_llm",
    "rows_marked_rejection",
    "rows_needing_review",
    "records_added",
    "records_updated",
    "records_total",
)
_CACHE_KEY_FIELDS = (
    "Message ID",
    "Thread ID",
    "Run Date",
    "Company",
    "From",
    "Subject",
    "Content",
    "Status",
)


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
        raise ValueError(f"Job_Rejections sheet is missing required headers: {missing}")

    return list(reader)


def fetch_candidate_job_rejection_rows() -> list[dict]:
    """
    Return rows from the configured Job_Rejections sheet for explicit import.

    This is not used by the normal workspace startup path.
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

_ALLOWED_APPLICATION_STATUSES = frozenset(
    {
        "rejection",
        "possible_rejection",
        "not_rejection",
        "unknown",
    }
)
_ALLOWED_CONFIDENCES = frozenset({"high", "medium", "low"})


# ---------------------------------------------------------------------------
# Text cleaning helpers
# ---------------------------------------------------------------------------


def _clean(value: object) -> str:
    return compact_whitespace(value)


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
    value = re.sub(r"\b(pty|ltd|limited|inc|co|corp|group|australia|au)\b", "", value)
    return compact_whitespace(value)


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


def match_job_application_history(job_record: dict, rejection_rows: list[dict]) -> dict | None:
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

    user_message = f"Sender: {sender}\nSubject: {subject}\n\nContent:\n{content[:3000]}"

    return {
        "system": _EXTRACTION_SYSTEM_PROMPT,
        "user": user_message,
        "response_format": "json",
    }


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _make_cache_key(raw_row: dict) -> str:
    parts = "|".join(str(raw_row.get(field) or "").strip() for field in _CACHE_KEY_FIELDS)
    return f"row:{hashlib.sha256(parts.encode()).hexdigest()[:16]}"


def _load_cache() -> dict:
    if not CANDIDATE_APPLICATION_HISTORY_CACHE_PATH.exists():
        return {}
    try:
        return _json.loads(CANDIDATE_APPLICATION_HISTORY_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache: dict) -> None:
    CANDIDATE_APPLICATION_HISTORY_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATE_APPLICATION_HISTORY_CACHE_PATH.write_text(
        _json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _make_failed_normalized_row(raw_row: dict, reason: str) -> dict:
    return {
        "run_date": _clean(raw_row.get("Run Date")),
        "raw_company": _clean(raw_row.get("Company")),
        "from": _clean(raw_row.get("From")),
        "subject": _clean(raw_row.get("Subject")),
        "content": _clean(raw_row.get("Content")),
        "thread_id": _clean(raw_row.get("Thread ID")),
        "message_id": _clean(raw_row.get("Message ID")),
        "status": _clean(raw_row.get("Status")),
        "llm_company": None,
        "llm_role": None,
        "llm_is_rejection": False,
        "llm_application_status": "unknown",
        "llm_confidence": "low",
        "llm_evidence": "",
        "llm_needs_review": True,
        "llm_review_reason": f"Row processing failed: {reason}",
    }


# ---------------------------------------------------------------------------
# Local store
# ---------------------------------------------------------------------------


def _candidate_history_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _load_candidate_application_history_store() -> list[dict]:
    return load_json_list(_CANDIDATE_APPLICATION_HISTORY_PATH)


def load_candidate_application_history() -> list[dict]:
    rows = _load_candidate_application_history_store()
    return [row for row in rows if isinstance(row, dict)]


def save_candidate_application_history(records: list[dict]) -> None:
    save_json(
        _CANDIDATE_APPLICATION_HISTORY_PATH,
        [dict(record) for record in records if isinstance(record, dict)],
    )


def _candidate_history_store_entry_id(entry: dict) -> str:
    current_id = _clean(entry.get("id"))
    if current_id:
        return current_id
    parts = "|".join(
        [
            _clean(entry.get("date")),
            _clean(entry.get("company")),
            _clean(entry.get("role")),
            _clean(entry.get("source")),
            _clean(entry.get("job_key")),
            _clean(entry.get("evidence")),
        ]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def _candidate_history_import_record_keys(record: dict) -> tuple[str, str]:
    message_id = _clean(record.get("message_id"))
    parts = "|".join(
        [
            _clean(record.get("date")),
            _clean(record.get("company")),
            _clean(record.get("role")),
        ]
    )
    fallback_key = f"company_role_date:{hashlib.sha256(parts.encode('utf-8')).hexdigest()[:16]}"
    if message_id:
        return f"message_id:{message_id}", fallback_key
    return fallback_key, fallback_key


def _candidate_history_store_entry_to_runtime(entry: dict) -> dict:
    message_id = _clean(entry.get("message_id")) or None
    normalized = {
        "id": _clean(entry.get("id")),
        "date": _clean(entry.get("date")),
        "company": _clean(entry.get("company")),
        "role": _clean(entry.get("role")),
        "status": _clean(entry.get("status")).lower(),
        "recruiter": entry.get("recruiter"),
        "source": _clean(entry.get("source")),
        "evidence": _clean(entry.get("evidence")),
        "job_key": entry.get("job_key") if entry.get("job_key") is not None else None,
        "created_at": _clean(entry.get("created_at")),
        "updated_at": _clean(entry.get("updated_at")),
        "confidence": _clean(entry.get("confidence")).lower(),
        "needs_review": bool(entry.get("needs_review", False)),
        "review_reason": _clean(entry.get("review_reason")) or None,
    }
    if (
        not normalized["id"]
        or not normalized["date"]
        or not normalized["company"]
        or not normalized["role"]
    ):
        raise ValueError("candidate history store entry is missing required fields")
    if normalized["status"] != _CANDIDATE_HISTORY_STATUS_REJECTION:
        raise ValueError(
            f"candidate history store entry has unsupported status: {normalized['status']!r}"
        )
    if normalized["source"] not in {
        _CANDIDATE_HISTORY_SOURCE_MANUAL,
        _CANDIDATE_HISTORY_SOURCE_SHEET_IMPORT,
    }:
        raise ValueError(
            f"candidate history store entry has unsupported source: {normalized['source']!r}"
        )

    runtime = dict(normalized)
    runtime.update(
        {
            "raw_company": normalized["company"],
            "subject": normalized["evidence"],
            "content": normalized["evidence"],
            "thread_id": normalized["id"],
            "message_id": message_id,
            "run_date": normalized["date"],
            "llm_company": normalized["company"],
            "llm_role": normalized["role"],
            "llm_is_rejection": True,
            "llm_application_status": _CANDIDATE_HISTORY_STATUS_REJECTION,
            "llm_confidence": normalized["confidence"],
            "llm_evidence": normalized["evidence"],
            "llm_needs_review": normalized["needs_review"],
            "llm_review_reason": normalized["review_reason"],
        }
    )
    return runtime


def _candidate_history_sheet_row_to_store_entry(normalized_row: dict, *, source: str) -> dict:
    status = _CANDIDATE_HISTORY_STATUS_REJECTION
    needs_review = bool(normalized_row.get("llm_needs_review", True))
    confidence = _clean(normalized_row.get("llm_confidence")).lower()
    evidence = _clean(normalized_row.get("llm_evidence"))
    company = _clean(normalized_row.get("llm_company") or normalized_row.get("raw_company"))
    role = _clean(normalized_row.get("llm_role"))
    created_at = _candidate_history_now()
    message_id = _clean(normalized_row.get("message_id"))
    if message_id:
        identifier = message_id
    else:
        identifier = _candidate_history_import_record_keys(
            {
                "date": _clean(normalized_row.get("run_date")),
                "company": company,
                "role": role,
                "message_id": "",
            }
        )[0].split(":", 1)[1]
    return {
        "id": identifier,
        "message_id": message_id or None,
        "date": _clean(normalized_row.get("run_date")),
        "company": company,
        "role": role,
        "status": status,
        "recruiter": None,
        "source": source,
        "evidence": evidence,
        "job_key": normalized_row.get("job_key")
        if normalized_row.get("job_key") is not None
        else None,
        "created_at": created_at,
        "updated_at": created_at,
        "confidence": confidence,
        "needs_review": needs_review,
        "review_reason": _clean(normalized_row.get("llm_review_reason")) or None,
    }


def add_candidate_rejection_record(record: dict) -> dict:
    now = _candidate_history_now()
    stored = {
        "id": _candidate_history_store_entry_id(
            {
                "date": _clean(record.get("date") or record.get("run_date")),
                "company": _clean(record.get("company")),
                "role": _clean(record.get("role")),
                "source": _CANDIDATE_HISTORY_SOURCE_MANUAL,
                "job_key": record.get("job_key"),
                "evidence": _clean(record.get("evidence")),
                "id": record.get("id"),
            }
        ),
        "date": _clean(record.get("date") or record.get("run_date")),
        "company": _clean(record.get("company")),
        "role": _clean(record.get("role")),
        "status": _CANDIDATE_HISTORY_STATUS_REJECTION,
        "recruiter": record.get("recruiter") if record.get("recruiter") is not None else None,
        "source": _CANDIDATE_HISTORY_SOURCE_MANUAL,
        "evidence": _clean(record.get("evidence")),
        "job_key": record.get("job_key") if record.get("job_key") is not None else None,
        "created_at": now,
        "updated_at": now,
    }
    existing = load_candidate_application_history()
    existing.append(stored)
    save_candidate_application_history(existing)
    return stored


def _candidate_history_import_sheet_rows() -> tuple[list[dict], dict]:
    if not is_candidate_application_history_enabled():
        return [], {
            "enabled": False,
            "rows_fetched": 0,
            "rows_loaded_from_cache": 0,
            "rows_sent_to_llm": 0,
            "rows_marked_rejection": 0,
            "rows_needing_review": 0,
            "failures": 0,
        }

    raw_rows = fetch_candidate_job_rejection_rows()
    cache = _load_cache()
    updated = False
    imported_store_rows: list[dict] = []
    cache_hits = 0
    extracted_count = 0
    failure_count = 0

    for raw_row in raw_rows:
        cache_key = _make_cache_key(raw_row)
        if cache_key in cache:
            normalized_row = cache[cache_key]
            cache_hits += 1
        else:
            try:
                normalized_row = normalize_job_rejection_row(raw_row)
            except Exception as exc:
                normalized_row = _make_failed_normalized_row(raw_row, str(exc))
                failure_count += 1
            else:
                extracted_count += 1
            cache[cache_key] = normalized_row
            updated = True
        imported_store_rows.append(
            _candidate_history_sheet_row_to_store_entry(
                normalized_row, source=_CANDIDATE_HISTORY_SOURCE_SHEET_IMPORT
            )
        )

    if updated:
        _save_cache(cache)

    summary = {
        "enabled": True,
        "rows_fetched": len(raw_rows),
        "rows_loaded_from_cache": cache_hits,
        "rows_sent_to_llm": extracted_count,
        "rows_marked_rejection": sum(
            1 for row in imported_store_rows if row["status"] == _CANDIDATE_HISTORY_STATUS_REJECTION
        ),
        "rows_needing_review": sum(
            1 for row in imported_store_rows if bool(row.get("needs_review"))
        ),
        "failures": failure_count,
    }
    return imported_store_rows, summary


def import_candidate_rejections_from_sheet() -> dict:
    imported_rows, summary = _candidate_history_import_sheet_rows()
    if not summary["enabled"]:
        print("[candidate_application_history] disabled")
        return summary | {
            "records_added": 0,
            "records_updated": 0,
            "records_total": len(load_candidate_application_history()),
        }

    existing_rows = load_candidate_application_history()
    existing_by_primary_key = {}
    existing_by_fallback_key = {}
    merged_rows = []
    for row in existing_rows:
        if not isinstance(row, dict):
            continue
        primary_key, fallback_key = _candidate_history_import_record_keys(row)
        existing_by_primary_key[primary_key] = row
        existing_by_fallback_key[fallback_key] = row
        merged_rows.append(row)

    records_added = 0
    records_updated = 0
    for row in imported_rows:
        primary_key, fallback_key = _candidate_history_import_record_keys(row)
        existing = existing_by_primary_key.get(primary_key) or existing_by_fallback_key.get(
            fallback_key
        )
        if existing is None:
            merged_rows.append(row)
            existing_by_primary_key[primary_key] = row
            existing_by_fallback_key[fallback_key] = row
            records_added += 1
            continue
        existing.update(row)
        existing["created_at"] = existing.get("created_at") or row["created_at"]
        existing["updated_at"] = row["updated_at"]
        existing_by_primary_key[primary_key] = existing
        existing_by_fallback_key[fallback_key] = existing
        records_updated += 1

    save_candidate_application_history(merged_rows)
    return summary | {
        "records_added": records_added,
        "records_updated": records_updated,
        "records_total": len(merged_rows),
    }


def load_candidate_job_rejection_history() -> list[dict]:
    """
    Load candidate application history from the local runtime store.

    Google Sheets are no longer the startup source of truth. Use the explicit
    import command to refresh the local store from the configured sheet.
    """
    if not is_candidate_application_history_enabled():
        print("[candidate_application_history] disabled")
        return []

    store_rows = load_candidate_application_history()
    runtime_rows: list[dict] = []
    invalid_count = 0
    for row in store_rows:
        try:
            runtime_rows.append(_candidate_history_store_entry_to_runtime(row))
        except Exception as exc:
            invalid_count += 1
            print(f"[candidate_application_history] invalid store row skipped: {exc}")

    print(f"[candidate_application_history] local store rows loaded: {len(runtime_rows)}")
    if invalid_count:
        print(f"[candidate_application_history] invalid store rows skipped: {invalid_count}")
    return runtime_rows


# ---------------------------------------------------------------------------
# Workspace enrichment
# ---------------------------------------------------------------------------


def enrich_records_with_application_history(
    records: list[dict], rejection_rows: list[dict]
) -> list[dict]:
    """
    Add candidate_application_history to each record that has a matching rejection row.

    Records with no match are returned unchanged (candidate_application_history absent).
    Record order is preserved. No records are removed.
    """
    enriched = []
    for record in records:
        match = match_job_application_history(record, rejection_rows)
        if match is not None:
            enriched.append({**record, "candidate_application_history": match})
        else:
            enriched.append(record)
    return enriched


def _print_summary(summary: dict, field_order: tuple[str, ...]) -> None:
    for field in field_order:
        print(f"{_OUTPUT_PREFIX} {field}: {summary.get(field, 0)}")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect the local candidate application history store or sync it "
            "from the configured Job_Rejections Google Sheet."
        )
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = False

    import_parser = subparsers.add_parser(
        _CLI_COMMAND_IMPORT_FROM_SHEET,
        help="Refresh the local JSON store from the configured Job_Rejections sheet.",
    )
    import_parser.set_defaults(command=_CLI_COMMAND_IMPORT_FROM_SHEET)

    status_parser = subparsers.add_parser(
        _CLI_COMMAND_STATUS,
        help="Print a summary of the local JSON store.",
    )
    status_parser.set_defaults(command=_CLI_COMMAND_STATUS)
    return parser


def _print_local_store_summary() -> dict:
    rows = load_candidate_application_history()
    summary = {
        "rows_fetched": 0,
        "rows_loaded_from_cache": 0,
        "rows_sent_to_llm": 0,
        "rows_marked_rejection": sum(
            1 for row in rows if row.get("status") == _CANDIDATE_HISTORY_STATUS_REJECTION
        ),
        "rows_needing_review": sum(1 for row in rows if bool(row.get("needs_review"))),
        "records_added": 0,
        "records_updated": 0,
        "records_total": len(rows),
    }
    _print_summary(summary, _SUMMARY_FIELD_ORDER)
    return summary


def _print_import_summary() -> dict:
    summary = import_candidate_rejections_from_sheet()
    _print_summary(summary, _SUMMARY_FIELD_ORDER)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = _build_argument_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == _CLI_COMMAND_IMPORT_FROM_SHEET:
            _print_import_summary()
        else:
            _print_local_store_summary()
    except Exception as exc:
        print(f"{_OUTPUT_PREFIX} unavailable: {exc}")
        _print_summary({field: 0 for field in _SUMMARY_FIELD_ORDER}, _SUMMARY_FIELD_ORDER)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
