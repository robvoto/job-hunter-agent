"""SEEK-specific connector helpers.

These functions are extracted from source_connector.py to keep SEEK-specific
I/O logic separate from the shared pipeline. Imported back into source_connector.py.
"""

import re
from typing import List, Optional
from urllib.parse import urljoin

from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.profile_store import get_search_settings
from job_hunter_agent.source_registry import SOURCE_SEEK
from job_hunter_agent.scrapers.base import keywords_to_search_string
from job_hunter_agent.record_schema import RECORD_LOCATION_KEY, RECORD_WORK_TYPE_KEY, RECORD_WORK_MODE_KEY, RECORD_WORK_MODE_SOURCE_KEY, RECORD_WORK_MODE_EVIDENCE_KEY, RECORD_WORK_MODE_NEEDS_REVIEW_KEY, RECORD_CARD_SALARY_KEY, RECORD_TEASER_KEY
from job_hunter_agent.utils import set_query_param
from job_hunter_agent.work_mode_extraction import extract_from_seek_card

# ---------------------------------------------------------------------------
# Playwright CSS selectors (SEEK-specific DOM)
# ---------------------------------------------------------------------------

SELECTOR_CARDS = 'article[data-automation="normalJob"], article[data-automation="premiumJob"]'
SELECTOR_TITLE = '[data-automation="jobTitle"]'
SELECTOR_COMPANY = '[data-automation="jobCompany"]'
SELECTOR_POSTED = '[data-automation="jobListingDate"]'
SELECTOR_LOCATION = '[data-automation="jobLocation"]'
SELECTOR_CARD_SALARY = '[data-automation="jobSalary"]'
SELECTOR_SHORT_DESCRIPTION = '[data-automation="jobShortDescription"]'
SELECTOR_DETAILS = '[data-automation="jobAdDetails"]'

SEEK_JOBS_BASE_URL = "https://www.seek.com.au/jobs"
DETAIL_PAGE_CHALLENGE_MARKERS = (
    "help us keep seek secure",
    "enable javascript and cookies to continue",
    "verification successful. waiting for www.seek.com.au to respond",
    "__cf_chl",
    "challenge-error-text",
)
DETAIL_PAGE_BLOCK_MARKERS = (
    "access denied",
    "temporarily unavailable",
    "request unsuccessful",
)

# ---------------------------------------------------------------------------
# Private helpers (not exported)
# ---------------------------------------------------------------------------


def _dedupe_preserve_order(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _normalize_posted_text(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return re.sub(r"^\s*posted\s+", "", text, flags=re.IGNORECASE).strip()


def _seek_posted_age_rules() -> dict:
    rules = load_parsing_rules().get("seek_posted_age_rules", {})
    return rules if isinstance(rules, dict) else {}


# ---------------------------------------------------------------------------
# Exported SEEK helpers
# ---------------------------------------------------------------------------


def extract_posted_text_from_card(card_text: str) -> str:
    text = _normalize_posted_text(card_text)
    pattern = str(_seek_posted_age_rules().get("card_match_pattern") or "").strip()
    if not pattern:
        return ""
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        return _normalize_posted_text(match.group(0))
    return ""


def extract_work_type(card_text: str) -> str:
    match = re.search(r"This is a ([^\n]+?) job", card_text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""


def extract_card_metadata(card, filter_state=None) -> dict:
    location_values = [
        (element.inner_text() or "").strip()
        for element in card.query_selector_all(SELECTOR_LOCATION)
    ]
    salary_el = card.query_selector(SELECTOR_CARD_SALARY)
    teaser_el = card.query_selector(SELECTOR_SHORT_DESCRIPTION)
    salary_text = salary_el.inner_text().strip() if salary_el else ""
    teaser_text = teaser_el.inner_text().strip() if teaser_el else ""
    card_text = (card.inner_text() or "").strip()

    wm = extract_from_seek_card(card_text, filter_state)
    return {
        RECORD_LOCATION_KEY: ", ".join(_dedupe_preserve_order(location_values)) or "",
        RECORD_WORK_TYPE_KEY: extract_work_type(card_text),
        RECORD_WORK_MODE_KEY: wm["work_mode"],
        RECORD_WORK_MODE_SOURCE_KEY: wm["work_mode_source"],
        RECORD_WORK_MODE_EVIDENCE_KEY: wm["work_mode_evidence"],
        RECORD_WORK_MODE_NEEDS_REVIEW_KEY: wm["work_mode_needs_review"],
        RECORD_CARD_SALARY_KEY: salary_text or "",
        RECORD_TEASER_KEY: teaser_text or "",
    }


def build_seek_search_targets(profile: dict, configured_date_range: int, sort_newest_first: bool) -> List[dict]:
    search_settings = get_search_settings(profile)
    keywords = keywords_to_search_string(search_settings.get("keywords") or "")
    locations = _dedupe_preserve_order(
        [str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()]
    ) or [""]
    classification_ids = _dedupe_preserve_order(
        [str(value).strip() for value in search_settings.get("classification_ids", []) if str(value).strip()]
    )

    targets: List[dict] = []
    for location in locations:
        search_url = SEEK_JOBS_BASE_URL
        search_url = set_query_param(search_url, "keywords", keywords)
        if location:
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


def classify_detail_page_text(text: str) -> str:
    lowered = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not lowered:
        return "empty"
    if any(marker in lowered for marker in DETAIL_PAGE_CHALLENGE_MARKERS):
        return "challenge_page"
    if any(marker in lowered for marker in DETAIL_PAGE_BLOCK_MARKERS):
        return "blocked_page"
    return "ok"


def _expand_detail_page(detail_page) -> None:
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


def fetch_job_details_payload(detail_page, full_url: str, attempts: int = 2) -> dict:
    last_status = "empty"
    last_text = ""

    try:
        detail_page.goto(full_url, wait_until="domcontentloaded")
    except Exception:
        return {"text": "", "status": "navigation_error", "retryable": False}

    for attempt_index in range(max(attempts, 1)):
        _expand_detail_page(detail_page)

        details_text = ""
        try:
            detail_page.wait_for_selector(SELECTOR_DETAILS, timeout=8000)
            details_text = (detail_page.text_content(SELECTOR_DETAILS) or "").strip()
        except Exception:
            details_text = ""

        details_status = classify_detail_page_text(details_text)
        if details_text and details_status == "ok":
            return {"text": details_text, "status": "ok", "source": "jobAdDetails", "retryable": False}

        try:
            detail_page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass

        try:
            body_text = (detail_page.text_content("body") or "").strip()
        except Exception:
            body_text = ""

        body_status = classify_detail_page_text(body_text)
        if body_text and body_status == "ok":
            return {"text": body_text, "status": "ok", "source": "body", "retryable": False}

        last_text = body_text or details_text or ""
        last_status = body_status if body_text else details_status
        should_retry = last_status in {"challenge_page", "blocked_page"} and attempt_index < (attempts - 1)
        if not should_retry:
            break
        try:
            detail_page.wait_for_timeout(2500 * (attempt_index + 1))
            detail_page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            break

    return {
        "text": "",
        "status": last_status,
        "retryable": last_status in {"challenge_page", "blocked_page"},
        "raw_text": last_text[:500],
    }


def stable_job_key(full_url: Optional[str]) -> Optional[str]:
    if not full_url:
        return None
    # Standardize to 'seek:id' via centralized normalization
    return normalize_job_key(full_url, source=SOURCE_SEEK)


def build_full_seek_url(relative_or_full_url: Optional[str]) -> Optional[str]:
    if not relative_or_full_url:
        return None
    return urljoin("https://www.seek.com.au", relative_or_full_url)
