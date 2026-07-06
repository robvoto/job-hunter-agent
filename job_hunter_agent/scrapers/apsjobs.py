"""APSJobs source scraper."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import List
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright

from job_hunter_agent.fit_scoring import fit_score_and_breakdown_displayed
from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_APSJOBS_RESULTS_PER_SEARCH,
    KEY_DATE_RANGE_DAYS,
)
from job_hunter_agent.io_utils import DEBUG_CAPTURE_SOURCE_PAYLOADS, write_source_payload_debug
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    ReviewPipelineHooks,
    print_job_human_summary,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.job_types import load_job_type
from job_hunter_agent.paths import PLAYWRIGHT_USER_DATA_DIR
from job_hunter_agent.posting_utils import parse_visible_posted_age_days
from job_hunter_agent.profile_store import get_search_settings
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_JOB_KEY,
    RECORD_LOCATION_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_SALARY_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
)
from job_hunter_agent.run_control import run_stop_requested, set_run_progress
from job_hunter_agent.scrapers.base import (
    BaseJobScraper,
    _build_initial_source_metadata,
    build_initial_flat_record,
    map_job_type,
)
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.source_registry import SOURCE_APSJOBS
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order
from job_hunter_agent.work_mode_extraction import WORK_MODE_UNKNOWN, extract_from_text, log_work_mode_result

logger = logging.getLogger(__name__)

APSJOBS_ROOT_URL = "https://www.apsjobs.gov.au/s/"
APSJOBS_SEARCH_INPUT_SELECTORS = (
    "input[type='search']",
    "input[placeholder*='search' i]",
    "input[aria-label*='search' i]",
    "input[name*='search' i]",
    "input[name*='keyword' i]",
)
APSJOBS_LOCATION_INPUT_SELECTORS = (
    "input[placeholder*='location' i]",
    "input[aria-label*='location' i]",
    "input[name*='location' i]",
)
APSJOBS_JOB_LINK_HINTS = (
    "/job/",
    "/jobs/",
    "jobdetail",
    "job-details",
    "vacanc",
    "career",
    "position",
)
APSJOBS_TITLE_SELECTORS = (
    "h1",
    "h2",
    "[data-testid*='job-title' i]",
    "[class*='job-title' i]",
    "[class*='jobtitle' i]",
)

job_type_rules = load_job_type()


def _first_non_empty(*values: object) -> str:
    for value in values:
        text = compact_whitespace(value)
        if text:
            return text
    return ""


def _page_text(page) -> str:
    try:
        return str(page.locator("body").inner_text() or "")
    except Exception:
        try:
            return str(page.text_content("body") or "")
        except Exception:
            try:
                return str(page.content() or "")
            except Exception:
                return ""


def _locator_text(page, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            if locator.count():
                text = compact_whitespace(locator.first.inner_text())
                if text:
                    return text
        except Exception:
            continue
    return ""


def _first_visible_locator(page, selectors: tuple[str, ...]):
    """Return the first visible element matching any selector, or None.

    A selector can match multiple elements (e.g. duplicate desktop/mobile
    copies of the same field); picking `.first` blindly can resolve to a
    hidden one and hang on `.fill()` until the action times out.
    """
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = locator.count()
        except Exception:
            continue
        for index in range(count):
            candidate = locator.nth(index)
            try:
                if candidate.is_visible():
                    return candidate
            except Exception:
                continue
    return None


def _looks_like_job_link(href: str, text: str) -> bool:
    lowered = f"{href} {text}".lower()
    if not href:
        return False
    if any(hint in lowered for hint in APSJOBS_JOB_LINK_HINTS):
        return True
    return bool(text) and "aps jobs" not in lowered and "home" not in lowered


def _collect_candidate_links(page, base_url: str, results_wanted: int) -> list[dict[str, str]]:
    anchors = page.locator("a[href]")
    anchor_count = min(anchors.count(), 500)
    collected: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for index in range(anchor_count):
        try:
            anchor = anchors.nth(index)
            href = str(anchor.get_attribute("href") or "").strip()
            text = compact_whitespace(anchor.inner_text())
        except Exception:
            continue
        abs_url = urljoin(base_url, href)
        if not _looks_like_job_link(abs_url, text):
            continue
        if abs_url in seen_urls:
            continue
        seen_urls.add(abs_url)
        collected.append({"url": abs_url, "text": text})
        if len(collected) >= results_wanted:
            break
    return collected


def _extract_labeled_value(lines: list[str], labels: tuple[str, ...]) -> str:
    labels_lower = tuple(label.lower() for label in labels)
    for index, line in enumerate(lines):
        cleaned = compact_whitespace(line)
        lowered = cleaned.lower()
        if not cleaned:
            continue
        if not any(label in lowered for label in labels_lower):
            continue
        if ":" in cleaned:
            _, tail = cleaned.split(":", 1)
            tail = compact_whitespace(tail)
            if tail:
                return tail
        if index + 1 < len(lines):
            next_line = compact_whitespace(lines[index + 1])
            if next_line:
                return next_line
    return ""


def _extract_posted_text(text: str) -> str:
    patterns = (
        r"\b(?:posted|advertised|published)\s+(?:on\s+)?\d{1,2}\s+[A-Za-z]+\s+\d{4}\b",
        r"\b(?:posted|advertised|published)\s+(?:on\s+)?[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b",
        r"\b(?:posted|advertised|published)\s+(?:on\s+)?\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago\b",
        r"\b\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago\b",
        r"\b(?:today|yesterday|just now)\b",
    )
    cleaned = compact_whitespace(text)
    lowered = cleaned.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered, flags=re.IGNORECASE)
        if match:
            return compact_whitespace(match.group(0))
    return ""


def _extract_job_type_text(text: str) -> str:
    lines = [compact_whitespace(line) for line in text.splitlines()]
    for label in ("employment type", "job type", "classification", "engagement type", "type"):
        value = _extract_labeled_value(lines, (label,))
        if value:
            return value
    lowered = compact_whitespace(text).lower()
    for candidate in (
        "ongoing",
        "non-ongoing",
        "permanent",
        "temporary",
        "contract",
        "full time",
        "part time",
    ):
        if candidate in lowered:
            return candidate
    return ""


def _extract_job_payload(page, *, job_url: str, anchor_text: str, run_iso: str) -> dict:
    body_text = _page_text(page)
    lines = body_text.splitlines()
    title = _first_non_empty(
        _locator_text(page, APSJOBS_TITLE_SELECTORS),
        anchor_text,
    )
    company = _extract_labeled_value(lines, ("agency", "organisation", "organization", "department", "employer", "company"))
    location = _extract_labeled_value(lines, ("location", "locations"))
    posted_text = _extract_posted_text(body_text)
    run_date = datetime.fromisoformat(run_iso).date()
    posted_age_days = parse_visible_posted_age_days(posted_text or body_text, run_date)

    work_mode_result = extract_from_text(body_text, source_label="apsjobs_text")
    work_mode = str(work_mode_result.get("work_mode") or WORK_MODE_UNKNOWN)
    work_mode_source = str(work_mode_result.get("work_mode_source") or "apsjobs_text")
    work_mode_evidence = dedupe_preserve_order(
        [str(item) for item in work_mode_result.get("work_mode_evidence") or [] if str(item).strip()]
    )
    work_mode_needs_review = bool(work_mode_result.get("needs_review"))
    log_work_mode_result(
        job_url,
        "APSJobs",
        {
            "job_key": job_url,
            "title": title or anchor_text,
            "work_mode": work_mode,
            "work_mode_source": work_mode_source,
            "work_mode_evidence": work_mode_evidence,
            "work_mode_needs_review": work_mode_needs_review,
        },
    )

    raw_job_type = _extract_job_type_text(body_text)
    work_type = map_job_type(raw_job_type, job_type_rules)
    salary = ""

    source_metadata = _build_initial_source_metadata(
        source=SOURCE_APSJOBS,
        raw_source_fields={
            "job_url": job_url,
            "anchor_text": anchor_text,
            "posted_text": posted_text,
            "page_text": body_text[:5000],
        },
        apply_url=job_url,
        canonical_url=job_url,
        company_profile_name=company,
        poster_company=company,
        hiring_company=company,
        platform_job_id=job_url,
    )

    normalized_job_key = normalize_job_key(job_url, source=SOURCE_APSJOBS)
    if not normalized_job_key:
        key_basis = compact_whitespace(urlsplit(job_url).path or anchor_text or "listing").lower()
        normalized_job_key = (
            f"{SOURCE_APSJOBS}:"
            f"{re.sub(r'[^a-z0-9_-]+', '-', key_basis).strip('-') or 'listing'}"
        )

    return {
        "job_key": normalized_job_key,
        "title": title or anchor_text or "APSJobs listing",
        "company": company,
        "location": location,
        "posted_text": posted_text,
        "posted_age_days": posted_age_days,
        "work_mode": work_mode,
        "work_mode_source": work_mode_source,
        "work_mode_evidence": work_mode_evidence,
        "work_mode_needs_review": work_mode_needs_review,
        "work_type": work_type,
        "salary": salary,
        "url": job_url,
        "teaser": body_text[:240].strip(),
        "details_text": body_text,
        "source_metadata": source_metadata,
    }


def build_apsjobs_search_targets(search_settings: dict) -> tuple[str, list[dict]]:
    """Build APSJobs search targets from search settings.

    Returns the trimmed keywords string and one target per configured location
    (or a single location-less target when none are configured).
    """
    keywords = str(search_settings.get("keywords") or "").strip()
    locations = [
        str(location).strip()
        for location in search_settings.get("locations", [])
        if str(location).strip()
    ]
    results_wanted = int(
        search_settings.get(
            KEY_APSJOBS_RESULTS_PER_SEARCH,
            DEFAULT_SEARCH_SETTINGS[KEY_APSJOBS_RESULTS_PER_SEARCH],
        )
        or DEFAULT_SEARCH_SETTINGS[KEY_APSJOBS_RESULTS_PER_SEARCH]
    )
    targets = [
        {"search_term": keywords, "location": location, "results_wanted": results_wanted}
        for location in locations
    ] or [{"search_term": keywords, "location": "", "results_wanted": results_wanted}]
    return keywords, targets


class APSJobsScraper(BaseJobScraper):
    source_name = SOURCE_APSJOBS

    def scrape(self) -> tuple:
        kept_records: List[dict] = []
        audit_rows: List[dict] = []
        skill_observations: List[dict] = []

        search_settings = get_search_settings(self.profile)
        keywords, targets = build_apsjobs_search_targets(search_settings)
        if not keywords:
            logger.info("[APSJobs] no search keywords configured; skipping")
            return kept_records, audit_rows, skill_observations

        review_context = ReviewPipelineContext(
            profile=self.profile,
            job_history=self.job_history,
            audit_rows=audit_rows,
            llm_cache=self.llm_cache,
            applied_job_keys=self.applied_job_keys,
            hidden_job_keys=self.hidden_job_keys,
            run_iso=self.run_iso,
            date_range_days=int(
                search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
                or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]
            ),
            source_name="APSJobs",
        )

        PLAYWRIGHT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        total_targets = len(targets)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PLAYWRIGHT_USER_DATA_DIR),
                headless=True,
                viewport={"width": 1400, "height": 900},
            )
            try:
                for target_index, target in enumerate(targets, start=1):
                    if run_stop_requested():
                        break
                    target_tag = f"[APSJobs target {target_index}/{total_targets}]"
                    set_run_progress(f"APSJobs search {target_index}/{total_targets}")
                    page = context.new_page()
                    try:
                        page.goto(APSJOBS_ROOT_URL, wait_until="domcontentloaded")
                        page.wait_for_timeout(1500)
                        search_box = _first_visible_locator(page, APSJOBS_SEARCH_INPUT_SELECTORS)
                        if search_box is not None:
                            try:
                                search_box.fill(target["search_term"], timeout=5000)
                                search_box.press("Enter")
                            except Exception:
                                logger.warning(
                                    "%s search box found but could not be filled; continuing without a search term",
                                    target_tag,
                                )
                        else:
                            logger.warning(
                                "%s no visible search box found; continuing without a search term",
                                target_tag,
                            )
                        location_box = _first_visible_locator(page, APSJOBS_LOCATION_INPUT_SELECTORS)
                        if location_box is not None and target["location"]:
                            try:
                                location_box.fill(target["location"], timeout=5000)
                            except Exception:
                                logger.warning(
                                    "%s location box found but could not be filled; continuing without a location filter",
                                    target_tag,
                                )
                        page.wait_for_timeout(2000)

                        candidate_links = _collect_candidate_links(
                            page, page.url or APSJOBS_ROOT_URL, int(target["results_wanted"])
                        )
                        if not candidate_links:
                            logger.info("%s no candidate links found", target_tag)
                            continue

                        logger.info("%s candidate_links=%d", target_tag, len(candidate_links))
                        for link in candidate_links:
                            if run_stop_requested():
                                break
                            detail_page = context.new_page()
                            try:
                                detail_page.goto(link["url"], wait_until="domcontentloaded")
                                detail_page.wait_for_timeout(1200)
                                payload = _extract_job_payload(
                                    detail_page,
                                    job_url=detail_page.url or link["url"],
                                    anchor_text=link["text"],
                                    run_iso=self.run_iso,
                                )
                            finally:
                                detail_page.close()

                            record = build_initial_flat_record(
                                run_iso=self.run_iso,
                                search_location=target["location"],
                                search_keywords=target["search_term"],
                                source=self.source_name,
                                job_key=payload["job_key"],
                                title=payload["title"],
                                company=payload["company"],
                                location=payload["location"],
                                posted_text=payload["posted_text"],
                                posted_age_days=payload["posted_age_days"],
                                work_mode=payload["work_mode"],
                                work_mode_source=payload["work_mode_source"],
                                work_mode_evidence=payload["work_mode_evidence"],
                                work_mode_needs_review=payload["work_mode_needs_review"],
                                work_type=payload["work_type"],
                                salary_str=payload["salary"],
                                url=payload["url"],
                                teaser=payload["teaser"],
                                details_text=payload["details_text"],
                                details_length=len(payload["details_text"]),
                                source_metadata=payload["source_metadata"],
                            )
                            record[RECORD_DESCRIPTION_SOURCE_KEY] = "apsjobs_detail_page"
                            record[RECORD_DETAILS_TEXT_KEY] = str(record.get(RECORD_DETAILS_TEXT_KEY) or "")

                            pre_outcome, record, _, should_fetch_details = review_pre_detail_normalized_job(
                                record, review_context
                            )
                            if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
                                continue

                            hooks = ReviewPipelineHooks()
                            outcome, record, record_skill_observations = review_post_detail_normalized_job(
                                record, review_context, hooks=hooks
                            )
                            if outcome["decision"] != "KEEP":
                                continue

                            skill_observations.extend(record_skill_observations)
                            kept_records.append(record)
                            score, breakdown = fit_score_and_breakdown_displayed(record, self.profile)
                            logger.info(
                                "%s KEPT %s @ %s | %s | %s | %s",
                                target_tag,
                                record.get(RECORD_TITLE_KEY),
                                record.get(RECORD_COMPANY_KEY),
                                record.get(RECORD_POSTED_AGE_DAYS_KEY),
                                record.get(RECORD_LOCATION_KEY),
                                record.get(RECORD_SALARY_KEY) or "N/A",
                            )
                            print_job_human_summary(record, self.profile, score=score, breakdown=breakdown)
                            if DEBUG_CAPTURE_SOURCE_PAYLOADS:
                                write_source_payload_debug(
                                    source=self.source_name,
                                    job_key=str(record.get(RECORD_JOB_KEY) or ""),
                                    payload={
                                        "search_term": target["search_term"],
                                        "location": target["location"],
                                        "page_url": detail_page.url or link["url"],
                                        "body_text": payload["details_text"],
                                    },
                                )
                    finally:
                        page.close()
            finally:
                context.close()

        logger.info("[APSJobs] done | kept=%d audit=%d", len(kept_records), len(audit_rows))
        set_run_progress("APSJobs complete")
        return kept_records, audit_rows, skill_observations
