"""APSJobs source scraper."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from time import monotonic
from typing import List
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright

from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_APSJOBS_RESULTS_PER_SEARCH,
    KEY_DATE_RANGE_DAYS,
)
from job_hunter_agent.io_utils import DEBUG_CAPTURE_SOURCE_PAYLOADS, write_source_payload_debug
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    ReviewPipelineHooks,
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
from job_hunter_agent.logging_utils import format_debug_marker
from job_hunter_agent.source_registry import SOURCE_APSJOBS
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.text_processing import compact_whitespace, dedupe_preserve_order
from job_hunter_agent.work_mode_extraction import WORK_MODE_UNKNOWN, extract_from_text, log_work_mode_result

logger = logging.getLogger(__name__)

APSJOBS_ROOT_URL = "https://www.apsjobs.gov.au/s/"
APSJOBS_JOB_SEARCH_URL = urljoin(APSJOBS_ROOT_URL, "job-search")
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
APSJOBS_STATE_SELECTORS = (
    "select[aria-label='Location']",
    "select[aria-label='State']",
)
APSJOBS_SEARCH_BUTTON_SELECTORS = (
    "button.header_search__block--button",
    "button:has-text('SEARCH')",
    "button:has-text('Search')",
)
APSJOBS_TITLE_SELECTORS = (
    ".job_detail__header h3",
    ".job_detail__header h2",
    "h1",
    "h2",
    "h3",
    "[data-testid*='job-title' i]",
    "[class*='job-title' i]",
    "[class*='jobtitle' i]",
)
APSJOBS_COMPANY_SELECTORS = (
    ".job_detail__header .content__label--quiet",
    ".job_detail__logo img[alt]",
)
APSJOBS_DETAIL_LOCATION_SELECTORS = (".job_detail__header .content__location",)

job_type_rules = load_job_type()
_APSJOBS_STATE_CODES = ("ACT", "NSW", "NT", "QLD", "SA", "TAS", "VIC", "WA")
_APSJOBS_LOCATION_TO_STATE = {
    "australian capital territory": "ACT",
    "canberra": "ACT",
    "new south wales": "NSW",
    "nsw": "NSW",
    "sydney": "NSW",
    "wollongong": "NSW",
    "newcastle": "NSW",
    "northern territory": "NT",
    "darwin": "NT",
    "queensland": "QLD",
    "qld": "QLD",
    "brisbane": "QLD",
    "south australia": "SA",
    "adelaide": "SA",
    "tasmania": "TAS",
    "hobart": "TAS",
    "victoria": "VIC",
    "vic": "VIC",
    "melbourne": "VIC",
    "western australia": "WA",
    "wa": "WA",
    "perth": "WA",
}
RUN_PROGRESS_ELAPSED_PREFIX = "elapsed "


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


def _normalize_apsjobs_location_filter(location: str) -> str:
    cleaned = compact_whitespace(location).lower()
    if not cleaned:
        return ""
    for state_code in _APSJOBS_STATE_CODES:
        if re.search(rf"\b{re.escape(state_code.lower())}\b", cleaned):
            return state_code
    for token, state_code in _APSJOBS_LOCATION_TO_STATE.items():
        if token in cleaned:
            return state_code
    return ""


def _looks_like_job_link(href: str, text: str) -> bool:
    if not href:
        return False
    parsed = urlsplit(href)
    path = parsed.path.lower()
    query = parsed.query.lower()
    _ = text
    return (
        "job-details" in path
        or "jobdetail" in path
        or "jobdetails" in path
        or "id=" in query
        or "jobid=" in query
        or "job_id=" in query
    )


def _format_apsjobs_elapsed(elapsed_s: float | int | None) -> str:
    if elapsed_s is None:
        return "0s"
    total_seconds = max(0, int(round(float(elapsed_s))))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _format_apsjobs_run_progress(
    target_index: int,
    total_targets: int,
    scanned_titles: list[str] | None = None,
    elapsed_s: float | int | None = None,
) -> str:
    step = f"APSJobs search {target_index}/{total_targets}"
    lines = [step]
    for title in scanned_titles or ():
        normalized_title = compact_whitespace(title)
        if normalized_title:
            lines.append(normalized_title)
    lines.append(f"{RUN_PROGRESS_ELAPSED_PREFIX}{_format_apsjobs_elapsed(elapsed_s)}")
    return "\n".join(lines)


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
    company = _first_non_empty(
        _locator_text(page, APSJOBS_COMPANY_SELECTORS),
        _extract_labeled_value(
            lines,
            ("agency", "organisation", "organization", "department", "employer", "company"),
        ),
    )
    location = _first_non_empty(
        _locator_text(page, APSJOBS_DETAIL_LOCATION_SELECTORS),
        _extract_labeled_value(lines, ("location", "locations")),
    )
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
        parsed_job_url = urlsplit(job_url)
        # Include the query string, not just the path: APSJobs listing paths
        # are constant ('/s/job-details') and the query carries the unique id.
        key_basis = compact_whitespace(
            "-".join(part for part in (parsed_job_url.path, parsed_job_url.query) if part)
            or anchor_text
            or "listing"
        ).lower()
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

    Returns the trimmed keywords string and one target per configured shared
    location mapped to an APS state or territory filter. Duplicate mapped
    states collapse to one target.
    """
    keywords = str(search_settings.get("keywords") or "").strip()
    raw_locations = [
        str(location).strip()
        for location in search_settings.get("locations", [])
        if str(location).strip()
    ]
    locations = dedupe_preserve_order(
        [
            mapped
            for mapped in (
                _normalize_apsjobs_location_filter(location) for location in raw_locations
            )
            if mapped
        ]
    )
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
        scanned_titles: list[str] = []

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
        logger.info(
            format_debug_marker(
                "BOARD_START",
                {
                    "source": self.source_name,
                    "targets": total_targets,
                    "keywords": keywords or "(unset)",
                },
            )
        )
        started_at = monotonic()
        try:
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
                        target_state = _normalize_apsjobs_location_filter(target["location"])
                        set_run_progress(
                            _format_apsjobs_run_progress(
                                target_index,
                                total_targets,
                                scanned_titles=scanned_titles,
                                elapsed_s=monotonic() - started_at,
                            )
                        )
                        logger.info(
                            "\n"
                            "================================================================\n"
                            "  STARTING APSJOBS TARGET %d/%d\n"
                            "  search_url=%s\n"
                            "  search_term=%s\n"
                            "  location=%s\n"
                            "  state_filter=%s\n"
                            "  results_wanted=%d\n"
                            "================================================================",
                            target_index,
                            total_targets,
                            APSJOBS_JOB_SEARCH_URL,
                            target["search_term"] or "(unset)",
                            target["location"] or "(all)",
                            target_state or "(none)",
                            target["results_wanted"],
                        )
                        page = context.new_page()
                        try:
                            page.goto(APSJOBS_JOB_SEARCH_URL, wait_until="domcontentloaded")
                            page.wait_for_timeout(2500)
                            search_box = _first_visible_locator(page, APSJOBS_SEARCH_INPUT_SELECTORS)
                            if search_box is None:
                                raise RuntimeError(
                                    "APSJobs job-search page did not expose a visible keyword search input"
                                )
                            try:
                                search_box.fill(target["search_term"], timeout=5000)
                            except Exception as exc:
                                raise RuntimeError(
                                    f"APSJobs keyword search input could not be filled: {type(exc).__name__}: {exc}"
                                ) from exc

                            if target_state:
                                state_select = _first_visible_locator(page, APSJOBS_STATE_SELECTORS)
                                if state_select is None:
                                    raise RuntimeError(
                                        "APSJobs job-search page did not expose a visible state selector"
                                    )
                                try:
                                    state_select.select_option(label=target_state, timeout=5000)
                                except Exception as exc:
                                    raise RuntimeError(
                                        f"APSJobs state selector could not apply {target_state}: "
                                        f"{type(exc).__name__}: {exc}"
                                    ) from exc
                            elif target["location"]:
                                logger.info(
                                    "%s APSJobs has state-only location filtering; no state mapping for %r",
                                    target_tag,
                                    target["location"],
                                )

                            search_button = _first_visible_locator(page, APSJOBS_SEARCH_BUTTON_SELECTORS)
                            if search_button is None:
                                raise RuntimeError(
                                    "APSJobs job-search page did not expose a visible search submit button"
                                )
                            try:
                                search_button.click(timeout=5000)
                            except Exception as exc:
                                raise RuntimeError(
                                    f"APSJobs search submit failed: {type(exc).__name__}: {exc}"
                                ) from exc

                            page.wait_for_timeout(5000)
                            logger.info(
                                "%s applied search_term=%r state_filter=%s final_url=%s",
                                target_tag,
                                target["search_term"],
                                target_state or "(none)",
                                page.url or APSJOBS_JOB_SEARCH_URL,
                            )
                            if page.url:
                                page.goto(page.url, wait_until="domcontentloaded")
                                page.wait_for_timeout(3000)

                            candidate_links = _collect_candidate_links(
                                page, page.url or APSJOBS_JOB_SEARCH_URL, int(target["results_wanted"])
                            )
                            logger.info(
                                "%s candidate collection url=%s",
                                target_tag,
                                page.url or APSJOBS_JOB_SEARCH_URL,
                            )
                            if not candidate_links:
                                logger.info("%s no candidate links found", target_tag)
                                continue

                            logger.info("%s candidate_links=%d", target_tag, len(candidate_links))
                            for link in candidate_links:
                                if run_stop_requested():
                                    break
                                scanned_title = compact_whitespace(link.get("text") or "") or "APSJobs listing"
                                scanned_titles.append(scanned_title)
                                set_run_progress(
                                    _format_apsjobs_run_progress(
                                        target_index,
                                        total_targets,
                                        scanned_titles=scanned_titles,
                                        elapsed_s=monotonic() - started_at,
                                    )
                                )
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
                                    resolved_title = compact_whitespace(payload.get("title") or "")
                                    if resolved_title and resolved_title != scanned_titles[-1]:
                                        scanned_titles[-1] = resolved_title
                                        set_run_progress(
                                            _format_apsjobs_run_progress(
                                                target_index,
                                                total_targets,
                                                scanned_titles=scanned_titles,
                                                elapsed_s=monotonic() - started_at,
                                            )
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
                                logger.info(
                                    "%s KEPT %s @ %s | %s | %s | %s",
                                    target_tag,
                                    record.get(RECORD_TITLE_KEY),
                                    record.get(RECORD_COMPANY_KEY),
                                    record.get(RECORD_POSTED_AGE_DAYS_KEY),
                                    record.get(RECORD_LOCATION_KEY),
                                    record.get(RECORD_SALARY_KEY) or "N/A",
                                )
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
        except Exception as exc:
            raise PartialSourceResultsError(
                self.source_name,
                kept_records=kept_records,
                audit_rows=audit_rows,
                skill_observations=skill_observations,
                original_error=exc,
            ) from exc

        logger.info(
            format_debug_marker(
                "BOARD_END",
                {
                    "source": self.source_name,
                    "targets": total_targets,
                    "kept": len(kept_records),
                    "audit_rows": len(audit_rows),
                },
            )
        )
        logger.info("[APSJobs] done | kept=%d audit=%d", len(kept_records), len(audit_rows))
        set_run_progress("APSJobs complete")
        return kept_records, audit_rows, skill_observations
