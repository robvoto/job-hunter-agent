"""Current direct-page job-source connector and dashboard builder.

Main goals:
- fetch current job listings from the active source implementation
- apply deterministic filtering and optional LLM fit review
- persist audit data, run stats, review insights, and dashboard HTML

Notes:
- this filename is historical; in product and documentation language we prefer
  "source connector" over "scraper"
- the current implementation is SEEK-specific, but the normalized record shape
  is intended to be reusable for additional sources later
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from config import MAX_PAGES_CAP, OUTPUT_HTML, SEEK_URL
from filters import passes_content_filters, passes_title_filters
from llm_gate import build_llm_cache_key, llm_is_enabled, llm_should_consider
from profile_store import get_search_settings, load_profile
from review_insights import build_review_data, extract_detected_skills
from utils import (
    extract_salary,
    extract_work_mode,
    parse_seek_posted_age_days,
    safe_html,
    set_page_param,
    set_query_param,
)


SELECTOR_CARDS = 'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
SELECTOR_TITLE = '[data-automation="jobTitle"]'
SELECTOR_COMPANY = '[data-automation="jobCompany"]'
SELECTOR_POSTED = '[data-automation="jobListingDate"]'
SELECTOR_LOCATION = '[data-automation="jobLocation"]'
SELECTOR_CARD_SALARY = '[data-automation="jobSalary"]'
SELECTOR_SHORT_DESCRIPTION = '[data-automation="jobShortDescription"]'
SELECTOR_DETAILS = '[data-automation="jobAdDetails"]'

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
MAX_LLM_CHARS = 3000
ARCHIVE_STALE_AFTER_DAYS = 15
HIDDEN_REVIEW_DAYS = 30
AUTO_REFRESH_SECONDS = 60
LLM_CACHE_PATH = DATA_DIR / "llm_cache.json"
DEBUG_JSON_PATH = OUTPUT_DIR / "seek_results.json"
JOB_HISTORY_PATH = DATA_DIR / "job_history.json"
RUN_STATS_PATH = OUTPUT_DIR / "seek_run_stats.json"
REVIEW_DATA_PATH = OUTPUT_DIR / "seek_review_data.json"
SEEK_JOBS_BASE_URL = "https://www.seek.com.au/jobs"
KEEP_SNAPSHOT_FIELDS = (
    "title",
    "company",
    "url",
    "posted",
    "posted_age_days",
    "salary",
    "work_mode",
    "location",
    "work_type",
    "teaser",
    "title_reason",
    "content_reason",
    "llm_decision",
    "search_location",
    "search_keywords",
)


def salary_sort_value(value: str) -> float:
    if not value or value == "N/A":
        return 0.0
    text = value.lower().replace(",", "").strip()
    match = re.search(r"(\d+(?:\.\d+)?)\s*k", text)
    if match:
        return float(match.group(1)) * 1000
    match = re.search(r"\$(\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return 0.0


def normalize_posted_text(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return "N/A"
    return re.sub(r"^\s*posted\s+", "", text, flags=re.IGNORECASE).strip()


def extract_posted_text_from_card(card_text: str) -> str:
    text = normalize_posted_text(card_text)
    match = re.search(
        r"\b(today|yesterday|\d+\s*[mhdy](?:\s*ago)?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return normalize_posted_text(match.group(1))
    return "N/A"


def configure_console_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json_dict(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def load_json_list(path: Path) -> List[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except Exception:
        pass
    return []


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_llm_cache() -> Dict[str, str]:
    raw = load_json_dict(LLM_CACHE_PATH)
    return {str(k): str(v) for k, v in raw.items()}


def save_llm_cache(cache: Dict[str, str]) -> None:
    save_json(LLM_CACHE_PATH, cache)


def load_job_history() -> Dict[str, dict]:
    return load_json_dict(JOB_HISTORY_PATH)


def save_job_history(history: Dict[str, dict]) -> None:
    save_json(JOB_HISTORY_PATH, history)


def write_debug_json(records: List[dict]) -> None:
    save_json(DEBUG_JSON_PATH, records)


def write_run_stats(payload: dict) -> None:
    save_json(RUN_STATS_PATH, payload)


def write_review_data(payload: dict) -> None:
    save_json(REVIEW_DATA_PATH, payload)


def build_full_url(relative_or_full_url: Optional[str]) -> Optional[str]:
    if not relative_or_full_url:
        return None
    return urljoin("https://www.seek.com.au", relative_or_full_url)


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


def extract_work_type(card_text: str) -> str:
    match = re.search(r"This is a ([^\n]+?) job", card_text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return "N/A"


def extract_card_metadata(card) -> dict:
    location_values = [
        (element.inner_text() or "").strip()
        for element in card.query_selector_all(SELECTOR_LOCATION)
    ]
    salary_el = card.query_selector(SELECTOR_CARD_SALARY)
    teaser_el = card.query_selector(SELECTOR_SHORT_DESCRIPTION)
    salary_text = salary_el.inner_text().strip() if salary_el else ""
    teaser_text = teaser_el.inner_text().strip() if teaser_el else ""
    card_text = (card.inner_text() or "").strip()

    return {
        "location": ", ".join(dedupe_preserve_order(location_values)) or "N/A",
        "work_type": extract_work_type(card_text),
        "work_mode": extract_work_mode("\n".join([card_text, teaser_text, salary_text])),
        "card_salary": salary_text or "N/A",
        "teaser": teaser_text or "N/A",
    }


def build_seek_search_targets(profile: dict, configured_date_range: int, sort_newest_first: bool) -> List[dict]:
    search_settings = get_search_settings(profile)
    keywords = str(search_settings.get("keywords") or "").strip()
    locations = dedupe_preserve_order(
        [str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()]
    ) or list(get_search_settings({}).get("locations", []))
    classification_ids = dedupe_preserve_order(
        [str(value).strip() for value in search_settings.get("classification_ids", []) if str(value).strip()]
    )

    targets: List[dict] = []
    for location in locations:
        search_url = SEEK_JOBS_BASE_URL
        search_url = set_query_param(search_url, "keywords", keywords)
        search_url = set_query_param(search_url, "where", location)
        if classification_ids:
            search_url = set_query_param(search_url, "classification", ",".join(classification_ids))
        search_url = set_query_param(search_url, "daterange", configured_date_range)
        if sort_newest_first:
            search_url = set_query_param(search_url, "sortMode", "ListedDate")
        targets.append(
            {
                "keywords": keywords,
                "location": location,
                "classification_ids": classification_ids,
                "url": search_url,
            }
        )
    return targets


def fetch_job_details_text(detail_page, full_url: str) -> str:
    try:
        detail_page.goto(full_url, wait_until="domcontentloaded")
    except Exception:
        return ""

    for selector in [
        'button:has-text("Show more")',
        'button:has-text("Read more")',
        'button:has-text("More")',
        '[aria-expanded="false"]',
    ]:
        try:
            locator = detail_page.locator(selector)
            max_clicks = min(locator.count(), 5)
            for index in range(max_clicks):
                try:
                    locator.nth(index).click(timeout=700)
                except Exception:
                    continue
        except Exception:
            continue

    try:
        detail_page.wait_for_selector(SELECTOR_DETAILS, timeout=8000)
        details_text = (detail_page.text_content(SELECTOR_DETAILS) or "").strip()
        if details_text:
            return details_text
    except Exception:
        pass

    try:
        detail_page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass

    try:
        return (detail_page.text_content("body") or "").strip()
    except Exception:
        return ""


def stable_job_key(full_url: Optional[str]) -> Optional[str]:
    if not full_url:
        return None
    match = re.search(r"/job/(\d+)", full_url)
    if match:
        return match.group(1)
    return full_url.split("#", 1)[0]


def normalize_job_key(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    match = re.search(r"/job/(\d+)", value)
    if match:
        return match.group(1)
    id_match = re.fullmatch(r"\d+", value)
    if id_match:
        return value
    return value.split("#", 1)[0]


def get_manual_skip_sets(profile: dict) -> tuple[Set[str], Set[str]]:
    review_controls = profile.get("review_controls", {})
    applied = {
        normalize_job_key(value)
        for value in review_controls.get("applied_job_keys", [])
        if normalize_job_key(value)
    }
    hidden = {
        normalize_job_key(value)
        for value in review_controls.get("hidden_job_keys", [])
        if normalize_job_key(value)
    }
    return applied, hidden


def format_timestamp_label(value: Optional[str]) -> str:
    if not value:
        return "N/A"
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y %I:%M %p")
    except Exception:
        return value


def format_posted_date_label(posted_text: Optional[str], posted_age_days: Optional[float], reference_time: Optional[datetime]) -> str:
    normalized_posted = normalize_posted_text(posted_text)
    if normalized_posted.lower() == "today":
        return "Today"
    if posted_age_days is None or reference_time is None:
        return "Unknown"
    try:
        posted_at = reference_time - timedelta(days=float(posted_age_days))
        return posted_at.strftime("%d %b %Y")
    except Exception:
        return "Unknown"


def location_fit_score(record: dict) -> int:
    search_location = str(record.get("search_location") or "").lower()
    location = str(record.get("location") or "").lower()
    if not search_location or not location or location == "n/a":
        return 0

    city_tokens = [
        ("sydney", "nsw"),
        ("canberra", "act"),
        ("melbourne", "vic"),
        ("brisbane", "qld"),
    ]
    for city, state in city_tokens:
        if city in search_location and city in location:
            return 6
        if city in search_location and state in location:
            return 4
    return 0


def score_to_match_label(score: int) -> str:
    if score >= 76:
        return "High"
    if score >= 52:
        return "Medium"
    return "Borderline"


def humanize_reject_reason(reason: Optional[str]) -> str:
    raw = str(reason or "").strip()
    if not raw:
        return "Other filtered-out roles"

    direct_map = {
        "TITLE_NOT_TARGET": "Title outside target role family",
        "NO_DETAILS": "Could not read full job details",
        "LLM_REJECT": "AI fit review rejected",
        "DUPLICATE_URL": "Duplicate listing removed",
        "ALREADY_APPLIED": "Already marked as applied",
        "MANUALLY_HIDDEN": "Already hidden by you",
        "UNKNOWN": "Other filtered-out roles",
    }
    if raw in direct_map:
        return direct_map[raw]

    prefix, _, detail = raw.partition(":")
    cleaned_detail = detail.replace("_", " ").strip()
    if prefix == "TITLE_BAD_KEYWORD" and cleaned_detail:
        return f"Excluded title keyword: {cleaned_detail}"
    if prefix == "TITLE_BAD_ROLE" and cleaned_detail:
        return f"Excluded role family: {cleaned_detail}"
    if prefix == "POSTED_TOO_OLD" and cleaned_detail:
        return f"Older than the search window ({cleaned_detail} days)"
    if prefix == "DESC_LOCATION" and cleaned_detail:
        return f"Location mismatch: {cleaned_detail}"
    if prefix == "DESC_FINANCE" and cleaned_detail:
        return f"Finance-domain mismatch: {cleaned_detail}"
    if prefix == "DESC_TREASURY" and cleaned_detail:
        return f"Treasury or banking-specialist role: {cleaned_detail}"
    if prefix == "DESC_ERP_FIN" and cleaned_detail:
        return f"ERP or finance-specialist workflow: {cleaned_detail}"
    if prefix == "DESC_CAPABILITY_LOW" and cleaned_detail:
        return f"Low-fit specialist area: {cleaned_detail}"
    if prefix == "CARD_EXCEPTION" and cleaned_detail:
        return f"Collection error: {cleaned_detail}"
    if prefix == "DESC_BAD_PHRASE" and cleaned_detail:
        return f"Excluded description phrase: {cleaned_detail}"
    if prefix == "DESC_BAD_REGEX" and cleaned_detail:
        return f"Excluded description pattern: {cleaned_detail}"
    if prefix == "TITLE_POTENTIAL_MATCH":
        return "Adjacent title match"

    fallback = raw.replace("_", " ").lower()
    return fallback[:1].upper() + fallback[1:]


def fit_score(record: dict) -> int:
    score = 0
    title_reason = str(record.get("title_reason") or "")
    llm_decision = str(record.get("llm_decision") or "").upper()
    content_reason = str(record.get("content_reason") or "")
    posted_age_days = record.get("posted_age_days")
    work_mode = str(record.get("work_mode") or "").lower()

    if title_reason == "OK":
        score += 24
    elif title_reason == "TITLE_POTENTIAL_MATCH":
        score += 12

    if llm_decision == "KEEP":
        score += 20
    elif llm_decision == "MAYBE":
        score += 11

    if content_reason == "OK":
        score += 5

    if posted_age_days is not None:
        if posted_age_days <= (1 / 24):
            score += 14
        elif posted_age_days <= 1:
            score += 11
        elif posted_age_days <= 3:
            score += 8
        elif posted_age_days <= 7:
            score += 4
        elif posted_age_days <= 15:
            score += 1

    score += location_fit_score(record)

    if work_mode == "hybrid":
        score += 4
    elif work_mode == "remote":
        score += 3
    elif work_mode == "on-site":
        score += 1

    if record.get("salary") not in (None, "", "N/A"):
        score += 2

    if viewed_by_user(record):
        score -= 3

    return max(min(score, 100), 0)


def parse_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def days_since(value: Optional[str], reference: datetime) -> Optional[int]:
    timestamp = parse_timestamp(value)
    if not timestamp:
        return None
    try:
        return max((reference - timestamp).days, 0)
    except Exception:
        return None


def build_keep_snapshot(record: dict) -> dict:
    snapshot = {}
    for field in KEEP_SNAPSHOT_FIELDS:
        if field in record:
            snapshot[field] = record.get(field)
    return snapshot


def can_reuse_kept_job(history_entry: dict, record: dict) -> bool:
    if not isinstance(history_entry, dict):
        return False
    if int(history_entry.get("times_kept", 0) or 0) <= 0:
        return False
    snapshot = history_entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        return False
    if not record.get("job_key"):
        return False
    previous_url = str(snapshot.get("url") or history_entry.get("url") or "").strip()
    current_url = str(record.get("url") or "").strip()
    if previous_url and current_url and previous_url != current_url:
        return False
    return True


def apply_kept_job_reuse(record: dict, history_entry: dict) -> dict:
    snapshot = history_entry.get("last_kept_snapshot") if isinstance(history_entry, dict) else {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    if record.get("posted") in {None, "", "N/A"}:
        record["posted"] = snapshot.get("posted") or "N/A"
    if record.get("posted_age_days") is None and snapshot.get("posted_age_days") is not None:
        record["posted_age_days"] = snapshot.get("posted_age_days")
    if record.get("salary") in {None, "", "N/A"}:
        record["salary"] = snapshot.get("salary") or "N/A"
    if record.get("teaser") in {None, "", "N/A"}:
        record["teaser"] = snapshot.get("teaser") or "N/A"
    if record.get("location") in {None, "", "N/A"}:
        record["location"] = snapshot.get("location") or "N/A"
    if record.get("work_mode") in {None, "", "N/A"}:
        record["work_mode"] = snapshot.get("work_mode") or "N/A"
    if record.get("work_type") in {None, "", "N/A"}:
        record["work_type"] = snapshot.get("work_type") or "N/A"

    record["content_reason"] = snapshot.get("content_reason")
    record["llm_decision"] = snapshot.get("llm_decision")
    record["decision"] = "KEEP"
    record["details_length"] = 0
    record["reused_history"] = True
    return record


def viewed_by_user(record: dict) -> bool:
    return int(record.get("times_viewed", 0) or 0) > 0


def update_job_history(history: Dict[str, dict], record: dict, run_iso: str) -> None:
    job_key = record.get("job_key")
    if not job_key:
        record["seen_before"] = False
        record["times_kept"] = 0
        record["first_kept_at"] = None
        return

    entry = history.get(job_key, {})
    prior_kept_count = int(entry.get("times_kept", 0) or 0)

    entry["job_key"] = job_key
    entry["title"] = record.get("title")
    entry["company"] = record.get("company")
    entry["url"] = record.get("url")
    entry["last_seen_at"] = run_iso
    entry["times_seen"] = int(entry.get("times_seen", 0) or 0) + 1
    if not entry.get("first_seen_at"):
        entry["first_seen_at"] = run_iso

    record["seen_before"] = prior_kept_count > 0
    record["times_seen"] = entry["times_seen"]
    record["times_kept"] = prior_kept_count
    record["times_viewed"] = int(entry.get("times_viewed", 0) or 0)
    record["first_kept_at"] = entry.get("first_kept_at")
    record["first_seen_at"] = entry.get("first_seen_at")
    record["last_seen_at"] = entry.get("last_seen_at")
    record["first_viewed_at"] = entry.get("first_viewed_at")
    record["last_viewed_at"] = entry.get("last_viewed_at")

    if record.get("decision") == "KEEP":
        if not entry.get("first_kept_at"):
            entry["first_kept_at"] = run_iso
        entry["last_kept_at"] = run_iso
        entry["times_kept"] = prior_kept_count + 1
        entry["last_kept_snapshot"] = build_keep_snapshot(record)
        record["times_kept"] = entry["times_kept"]
        record["first_kept_at"] = entry["first_kept_at"]
        record["last_kept_at"] = entry["last_kept_at"]

    history[job_key] = entry


def finalize_record(history: Dict[str, dict], audit_rows: List[dict], record: dict, run_iso: str) -> None:
    update_job_history(history, record, run_iso)
    audit_rows.append(record)


def build_history_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> Optional[dict]:
    if int(entry.get("times_kept", 0) or 0) <= 0:
        return None

    snapshot = entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    archived_age_days = days_since(entry.get("last_kept_at"), run_started_at)
    record = {
        "job_key": job_key,
        "title": snapshot.get("title") or entry.get("title") or "Untitled",
        "company": snapshot.get("company") or entry.get("company") or "N/A",
        "url": snapshot.get("url") or entry.get("url") or "#",
        "posted": snapshot.get("posted") or "N/A",
        "posted_age_days": snapshot.get("posted_age_days"),
        "salary": snapshot.get("salary") or "N/A",
        "location": snapshot.get("location") or "N/A",
        "work_mode": snapshot.get("work_mode") or "N/A",
        "work_type": snapshot.get("work_type") or "N/A",
        "teaser": snapshot.get("teaser") or "N/A",
        "title_reason": snapshot.get("title_reason"),
        "content_reason": snapshot.get("content_reason"),
        "llm_decision": snapshot.get("llm_decision"),
        "search_location": snapshot.get("search_location") or "N/A",
        "search_keywords": snapshot.get("search_keywords") or "",
        "seen_before": True,
        "times_viewed": int(entry.get("times_viewed", 0) or 0),
        "times_kept": int(entry.get("times_kept", 0) or 0),
        "first_kept_at": entry.get("first_kept_at"),
        "last_kept_at": entry.get("last_kept_at"),
        "first_seen_at": entry.get("first_seen_at"),
        "last_seen_at": entry.get("last_seen_at"),
        "first_viewed_at": entry.get("first_viewed_at"),
        "last_viewed_at": entry.get("last_viewed_at"),
        "archived": True,
        "archived_age_days": archived_age_days,
        "is_stale": archived_age_days is not None and archived_age_days > ARCHIVE_STALE_AFTER_DAYS,
    }
    return record


def build_archive_records(
    history: Dict[str, dict],
    current_run_keys: Set[str],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    run_started_at: datetime,
) -> List[dict]:
    records: List[dict] = []
    blocked_keys = applied_job_keys | hidden_job_keys

    for job_key, entry in history.items():
        normalized_key = normalize_job_key(str(job_key))
        if not normalized_key or normalized_key in current_run_keys or normalized_key in blocked_keys:
            continue
        record = build_history_dashboard_record(normalized_key, entry, run_started_at)
        if record:
            records.append(record)

    records.sort(
        key=lambda item: parse_timestamp(item.get("last_kept_at")) or datetime.min,
        reverse=True,
    )
    return records


def build_hidden_dashboard_record(job_key: str, entry: dict, run_started_at: datetime) -> dict:
    snapshot = entry.get("last_kept_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {}

    hidden_at = entry.get("last_hidden_at") or entry.get("first_hidden_at")
    hidden_age_days = days_since(hidden_at, run_started_at) if hidden_at else None
    return {
        "job_key": job_key,
        "title": snapshot.get("title") or entry.get("title") or f"Hidden job {job_key}",
        "company": snapshot.get("company") or entry.get("company") or "N/A",
        "url": snapshot.get("url") or entry.get("url") or "#",
        "posted": snapshot.get("posted") or "N/A",
        "posted_age_days": snapshot.get("posted_age_days"),
        "salary": snapshot.get("salary") or "N/A",
        "location": snapshot.get("location") or "N/A",
        "work_mode": snapshot.get("work_mode") or "N/A",
        "work_type": snapshot.get("work_type") or "N/A",
        "teaser": snapshot.get("teaser") or "N/A",
        "title_reason": snapshot.get("title_reason"),
        "content_reason": snapshot.get("content_reason"),
        "llm_decision": snapshot.get("llm_decision"),
        "search_location": snapshot.get("search_location") or "N/A",
        "search_keywords": snapshot.get("search_keywords") or "",
        "times_viewed": int(entry.get("times_viewed", 0) or 0),
        "first_seen_at": entry.get("first_seen_at"),
        "last_seen_at": entry.get("last_seen_at"),
        "first_viewed_at": entry.get("first_viewed_at"),
        "last_viewed_at": entry.get("last_viewed_at"),
        "first_hidden_at": entry.get("first_hidden_at"),
        "last_hidden_at": entry.get("last_hidden_at"),
        "hidden_age_days": hidden_age_days,
        "hidden": True,
    }


def build_hidden_records(
    hidden_job_keys: Set[str],
    history: Dict[str, dict],
    run_started_at: datetime,
) -> List[dict]:
    records: List[dict] = []
    for job_key in hidden_job_keys:
        entry = history.get(job_key, {})
        hidden_at = entry.get("last_hidden_at") or entry.get("first_hidden_at")
        hidden_age_days = days_since(hidden_at, run_started_at) if hidden_at else None
        if hidden_age_days is not None and hidden_age_days > HIDDEN_REVIEW_DAYS:
            continue
        records.append(build_hidden_dashboard_record(job_key, entry, run_started_at))

    records.sort(
        key=lambda item: (
            parse_timestamp(item.get("last_hidden_at")) or datetime.min,
            parse_timestamp(item.get("last_seen_at")) or datetime.min,
        ),
        reverse=True,
    )
    return records


def render_job_card(record: dict) -> str:
    title = safe_html(record.get("title", "Untitled"))
    company = safe_html(record.get("company", "N/A"))
    url = safe_html(record.get("url", "#"))
    job_key = safe_html(str(record.get("job_key") or ""))
    teaser = record.get("teaser", "N/A")
    title_reason = record.get("title_reason")
    archived = bool(record.get("archived"))
    hidden_record = bool(record.get("hidden"))
    is_stale = bool(record.get("is_stale"))
    seen_by_you = viewed_by_user(record)
    fit_points = fit_score(record)
    fit_label = score_to_match_label(fit_points)
    posted_text = normalize_posted_text(record.get("posted"))
    posted_date_label = format_posted_date_label(
        posted_text,
        record.get("posted_age_days"),
        parse_timestamp(record.get("last_seen_at")) or parse_timestamp(record.get("first_seen_at")),
    )
    work_mode = str(record.get("work_mode") or "N/A")
    posted_age_days = record.get("posted_age_days")
    salary_value = salary_sort_value(str(record.get("salary") or ""))
    record_kind = "hidden" if hidden_record else ("saved" if archived else "current")

    badges = []
    if hidden_record:
        badges.append('<span class="badge badge-hidden">Hidden</span>')
    elif archived:
        badges.append('<span class="badge badge-archive">Saved For Later</span>')
    else:
        badges.append('<span class="badge badge-new">New Job</span>')
    if is_stale:
        badges.append('<span class="badge badge-stale">15+ Days Old</span>')
    if seen_by_you:
        badges.append('<span class="badge badge-viewed">Opened By You</span>')

    score_html = (
        '<div class="match-score">'
        f'<span class="match-score-number">{fit_points}/100</span>'
        f'<span class="match-score-label">{safe_html(fit_label)} fit</span>'
        "</div>"
    )

    posted_display = posted_text
    if posted_age_days is not None and posted_age_days >= 1 and posted_text not in ("N/A", ""):
        if posted_date_label != "Unknown" and posted_date_label != posted_text:
            posted_display = f"{posted_text} ({posted_date_label})"
    elif posted_display in ("N/A", "") and posted_date_label != "Unknown":
        posted_display = posted_date_label

    chips = []
    for label, value in [
        ("Posted", posted_display),
        ("Location", record.get("location")),
        ("Work mode", record.get("work_mode")),
        ("Type", record.get("work_type")),
        ("Salary", record.get("salary")),
    ]:
        if value and value != "N/A" and value != "Unknown":
            chips.append(
                f'<span class="chip"><strong>{safe_html(label)}:</strong> {safe_html(str(value))}</span>'
            )
    context_bits = []
    if record.get("search_location") not in (None, "", "N/A"):
        context_bits.append(f"Search: {record.get('search_location')}")
    if title_reason == "TITLE_POTENTIAL_MATCH":
        context_bits.append("Adjacent title match, kept because the description still looked relevant")
    if seen_by_you and record.get("last_viewed_at"):
        context_bits.append(f"Opened by you {format_timestamp_label(record.get('last_viewed_at'))}")
    if hidden_record and record.get("last_hidden_at"):
        context_bits.append(f"Hidden {format_timestamp_label(record.get('last_hidden_at'))}")
    elif archived and record.get("last_kept_at"):
        context_bits.append(f"Saved from an earlier run {format_timestamp_label(record.get('last_kept_at'))}")
    context_html = (
        f'<div class="job-context">{safe_html(" | ".join(context_bits))}</div>'
        if context_bits
        else ""
    )

    teaser_html = (
        f'<p class="job-teaser">{safe_html(teaser)}</p>'
        if teaser and teaser != "N/A"
        else ""
    )

    if hidden_record:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-unhide" type="button" data-review-action="unhide" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">Unhide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )
    else:
        actions_html = (
            '<div class="job-actions">'
            f'<button class="review-button review-applied" type="button" data-review-action="applied" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">Applied</button>'
            f'<button class="review-button review-hide" type="button" data-review-action="hidden" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">Hide</button>'
            '<span class="review-status" aria-live="polite"></span>'
            "</div>"
        )

    return (
        f'<article class="job-card" data-fit-score="{fit_points}" data-posted-age="{posted_age_days if posted_age_days is not None else 9999}" data-salary-sort="{salary_value}" data-work-mode="{safe_html(work_mode.lower())}" data-viewed="{1 if seen_by_you else 0}" data-record-kind="{record_kind}" data-fit-label="{safe_html(fit_label.lower())}" data-title-search="{safe_html((record.get("title") or "").lower())}" data-company-search="{safe_html((record.get("company") or "").lower())}">'
        f'<div class="job-badges">{"".join(badges)}</div>'
        f'<a class="job-link" href="{url}" target="_blank" rel="noopener noreferrer" data-job-key="{job_key}" data-job-url="{url}" data-job-title="{title}">{title}</a>'
        f'<div class="job-company">{company}</div>'
        f"{score_html}"
        f'<div class="job-meta">{"".join(chips)}</div>'
        f"{teaser_html}"
        f"{context_html}"
        f"{actions_html}"
        "</article>"
    )


def section_dom_id(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "matches"


def render_section(title: str, records: List[dict], empty_message: str) -> str:
    if not records:
        return (
            f'<section class="section"><h2>{safe_html(title)}</h2>'
            f'<p class="empty-state">{safe_html(empty_message)}</p></section>'
        )
    dom_id = section_dom_id(title)
    cards = "".join(render_job_card(record) for record in records)
    return (
        f'<section class="section job-section" data-section-id="{safe_html(dom_id)}">'
        '<div class="section-head">'
        f'<h2>{safe_html(title)}</h2>'
        '<div class="section-tools">'
        '<span class="pagination-label"></span>'
        '<button class="pagination-button" type="button" data-page-direction="prev">Prev</button>'
        '<button class="pagination-button" type="button" data-page-direction="next">Next</button>'
        "</div>"
        "</div>"
        f'<div class="job-grid">{cards}</div>'
        "</section>"
    )


def load_last_kept_records() -> List[dict]:
    audit_rows = load_json_list(DEBUG_JSON_PATH)
    if not audit_rows:
        return []

    latest_run_started_at = max(
        (str(row.get("run_started_at") or "") for row in audit_rows if row.get("run_started_at")),
        default="",
    )
    if not latest_run_started_at:
        return []

    return [
        row
        for row in audit_rows
        if row.get("decision") == "KEEP" and str(row.get("run_started_at") or "") == latest_run_started_at
    ]


def build_run_stats(
    audit_rows: List[dict],
    kept_records: List[dict],
    run_started_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    max_pages_cap: int,
) -> dict:
    search_targets: Dict[str, Set[int]] = {}
    reject_counts: Dict[str, int] = {}
    skip_counts: Dict[str, int] = {}

    for row in audit_rows:
        search_location = str(row.get("search_location") or "Unknown")
        page_num = row.get("page")
        if page_num is not None:
            search_targets.setdefault(search_location, set()).add(int(page_num))

        reason = row.get("reject_reason") or "UNKNOWN"
        decision = row.get("decision")
        if decision == "SKIP":
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
        elif decision != "KEEP":
            reject_counts[reason] = reject_counts.get(reason, 0) + 1

    top_reject_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(reject_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
    ]

    detail_fetches = sum(1 for row in audit_rows if int(row.get("details_length") or 0) > 0)
    cards_seen = len(audit_rows)
    kept_count = len(kept_records)

    return {
        "run_started_at": run_started_at.isoformat(timespec="seconds"),
        "search_window_days": date_range_days,
        "sort_newest_first": sort_newest_first,
        "max_pages_cap": max_pages_cap,
        "search_targets": {
            location: sorted(pages)
            for location, pages in sorted(search_targets.items())
        },
        "page_count": sum(len(pages) for pages in search_targets.values()),
        "cards_seen": cards_seen,
        "detail_fetches": detail_fetches,
        "kept_count": kept_count,
        "keep_rate": round((kept_count / cards_seen), 4) if cards_seen else 0.0,
        "top_reject_reasons": top_reject_reasons,
        "skip_counts": skip_counts,
    }


def render_html(
    output_path: str,
    kept_records: List[dict],
    run_started_at: datetime,
    date_range_days: int,
    sort_newest_first: bool,
    run_stats: dict,
    job_history: Dict[str, dict],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    dashboard_reference_at: Optional[datetime] = None,
) -> None:
    reference_time = dashboard_reference_at or run_started_at
    current_records = sorted(
        kept_records,
        key=lambda record: (
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -fit_score(record),
            -(1 if not viewed_by_user(record) else 0),
        ),
    )
    current_run_keys = {
        normalize_job_key(str(record.get("job_key") or ""))
        for record in kept_records
        if normalize_job_key(str(record.get("job_key") or ""))
    }
    archive_records = build_archive_records(
        job_history,
        current_run_keys,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    )
    hidden_records = build_hidden_records(hidden_job_keys, job_history, reference_time)
    recent_archive_records = sorted(
        [record for record in archive_records if not record.get("is_stale")],
        key=lambda record: (
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -(fit_score(record)),
            -(parse_timestamp(record.get("last_kept_at")) or datetime.min).timestamp()
            if parse_timestamp(record.get("last_kept_at"))
            else float("-inf"),
        ),
    )
    stale_archive_records = sorted(
        [record for record in archive_records if record.get("is_stale")],
        key=lambda record: (
            record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999,
            -(fit_score(record)),
            -(parse_timestamp(record.get("last_kept_at")) or datetime.min).timestamp()
            if parse_timestamp(record.get("last_kept_at"))
            else float("-inf"),
        ),
    )
    run_label = run_started_at.strftime("%d %b %Y %I:%M %p")
    target_summaries = []
    for location, pages in (run_stats.get("search_targets") or {}).items():
        page_label = ", ".join(str(page) for page in pages) if pages else "none"
        target_summaries.append(f"{location}: pages {page_label}")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="{AUTO_REFRESH_SECONDS}">
  <title>SEEK Filtered Results</title>
  <style>
    :root {{
      --bg: #f4efe7;
      --panel: #fffaf2;
      --card: #ffffff;
      --ink: #1f2933;
      --muted: #5b6470;
      --line: #e6dccd;
      --accent: #14532d;
      --accent-soft: #e6f4ea;
      --warm: #9a3412;
      --warm-soft: #fff0e6;
      --cool: #1d4ed8;
      --cool-soft: #e8f0ff;
      --shadow: 0 12px 30px rgba(31, 41, 51, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(20, 83, 45, 0.08), transparent 28%),
        radial-gradient(circle at top right, rgba(154, 52, 18, 0.08), transparent 24%),
        var(--bg);
      color: var(--ink);
    }}
    .page {{
      max-width: 1380px;
      margin: 0 auto;
      padding: 32px 20px 64px;
    }}
    .dashboard-layout {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) 340px;
      gap: 24px;
      align-items: start;
    }}
    .dashboard-main {{
      min-width: 0;
    }}
    .dashboard-sidebar {{
      position: sticky;
      top: 20px;
      display: grid;
      gap: 16px;
    }}
    .hero {{
      background: linear-gradient(135deg, rgba(255, 250, 242, 0.96), rgba(255, 255, 255, 0.96));
      border: 1px solid var(--line);
      border-radius: 24px;
      padding: 28px;
      box-shadow: var(--shadow);
      margin-bottom: 24px;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: clamp(2rem, 4vw, 3.2rem);
      line-height: 1;
      letter-spacing: -0.04em;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
    }}
    .hero-note {{
      margin-top: 12px;
      max-width: 50rem;
      line-height: 1.55;
    }}
    .side-panel {{
      background: rgba(255, 250, 242, 0.96);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .side-panel summary {{
      list-style: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 18px;
      font-size: 1rem;
      font-weight: 800;
      letter-spacing: -0.02em;
    }}
    .side-panel summary::-webkit-details-marker {{
      display: none;
    }}
    .side-panel[open] summary {{
      border-bottom: 1px solid var(--line);
    }}
    .side-panel-body {{
      padding: 18px;
    }}
    .side-panel-copy {{
      margin: 0 0 14px;
      color: var(--muted);
      line-height: 1.5;
    }}
    .side-panel-copy:last-child {{
      margin-bottom: 0;
    }}
    .side-panel-summary-grid {{
      display: grid;
      gap: 12px;
      grid-template-columns: 1fr;
    }}
    .side-toggle-hint {{
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin: 20px 0 0;
    }}
    .summary-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
    }}
    .summary-card strong {{
      display: block;
      font-size: 1.75rem;
      margin-bottom: 6px;
    }}
    .summary-card span {{
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .section {{
      margin-top: 28px;
    }}
    .section h2 {{
      margin: 0 0 14px;
      font-size: 1.35rem;
      letter-spacing: -0.02em;
    }}
    .job-grid {{
      display: grid;
      gap: 16px;
    }}
    .job-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .job-badges {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 12px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      border-radius: 999px;
      padding: 6px 10px;
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .badge-new {{ background: var(--accent-soft); color: var(--accent); }}
    .badge-potential {{ background: var(--warm-soft); color: var(--warm); }}
    .badge-archive {{ background: #f3e8ff; color: #6b21a8; }}
    .badge-hidden {{ background: #fee2e2; color: #991b1b; }}
    .badge-stale {{ background: #f3f4f6; color: #4b5563; }}
    .badge-viewed {{ background: #fef3c7; color: #92400e; }}
    .badge-fit-high {{ background: #dcfce7; color: #166534; }}
    .badge-fit-medium {{ background: #fef3c7; color: #92400e; }}
    .badge-fit-borderline {{ background: #e5e7eb; color: #374151; }}
    .filter-panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      box-shadow: var(--shadow);
    }}
    .filter-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }}
    .filter-field {{
      display: block;
    }}
    .filter-field span {{
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 0.88rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}
    .filter-field select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 12px;
      font: inherit;
      background: white;
      color: var(--ink);
    }}
    .section-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}
    .section-head h2 {{
      margin: 0;
    }}
    .section-tools {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .pagination-label {{
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .pagination-button {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 8px 12px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: white;
      color: var(--cool);
    }}
    .pagination-button[disabled] {{
      opacity: 0.5;
      cursor: default;
    }}
    .section-copy {{
      margin: 0 0 14px;
      color: var(--muted);
    }}
    .job-link {{
      display: inline-block;
      color: var(--ink);
      text-decoration: none;
      font-size: 1.35rem;
      font-weight: 750;
      line-height: 1.2;
      margin-bottom: 6px;
    }}
    .job-link:hover {{ text-decoration: underline; }}
    .job-company {{
      color: var(--muted);
      font-size: 1rem;
      margin-bottom: 10px;
    }}
    .match-score {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 12px;
    }}
    .match-score-number {{
      font-size: 1.25rem;
      font-weight: 800;
      color: var(--accent);
    }}
    .match-score-label {{
      padding: 6px 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.9rem;
      font-weight: 700;
    }}
    .match-score-stars {{
      display: inline-flex;
      gap: 3px;
      line-height: 1;
    }}
    .star {{
      font-size: 1rem;
    }}
    .star-on {{
      color: #f59e0b;
    }}
    .star-off {{
      color: #d1d5db;
    }}
    .job-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 12px;
    }}
    .chip {{
      display: inline-flex;
      gap: 6px;
      align-items: center;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--panel);
      border: 1px solid var(--line);
      font-size: 0.92rem;
    }}
    .chip-score {{
      background: #eefbf3;
      border-color: #ccebd7;
    }}
    .job-teaser {{
      margin: 0 0 10px;
      color: var(--ink);
      line-height: 1.45;
    }}
    .job-context {{
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.45;
    }}
    .job-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
      margin: 14px 0 10px;
    }}
    .review-button {{
      border: 0;
      border-radius: 999px;
      padding: 9px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 120ms ease, opacity 120ms ease;
    }}
    .review-button:hover {{
      transform: translateY(-1px);
    }}
    .review-applied {{
      background: var(--accent);
      color: white;
      box-shadow: 0 10px 18px rgba(20, 83, 45, 0.18);
    }}
    .review-hide {{
      background: white;
      color: var(--warm);
      border: 1px solid rgba(154, 52, 18, 0.22);
    }}
    .review-unhide {{
      background: var(--cool);
      color: white;
      box-shadow: 0 10px 18px rgba(29, 78, 216, 0.16);
    }}
    .review-button[disabled] {{
      opacity: 0.6;
      cursor: progress;
      transform: none;
    }}
    .review-status {{
      color: var(--muted);
      font-size: 0.9rem;
      min-height: 1.2rem;
    }}
    .job-card.is-reviewed {{
      opacity: 0.55;
    }}
    .empty-state {{
      margin: 0;
      padding: 18px;
      background: var(--card);
      border: 1px dashed var(--line);
      border-radius: 18px;
      color: var(--muted);
    }}
    .toggle-button {{
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 9px 14px;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      background: var(--card);
      color: var(--cool);
    }}
    .toggle-button[disabled] {{
      opacity: 0.55;
      cursor: default;
    }}
    @media (max-width: 700px) {{
      .page {{ padding: 20px 14px 40px; }}
      .hero {{ padding: 22px 18px; }}
      .job-card {{ padding: 16px; }}
      .job-link {{ font-size: 1.15rem; }}
    }}
    @media (max-width: 1080px) {{
      .dashboard-layout {{
        grid-template-columns: 1fr;
      }}
      .dashboard-sidebar {{
        position: static;
      }}
      .side-panel-summary-grid {{
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <div class="dashboard-layout">
      <div class="dashboard-main">
        <section class="hero">
          <h1>Personal SEEK Dashboard</h1>
          <p class="hero-note">Your shortlist stays front and center here. The run stats, latest-run explanation, and efficiency notes are tucked into the side panel so they are there when you want them, but out of the way when you are focused on jobs.</p>
        </section>
        <section class="section filter-panel">
          <div class="section-head">
            <h2>Match Controls</h2>
          </div>
          <p class="section-copy">Fresh matches are jobs kept in the latest scrape. Saved jobs are earlier strong matches you may still want to revisit. Hide removes a job from future runs; Applied also removes it, but files it under jobs you acted on.</p>
          <div class="filter-grid">
            <label class="filter-field">
              <span>Sort</span>
              <select id="sort_select">
                <option value="newest">Newest posted first</option>
                <option value="fit">Best match first</option>
                <option value="salary">Highest salary first</option>
                <option value="unseen">Not opened by me first</option>
              </select>
            </label>
            <label class="filter-field">
              <span>Per page</span>
              <select id="page_size_select">
                <option value="12">12</option>
                <option value="24">24</option>
                <option value="48">48</option>
                <option value="96">96</option>
              </select>
            </label>
            <label class="filter-field">
              <span>Show</span>
              <select id="scope_filter">
                <option value="all">All matches</option>
                <option value="current">Fresh this run</option>
                <option value="saved">Saved from earlier</option>
                <option value="hidden">Hidden jobs</option>
                <option value="unseen">Not opened by me</option>
                <option value="viewed">Opened by me</option>
              </select>
            </label>
            <label class="filter-field">
              <span>Posted</span>
              <select id="posted_filter">
                <option value="all">Any time</option>
                <option value="1">Today</option>
                <option value="3">Last 3 days</option>
                <option value="7">Last 7 days</option>
                <option value="15">Last 15 days</option>
              </select>
            </label>
            <label class="filter-field">
              <span>Work mode</span>
              <select id="work_mode_filter">
                <option value="all">Any</option>
                <option value="remote">Remote</option>
                <option value="hybrid">Hybrid</option>
                <option value="on-site">On-site</option>
              </select>
            </label>
            <label class="filter-field">
              <span>Match score</span>
              <select id="score_filter">
                <option value="all">Any</option>
                <option value="85">85+ only</option>
                <option value="70">70+ only</option>
                <option value="55">55+ only</option>
              </select>
            </label>
          </div>
        </section>
        {render_section("Fresh Matches", current_records, "No fresh kept roles this run.")}
        {render_section("Saved From Earlier Runs", recent_archive_records, "No saved matches from earlier runs right now.")}
        {render_section("Hidden Jobs", hidden_records, "No hidden jobs right now.")}
        <section class="section job-section" data-section-id="older-saved">
          <div class="section-head">
            <h2>Older Saved Jobs</h2>
            <div class="section-tools">
              <span class="pagination-label"></span>
              <button class="pagination-button" type="button" data-page-direction="prev">Prev</button>
              <button class="pagination-button" type="button" data-page-direction="next">Next</button>
              <button class="toggle-button" type="button" data-toggle-target="older-archive" {'disabled' if not stale_archive_records else ''}>{'Show' if stale_archive_records else 'No'} Older Saved Jobs ({len(stale_archive_records)})</button>
            </div>
          </div>
          <p class="section-copy">Saved jobs older than {ARCHIVE_STALE_AFTER_DAYS} days since their last keep are hidden by default so the dashboard stays focused. Open this when you want to revisit older strong roles.</p>
          <div id="older-archive" hidden>
            <div class="job-grid">
              {''.join(render_job_card(record) for record in stale_archive_records)}
            </div>
          </div>
          {'' if stale_archive_records else '<p class="empty-state">No older saved matches right now.</p>'}
        </section>
      </div>
      <aside class="dashboard-sidebar">
        <details class="side-panel" open>
          <summary>
            <span>Run Snapshot</span>
            <span class="side-toggle-hint">Show / hide</span>
          </summary>
          <div class="side-panel-body">
            <p class="side-panel-copy">Latest run: {safe_html(run_label)}. Search window: roles published within the last {date_range_days} day(s). Result order: {"newest jobs first" if sort_newest_first else "source default relevance"}. This page rebuilds from the latest scrape plus your local keep history, so strong roles stay visible even after they fall outside the live SEEK date window. The page auto-refreshes every {AUTO_REFRESH_SECONDS} seconds so it picks up later runs without a manual browser reload.</p>
            <div class="side-panel-summary-grid">
              <div class="summary-card"><strong>{len(kept_records)}</strong><span>Fresh Matches</span></div>
              <div class="summary-card"><strong>{sum(1 for record in current_records if not record.get("seen_before"))}</strong><span>New Jobs</span></div>
              <div class="summary-card"><strong>{sum(1 for record in current_records if viewed_by_user(record))}</strong><span>Opened By You</span></div>
              <div class="summary-card"><strong>{len(recent_archive_records)}</strong><span>Saved For Later</span></div>
              <div class="summary-card"><strong>{len(hidden_records)}</strong><span>Hidden Jobs</span></div>
              <div class="summary-card"><strong>{len(stale_archive_records)}</strong><span>Older Saved</span></div>
              <div class="summary-card"><strong>{run_stats.get("page_count", 0)}</strong><span>Pages Crawled</span></div>
              <div class="summary-card"><strong>{run_stats.get("cards_seen", 0)}</strong><span>Cards Seen</span></div>
              <div class="summary-card"><strong>{run_stats.get("detail_fetches", 0)}</strong><span>Detail Pages Opened</span></div>
              <div class="summary-card"><strong>{round(float(run_stats.get("keep_rate", 0.0)) * 100, 1)}%</strong><span>Keep Rate</span></div>
            </div>
          </div>
        </details>
        <details class="side-panel">
          <summary>
            <span>Run Efficiency</span>
            <span class="side-toggle-hint">Show / hide</span>
          </summary>
          <div class="side-panel-body">
            <p class="side-panel-copy">Search targets this run: {safe_html(" | ".join(target_summaries) or "None")}. This is the fastest way to tell whether we stopped early because SEEK ran out of fresh pages or because the current page-check limit was reached.</p>
            <div class="job-meta">
              {''.join(f'<span class="chip" title="{safe_html(str(item.get("reason", "UNKNOWN")))}"><strong>{safe_html(humanize_reject_reason(str(item.get("reason", "UNKNOWN"))))}:</strong> {safe_html(str(item.get("count", 0)))}</span>' for item in run_stats.get("top_reject_reasons", []))}
            </div>
          </div>
        </details>
      </aside>
    </div>
  </main>
  <script>
    const REVIEW_API_URL = 'http://127.0.0.1:8765/api/review';
    const sortSelect = document.getElementById('sort_select');
    const pageSizeSelect = document.getElementById('page_size_select');
    const scopeFilter = document.getElementById('scope_filter');
    const postedFilter = document.getElementById('posted_filter');
    const workModeFilter = document.getElementById('work_mode_filter');
    const scoreFilter = document.getElementById('score_filter');
    const paginationState = {{}};

    function getVisibleCards() {{
      return Array.from(document.querySelectorAll('.job-card'));
    }}

    function resetPagination() {{
      for (const key of Object.keys(paginationState)) {{
        paginationState[key] = 1;
      }}
    }}

    function applySectionPagination(section) {{
      const grid = section.querySelector('.job-grid');
      if (!grid) {{
        return;
      }}

      const sectionId = section.dataset.sectionId || 'matches';
      const cards = Array.from(grid.querySelectorAll('.job-card'));
      const matchingCards = cards.filter(card => card.dataset.matchesFilters !== '0');
      const pageSize = Number(pageSizeSelect?.value || 12);
      const totalPages = Math.max(Math.ceil(matchingCards.length / pageSize), 1);

      if (!paginationState[sectionId]) {{
        paginationState[sectionId] = 1;
      }}
      paginationState[sectionId] = Math.min(Math.max(paginationState[sectionId], 1), totalPages);

      const currentPage = paginationState[sectionId];
      const startIndex = (currentPage - 1) * pageSize;
      const endIndex = startIndex + pageSize;

      cards.forEach(card => {{
        card.hidden = true;
      }});
      matchingCards.slice(startIndex, endIndex).forEach(card => {{
        card.hidden = false;
      }});

      const label = section.querySelector('.pagination-label');
      if (label) {{
        label.textContent = matchingCards.length
          ? `${{matchingCards.length}} matches | Page ${{currentPage}} of ${{totalPages}}`
          : '0 matches';
      }}

      const prevButton = section.querySelector('[data-page-direction="prev"]');
      const nextButton = section.querySelector('[data-page-direction="next"]');
      if (prevButton) prevButton.disabled = currentPage <= 1 || matchingCards.length === 0;
      if (nextButton) nextButton.disabled = currentPage >= totalPages || matchingCards.length === 0;
    }}

    function applyDashboardControls() {{
      const sortMode = sortSelect?.value || 'newest';
      const scopeMode = scopeFilter?.value || 'all';
      const postedLimit = postedFilter?.value || 'all';
      const workMode = workModeFilter?.value || 'all';
      const scoreMode = scoreFilter?.value || 'all';

      for (const card of getVisibleCards()) {{
        const cardScope = card.dataset.recordKind || 'current';
        const viewed = card.dataset.viewed === '1';
        const cardWorkMode = (card.dataset.workMode || '').toLowerCase();
        const cardScore = Number(card.dataset.fitScore || 0);
        const postedAge = Number(card.dataset.postedAge || 9999);

        let visible = true;
        if (scopeMode === 'current' && cardScope !== 'current') visible = false;
        if (scopeMode === 'saved' && cardScope !== 'saved') visible = false;
        if (scopeMode === 'hidden' && cardScope !== 'hidden') visible = false;
        if (scopeMode === 'unseen' && viewed) visible = false;
        if (scopeMode === 'viewed' && !viewed) visible = false;
        if (postedLimit !== 'all' && postedAge > Number(postedLimit)) visible = false;
        if (workMode !== 'all' && cardWorkMode !== workMode) visible = false;
        if (scoreMode !== 'all' && cardScore < Number(scoreMode)) visible = false;

        card.dataset.matchesFilters = visible ? '1' : '0';
      }}

      for (const grid of Array.from(document.querySelectorAll('.job-grid'))) {{
        const cards = Array.from(grid.querySelectorAll('.job-card'));
        cards.sort((a, b) => {{
          if (sortMode === 'newest') {{
            return Number(a.dataset.postedAge || 9999) - Number(b.dataset.postedAge || 9999);
          }}
          if (sortMode === 'salary') {{
            return Number(b.dataset.salarySort || 0) - Number(a.dataset.salarySort || 0);
          }}
          if (sortMode === 'unseen') {{
            const viewedDiff = Number(a.dataset.viewed || 0) - Number(b.dataset.viewed || 0);
            if (viewedDiff !== 0) return viewedDiff;
          }}
          const fitDiff = Number(b.dataset.fitScore || 0) - Number(a.dataset.fitScore || 0);
          if (fitDiff !== 0) return fitDiff;
          return Number(a.dataset.postedAge || 9999) - Number(b.dataset.postedAge || 9999);
        }});
        for (const card of cards) {{
          grid.appendChild(card);
        }}
      }}

      for (const section of Array.from(document.querySelectorAll('.job-section'))) {{
        applySectionPagination(section);
      }}
    }}

    function markCardViewed(link) {{
      const card = link.closest('.job-card');
      if (!card) return;
      card.dataset.viewed = '1';
      if (!card.querySelector('.badge-viewed')) {{
        const badges = card.querySelector('.job-badges');
        if (badges) {{
          const badge = document.createElement('span');
          badge.className = 'badge badge-viewed';
          badge.textContent = 'Opened By You';
          badges.appendChild(badge);
        }}
      }}
      applyDashboardControls();
    }}

    function sendViewedBeacon(link) {{
      const payload = JSON.stringify({{
        action: 'viewed',
        job_key: link.dataset.jobKey || '',
        url: link.dataset.jobUrl || '',
        title: link.dataset.jobTitle || '',
      }});

      try {{
        const blob = new Blob([payload], {{ type: 'application/json' }});
        navigator.sendBeacon(REVIEW_API_URL, blob);
      }} catch (error) {{
      }}
    }}

    async function saveReviewAction(button) {{
      const card = button.closest('.job-card');
      const status = card?.querySelector('.review-status');
      const action = button.dataset.reviewAction;
      const jobKey = button.dataset.jobKey || '';
      const jobUrl = button.dataset.jobUrl || '';

      if (!status) {{
        return;
      }}

      const buttons = card.querySelectorAll('.review-button');
      buttons.forEach(item => item.disabled = true);
      status.textContent = action === 'applied'
        ? 'Saving as applied...'
        : action === 'unhide'
          ? 'Removing from hidden jobs...'
          : 'Saving hidden job...';

      try {{
        const response = await fetch(REVIEW_API_URL, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            action,
            job_key: jobKey,
            url: jobUrl
          }})
        }});

        const payload = await response.json().catch(() => ({{}}));
        if (!response.ok) {{
          throw new Error(payload.error || 'Could not save review action');
        }}

        card.classList.add('is-reviewed');
        status.textContent = action === 'applied'
          ? 'Saved to Applied jobs. It will be hidden in future runs.'
          : action === 'unhide'
            ? 'Removed from Hidden jobs. It can appear again in future runs.'
            : 'Saved to Hidden jobs. It will stay out of future runs.';
        window.setTimeout(() => {{
          card.style.display = 'none';
        }}, 900);
      }} catch (error) {{
        buttons.forEach(item => item.disabled = false);
        status.textContent = error.message || 'Could not save review action.';
      }}
    }}

    document.addEventListener('click', event => {{
      const toggle = event.target.closest('[data-toggle-target]');
      if (toggle) {{
        const target = document.getElementById(toggle.dataset.toggleTarget || '');
        if (!target) {{
          return;
        }}
        const isHidden = target.hasAttribute('hidden');
        if (isHidden) {{
          target.removeAttribute('hidden');
          toggle.textContent = toggle.textContent.replace('Show', 'Hide');
        }} else {{
          target.setAttribute('hidden', '');
          toggle.textContent = toggle.textContent.replace('Hide', 'Show');
        }}
        return;
      }}

      const pageButton = event.target.closest('[data-page-direction]');
      if (pageButton) {{
        const section = pageButton.closest('.job-section');
        if (!section) {{
          return;
        }}
        const sectionId = section.dataset.sectionId || 'matches';
        const delta = pageButton.dataset.pageDirection === 'next' ? 1 : -1;
        paginationState[sectionId] = (paginationState[sectionId] || 1) + delta;
        applySectionPagination(section);
        return;
      }}

      const link = event.target.closest('.job-link');
      if (link) {{
        markCardViewed(link);
        sendViewedBeacon(link);
        return;
      }}

      const button = event.target.closest('.review-button');
      if (!button) {{
        return;
      }}
      saveReviewAction(button);
    }});

    for (const control of [sortSelect, pageSizeSelect, scopeFilter, postedFilter, workModeFilter, scoreFilter]) {{
      control?.addEventListener('change', () => {{
        resetPagination();
        applyDashboardControls();
      }});
    }}

    applyDashboardControls();
  </script>
</body>
</html>
"""
    output_file = Path(output_path)
    if not output_file.is_absolute():
        output_file = ROOT_DIR / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(html, encoding="utf-8")


def scrape_seek_jobs_direct(max_pages_cap: int = MAX_PAGES_CAP, headless: bool = False) -> str:
    configure_console_output()

    profile = load_profile()
    search_settings = get_search_settings(profile)
    configured_max_pages = int(search_settings.get("max_pages_cap", max_pages_cap) or max_pages_cap)
    configured_date_range = int(search_settings.get("date_range_days", 3) or 3)
    enforce_posted_age_limit = bool(search_settings.get("enforce_posted_age_limit", True))
    sort_newest_first = bool(search_settings.get("sort_newest_first", True))
    search_targets = build_seek_search_targets(profile, configured_date_range, sort_newest_first)
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)

    run_started_at = datetime.now().astimezone()
    run_iso = run_started_at.isoformat(timespec="seconds")
    llm_cache: Dict[str, str] = load_llm_cache()
    job_history = load_job_history()
    audit_rows: List[dict] = []
    kept_records: List[dict] = []
    skill_observations: List[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        list_page = browser.new_page(viewport={"width": 1400, "height": 900})
        detail_page = browser.new_page(viewport={"width": 1400, "height": 900})

        try:
            seen_urls: Set[str] = set()
            for search_target in search_targets:
                base_search_url = search_target["url"]
                search_location = search_target["location"]
                search_keywords = search_target["keywords"]
                classification_ids = ",".join(search_target.get("classification_ids", []))
                current_page_num = 1

                while current_page_num <= configured_max_pages:
                    page_url = set_page_param(base_search_url, current_page_num) if current_page_num > 1 else base_search_url

                    print(f"\n=== {search_location} | Page {current_page_num} ===")
                    print("URL:", page_url)

                    try:
                        list_page.goto(page_url, wait_until="domcontentloaded")
                        list_page.wait_for_selector(SELECTOR_CARDS, timeout=8000)
                    except Exception as exc:
                        print(
                            f"No visible job cards for {search_location} on page {current_page_num}. "
                            f"Stopping this target. [{type(exc).__name__}]"
                        )
                        break

                    job_cards = list_page.query_selector_all(SELECTOR_CARDS)
                    print(f"Found {len(job_cards)} job cards")

                    if len(job_cards) == 0:
                        print("No cards found. Stopping this target.")
                        break

                    page_has_fresh_card = False

                    for card in job_cards:
                        title = ""
                        company = "N/A"
                        record = {
                            "run_started_at": run_iso,
                            "search_location": search_location,
                            "search_keywords": search_keywords,
                            "search_classifications": classification_ids,
                            "page": current_page_num,
                            "job_key": None,
                            "title": "",
                            "company": company,
                            "posted": "N/A",
                            "posted_age_days": None,
                            "url": None,
                            "salary": "N/A",
                            "location": "N/A",
                            "work_mode": "N/A",
                            "work_type": "N/A",
                            "teaser": "N/A",
                            "decision": "REJECT",
                            "reject_reason": None,
                            "title_reason": None,
                            "content_reason": None,
                            "llm_decision": None,
                            "details_length": 0,
                        }

                        try:
                            title_el = card.query_selector(SELECTOR_TITLE)
                            company_el = card.query_selector(SELECTOR_COMPANY)
                            posted_el = card.query_selector(SELECTOR_POSTED)
                            card_meta = extract_card_metadata(card)
                            card_text = (card.inner_text() or "").strip()

                            title = title_el.inner_text().strip() if title_el else ""
                            company = company_el.inner_text().strip() if company_el else "N/A"
                            posted = posted_el.inner_text().strip() if posted_el else ""
                            if not posted:
                                posted = extract_posted_text_from_card(card_text)
                            posted = normalize_posted_text(posted)
                            posted_age_days = parse_seek_posted_age_days(posted)
                            record.update({
                                "title": title,
                                "company": company,
                                "posted": posted,
                                "posted_age_days": posted_age_days,
                                "location": card_meta["location"],
                                "work_mode": card_meta["work_mode"],
                                "work_type": card_meta["work_type"],
                                "teaser": card_meta["teaser"],
                            })

                            if posted_age_days is None or posted_age_days <= configured_date_range:
                                page_has_fresh_card = True

                            ok_title, title_reason = passes_title_filters(title)
                            record["title_reason"] = title_reason
                            if not ok_title:
                                print(f"REJECTED (title) [{title_reason}] {title}")
                                record["reject_reason"] = title_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            relative_url = title_el.get_attribute("href") if title_el else None
                            full_url = build_full_url(relative_url)
                            record["url"] = full_url
                            record["job_key"] = stable_job_key(full_url)
                            if not full_url:
                                print(f"REJECTED (card) [NO_URL] {title} @ {company}")
                                record["reject_reason"] = "NO_URL"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record["job_key"] in applied_job_keys:
                                print(f"SKIP (applied) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "ALREADY_APPLIED"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record["job_key"] in hidden_job_keys:
                                print(f"SKIP (hidden) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "MANUALLY_HIDDEN"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if (
                                enforce_posted_age_limit
                                and posted_age_days is not None
                                and posted_age_days > configured_date_range
                            ):
                                print(
                                    f"REJECTED (posted) [POSTED_TOO_OLD:{configured_date_range}] "
                                    f"{title} @ {company} | {posted}"
                                )
                                record["reject_reason"] = f"POSTED_TOO_OLD:{configured_date_range}"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if full_url in seen_urls:
                                print(f"SKIP (duplicate) {title} @ {company}")
                                record["decision"] = "SKIP"
                                record["reject_reason"] = "DUPLICATE_URL"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            seen_urls.add(full_url)

                            history_entry = job_history.get(record["job_key"] or "", {})
                            if can_reuse_kept_job(history_entry, record):
                                record = apply_kept_job_reuse(record, history_entry)
                                finalize_record(job_history, audit_rows, record, run_iso)
                                kept_records.append(record)
                                print(
                                    f"KEPT (history reuse): {title} @ {company} | {posted} | "
                                    f"{record['location']} | {record['work_type']} | {record['salary']}"
                                )
                                continue

                            details_text = fetch_job_details_text(detail_page, full_url)
                            record["details_length"] = len(details_text)
                            if not details_text:
                                print(f"REJECTED (details) [NO_DETAILS] {title} @ {company} | {full_url}")
                                record["reject_reason"] = "NO_DETAILS"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            for skill in extract_detected_skills(details_text):
                                skill_observations.append(
                                    {
                                        "skill": skill,
                                        "title": title,
                                        "company": company,
                                        "url": full_url,
                                        "search_location": search_location,
                                    }
                                )

                            ok_desc, desc_reason = passes_content_filters(details_text, record["location"])
                            record["content_reason"] = desc_reason
                            if not ok_desc:
                                print(f"REJECTED (content) [{desc_reason}] {title} @ {company}")
                                record["reject_reason"] = desc_reason
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            llm_input_text = details_text[:MAX_LLM_CHARS]
                            llm_fp = build_llm_cache_key(llm_input_text)

                            if not llm_is_enabled():
                                llm_decision = "MAYBE"
                                print(f"[LLM][DISABLED] {llm_decision} {title} @ {company}")
                            elif llm_fp in llm_cache:
                                llm_decision = llm_cache[llm_fp]
                                print(f"[LLM][CACHE] {llm_decision} {title} @ {company}")
                            else:
                                llm_decision = llm_should_consider(llm_input_text)
                                llm_cache[llm_fp] = llm_decision
                                print(f"[LLM] {llm_decision} {title} @ {company}")

                            record["llm_decision"] = llm_decision
                            if llm_decision == "REJECT":
                                print(f"REJECTED (llm) [LLM_REJECT] {title} @ {company}")
                                record["reject_reason"] = "LLM_REJECT"
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            salary = extract_salary(details_text)
                            if salary == "N/A":
                                salary = card_meta["card_salary"]
                            record["salary"] = salary
                            detail_work_mode = extract_work_mode(details_text)
                            if detail_work_mode != "N/A":
                                record["work_mode"] = detail_work_mode
                            record["decision"] = "KEEP"

                            finalize_record(job_history, audit_rows, record, run_iso)
                            kept_records.append(record)
                            print(
                                f"KEPT: {title} @ {company} | {posted} | "
                                f"{record['location']} | {record['work_type']} | {salary} | "
                                f"{'SEEN_BEFORE' if record.get('seen_before') else 'NEW'}"
                            )
                        except Exception as exc:
                            record["reject_reason"] = f"CARD_EXCEPTION:{type(exc).__name__}"
                            print(f"REJECTED (card) [CARD_EXCEPTION:{type(exc).__name__}] {title} @ {company}")
                            finalize_record(job_history, audit_rows, record, run_iso)

                    if enforce_posted_age_limit and not page_has_fresh_card:
                        print(
                            f"All cards for {search_location} on page {current_page_num} "
                            f"were older than {configured_date_range} day(s). Stopping this target."
                        )
                        break

                    current_page_num += 1

            run_stats = build_run_stats(
                audit_rows,
                kept_records,
                run_started_at,
                configured_date_range,
                sort_newest_first,
                configured_max_pages,
            )

            render_html(
                OUTPUT_HTML,
                kept_records,
                run_started_at,
                configured_date_range,
                sort_newest_first,
                run_stats,
                job_history,
                applied_job_keys,
                hidden_job_keys,
                run_started_at,
            )
            save_llm_cache(llm_cache)
            save_job_history(job_history)
            write_debug_json(audit_rows)
            write_run_stats(run_stats)
            write_review_data(build_review_data(audit_rows, skill_observations, profile))
            print(f"\nSaved {len(kept_records)} jobs to {OUTPUT_HTML}")
            print(f"Saved {len(audit_rows)} audit rows to {DEBUG_JSON_PATH}")
            print(f"Saved run stats to {RUN_STATS_PATH}")
            print(f"Saved review data to {REVIEW_DATA_PATH}")
            print(f"Saved history for {len(job_history)} jobs to {JOB_HISTORY_PATH}")
            return OUTPUT_HTML

        finally:
            browser.close()


def rebuild_html_dashboard() -> str:
    profile = load_profile()
    search_settings = get_search_settings(profile)
    configured_date_range = int(search_settings.get("date_range_days", 3) or 3)
    sort_newest_first = bool(search_settings.get("sort_newest_first", True))
    run_stats = load_json_dict(RUN_STATS_PATH)
    run_started_at = parse_timestamp(run_stats.get("run_started_at")) or datetime.now().astimezone()
    reference_time = datetime.now().astimezone()
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    job_history = load_job_history()
    kept_records = load_last_kept_records()

    render_html(
        OUTPUT_HTML,
        kept_records,
        run_started_at,
        configured_date_range,
        sort_newest_first,
        run_stats,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    )
    return OUTPUT_HTML


if __name__ == "__main__":
    if "--rebuild-dashboard" in sys.argv:
        rebuild_html_dashboard()
    else:
        scrape_seek_jobs_direct()
