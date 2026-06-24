"""Scraper helpers for seek runner."""

from __future__ import annotations

import asyncio
import logging
import pathlib
import re
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Set
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

from playwright._impl._errors import TargetClosedError
from playwright.async_api import async_playwright as async_playwright_ctx
from playwright.sync_api import sync_playwright

import job_hunter_agent.record_schema as rs
from job_hunter_agent.fit_scoring import fit_score_and_breakdown_displayed
from job_hunter_agent.global_settings import get_playwright_browser_mode
from job_hunter_agent.history import finalize_record
from job_hunter_agent.io_utils import DEBUG_CAPTURE_SOURCE_PAYLOADS, write_source_payload_debug
from job_hunter_agent.job_quality import detect_broad_engagement_signal
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    ReviewPipelineHooks,
    close_job_block,
    print_job_human_summary,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.paths import PLAYWRIGHT_USER_DATA_DIR
from job_hunter_agent.run_control import run_stop_requested, set_run_progress
from job_hunter_agent.runtime_helpers import CLI_FLAG_DEBUG, has_cli_flag
from job_hunter_agent.scrapers.base import _build_initial_source_metadata, build_initial_flat_record
from job_hunter_agent.scrapers.seek import (
    SELECTOR_CARDS,
    SELECTOR_COMPANY,
    SELECTOR_POSTED,
    SELECTOR_TITLE,
    build_full_seek_url,
    extract_card_metadata,
    extract_posted_text_from_card,
    fetch_job_details_payload_async,
    stable_job_key,
)
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order
from job_hunter_agent.utils import parse_seek_posted_age_days, set_page_param
from job_hunter_agent.work_mode_extraction import (
    WORK_MODE_UNKNOWN,
    extract_from_seek_detail,
    extract_seek_filter_panel_state,
    log_work_mode_result,
)

WORKSPACE_DEBUG_MODE = has_cli_flag(sys.argv, CLI_FLAG_DEBUG)
RUN_PROGRESS_ITEM_SEPARATOR = " | "


class BotChallengeDetected(Exception):
    """Raised when SEEK needs manual help or an AWS browser session retry after a blocked page."""

    def __init__(self, message: str, *, failure_class: str = "SEEK_UNKNOWN_FAILURE") -> None:
        super().__init__(message)
        self.failure_class = failure_class

# Chromium flags and init script applied to every browser launch to suppress the
# navigator.webdriver fingerprint that automated browsers expose. Without these,
# SEEK's bot detection serves a challenge page instead of job listings in headless mode.
_BROWSER_ARGS = ["--disable-blink-features=AutomationControlled"]
_WEBDRIVER_INIT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
RUN_PROGRESS_TITLE_SEPARATOR = " @ "
RUN_PROGRESS_ELAPSED_PREFIX = "elapsed "
SEEK_HUMAN_VERIFICATION = "SEEK_HUMAN_VERIFICATION"
SEEK_BOT_CHALLENGE = "SEEK_BOT_CHALLENGE"
SEEK_TIMEOUT_NO_CARDS = "SEEK_TIMEOUT_NO_CARDS"
SEEK_UNKNOWN_FAILURE = "SEEK_UNKNOWN_FAILURE"
SEEK_ASSISTED_BROWSER_SESSION_ENABLED = "AWS-assisted SEEK browser session is enabled."
_SEEK_HUMAN_VERIFICATION_MARKERS = (
    "help us keep seek secure",
    "enable javascript and cookies",
)
_SEEK_BOT_CHALLENGE_MARKERS = (
    "just a moment",
    "confirm you are human",
)
_SEEK_BLOCK_MARKERS = (
    "access denied",
    "temporarily unavailable",
    "request unsuccessful",
)
_SEEK_FAILURE_MESSAGES = {
    SEEK_HUMAN_VERIFICATION: (
        "SEEK needs human verification. Open the AWS browser session and complete the check."
    ),
    SEEK_BOT_CHALLENGE: "SEEK is showing a bot challenge page and did not reach job cards.",
    SEEK_TIMEOUT_NO_CARDS: "SEEK timed out before any job cards appeared.",
    SEEK_UNKNOWN_FAILURE: "SEEK failed before it could load job cards.",
}
_SEEK_LIST_PAGE_CHALLENGE_MARKERS = (
    "help us keep seek secure",
    "confirm you are human",
    "enable javascript and cookies to continue",
    "verification successful. waiting for www.seek.com.au to respond",
    "__cf_chl",
    "challenge-error-text",
)
_SEEK_LIST_PAGE_BLOCK_MARKERS = (
    "access denied",
    "temporarily unavailable",
    "request unsuccessful",
)

def _format_seek_elapsed(elapsed_s: float | int | None) -> str:
    elapsed = max(int(float(elapsed_s or 0)), 0)
    minutes, seconds = divmod(elapsed, 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _classify_seek_list_page_text(text: str) -> str:
    lowered = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not lowered:
        return "empty"
    if any(marker in lowered for marker in _SEEK_LIST_PAGE_CHALLENGE_MARKERS):
        return "challenge_page"
    if any(marker in lowered for marker in _SEEK_LIST_PAGE_BLOCK_MARKERS):
        return "blocked_page"
    return "ok"


def _classify_seek_list_page_failure(
    title: str,
    body_text: str,
    selector_count: int | None = None,
) -> str:
    lowered = " ".join(
        part for part in [str(title or ""), str(body_text or "")] if part.strip()
    ).lower()
    if any(marker in lowered for marker in _SEEK_HUMAN_VERIFICATION_MARKERS):
        return SEEK_HUMAN_VERIFICATION
    if any(marker in lowered for marker in _SEEK_BOT_CHALLENGE_MARKERS):
        return SEEK_BOT_CHALLENGE
    if selector_count == 0:
        if any(marker in lowered for marker in _SEEK_BLOCK_MARKERS):
            return SEEK_UNKNOWN_FAILURE
        return SEEK_TIMEOUT_NO_CARDS
    if any(marker in lowered for marker in _SEEK_BLOCK_MARKERS):
        return SEEK_UNKNOWN_FAILURE
    return SEEK_UNKNOWN_FAILURE


def _seek_list_page_diagnostics(list_page) -> dict[str, object]:
    try:
        page_title = list_page.title()
    except Exception as title_exc:
        page_title = f"<title unavailable: {title_exc}>"

    try:
        page_url_actual = list_page.url
    except Exception as url_exc:
        page_url_actual = f"<url unavailable: {url_exc}>"

    try:
        body_text = (list_page.inner_text("body") or "")[:500].replace("\n", " ")
    except Exception as body_exc:
        body_text = f"<body unavailable: {body_exc}>"

    try:
        selector_count = list_page.locator(SELECTOR_CARDS).count()
    except Exception as count_exc:
        selector_count = -1
        logger.info("[SEEK] card selector count unavailable: %s", count_exc)

    page_status = _classify_seek_list_page_text(body_text)
    failure_class = _classify_seek_list_page_failure(page_title, body_text, selector_count)
    return {
        "title": page_title,
        "url": page_url_actual,
        "body_text": body_text,
        "selector_count": selector_count,
        "page_status": page_status,
        "failure_class": failure_class,
    }


def _log_seek_list_page_diagnostics(
    page_tag: str,
    list_page,
    exc: Exception,
    *,
    selector_timeout: int,
) -> str:
    snapshot = _seek_list_page_diagnostics(list_page)
    page_title = str(snapshot["title"])
    page_url_actual = str(snapshot["url"])
    body_text = str(snapshot["body_text"])
    selector_count = int(snapshot["selector_count"])
    page_status = str(snapshot["page_status"])
    failure_class = str(snapshot["failure_class"])
    logger.info(
        "%s title=%r actual_url=%s card_selector_count=%s body_status=%s failure_class=%s body_len=%d "
        "selector_timeout_ms=%d body_snippet=%r",
        page_tag,
        page_title,
        page_url_actual,
        selector_count,
        page_status,
        failure_class,
        len(body_text),
        selector_timeout,
        body_text,
    )
    logger.info("%s wait_for_selector failed with %s", page_tag, type(exc).__name__)
    if page_status == "challenge_page":
        logger.warning("%s SEEK list page looks like a SEEK bot challenge page", page_tag)
    elif page_status == "blocked_page":
        logger.warning("%s SEEK list page looks blocked or unavailable", page_tag)
    return page_status


def _wait_for_seek_user_verification(list_page, page_tag: str, timeout_ms: int) -> bool:
    logger.warning(
        "[SEEK][WAITING_FOR_USER_VERIFICATION] %s waiting up to %dms for manual verification",
        page_tag,
        timeout_ms,
    )
    set_run_progress(_SEEK_FAILURE_MESSAGES[SEEK_HUMAN_VERIFICATION])
    try:
        list_page.wait_for_selector(SELECTOR_CARDS, timeout=timeout_ms)
    except Exception:
        logger.warning(
            "[SEEK][USER_VERIFICATION_TIMEOUT] %s manual verification did not complete in time",
            page_tag,
        )
        return False
    logger.info("[SEEK][USER_VERIFICATION_RESOLVED] %s manual verification completed", page_tag)
    return True


def _wait_for_seek_bot_challenge_or_manual_verification(
    list_page,
    page_tag: str,
    *,
    headless: bool,
    use_persistent_browser: bool,
    assisted_verification_enabled: bool,
    playwright_selector_timeout: int,
) -> bool:
    try:
        page_title = list_page.title()
    except Exception as title_exc:
        page_title = f"<title unavailable: {title_exc}>"

    try:
        body_text = str(list_page.inner_text("body") or "")
    except Exception as body_exc:
        body_text = f"<body unavailable: {body_exc}>"

    lowered = " ".join(part for part in [str(page_title or ""), body_text] if part.strip()).lower()
    if not any(marker in lowered for marker in _SEEK_BOT_CHALLENGE_MARKERS):
        return False

    logger.warning(
        "[SEEK][BOT_CHALLENGE_DETECTED] %s title=%r headless=%s persistent=%s",
        page_tag,
        page_title,
        headless,
        use_persistent_browser,
    )
    if assisted_verification_enabled and use_persistent_browser and not headless:
        set_run_progress(
            "SEEK needs verification. Open the AWS browser session and complete the check."
        )
        try:
            list_page.wait_for_selector(SELECTOR_CARDS, timeout=playwright_selector_timeout)
        except Exception as exc:
            logger.warning(
                "[SEEK][USER_VERIFICATION_TIMEOUT] %s challenge did not resolve in time",
                page_tag,
            )
            raise BotChallengeDetected(
                "SEEK is showing a bot challenge page and did not reach job cards.",
                failure_class=SEEK_BOT_CHALLENGE,
            ) from exc
        logger.info("[SEEK][BOT_CHALLENGE_RESOLVED] %s continuing scrape after verification", page_tag)
        return True

    raise BotChallengeDetected(
        "SEEK is showing a bot challenge page and did not reach job cards.",
        failure_class=SEEK_BOT_CHALLENGE,
    )


def _handle_seek_list_page_failure(
    page_tag: str,
    list_page,
    exc: Exception,
    snapshot: dict[str, object],
    *,
    page_status: str,
    failure_class: str,
    headless: bool,
    use_persistent_browser: bool,
    assisted_verification_enabled: bool,
    playwright_selector_timeout: int,
) -> bool:
    page_title = str(snapshot["title"])
    if failure_class == SEEK_HUMAN_VERIFICATION:
        logger.warning(
            "[SEEK][HUMAN_VERIFICATION_DETECTED] %s title=%r status=%s headless=%s persistent=%s",
            page_tag,
            page_title,
            page_status,
            headless,
            use_persistent_browser,
        )
        if assisted_verification_enabled and use_persistent_browser and not headless:
            page_recovered = _wait_for_seek_user_verification(
                list_page, page_tag, playwright_selector_timeout
            )
            if page_recovered:
                logger.info(
                    "[SEEK][HUMAN_VERIFICATION_RESOLVED] %s continuing scrape after manual verification",
                    page_tag,
                )
                set_run_progress("SEEK human verification resolved; continuing scrape.")
                return True
            set_run_progress(_SEEK_FAILURE_MESSAGES[SEEK_HUMAN_VERIFICATION])
            raise BotChallengeDetected(
                _SEEK_FAILURE_MESSAGES[SEEK_HUMAN_VERIFICATION],
                failure_class=SEEK_HUMAN_VERIFICATION,
            ) from exc
        logger.warning(
            "%s assisted SEEK verification requires AWS browser session access; "
            "on AWS this needs VNC/noVNC or secure admin port forwarding",
            page_tag,
        )
        set_run_progress(_SEEK_FAILURE_MESSAGES[SEEK_HUMAN_VERIFICATION])
        raise BotChallengeDetected(
            _SEEK_FAILURE_MESSAGES[SEEK_HUMAN_VERIFICATION],
            failure_class=SEEK_HUMAN_VERIFICATION,
        ) from exc
    if failure_class == SEEK_BOT_CHALLENGE:
        logger.warning(
            "[SEEK][BOT_CHALLENGE_DETECTED] %s title=%r status=%s headless=%s persistent=%s",
            page_tag,
            page_title,
            page_status,
            headless,
            use_persistent_browser,
        )
        set_run_progress(_SEEK_FAILURE_MESSAGES[SEEK_BOT_CHALLENGE])
        raise BotChallengeDetected(
            _SEEK_FAILURE_MESSAGES[SEEK_BOT_CHALLENGE],
            failure_class=SEEK_BOT_CHALLENGE,
        ) from exc
    if failure_class == SEEK_TIMEOUT_NO_CARDS:
        logger.info(
            "[SEEK][TIMEOUT_NO_CARDS] %s title=%r status=%s cards=%s",
            page_tag,
            page_title,
            page_status,
            snapshot["selector_count"],
        )
        set_run_progress(_SEEK_FAILURE_MESSAGES[SEEK_TIMEOUT_NO_CARDS])
        return False
    logger.warning(
        "[SEEK][UNKNOWN_FAILURE] %s title=%r status=%s headless=%s persistent=%s",
        page_tag,
        page_title,
        page_status,
        headless,
        use_persistent_browser,
    )
    set_run_progress(_SEEK_FAILURE_MESSAGES[SEEK_UNKNOWN_FAILURE])
    return False


def _seek_run_progress(
    page_num: int,
    total_pages: int,
    title: str = "",
    company: str = "",
    elapsed_s: float | int | None = None,
) -> str:
    progress = f"SEEK page {page_num}/{total_pages}"
    title_text = str(title or "").strip()
    company_text = str(company or "").strip()
    elapsed_text = _format_seek_elapsed(elapsed_s)
    if title_text and company_text:
        return (
            f"{progress}{RUN_PROGRESS_ITEM_SEPARATOR}"
            f"{title_text}{RUN_PROGRESS_TITLE_SEPARATOR}{company_text}"
            f"{RUN_PROGRESS_ITEM_SEPARATOR}{RUN_PROGRESS_ELAPSED_PREFIX}{elapsed_text}"
        )
    if title_text:
        return f"{progress}{RUN_PROGRESS_ITEM_SEPARATOR}{title_text}{RUN_PROGRESS_ITEM_SEPARATOR}{RUN_PROGRESS_ELAPSED_PREFIX}{elapsed_text}"
    if company_text:
        return f"{progress}{RUN_PROGRESS_ITEM_SEPARATOR}{company_text}{RUN_PROGRESS_ITEM_SEPARATOR}{RUN_PROGRESS_ELAPSED_PREFIX}{elapsed_text}"
    return f"{progress}{RUN_PROGRESS_ITEM_SEPARATOR}{RUN_PROGRESS_ELAPSED_PREFIX}{elapsed_text}"


def _seek_nested_value(payload: object, key_names: tuple[str, ...]) -> object:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key or "")
            if any(name in key_text for name in key_names) and value not in (None, "", [], {}):
                return value
            nested = _seek_nested_value(value, key_names)
            if nested not in (None, "", [], {}):
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _seek_nested_value(item, key_names)
            if nested not in (None, "", [], {}):
                return nested
    return None


def _seek_string_value(payload: object, key_names: tuple[str, ...]) -> str:
    value = _seek_nested_value(payload, key_names)
    return str(value).strip() if value not in (None, "", [], {}) else ""


def _seek_json_safe_value(value: object):
    if isinstance(value, dict):
        return {str(key): _seek_json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_seek_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_seek_json_safe_value(item) for item in value]
    if isinstance(value, (datetime,)):
        return value.isoformat()
    return value


def _seek_canonical_url(url: str) -> str:
    """Return the SEEK job URL with tracking params and fragment stripped."""
    try:
        parsed = urlsplit(url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    except Exception:
        return url.split("?", 1)[0].split("#", 1)[0]


def _seek_job_id_from_url(url: str) -> str:
    """Extract the numeric SEEK job ID from a job listing URL."""
    m = re.search(r"/job/(\d+)", url)
    return m.group(1) if m else ""


def _seek_advertiser_id_from_payload(payload: object) -> str:
    """Extract the advertiser or hirer ID from a SEEK page payload when present."""
    if not isinstance(payload, dict):
        return ""
    for block_key in ("advertiser", "hirer"):
        block = payload.get(block_key)
        if isinstance(block, dict):
            aid = str(block.get("id") or "").strip()
            if aid:
                return aid
    return ""


def _seek_source_metadata(
    detail_page, details_payload: dict, *, redux_payload=None, url: str = ""
) -> tuple[dict, object]:
    if redux_payload is None and detail_page is not None:
        try:
            redux_payload = detail_page.evaluate("window.SEEK_REDUX_DATA || null")
        except Exception:
            redux_payload = None

    combined_payload = redux_payload if redux_payload not in (None, "", [], {}) else details_payload
    apply_url = _seek_string_value(combined_payload, ("shareLink",))
    company_profile_url = _seek_string_value(combined_payload, ("companySearchUrl",))
    company_profile_name = _seek_string_value(
        combined_payload, ("normalisedOrganisationName", "companyProfileName")
    )
    advertiser_block = _seek_nested_value(combined_payload, ("advertiser",))
    if isinstance(advertiser_block, dict):
        poster_company = _seek_string_value(advertiser_block, ("name", "label", "value"))
    else:
        poster_company = _seek_string_value(combined_payload, ("advertiser", "name"))
    hiring_company = _seek_string_value(
        combined_payload, ("normalisedOrganisationName", "companyProfileName", "name")
    )
    raw_source_fields = {}
    for key in [
        "seekPostingSourceCode",
        "seekHirerJobReference",
        "seekPartnerMetadata",
        "hirer",
        "advertiser",
        "companySearchUrl",
        "companyProfile",
        "shareLink",
    ]:
        value = _seek_nested_value(combined_payload, (key,))
        if value not in (None, "", [], {}):
            raw_source_fields[key] = _seek_json_safe_value(value)

    ats_requisition_id = str(
        _seek_string_value(combined_payload, ("seekHirerJobReference",)) or ""
    ).strip()
    platform_job_id = str(
        _seek_string_value(combined_payload, ("seekPostingSourceCode",)) or ""
    ).strip()
    # Fall back to the numeric job ID embedded in the listing URL when payload lacks it.
    if not platform_job_id and url:
        platform_job_id = _seek_job_id_from_url(url)
    canonical_url = _seek_canonical_url(url) if url else ""
    advertiser_id = _seek_advertiser_id_from_payload(combined_payload)
    metadata = _build_initial_source_metadata(
        source="seek",
        raw_source_fields=raw_source_fields,
        apply_url=apply_url,
        canonical_url=canonical_url,
        company_profile_url=company_profile_url,
        company_profile_name=company_profile_name,
        advertiser_id=advertiser_id,
        poster_company=poster_company,
        hiring_company=hiring_company,
        platform_job_id=platform_job_id,
        ats_requisition_id=ats_requisition_id,
        ats_source="seek" if ats_requisition_id else "",
    )
    return metadata, combined_payload


def build_seek_card_record(
    card, search_target: dict, run_iso: str, page_num: int, filter_state=None
) -> dict:
    title_el = card.query_selector(SELECTOR_TITLE)
    company_el = card.query_selector(SELECTOR_COMPANY)
    posted_el = card.query_selector(SELECTOR_POSTED)
    card_meta = extract_card_metadata(card, filter_state=filter_state)
    card_text = (card.inner_text() or "").strip()

    title = title_el.inner_text().strip() if title_el else ""
    company = company_el.inner_text().strip() if company_el else ""
    posted = posted_el.inner_text().strip() if posted_el else ""
    if not posted:
        posted = extract_posted_text_from_card(card_text)
    posted = compact_whitespace(posted)
    posted_age_days = parse_seek_posted_age_days(posted)

    relative_url = title_el.get_attribute("href") if title_el else None
    full_url = build_full_seek_url(relative_url)
    record = build_initial_flat_record(
        run_iso=run_iso,
        search_location=search_target["location"],
        search_keywords=search_target["keywords"],
        source="seek",
        job_key=stable_job_key(full_url) if full_url else None,
        title=title,
        company=company,
        location=card_meta["location"],
        posted_text=posted,
        posted_age_days=posted_age_days,
        work_mode=card_meta["work_mode"],
        work_mode_source=card_meta["work_mode_source"],
        work_mode_evidence=card_meta["work_mode_evidence"],
        work_mode_needs_review=card_meta["work_mode_needs_review"],
        work_type=card_meta["work_type"],
        salary_str="",
        url=full_url,
        teaser=card_meta["teaser"],
        details_text="",
        details_length=0,
    )
    record[rs.RECORD_CARD_SALARY_KEY] = card_meta["card_salary"]
    return record


def apply_work_mode_enrichment(record: dict, raw_source_payload: object, details_text: str) -> None:
    detail_extraction = extract_from_seek_detail(raw_source_payload, details_text)
    detail_mode = detail_extraction["work_mode"]
    current_mode = record.get(rs.RECORD_WORK_MODE_KEY) or ""
    if detail_mode != WORK_MODE_UNKNOWN or not current_mode or current_mode == WORK_MODE_UNKNOWN:
        record[rs.RECORD_WORK_MODE_KEY] = detail_extraction["work_mode"]
        record[rs.RECORD_WORK_MODE_SOURCE_KEY] = detail_extraction["work_mode_source"]
        record[rs.RECORD_WORK_MODE_EVIDENCE_KEY] = detail_extraction["work_mode_evidence"]
        record[rs.RECORD_WORK_MODE_NEEDS_REVIEW_KEY] = detail_extraction["work_mode_needs_review"]
        log_work_mode_result(str(record.get(rs.RECORD_JOB_KEY) or ""), "seek", record)


def _build_seek_review_hooks(
    raw_html: str | None, raw_source_payload: object
) -> ReviewPipelineHooks:
    """Build review hooks from pre-captured page data.

    raw_html and raw_source_payload are captured in the main Playwright thread before
    any thread pool dispatch, so the hooks hold only plain Python objects — no live page.
    """

    def _after_description_loaded(record: dict, context: ReviewPipelineContext) -> None:
        if DEBUG_CAPTURE_SOURCE_PAYLOADS and raw_html is not None:
            try:
                write_source_payload_debug(
                    "seek",
                    str(
                        record.get(rs.RECORD_JOB_KEY) or record.get(rs.RECORD_URL_KEY) or "unknown"
                    ),
                    raw_html=raw_html,
                    raw_json=raw_source_payload,
                    normalized_record=record,
                )
            except Exception:
                pass

    def _after_preference_filters(record: dict, context: ReviewPipelineContext) -> None:
        apply_work_mode_enrichment(
            record, raw_source_payload, str(record.get(rs.RECORD_FIT_SOURCE_TEXT_KEY) or "")
        )

    return ReviewPipelineHooks(
        after_description_loaded=_after_description_loaded,
        after_preference_filters=_after_preference_filters,
    )


def _review_seek_job_detail(
    record: dict,
    review_context: ReviewPipelineContext,
) -> tuple[dict, dict, list[dict]]:
    """LLM review phase: run the review pipeline on a pre-fetched record.

    No Playwright calls — safe to run in a thread pool. Reads raw_source_payload and
    raw_html from private record keys written by _fetch_seek_job_detail.
    """
    raw_source_payload = record.pop("_raw_source_payload", None)
    raw_html = record.pop("_raw_html", None)
    hooks = _build_seek_review_hooks(raw_html, raw_source_payload)
    return review_post_detail_normalized_job(record, review_context, hooks=hooks)


async def _fetch_seek_job_detail_async(record: dict, page) -> dict:
    """Async Playwright fetch — mirrors _fetch_seek_job_detail but uses an async page.

    Called concurrently from _seek_detail_batch_async; each call owns its own page.
    Stores _raw_source_payload and _raw_html on the record for _review_seek_job_detail.
    """
    job_key = str(record.get(rs.RECORD_JOB_KEY) or "unknown")
    title = str(record.get(rs.RECORD_TITLE_KEY) or "")
    company = str(record.get(rs.RECORD_COMPANY_KEY) or "")
    logger.info(
        "[PIPELINE][DETAIL_FETCH_START] source=SEEK job_key=%s title=%r company=%r url=%r",
        job_key,
        title,
        company,
        str(record.get(rs.RECORD_URL_KEY) or ""),
    )
    _t0 = time.monotonic()
    details_payload = await fetch_job_details_payload_async(page, record[rs.RECORD_URL_KEY])
    details_text = str(details_payload.get("text") or "")
    details_status = str(details_payload.get("status") or ("ok" if details_text else "empty"))
    _fetch_ms = int((time.monotonic() - _t0) * 1000)
    logger.info(
        "[PIPELINE][DETAIL_FETCH_DONE] source=SEEK job_key=%s title=%r company=%r status=%r elapsed_ms=%d text_len=%d",
        job_key,
        title,
        company,
        details_status,
        _fetch_ms,
        len(details_text),
    )
    record["_obs_detail_fetch_ms"] = _fetch_ms

    redux_payload = None
    try:
        redux_payload = await page.evaluate("window.SEEK_REDUX_DATA || null")
    except Exception:
        pass
    raw_html = await page.content() if DEBUG_CAPTURE_SOURCE_PAYLOADS else None

    source_metadata, raw_source_payload = _seek_source_metadata(
        None, details_payload, redux_payload=redux_payload,
        url=str(record.get(rs.RECORD_URL_KEY) or ""),
    )
    record[rs.RECORD_SOURCE_METADATA_KEY] = source_metadata
    record[rs.RECORD_DESCRIPTION_SOURCE_KEY] = details_payload.get("source") or ""
    record[rs.RECORD_DETAILS_TEXT_KEY] = details_text
    record[rs.RECORD_DETAILS_STATUS_KEY] = details_status
    record["_raw_source_payload"] = raw_source_payload
    record["_raw_html"] = raw_html
    return record


async def _seek_detail_batch_on_context(
    needs_detail: list,
    browser_context,
    review_context,
    n_workers: int,
) -> dict:
    """Parallel detail fetch + LLM review on an existing async browser context.

    Each coroutine creates and closes its own page within the shared context.
    A semaphore caps concurrency to n_workers.
    Returns card_index -> (outcome, record, skill_obs, elapsed_s).
    """
    semaphore = asyncio.Semaphore(n_workers)
    results: dict[int, tuple] = {}

    async def _process_one(idx: int, rec: dict) -> None:
        # Skip queued-but-not-yet-started jobs immediately when stop is requested.
        # Jobs already holding the semaphore (in-flight LLM/fetch) run to completion.
        if run_stop_requested():
            rec[rs.RECORD_DECISION_KEY] = "REJECT"
            rec[rs.RECORD_REJECT_REASON_KEY] = "STOP_REQUESTED"
            finalize_record(
                review_context.job_history, review_context.audit_rows, rec, review_context.run_iso
            )
            results[idx] = ({"decision": "REJECT", "reject_reason": "STOP_REQUESTED"}, rec, [], 0.0)
            return
        async with semaphore:
            if run_stop_requested():
                rec[rs.RECORD_DECISION_KEY] = "REJECT"
                rec[rs.RECORD_REJECT_REASON_KEY] = "STOP_REQUESTED"
                finalize_record(
                    review_context.job_history,
                    review_context.audit_rows,
                    rec,
                    review_context.run_iso,
                )
                results[idx] = (
                    {"decision": "REJECT", "reject_reason": "STOP_REQUESTED"},
                    rec,
                    [],
                    0.0,
                )
                return
            page = await browser_context.new_page()
            t0 = time.monotonic()
            try:
                rec = await _fetch_seek_job_detail_async(rec, page)
                result = await asyncio.to_thread(_review_seek_job_detail, rec, review_context)
                results[idx] = (*result, time.monotonic() - t0)
            except Exception as exc:
                rec[rs.RECORD_DECISION_KEY] = "REJECT"
                rec[rs.RECORD_REJECT_REASON_KEY] = f"CARD_EXCEPTION:{type(exc).__name__}"
                finalize_record(
                    review_context.job_history,
                    review_context.audit_rows,
                    rec,
                    review_context.run_iso,
                )
                results[idx] = (
                    {"decision": "REJECT", "reject_reason": rec[rs.RECORD_REJECT_REASON_KEY]},
                    rec,
                    [],
                    0.0,
                )
                logger.warning(
                    "[SEEK] REJECTED (async detail) [CARD_EXCEPTION:%s] %s @ %s\n%s",
                    type(exc).__name__,
                    str(rec.get(rs.RECORD_TITLE_KEY) or ""),
                    str(rec.get(rs.RECORD_COMPANY_KEY) or ""),
                    traceback.format_exc(),
                )
            finally:
                await page.close()

    await asyncio.gather(*[_process_one(idx, rec) for idx, rec in needs_detail])
    return results


class _AsyncDetailSession:
    """Long-lived async Playwright session for SEEK detail page fetches.

    Runs a dedicated asyncio event loop in a background daemon thread and keeps
    one browser alive for the full duration of a scrape run.  All results pages
    submit their detail batches via run_batch() rather than relaunching the
    browser on every call.
    """

    def __init__(
        self, headless: bool, viewport_width: int, viewport_height: int, n_workers: int
    ) -> None:
        self._n_workers = n_workers
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="seek-detail-loop"
        )
        self._thread.start()
        init = asyncio.run_coroutine_threadsafe(
            self._start(headless, viewport_width, viewport_height), self._loop
        )
        init.result(timeout=30)

    async def _start(self, headless: bool, viewport_width: int, viewport_height: int) -> None:
        self._pw_cm = async_playwright_ctx()
        self._pw = await self._pw_cm.__aenter__()
        self._browser = await self._pw.chromium.launch(headless=headless, args=_BROWSER_ARGS)
        self._browser_context = await self._browser.new_context(
            viewport={"width": viewport_width, "height": viewport_height}
        )
        await self._browser_context.add_init_script(_WEBDRIVER_INIT)

    def run_batch(self, needs_detail: list, review_context) -> dict:
        """Submit a batch of cards for parallel fetch + LLM. Blocking until complete."""
        future = asyncio.run_coroutine_threadsafe(
            _seek_detail_batch_on_context(
                needs_detail, self._browser_context, review_context, self._n_workers
            ),
            self._loop,
        )
        return future.result()

    def close(self) -> None:
        """Shut down the browser and stop the background event loop cleanly."""
        close = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        close.result(timeout=30)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=10)

    async def _shutdown(self) -> None:
        await self._browser_context.close()
        await self._browser.close()
        await self._pw_cm.__aexit__(None, None, None)


def seek_scrape_to_records(
    profile: dict,
    search_targets: List[dict],
    job_history: Dict[str, dict],
    llm_cache: Dict[str, Any],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    run_iso: str,
    configured_date_range: int,
    configured_seek_max_pages: int,
    playwright_viewport_width: int,
    playwright_viewport_height: int,
    playwright_selector_timeout: int,
    seek_parallel_detail_workers: int,
    headless: bool,
    assisted_verification_enabled: bool,
) -> tuple:
    audit_rows: List[dict] = []
    kept_records: List[dict] = []
    skill_observations: List[dict] = []
    seen_urls: set[str] = set()
    review_context = ReviewPipelineContext(
        profile=profile,
        job_history=job_history,
        audit_rows=audit_rows,
        llm_cache=llm_cache,
        applied_job_keys=applied_job_keys,
        hidden_job_keys=hidden_job_keys,
        seen_job_keys=set(),
        seen_urls=seen_urls,
        run_iso=run_iso,
        date_range_days=configured_date_range,
        source_name="SEEK",
    )

    browser_mode = "persistent" if WORKSPACE_DEBUG_MODE else get_playwright_browser_mode()
    use_persistent_browser = browser_mode == "persistent"

    with sync_playwright() as playwright:
        n_detail_workers = max(1, seek_parallel_detail_workers)
        if use_persistent_browser:
            PLAYWRIGHT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PLAYWRIGHT_USER_DATA_DIR),
                headless=headless,
                viewport={"width": playwright_viewport_width, "height": playwright_viewport_height},
                args=_BROWSER_ARGS,
            )
            context.add_init_script(_WEBDRIVER_INIT)
            list_page = context.new_page()
        else:
            browser = playwright.chromium.launch(headless=headless, args=_BROWSER_ARGS)
            bctx = browser.new_context(
                viewport={"width": playwright_viewport_width, "height": playwright_viewport_height}
            )
            bctx.add_init_script(_WEBDRIVER_INIT)
            list_page = bctx.new_page()
            context = browser

        detail_session = _AsyncDetailSession(
            headless=headless,
            viewport_width=playwright_viewport_width,
            viewport_height=playwright_viewport_height,
            n_workers=n_detail_workers,
        )
        try:
            total_targets = len(search_targets)
            for target_index, search_target in enumerate(search_targets, start=1):
                if run_stop_requested():
                    logger.info("[SEEK] stop requested; ending scrape")
                    break
                base_search_url = search_target["url"]
                search_location = search_target["location"]
                search_keywords = search_target["keywords"]
                classification_ids = ",".join(search_target.get("classification_ids", []))
                current_page_num = 1
                target_t0 = time.monotonic()

                logger.info(
                    "[SEEK] target %d/%d | location=%s | keywords=%s | classifications=%s | pages=1..%d",
                    target_index,
                    total_targets,
                    search_location or "(all)",
                    search_keywords or "(unset)",
                    classification_ids or "(none)",
                    configured_seek_max_pages,
                )

                while current_page_num <= configured_seek_max_pages:
                    page_tag = f"[SEEK p{current_page_num}/{configured_seek_max_pages}]"
                    if run_stop_requested():
                        logger.info("%s stop requested; ending scrape", page_tag)
                        break
                    page_url = (
                        set_page_param(base_search_url, current_page_num)
                        if current_page_num > 1
                        else base_search_url
                    )

                    logger.info("%s url=%s", page_tag, page_url)

                    stop_target = False
                    try:
                        list_page.goto(page_url, wait_until="domcontentloaded")
                        bot_challenge_resolved = _wait_for_seek_bot_challenge_or_manual_verification(
                            list_page,
                            page_tag,
                            headless=headless,
                            use_persistent_browser=use_persistent_browser,
                            assisted_verification_enabled=assisted_verification_enabled,
                            playwright_selector_timeout=playwright_selector_timeout,
                        )
                        if not bot_challenge_resolved:
                            list_page.wait_for_selector(
                                SELECTOR_CARDS, timeout=playwright_selector_timeout
                            )
                    except Exception as exc:
                        page_status = _log_seek_list_page_diagnostics(
                            page_tag,
                            list_page,
                            exc,
                            selector_timeout=playwright_selector_timeout,
                        )
                        snapshot = _seek_list_page_diagnostics(list_page)
                        failure_class = str(snapshot["failure_class"])
                        try:
                            screenshot_path = pathlib.Path("output") / "seek_timeout_debug.png"
                            list_page.screenshot(path=str(screenshot_path), full_page=False)
                            logger.info("%s screenshot saved to %s", page_tag, screenshot_path)
                        except Exception as diag_exc:
                            logger.info("%s diagnostic capture failed: %s", page_tag, diag_exc)
                        _handle_seek_list_page_failure(
                            page_tag,
                            list_page,
                            exc,
                            snapshot,
                            page_status=page_status,
                            failure_class=failure_class,
                            headless=headless,
                            use_persistent_browser=use_persistent_browser,
                            assisted_verification_enabled=assisted_verification_enabled,
                            playwright_selector_timeout=playwright_selector_timeout,
                        )
                        if failure_class in {SEEK_TIMEOUT_NO_CARDS, SEEK_UNKNOWN_FAILURE}:
                            stop_target = True
                    if stop_target:
                        break

                    job_cards = list_page.query_selector_all(SELECTOR_CARDS)
                    logger.info("%s cards=%d", page_tag, len(job_cards))

                    if len(job_cards) == 0:
                        logger.info("%s no cards found; stopping target", page_tag)
                        break

                    filter_state = extract_seek_filter_panel_state(list_page)

                    # Phase 1: extract all card records from DOM before any page navigation
                    card_records: list[dict] = []
                    target_closed = False
                    for card in job_cards:
                        if run_stop_requested():
                            logger.info("%s stop requested; finishing current page", page_tag)
                            break
                        try:
                            record = build_seek_card_record(
                                card, search_target, run_iso, current_page_num, filter_state
                            )
                            record["job_quality_signals"] = detect_broad_engagement_signal(record)
                            card_records.append(record)
                        except TargetClosedError:
                            logger.warning(
                                "%s browser target closed during card build; stopping page",
                                page_tag,
                            )
                            target_closed = True
                            break
                        except Exception as exc:
                            logger.warning(
                                "%s REJECTED (card build) [%s]\n%s",
                                page_tag,
                                type(exc).__name__,
                                traceback.format_exc(),
                            )

                    set_run_progress(
                        _seek_run_progress(
                            current_page_num,
                            configured_seek_max_pages,
                            elapsed_s=time.monotonic() - target_t0,
                        )
                    )

                    page_has_fresh_card = any(
                        r.get(rs.RECORD_POSTED_AGE_DAYS_KEY) is None
                        or r.get(rs.RECORD_POSTED_AGE_DAYS_KEY) <= configured_date_range
                        for r in card_records
                    )

                    # Phase 2: pre-detail checks (fast, no network)
                    pre_decided: list[tuple[int, tuple]] = []
                    needs_detail: list[tuple[int, dict]] = []
                    for i, record in enumerate(card_records):
                        pre_outcome, record, _, should_fetch_details = (
                            review_pre_detail_normalized_job(record, review_context)
                        )
                        if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
                            pre_decided.append((i, (pre_outcome, record, [], 0.0)))
                        else:
                            needs_detail.append((i, record))

                    # batch_results: card_index -> (outcome, record, skill_obs, elapsed_s)
                    batch_results: dict[int, tuple] = {i: res for i, res in pre_decided}

                    # Phase 3: parallel detail fetch + LLM via persistent async browser
                    if needs_detail and not run_stop_requested() and not target_closed:
                        batch_results.update(detail_session.run_batch(needs_detail, review_context))

                    # Phase 4: process results in original card order
                    for i in range(len(card_records)):
                        if i not in batch_results:
                            continue
                        outcome, record, record_skill_observations, job_elapsed_s = batch_results[i]
                        title = str(record.get(rs.RECORD_TITLE_KEY) or "")
                        company = str(record.get(rs.RECORD_COMPANY_KEY) or "")
                        _job_decision = outcome.get("decision")
                        _job_score: int | None = None
                        _job_breakdown: list | None = None

                        if _job_decision == "KEEP":
                            _job_score, _job_breakdown = fit_score_and_breakdown_displayed(
                                record, profile
                            )
                            skill_observations.extend(record_skill_observations)
                            kept_records.append(record)
                            logger.info(
                                "%s KEPT %s @ %s | %s",
                                page_tag,
                                title,
                                company,
                                "SEEN_BEFORE" if record.get("seen_before") else "NEW",
                            )

                        if _job_decision in {"KEEP", "REJECT"}:
                            print_job_human_summary(
                                record,
                                profile,
                                elapsed_s=job_elapsed_s or None,
                                score=_job_score,
                                llm_cost=0.0,
                                breakdown=_job_breakdown,
                            )
                            close_job_block(str(record.get(rs.RECORD_JOB_KEY) or ""))

                    if target_closed:
                        break

                    if not page_has_fresh_card:
                        logger.info(
                            "%s all cards were older than %d day(s); stopping target",
                            page_tag,
                            configured_date_range,
                        )
                        break

                    if run_stop_requested():
                        break

                    current_page_num += 1
            set_run_progress("SEEK complete")
        finally:
            detail_session.close()
            context.close()

    return kept_records, audit_rows, skill_observations
