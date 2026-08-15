"""SEEK scraper runner helpers.

Purpose: orchestrate the SEEK Playwright flow, detail review, and record finalization.
"""

from __future__ import annotations

import asyncio
import copy
import contextvars
import json
import logging
import re
import sys
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, TimeoutError as FutureTimeoutError, wait
from datetime import datetime
from typing import Any, Dict, List, Set, cast
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

from playwright._impl._errors import TargetClosedError
from playwright.async_api import async_playwright as async_playwright_ctx
from playwright.sync_api import sync_playwright

import job_hunter_agent.record_schema as rs
from job_hunter_agent.global_settings import KEY_SEEK_QUICK_APPLY_ONLY, get_playwright_browser_mode
from job_hunter_agent.history import (
    apply_detail_evidence_reuse,
    build_detail_evidence_snapshot,
    can_reuse_detail_evidence,
    finalize_record,
)
from job_hunter_agent.io_utils import DEBUG_CAPTURE_SOURCE_PAYLOADS, write_source_payload_debug
from job_hunter_agent.job_quality import detect_broad_engagement_signal
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    ReviewPipelineHooks,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.paths import PLAYWRIGHT_USER_DATA_DIR
from job_hunter_agent.run_control import (
    run_stop_requested,
    set_run_progress,
    set_run_progress_state,
    step_through_enabled,
)
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
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.text_processing import compact_whitespace
from job_hunter_agent.utils import parse_seek_posted_age_days, set_page_param
from job_hunter_agent.work_mode_extraction import (
    WORK_MODE_UNKNOWN,
    extract_from_seek_detail,
    extract_seek_filter_panel_state,
    log_work_mode_result,
)

WORKSPACE_DEBUG_MODE = has_cli_flag(sys.argv, CLI_FLAG_DEBUG)
RUN_PROGRESS_ITEM_SEPARATOR = " | "


def seek_quick_apply_filter_matches(setting: object, apply_method: str) -> bool:
    """Return whether a SEEK record passes the configured Quick Apply filter."""
    if setting is None:
        return True
    is_quick_apply = str(apply_method or "").strip() == rs.APPLY_METHOD_QUICK_APPLY
    return bool(setting) == is_quick_apply


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
SEEK_DETAIL_SESSION_CLOSE_TIMEOUT_SECONDS = 2.0
SEEK_JOB_WAIT_TIMEOUT_SECONDS = 30.0
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
        logger.debug("[SEEK] card selector count unavailable: %s", count_exc)

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
    selector_count = cast(int, snapshot["selector_count"])
    page_status = str(snapshot["page_status"])
    failure_class = str(snapshot["failure_class"])
    logger.debug(
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
    logger.debug("%s wait_for_selector failed with %s", page_tag, type(exc).__name__)
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
    _CF_AUTO_RESOLVE_TIMEOUT_MS = 15000

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

    # Cloudflare's "Just a moment..." challenge runs JS and auto-resolves in a few seconds.
    # Wait for the title to change before deciding human intervention is required.
    if "just a moment" in lowered:
        logger.debug(
            "[SEEK][BOT_CHALLENGE_DETECTED] %s title=%r — Cloudflare JS challenge; waiting up to %dms for auto-resolve",
            page_tag,
            page_title,
            _CF_AUTO_RESOLVE_TIMEOUT_MS,
        )
        try:
            list_page.wait_for_function(
                "() => !document.title.toLowerCase().includes('just a moment')",
                timeout=_CF_AUTO_RESOLVE_TIMEOUT_MS,
            )
            try:
                page_title = list_page.title()
                body_text = str(list_page.inner_text("body") or "")
            except Exception:
                pass
            lowered = " ".join(
                part for part in [str(page_title or ""), body_text] if part.strip()
            ).lower()
            if not any(marker in lowered for marker in _SEEK_BOT_CHALLENGE_MARKERS):
                logger.info(
                    "[SEEK][BOT_CHALLENGE_RESOLVED] %s Cloudflare challenge auto-resolved", page_tag
                )
                return False
        except Exception:
            logger.debug(
                "[SEEK][BOT_CHALLENGE_WAIT] %s Cloudflare auto-resolve timed out; checking for human verification",
                page_tag,
            )
            try:
                page_title = list_page.title()
                body_text = str(list_page.inner_text("body") or "")
            except Exception:
                pass
            lowered = " ".join(
                part for part in [str(page_title or ""), body_text] if part.strip()
            ).lower()
            if not any(marker in lowered for marker in _SEEK_BOT_CHALLENGE_MARKERS):
                return False

    logger.warning(
        "[SEEK][BOT_CHALLENGE_DETECTED] %s title=%r headless=%s persistent=%s",
        page_tag,
        page_title,
        headless,
        use_persistent_browser,
    )
    if use_persistent_browser and not headless:
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
        if use_persistent_browser and not headless:
            page_recovered = _wait_for_seek_user_verification(
                list_page, page_tag, playwright_selector_timeout
            )
            if page_recovered:
                logger.debug(
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
        if use_persistent_browser and not headless:
            set_run_progress("SEEK needs verification. Open the AWS browser session and complete the check.")
            try:
                list_page.wait_for_selector(SELECTOR_CARDS, timeout=playwright_selector_timeout)
            except Exception as wait_exc:
                logger.warning(
                    "[SEEK][USER_VERIFICATION_TIMEOUT] %s challenge did not resolve in time",
                    page_tag,
                )
                raise BotChallengeDetected(
                    _SEEK_FAILURE_MESSAGES[SEEK_BOT_CHALLENGE],
                    failure_class=SEEK_BOT_CHALLENGE,
                ) from wait_exc
            logger.info("[SEEK][BOT_CHALLENGE_RESOLVED] %s continuing scrape after verification", page_tag)
            return True
        set_run_progress(_SEEK_FAILURE_MESSAGES[SEEK_BOT_CHALLENGE])
        raise BotChallengeDetected(
            _SEEK_FAILURE_MESSAGES[SEEK_BOT_CHALLENGE],
            failure_class=SEEK_BOT_CHALLENGE,
        ) from exc
    if failure_class == SEEK_TIMEOUT_NO_CARDS:
        logger.debug(
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



def _seek_run_progress(page_num: int, total_pages: int) -> str:
    """Return stable text progress; job detail and elapsed time are separate fields."""
    return f"SEEK page {page_num}/{total_pages}"


def _set_seek_run_progress(
    page_num: int,
    total_pages: int,
    *,
    detail: str = "",
) -> None:
    """Emit SEEK page progress using already-normalized card detail only."""
    set_run_progress_state(
        _seek_run_progress(page_num, total_pages),
        stage="source_collection",
        source="seek",
        headline=f"SEEK page {page_num} of {total_pages}",
        detail=str(detail or "").strip(),
        current=page_num,
        total=total_pages,
    )


def _seek_nested_value(payload: object, key_names: tuple[str, ...]) -> object:
    """Find the first matching SEEK GraphQL field by exact/base field name.

    SEEK serializes some fields as ``label({...})``; matching the base name
    is valid, but arbitrary substring matching would incorrectly treat
    ``__typename`` as a match for ``name``.
    """
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key or "")
            key_matches = any(
                key_text == name or key_text.startswith(f"{name}(") for name in key_names
            )
            if key_matches and value not in (None, "", [], {}):
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


def _seek_json_assignment_value(script_text: str, variable_name: str) -> object:
    """Read one JSON-backed window assignment from SEEK's server-state script."""
    marker = f"window.{variable_name} ="
    marker_index = script_text.find(marker)
    if marker_index < 0:
        return None

    json_text = script_text[marker_index + len(marker) :].lstrip()
    try:
        value, _ = json.JSONDecoder().raw_decode(json_text)
    except json.JSONDecodeError as exc:
        logger.warning(
            "[SEEK][SOURCE_METADATA] invalid %s JSON in server-state script: %s",
            variable_name,
            exc,
        )
        return None
    return value


async def _read_seek_redux_payload_async(page) -> object:
    """Read SEEK_REDUX_DATA from the structured server-state script.

    SEEK's job page can expose the JSON in the script before/without publishing
    the matching window global, so the script is the source-of-truth boundary.
    """
    locator = page.locator('script[data-automation="server-state"]')
    if await locator.count() == 0:
        logger.warning("[SEEK][SOURCE_METADATA] server-state script is missing")
        return None
    script_text = str(await locator.first.text_content() or "")
    return _seek_json_assignment_value(script_text, "SEEK_REDUX_DATA")


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
    """Extract the advertiser or hirer ID from SEEK's nested page payload."""
    for block_key in ("advertiser", "hirer"):
        block = _seek_nested_value(payload, (block_key,))
        if isinstance(block, dict):
            aid = str(block.get("id") or "").strip()
            if aid:
                return aid
    return ""


def _seek_source_metadata(
    detail_page, details_payload: dict, *, redux_payload=None, url: str = ""
) -> tuple[dict, object]:
    """Normalize SEEK publisher/company evidence without deciding posting channel.

    Structured source facts are preserved here for the later classifier.
    """
    if redux_payload is None and detail_page is not None:
        try:
            redux_payload = detail_page.evaluate("window.SEEK_REDUX_DATA || null")
        except Exception:
            redux_payload = None

    combined_payload = redux_payload if redux_payload not in (None, "", [], {}) else details_payload
    apply_url = str(details_payload.get("apply_url") or "").strip() or _seek_string_value(
        combined_payload, ("shareLink",)
    )
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
    if apply_url:
        raw_source_fields["apply_url"] = apply_url

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
        url=full_url or "",
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


def _review_pre_detail_batch(
    card_records: list[dict],
    review_context: ReviewPipelineContext,
    max_workers: int,
) -> tuple[list[tuple[int, tuple]], list[tuple[int, dict]]]:
    """Review title gates concurrently so one slow role cannot block later roles."""
    if not card_records:
        return [], []

    executor = ThreadPoolExecutor(max_workers=max(1, max_workers))
    started_at: dict[int, float] = {}
    started_lock = threading.Lock()

    def _run_one(index: int, record: dict):
        with started_lock:
            started_at[index] = time.monotonic()
        return review_pre_detail_normalized_job(record, review_context)

    # ThreadPoolExecutor workers don't inherit the caller's contextvars (e.g. the
    # signed-in user id), so per-user resource lookups inside the review pipeline
    # would fail without running each task in a copy of the caller's context. Each
    # submission gets its own copy since a Context can't run concurrently on two
    # threads at once.
    futures = {
        executor.submit(contextvars.copy_context().run, _run_one, index, record): (index, record)
        for index, record in enumerate(card_records)
    }
    pending = set(futures)
    pre_decided: list[tuple[int, tuple]] = []
    needs_detail: list[tuple[int, dict]] = []

    try:
        while pending:
            now = time.monotonic()
            expired = []
            for future in pending:
                index, _ = futures[future]
                with started_lock:
                    job_started_at = started_at.get(index)
                if (
                    job_started_at is not None
                    and now - job_started_at >= SEEK_JOB_WAIT_TIMEOUT_SECONDS
                    and not future.done()
                ):
                    expired.append(future)
            for future in expired:
                pending.remove(future)
                index, record = futures[future]
                future.cancel()
                record[rs.RECORD_DECISION_KEY] = "REJECT"
                record[rs.RECORD_REJECT_REASON_KEY] = "SEEK_JOB_TIMEOUT"
                finalize_record(
                    review_context.job_history,
                    review_context.audit_rows,
                    record,
                    review_context.run_iso,
                )
                pre_decided.append(
                    (
                        index,
                        (
                            {"decision": "REJECT", "reject_reason": "SEEK_JOB_TIMEOUT"},
                            record,
                            [],
                            SEEK_JOB_WAIT_TIMEOUT_SECONDS,
                        ),
                    )
                )
                logger.warning(
                    "[SEEK][JOB_TIMEOUT] job_key=%s title=%r timeout_seconds=%s; continuing with other roles",
                    str(record.get(rs.RECORD_JOB_KEY) or ""),
                    str(record.get(rs.RECORD_TITLE_KEY) or ""),
                    SEEK_JOB_WAIT_TIMEOUT_SECONDS,
                )

            if not pending:
                break

            done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                pending.remove(future)
                index, _ = futures[future]
                pre_outcome, record, skill_observations, should_fetch_details = future.result()
                if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
                    pre_decided.append((index, (pre_outcome, record, skill_observations, 0.0)))
                else:
                    needs_detail.append((index, record))
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    pre_decided.sort(key=lambda item: item[0])
    needs_detail.sort(key=lambda item: item[0])
    return pre_decided, needs_detail


def _review_seek_card_batch(
    card_records: list[dict],
    review_context: ReviewPipelineContext,
    detail_session: "_AsyncDetailSession",
    n_detail_workers: int,
    kept_records: list[dict],
    skill_observations: list[dict],
) -> None:
    """Review live or cached discovery records through the existing pipeline."""
    if not card_records:
        return
    if step_through_enabled():
        for index, record in enumerate(card_records):
            if run_stop_requested():
                break
            pre_outcome, record, _, should_fetch_details = review_pre_detail_normalized_job(
                record, review_context
            )
            if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
                outcome, observations = pre_outcome, []
            else:
                outcome, _, observations, _ = detail_session.run_batch(
                    [(index, record)], review_context
                )[index]
            if outcome.get("decision") == "KEEP":
                skill_observations.extend(observations)
                kept_records.append(record)
        return

    pre_decided, needs_detail = _review_pre_detail_batch(
        card_records, review_context, n_detail_workers
    )
    batch_results: dict[int, tuple] = {index: result for index, result in pre_decided}
    if needs_detail and not run_stop_requested():
        batch_results.update(detail_session.run_batch(needs_detail, review_context))
    for index in range(len(card_records)):
        if index not in batch_results:
            continue
        outcome, record, observations, _ = batch_results[index]
        if outcome.get("decision") == "KEEP":
            skill_observations.extend(observations)
            kept_records.append(record)


async def _fetch_seek_job_detail_async(record: dict, page) -> dict:
    """Async Playwright fetch — mirrors _fetch_seek_job_detail but uses an async page.

    Called concurrently from _seek_detail_batch_async; each call owns its own page.
    Stores _raw_source_payload and _raw_html on the record for _review_seek_job_detail.
    """
    job_key = str(record.get(rs.RECORD_JOB_KEY) or "unknown")
    title = str(record.get(rs.RECORD_TITLE_KEY) or "")
    company = str(record.get(rs.RECORD_COMPANY_KEY) or "")
    logger.debug(
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
    logger.debug(
        "[PIPELINE][DETAIL_FETCH_DONE] source=SEEK job_key=%s title=%r company=%r status=%r elapsed_ms=%d text_len=%d",
        job_key,
        title,
        company,
        details_status,
        _fetch_ms,
        len(details_text),
    )
    record["_obs_detail_fetch_ms"] = _fetch_ms

    redux_payload = await _read_seek_redux_payload_async(page)
    raw_html = await page.content() if DEBUG_CAPTURE_SOURCE_PAYLOADS else None

    source_metadata, raw_source_payload = _seek_source_metadata(
        None, details_payload, redux_payload=redux_payload,
        url=str(record.get(rs.RECORD_URL_KEY) or ""),
    )
    record[rs.RECORD_SOURCE_METADATA_KEY] = source_metadata
    record[rs.RECORD_DESCRIPTION_SOURCE_KEY] = details_payload.get("source") or ""
    record[rs.RECORD_DETAILS_TEXT_KEY] = details_text
    record[rs.RECORD_DETAILS_STATUS_KEY] = details_status
    record[rs.RECORD_APPLY_METHOD_KEY] = details_payload.get("apply_method") or rs.APPLY_METHOD_UNKNOWN
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
            job_key = str(rec.get(rs.RECORD_JOB_KEY) or "")
            history_entry = review_context.job_history.get(job_key) if job_key else None
            cache_hit = history_entry is not None and can_reuse_detail_evidence(
                history_entry, review_context.date_range_days, review_context.run_iso
            )
            page = None
            t0 = time.monotonic()
            try:
                if cache_hit:
                    rec = apply_detail_evidence_reuse(rec, history_entry)
                    logger.debug(
                        "[PIPELINE][DETAIL_CACHE_HIT] source=SEEK job_key=%s title=%r company=%r url=%r",
                        job_key,
                        rec.get(rs.RECORD_TITLE_KEY),
                        rec.get(rs.RECORD_COMPANY_KEY),
                        rec.get(rs.RECORD_URL_KEY),
                    )
                else:
                    page = await browser_context.new_page()
                    rec = await _fetch_seek_job_detail_async(rec, page)
                    if job_key:
                        entry = review_context.job_history.setdefault(job_key, {})
                        entry["detail_evidence"] = build_detail_evidence_snapshot(
                            rec, review_context.run_iso
                        )
                quick_apply_only = review_context.profile.get("search_settings", {}).get(
                    KEY_SEEK_QUICK_APPLY_ONLY
                )
                apply_method = str(rec.get(rs.RECORD_APPLY_METHOD_KEY) or rs.APPLY_METHOD_UNKNOWN)
                if not seek_quick_apply_filter_matches(quick_apply_only, apply_method):
                    rec[rs.RECORD_DECISION_KEY] = "REJECT"
                    rec[rs.RECORD_REJECT_REASON_KEY] = "SEEK_QUICK_APPLY_FILTER"
                    finalize_record(
                        review_context.job_history,
                        review_context.audit_rows,
                        rec,
                        review_context.run_iso,
                    )
                    result = (
                        {"decision": "REJECT", "reject_reason": "SEEK_QUICK_APPLY_FILTER"},
                        rec,
                        [],
                    )
                else:
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
                if page is not None:
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
        # This thread doesn't inherit the caller's contextvars (e.g. the signed-in
        # user id), so per-user resource lookups inside review work scheduled on
        # this loop would fail without running it in a copy of the caller's context.
        loop_context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=loop_context.run,
            args=(self._loop.run_forever,),
            daemon=True,
            name="seek-detail-loop",
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
        try:
            close.result(timeout=SEEK_DETAIL_SESSION_CLOSE_TIMEOUT_SECONDS)
        except FutureTimeoutError:
            logger.warning(
                "[SEEK] detail session close timed out after %.1fs; forcing loop shutdown",
                SEEK_DETAIL_SESSION_CLOSE_TIMEOUT_SECONDS,
            )
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
    discovery_records: list[dict] | None = None,
    discovery_capture: list[dict] | None = None,
) -> tuple:
    """Collect, review and return SEEK records while publishing bounded stage progress.

    Progress must reuse normalized card data and must not add browser calls that
    could change or break scraping behaviour.
    """
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
    logger.debug(
        "[SEEK][BROWSER_MODE] mode=%s headless=%s assisted_verification=%s profile_dir=%s",
        browser_mode,
        headless,
        assisted_verification_enabled,
        str(PLAYWRIGHT_USER_DATA_DIR) if use_persistent_browser else "(ephemeral)",
    )

    try:
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
                if discovery_records is not None:
                    cached_records = [copy.deepcopy(record) for record in discovery_records]
                    for record in cached_records:
                        record[rs.RECORD_RUN_STARTED_AT_KEY] = run_iso
                    _set_seek_run_progress(
                        1, max(1, total_targets), detail="Cached discovery results"
                    )
                    _review_seek_card_batch(
                        cached_records,
                        review_context,
                        detail_session,
                        n_detail_workers,
                        kept_records,
                        skill_observations,
                    )
                for target_index, search_target in enumerate(search_targets, start=1):
                    if discovery_records is not None:
                        break
                    if run_stop_requested():
                        logger.debug("[SEEK] stop requested; ending scrape")
                        break
                    base_search_url = search_target["url"]
                    search_location = search_target["location"]
                    search_keywords = search_target["keywords"]
                    classification_ids = ",".join(search_target.get("classification_ids", []))
                    current_page_num = 1
                    target_t0 = time.monotonic()

                    logger.debug(
                        "\n"
                        "================================================================\n"
                        "  STARTING SEEK TARGET %d/%d\n"
                        "  location=%s\n"
                        "  keywords=%s\n"
                        "  classifications=%s\n"
                        "  pages=1..%d\n"
                        "================================================================",
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
                            logger.debug("%s stop requested; ending scrape", page_tag)
                            break
                        page_url = (
                            set_page_param(base_search_url, current_page_num)
                            if current_page_num > 1
                            else base_search_url
                        )

                        logger.debug("%s url=%s", page_tag, page_url)

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
                        logger.debug("%s cards=%d", page_tag, len(job_cards))

                        if len(job_cards) == 0:
                            logger.debug("%s no cards found; stopping target", page_tag)
                            break

                        filter_state = extract_seek_filter_panel_state(list_page)

                        # Phase 1: extract all card records from DOM before any page navigation
                        card_records: list[dict] = []
                        target_closed = False
                        for card in job_cards:
                            if run_stop_requested():
                                logger.debug("%s stop requested; finishing current page", page_tag)
                                break
                            try:
                                record = build_seek_card_record(
                                    card, search_target, run_iso, current_page_num, filter_state
                                )
                                record[rs.RECORD_PAGE_KEY] = current_page_num
                                record["job_quality_signals"] = detect_broad_engagement_signal(record)
                                if discovery_capture is not None:
                                    discovery_capture.append(copy.deepcopy(record))
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

                        # Reuse already-extracted card records for progress detail.
                        # This avoids extra DOM queries that could fail or slow scraping.
                        first_title = ""
                        first_company = ""
                        if card_records:
                            first_record = card_records[0]
                            first_title = str(first_record.get(rs.RECORD_TITLE_KEY) or "").strip()
                            first_company = str(first_record.get(rs.RECORD_COMPANY_KEY) or "").strip()

                        if first_title and first_company:
                            detail_text = f"{first_title} at {first_company}"
                        elif first_title:
                            detail_text = first_title
                        elif first_company:
                            detail_text = first_company
                        else:
                            detail_text = ""

                        _set_seek_run_progress(
                            current_page_num,
                            configured_seek_max_pages,
                            detail=detail_text,
                        )

                        page_has_fresh_card = any(
                            (age := r.get(rs.RECORD_POSTED_AGE_DAYS_KEY)) is None
                            or age <= configured_date_range
                            for r in card_records
                        )

                        if step_through_enabled():
                            # Step-through mode runs card-by-card so the operator can review
                            # each job before the batch advances.
                            for i, record in enumerate(card_records):
                                if run_stop_requested():
                                    break
                                pre_outcome, record, _, should_fetch_details = (
                                    review_pre_detail_normalized_job(record, review_context)
                                )
                                if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
                                    outcome, record, record_skill_observations, job_elapsed_s = (
                                        pre_outcome,
                                        record,
                                        [],
                                        0.0,
                                    )
                                else:
                                    single_result = detail_session.run_batch(
                                        [(i, record)], review_context
                                    )
                                    outcome, record, record_skill_observations, job_elapsed_s = (
                                        single_result[i]
                                    )

                                title = str(record.get(rs.RECORD_TITLE_KEY) or "")
                                company = str(record.get(rs.RECORD_COMPANY_KEY) or "")
                                _job_decision = outcome.get("decision")

                                if _job_decision == "KEEP":
                                    skill_observations.extend(record_skill_observations)
                                    kept_records.append(record)
                                    logger.debug(
                                        "%s KEPT %s @ %s | %s",
                                        page_tag,
                                        title,
                                        company,
                                        "SEEN_BEFORE" if record.get("seen_before") else "NEW",
                                    )
                        else:
                            # Phase 2: title/O*NET/LLM checks run concurrently. A slow role
                            # cannot hold every later role behind it.
                            pre_decided, needs_detail = _review_pre_detail_batch(
                                card_records,
                                review_context,
                                n_detail_workers,
                            )

                            # batch_results: card_index -> (outcome, record, skill_obs, elapsed_s)
                            batch_results: dict[int, tuple] = {i: res for i, res in pre_decided}

                            # Phase 3: parallel detail fetch + LLM via persistent async browser
                            if needs_detail and not run_stop_requested() and not target_closed:
                                batch_results.update(
                                    detail_session.run_batch(needs_detail, review_context)
                                )

                            # Phase 4: process results in original card order
                            for i in range(len(card_records)):
                                if i not in batch_results:
                                    continue
                                outcome, record, record_skill_observations, job_elapsed_s = (
                                    batch_results[i]
                                )
                                title = str(record.get(rs.RECORD_TITLE_KEY) or "")
                                company = str(record.get(rs.RECORD_COMPANY_KEY) or "")
                                _job_decision = outcome.get("decision")

                                if _job_decision == "KEEP":
                                    skill_observations.extend(record_skill_observations)
                                    kept_records.append(record)
                                    logger.debug(
                                        "%s KEPT %s @ %s | %s",
                                        page_tag,
                                        title,
                                        company,
                                        "SEEN_BEFORE" if record.get("seen_before") else "NEW",
                                    )

                        if target_closed:
                            break

                        if not page_has_fresh_card:
                            logger.debug(
                                "%s all cards were older than %d day(s); stopping target",
                                page_tag,
                                configured_date_range,
                            )
                            break

                        if run_stop_requested():
                            break

                        current_page_num += 1
                set_run_progress_state(
                    "SEEK complete",
                    stage="source_collection",
                    source="seek",
                    headline="SEEK",
                    detail="Source collection complete",
                    determinate=False,
                )
            finally:
                detail_session.close()
                context.close()
    except BotChallengeDetected:
        raise
    except Exception as exc:
        raise PartialSourceResultsError(
            "seek",
            kept_records=kept_records,
            audit_rows=audit_rows,
            skill_observations=skill_observations,
            original_error=exc,
        ) from exc

    return kept_records, audit_rows, skill_observations
