"""SEEK-specific connector helpers.

These functions are extracted from source_connector.py to keep SEEK-specific
I/O logic separate from the shared pipeline. Imported back into source_connector.py.
"""

import re
from typing import List, Optional
from urllib.parse import urljoin

from job_hunter_agent.io_utils import load_parsing_rules
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.job_types import load_job_type
from job_hunter_agent.knowledge_store import get_knowledge
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.profile_store import get_search_settings
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EXTERNAL_APPLY,
    APPLY_METHOD_QUICK_APPLY,
    APPLY_METHOD_UNKNOWN,
    RECORD_CARD_SALARY_KEY,
    RECORD_LOCATION_KEY,
    RECORD_TEASER_KEY,
    RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY,
    RECORD_WORK_MODE_SOURCE_KEY,
    RECORD_WORK_TYPE_KEY,
)
from job_hunter_agent.scrapers.base import map_job_type
from job_hunter_agent.scrapers.location_adapters import to_seek
from job_hunter_agent.source_registry import SOURCE_SEEK
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
SELECTOR_APPLY_BUTTON = '[data-automation="job-detail-apply"]'

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


def _seek_quick_apply_text_markers() -> List[str]:
    rules = (get_knowledge("apply_method_indicators") or {}).get(
        "apply_method_indicators", {}
    )
    return [
        str(marker or "").strip().lower()
        for marker in rules.get("seek_quick_apply_text_markers", [])
        if str(marker or "").strip()
    ]


def classify_seek_apply_method(apply_button_text: Optional[str]) -> str:
    """Classify SEEK's apply-button text into a normalised apply_method value."""
    text = str(apply_button_text or "").strip().lower()
    if not text:
        return APPLY_METHOD_UNKNOWN
    markers = _seek_quick_apply_text_markers()
    if any(marker in text for marker in markers):
        return APPLY_METHOD_QUICK_APPLY
    return APPLY_METHOD_EXTERNAL_APPLY


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
        RECORD_WORK_TYPE_KEY: map_job_type(extract_work_type(card_text), load_job_type()),
        RECORD_WORK_MODE_KEY: wm["work_mode"],
        RECORD_WORK_MODE_SOURCE_KEY: wm["work_mode_source"],
        RECORD_WORK_MODE_EVIDENCE_KEY: wm["work_mode_evidence"],
        RECORD_WORK_MODE_NEEDS_REVIEW_KEY: wm["work_mode_needs_review"],
        RECORD_CARD_SALARY_KEY: salary_text or "",
        RECORD_TEASER_KEY: teaser_text or "",
    }


def build_seek_search_targets(
    profile: dict, configured_date_range: int, sort_newest_first: bool
) -> List[dict]:
    search_settings = get_search_settings(profile)
    preferred_roles = [
        str(value).strip() for value in (profile.get("target_roles") or []) if str(value).strip()
    ]
    keywords = preferred_roles[0] if preferred_roles else str(search_settings.get("keywords") or "").strip()
    if not keywords:
        raise ValueError(
            "No preferred role is configured. Please complete onboarding and add a preferred role before running."
        )
    locations = _dedupe_preserve_order(
        [str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()]
    ) or [""]

    targets: List[dict] = []
    for location in locations:
        search_url = SEEK_JOBS_BASE_URL
        search_url = set_query_param(search_url, "keywords", keywords)
        if location:
            search_location = to_seek(resolve_location(location))
            search_url = set_query_param(search_url, "where", search_location)
        search_url = set_query_param(search_url, "daterange", configured_date_range)
        if sort_newest_first:
            search_url = set_query_param(search_url, "sortMode", "ListedDate")
        targets.append(
            {
                "keywords": keywords,
                "location": search_location if location else "",
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


def _read_visible_text(page, selector: str) -> str:
    try:
        page.wait_for_selector(selector, timeout=8000)
    except Exception:
        return ""

    for reader in ("inner_text", "text_content"):
        try:
            text = getattr(page.locator(selector), reader)()
            if text:
                return str(text).strip()
        except Exception:
            continue
    return ""


def _read_href(page, selector: str, page_url: str) -> str:
    try:
        page.wait_for_selector(selector, timeout=8000)
    except Exception:
        return ""
    try:
        href = str(page.locator(selector).get_attribute("href") or "").strip()
    except Exception:
        return ""
    return urljoin(page_url, href) if href else ""


def fetch_job_details_payload(detail_page, full_url: str, attempts: int = 2) -> dict:
    last_status = "empty"
    last_text = ""

    try:
        detail_page.goto(full_url, wait_until="domcontentloaded")
    except Exception:
        return {"text": "", "status": "navigation_error", "retryable": False}

    apply_button_text = _read_visible_text(detail_page, SELECTOR_APPLY_BUTTON)
    apply_method = classify_seek_apply_method(apply_button_text)
    apply_url = _read_href(detail_page, SELECTOR_APPLY_BUTTON, full_url)

    for attempt_index in range(max(attempts, 1)):
        _expand_detail_page(detail_page)

        details_text = _read_visible_text(detail_page, SELECTOR_DETAILS)

        details_status = classify_detail_page_text(details_text)
        if details_text and details_status == "ok":
            return {
                "text": details_text,
                "status": "ok",
                "source": "jobAdDetails",
                "retryable": False,
                "apply_method": apply_method,
                "apply_url": apply_url,
            }

        try:
            detail_page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass

        body_text = _read_visible_text(detail_page, "body")

        body_status = classify_detail_page_text(body_text)
        if body_text and body_status == "ok":
            return {
                "text": body_text,
                "status": "ok",
                "source": "body",
                "retryable": False,
                "apply_method": apply_method,
                "apply_url": apply_url,
            }

        last_text = body_text or details_text or ""
        last_status = body_status if body_text else details_status
        should_retry = last_status in {"challenge_page", "blocked_page"} and attempt_index < (
            attempts - 1
        )
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
        "apply_method": apply_method,
        "apply_url": apply_url,
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


# ---------------------------------------------------------------------------
# Async Playwright helpers — mirror of the sync versions above, used by
# the parallel detail-fetch path in seek_runner.py.
# ---------------------------------------------------------------------------


async def _expand_detail_page_async(page) -> None:
    for selector in [
        'button:has-text("Show more")',
        'button:has-text("Read more")',
        'button:has-text("More")',
        '[aria-expanded="false"]',
    ]:
        try:
            locator = page.locator(selector)
            max_clicks = min(await locator.count(), 5)
            for index in range(max_clicks):
                try:
                    await locator.nth(index).click(timeout=700)
                except Exception:
                    continue
        except Exception:
            continue


async def _read_visible_text_async(page, selector: str) -> str:
    try:
        await page.wait_for_selector(selector, timeout=8000)
    except Exception:
        return ""
    for reader in ("inner_text", "text_content"):
        try:
            text = await getattr(page.locator(selector), reader)()
            if text:
                return str(text).strip()
        except Exception:
            continue
    return ""


async def _read_href_async(page, selector: str, page_url: str) -> str:
    try:
        await page.wait_for_selector(selector, timeout=8000)
    except Exception:
        return ""
    try:
        href = str(await page.locator(selector).get_attribute("href") or "").strip()
    except Exception:
        return ""
    return urljoin(page_url, href) if href else ""


async def fetch_job_details_payload_async(page, full_url: str, attempts: int = 2) -> dict:
    """Async mirror of fetch_job_details_payload — use with async_playwright pages."""
    last_status = "empty"
    last_text = ""

    try:
        await page.goto(full_url, wait_until="domcontentloaded")
    except Exception:
        return {"text": "", "status": "navigation_error", "retryable": False}

    apply_button_text = await _read_visible_text_async(page, SELECTOR_APPLY_BUTTON)
    apply_method = classify_seek_apply_method(apply_button_text)
    apply_url = await _read_href_async(page, SELECTOR_APPLY_BUTTON, full_url)

    for attempt_index in range(max(attempts, 1)):
        await _expand_detail_page_async(page)

        details_text = await _read_visible_text_async(page, SELECTOR_DETAILS)
        details_status = classify_detail_page_text(details_text)
        if details_text and details_status == "ok":
            return {
                "text": details_text,
                "status": "ok",
                "source": "jobAdDetails",
                "retryable": False,
                "apply_method": apply_method,
                "apply_url": apply_url,
            }

        try:
            await page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass

        body_text = await _read_visible_text_async(page, "body")
        body_status = classify_detail_page_text(body_text)
        if body_text and body_status == "ok":
            return {
                "text": body_text,
                "status": "ok",
                "source": "body",
                "retryable": False,
                "apply_method": apply_method,
                "apply_url": apply_url,
            }

        last_text = body_text or details_text or ""
        last_status = body_status if body_text else details_status
        should_retry = last_status in {"challenge_page", "blocked_page"} and attempt_index < (
            attempts - 1
        )
        if not should_retry:
            break
        try:
            await page.wait_for_timeout(2500 * (attempt_index + 1))
            await page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            break

    return {
        "text": "",
        "status": last_status,
        "retryable": last_status in {"challenge_page", "blocked_page"},
        "raw_text": last_text[:500],
        "apply_method": apply_method,
        "apply_url": apply_url,
    }
