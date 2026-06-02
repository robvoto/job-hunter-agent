"""Scraper helpers for seek runner."""

from __future__ import annotations

import logging
import sys
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)

from playwright._impl._errors import TargetClosedError
from playwright.sync_api import sync_playwright

from job_hunter_agent.fit_scoring import fit_score, fit_score_breakdown
from job_hunter_agent.llm_gate import get_session_cost_usd
from job_hunter_agent.global_settings import get_playwright_browser_mode
from job_hunter_agent.io_utils import DEBUG_CAPTURE_SOURCE_PAYLOADS, write_source_payload_debug
from job_hunter_agent.history import finalize_record
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
import job_hunter_agent.record_schema as rs
from job_hunter_agent.runtime_helpers import CLI_FLAG_DEBUG, has_cli_flag
from job_hunter_agent.scrapers.base import build_initial_flat_record, _build_initial_source_metadata
from job_hunter_agent.scrapers.seek import (
    SELECTOR_CARDS,
    SELECTOR_COMPANY,
    SELECTOR_POSTED,
    SELECTOR_TITLE,
    build_full_seek_url,
    extract_card_metadata,
    extract_posted_text_from_card,
    fetch_job_details_payload,
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
RUN_PROGRESS_TITLE_SEPARATOR = " @ "
RUN_PROGRESS_ELAPSED_PREFIX = "elapsed "


def _format_seek_elapsed(elapsed_s: float | int | None) -> str:
    elapsed = max(int(float(elapsed_s or 0)), 0)
    minutes, seconds = divmod(elapsed, 60)
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


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


def _seek_source_metadata(detail_page, details_payload: dict) -> tuple[dict, object]:
    redux_payload = None
    try:
        redux_payload = detail_page.evaluate("window.SEEK_REDUX_DATA || null")
    except Exception:
        redux_payload = None

    combined_payload = redux_payload if redux_payload not in (None, "", [], {}) else details_payload
    apply_url = _seek_string_value(combined_payload, ("shareLink",))
    company_profile_url = _seek_string_value(combined_payload, ("companySearchUrl",))
    company_profile_name = _seek_string_value(combined_payload, ("normalisedOrganisationName", "companyProfileName"))
    advertiser_block = _seek_nested_value(combined_payload, ("advertiser",))
    if isinstance(advertiser_block, dict):
        poster_company = _seek_string_value(advertiser_block, ("name", "label", "value"))
    else:
        poster_company = _seek_string_value(combined_payload, ("advertiser", "name"))
    hiring_company = _seek_string_value(combined_payload, ("normalisedOrganisationName", "companyProfileName", "name"))
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

    ats_requisition_id = str(_seek_string_value(combined_payload, ("seekHirerJobReference",)) or "").strip()
    platform_job_id = str(_seek_string_value(combined_payload, ("seekPostingSourceCode",)) or "").strip()
    metadata = _build_initial_source_metadata(
        source="seek",
        raw_source_fields=raw_source_fields,
        apply_url=apply_url,
        company_profile_url=company_profile_url,
        company_profile_name=company_profile_name,
        poster_company=poster_company,
        hiring_company=hiring_company,
        platform_job_id=platform_job_id,
        ats_requisition_id=ats_requisition_id,
        ats_source="seek" if ats_requisition_id else "",
    )
    return metadata, combined_payload


def build_seek_card_record(card, search_target: dict, run_iso: str, page_num: int, filter_state=None) -> dict:
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


def _build_seek_review_hooks(detail_page, raw_source_payload: object) -> ReviewPipelineHooks:
    def _after_description_loaded(record: dict, context: ReviewPipelineContext) -> None:
        if DEBUG_CAPTURE_SOURCE_PAYLOADS:
            try:
                write_source_payload_debug(
                    "seek",
                    str(record.get(rs.RECORD_JOB_KEY) or record.get(rs.RECORD_URL_KEY) or "unknown"),
                    raw_html=detail_page.content(),
                    raw_json=raw_source_payload,
                    normalized_record=record,
                )
            except Exception:
                pass

    def _after_preference_filters(record: dict, context: ReviewPipelineContext) -> None:
        apply_work_mode_enrichment(record, raw_source_payload, str(record.get(rs.RECORD_FIT_SOURCE_TEXT_KEY) or ""))

    return ReviewPipelineHooks(
        after_description_loaded=_after_description_loaded,
        after_preference_filters=_after_preference_filters,
    )


def _process_seek_job_details(
    record: dict,
    detail_page,
    review_context: ReviewPipelineContext,
) -> tuple[dict, dict, list[dict]]:
    job_key = str(record.get(rs.RECORD_JOB_KEY) or "unknown")
    title = str(record.get(rs.RECORD_TITLE_KEY) or "")
    company = str(record.get(rs.RECORD_COMPANY_KEY) or "")
    url = str(record.get(rs.RECORD_URL_KEY) or "")
    try:
        logger.info("[PIPELINE][DETAIL_FETCH_START] source=SEEK job_key=%s title=%r company=%r url=%r",
                    job_key, title, company, url)
        _t0 = time.monotonic()
        details_payload = fetch_job_details_payload(detail_page, record[rs.RECORD_URL_KEY])
        details_text = str(details_payload.get("text") or "")
        details_status = str(details_payload.get("status") or ("ok" if details_text else "empty"))
        _fetch_ms = int((time.monotonic() - _t0) * 1000)
        logger.info("[PIPELINE][DETAIL_FETCH_DONE] source=SEEK job_key=%s title=%r company=%r status=%r elapsed_ms=%d text_len=%d",
                    job_key, title, company, details_status, _fetch_ms, len(details_text))
        record["_obs_detail_fetch_ms"] = _fetch_ms
        source_metadata, raw_source_payload = _seek_source_metadata(detail_page, details_payload)
        record[rs.RECORD_SOURCE_METADATA_KEY] = source_metadata
        record[rs.RECORD_DESCRIPTION_SOURCE_KEY] = details_payload.get("source") or ""
        record[rs.RECORD_DETAILS_TEXT_KEY] = details_text
        record[rs.RECORD_DETAILS_STATUS_KEY] = details_status

        hooks = _build_seek_review_hooks(detail_page, raw_source_payload)
        return review_post_detail_normalized_job(record, review_context, hooks=hooks)
    except TargetClosedError:
        raise
    except Exception as exc:
        record[rs.RECORD_DECISION_KEY] = "REJECT"
        record[rs.RECORD_REJECT_REASON_KEY] = f"CARD_EXCEPTION:{type(exc).__name__}"
        finalize_record(review_context.job_history, review_context.audit_rows, record, review_context.run_iso)
        return {"decision": "REJECT", "reject_reason": record[rs.RECORD_REJECT_REASON_KEY]}, record, []


def review_seek_card_record(
    record: dict,
    detail_page,
    review_context: ReviewPipelineContext,
) -> tuple[dict, dict, list[dict]]:
    record["job_quality_signals"] = detect_broad_engagement_signal(record)
    pre_outcome, record, _, should_fetch_details = review_pre_detail_normalized_job(record, review_context)
    if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
        return pre_outcome, record, []
    return _process_seek_job_details(record, detail_page, review_context)


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
    headless: bool,
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
        if use_persistent_browser:
            PLAYWRIGHT_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(PLAYWRIGHT_USER_DATA_DIR),
                headless=headless,
                viewport={"width": playwright_viewport_width, "height": playwright_viewport_height},
            )
            list_page = context.new_page()
            detail_page = context.new_page()
        else:
            browser = playwright.chromium.launch(headless=headless)
            context = browser
            list_page = browser.new_page(viewport={"width": playwright_viewport_width, "height": playwright_viewport_height})
            detail_page = browser.new_page(viewport={"width": playwright_viewport_width, "height": playwright_viewport_height})

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
                    target_index, total_targets,
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
                    page_url = set_page_param(base_search_url, current_page_num) if current_page_num > 1 else base_search_url

                    logger.info("%s url=%s", page_tag, page_url)

                    try:
                        list_page.goto(page_url, wait_until="domcontentloaded")
                        list_page.wait_for_selector(SELECTOR_CARDS, timeout=playwright_selector_timeout)
                    except Exception as exc:
                        logger.info("%s no visible job cards; stopping target [%s]", page_tag, type(exc).__name__)
                        break

                    job_cards = list_page.query_selector_all(SELECTOR_CARDS)
                    logger.info("%s cards=%d", page_tag, len(job_cards))

                    if len(job_cards) == 0:
                        logger.info("%s no cards found; stopping target", page_tag)
                        break

                    filter_state = extract_seek_filter_panel_state(list_page)
                    page_has_fresh_card = False

                    for card in job_cards:
                        if run_stop_requested():
                            logger.info("%s stop requested; finishing current page", page_tag)
                            break
                        record = {}
                        title = ""
                        company = ""
                        try:
                            record = build_seek_card_record(card, search_target, run_iso, current_page_num, filter_state)
                            title, company = record[rs.RECORD_TITLE_KEY], record[rs.RECORD_COMPANY_KEY]
                            set_run_progress(
                                _seek_run_progress(
                                    current_page_num,
                                    configured_seek_max_pages,
                                    title,
                                    company,
                                    time.monotonic() - target_t0,
                                )
                            )
                            posted_age_days = record[rs.RECORD_POSTED_AGE_DAYS_KEY]
                            if posted_age_days is None or posted_age_days <= configured_date_range:
                                page_has_fresh_card = True

                            _job_t0 = time.monotonic()
                            _job_cost_start = get_session_cost_usd()
                            outcome, record, record_skill_observations = review_seek_card_record(
                                record,
                                detail_page,
                                review_context,
                            )
                            _job_elapsed_s = time.monotonic() - _job_t0
                            _job_llm_cost  = max(get_session_cost_usd() - _job_cost_start, 0.0)
                            _job_decision  = outcome.get("decision")
                            _job_score: int | None = None

                            _job_breakdown: list | None = None
                            if _job_decision == "KEEP":
                                _job_score = fit_score(record, profile)
                                _job_breakdown = fit_score_breakdown(record, profile)
                                skill_observations.extend(record_skill_observations)
                                kept_records.append(record)
                                logger.info(
                                    "%s KEPT %s @ %s | %s",
                                    page_tag, title, company,
                                    "SEEN_BEFORE" if record.get("seen_before") else "NEW",
                                )

                            if _job_decision in {"KEEP", "REJECT"}:
                                print_job_human_summary(record, profile, elapsed_s=_job_elapsed_s, score=_job_score, llm_cost=_job_llm_cost, breakdown=_job_breakdown)
                                close_job_block(str(record.get(rs.RECORD_JOB_KEY) or ""))

                        except TargetClosedError:
                            logger.warning("%s browser target closed; stopping target", page_tag)
                            break
                        except Exception as exc:
                            record[rs.RECORD_DECISION_KEY] = "REJECT"
                            record[rs.RECORD_REJECT_REASON_KEY] = f"CARD_EXCEPTION:{type(exc).__name__}"
                            finalize_record(job_history, audit_rows, record, run_iso)
                            logger.warning(
                                "%s REJECTED (card) [CARD_EXCEPTION:%s] %s @ %s\n%s",
                                page_tag, type(exc).__name__, title, company, traceback.format_exc(),
                            )

                    if not page_has_fresh_card:
                        logger.info("%s all cards were older than %d day(s); stopping target", page_tag, configured_date_range)
                        break

                    if run_stop_requested():
                        break

                    current_page_num += 1
            set_run_progress("SEEK complete")
        finally:
            context.close()

    return kept_records, audit_rows, skill_observations
