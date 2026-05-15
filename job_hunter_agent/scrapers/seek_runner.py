from __future__ import annotations

import re
import sys
import traceback
from datetime import datetime
from typing import Any, Dict, List, Set

from playwright.sync_api import sync_playwright

from job_hunter_agent.advance_settings import (
    get_playwright_browser_mode,
)
from job_hunter_agent.description_trust import get_min_trusted_description_length, get_trusted_sources
from job_hunter_agent.filters import (
    analyze_title_filters,
    passes_content_filters,
    passes_quick_card_filters,
)
from job_hunter_agent.hard_blocker_rules import find_hard_block_matches
from job_hunter_agent.io_utils import DEBUG_CAPTURE_SOURCE_PAYLOADS, write_source_payload_debug
from job_hunter_agent.history import apply_kept_job_reuse, can_reuse_kept_job, finalize_record
from job_hunter_agent.paths import PLAYWRIGHT_USER_DATA_DIR
from job_hunter_agent.preferences import passes_preference_filters
import job_hunter_agent.record_schema as rs
from job_hunter_agent.runtime_helpers import CLI_FLAG_DEBUG, has_cli_flag
from job_hunter_agent.capability_matching import build_risk_and_missing_evidence, reviewed_signal_matches_for_text
from job_hunter_agent.fit_scoring import build_fit_highlights, fit_score, fit_score_breakdown
from job_hunter_agent.role_analysis import infer_posting_channel
from job_hunter_agent.scrapers.base import (
    build_initial_flat_record,
    _build_initial_source_metadata,
)
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
from job_hunter_agent.signal_detection import (
    detect_competitive_signals,
    evaluate_competitive_signal_alignment,
    extract_skill_observations,
    hard_block_entries,
)
from job_hunter_agent.signal_schema import HARD_BLOCK_REASONS_KEY
from job_hunter_agent.source_learning import (
    has_high_value_ambiguous_learning_candidate,
    merge_pending_learning_signals,
    register_pending_learning_signals,
    resolve_llm_review_payload,
    build_ad_learning_signals,
    deterministic_review_outcome,
    register_hard_blocker_learning_from_rejection,
)
from job_hunter_agent.text_processing import build_role_summary, compact_whitespace, dedupe_preserve_order
from job_hunter_agent.utils import extract_salary, parse_seek_posted_age_days, set_page_param
from job_hunter_agent.work_mode_extraction import WORK_MODE_UNKNOWN, extract_from_seek_detail, extract_seek_filter_panel_state, log_work_mode_result

WORKSPACE_DEBUG_MODE = has_cli_flag(sys.argv, CLI_FLAG_DEBUG)


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


def apply_title_match_result(record: dict, title_analysis: dict, title_reason: str) -> None:
    record[rs.RECORD_TITLE_REASON_KEY] = title_reason
    record[rs.RECORD_TITLE_MATCH_METADATA_KEY] = title_analysis


def apply_reject_result(record: dict, reason: str) -> None:
    record[rs.RECORD_REJECT_REASON_KEY] = reason


def apply_skip_result(record: dict, reason: str) -> None:
    record.update({rs.RECORD_DECISION_KEY: "SKIP", rs.RECORD_REJECT_REASON_KEY: reason})


def apply_detail_payload_to_record(record: dict, details_payload: dict, details_text: str, details_status: str) -> tuple[bool, str]:
    record[rs.RECORD_DETAILS_STATUS_KEY] = details_status
    record[rs.RECORD_DETAILS_LENGTH_KEY] = len(details_text)

    if details_status != "ok" or not details_text:
        reject_reason = {
            "challenge_page": "DETAILS_CHALLENGE_PAGE",
            "blocked_page": "DETAILS_BLOCKED_PAGE",
            "navigation_error": "DETAILS_NAVIGATION_ERROR",
            "empty": "NO_DETAILS",
        }.get(details_status, "NO_DETAILS")
        record[rs.RECORD_CONTENT_REASON_KEY] = reject_reason
        return False, reject_reason

    record[rs.RECORD_FIT_SOURCE_TEXT_KEY] = details_text
    record[rs.RECORD_FULL_DESCRIPTION_KEY] = details_text
    record[rs.RECORD_DESCRIPTION_SOURCE_KEY] = details_payload.get("source") or ""
    source = str(record.get(rs.RECORD_DESCRIPTION_SOURCE_KEY) or "").strip().lower()
    is_trusted = source in get_trusted_sources() and len(details_text) >= get_min_trusted_description_length()
    record[rs.RECORD_FIT_CONFIDENCE_KEY] = rs.CONFIDENCE_HIGH if is_trusted else rs.CONFIDENCE_LOW
    record[rs.RECORD_CONTENT_REASON_KEY] = "OK"
    return True, "OK"


def apply_source_metadata_to_record(record: dict, source_metadata: dict, details_text: str) -> None:
    record[rs.RECORD_SOURCE_METADATA_KEY] = source_metadata
    channel_signal = infer_posting_channel(record, details_text)
    record[rs.RECORD_POSTING_CHANNEL_EVIDENCE_KEY] = {
        "trusted_metadata": list(channel_signal.get("trusted_metadata") or []),
        "weak_text_matches": list(channel_signal.get("weak_text_matches") or []),
        "needs_review": bool(channel_signal.get("needs_review")),
    }


def apply_content_filter_result(record: dict, details_text: str, profile: dict, title_reason: str) -> tuple[bool, str]:
    ok_desc, desc_reason = passes_content_filters(details_text, record[rs.RECORD_LOCATION_KEY], title_reason)
    if not ok_desc:
        if desc_reason.startswith("DESC_HARD_BLOCK_RULE"):
            knowledge_matches = find_hard_block_matches(details_text, profile.get("must_not_require_skills", []))
            record[HARD_BLOCK_REASONS_KEY] = dedupe_preserve_order(
                [
                    compact_whitespace(match.get("value") or match.get("matched_term") or "")
                    for match in knowledge_matches
                ]
            )[:3]
        register_hard_blocker_learning_from_rejection(record, desc_reason, details_text, profile=profile)
        return False, desc_reason
    return True, "OK"


def apply_competitive_signal_enrichment(record: dict, details_text: str, profile: dict) -> None:
    record[rs.RECORD_COMPETITIVE_SIGNALS_KEY] = [
        evaluate_competitive_signal_alignment(signal, profile)
        for signal in detect_competitive_signals(details_text, profile)
    ]
    record[rs.RECORD_REVIEWED_SIGNAL_MATCHES_KEY] = reviewed_signal_matches_for_text(details_text)


def apply_hard_block_result(record: dict, details_text: str, profile: dict) -> tuple[bool, str]:
    hard_block_matches = hard_block_entries(record, profile)
    record[rs.RECORD_HARD_BLOCK_REASONS_KEY] = [entry["text"] for entry in hard_block_matches]
    if record[rs.RECORD_HARD_BLOCK_REASONS_KEY]:
        term = compact_whitespace(record[rs.RECORD_HARD_BLOCK_REASONS_KEY][0]).lower()
        reason_code = f"DESC_HARD_BLOCK_RULE:{re.sub(r'[^a-z0-9]+', '_', term).strip('_') or 'hard_block'}"
        register_hard_blocker_learning_from_rejection(record, reason_code, details_text, hard_block_matches, profile=profile)
        return False, reason_code
    return True, "OK"


def apply_learning_signal_enrichment(record: dict, details_text: str, profile: dict) -> None:
    record["skill_observations"] = extract_skill_observations(record, profile)
    record["ad_learning_signals"] = build_ad_learning_signals(record, details_text, profile)
    record[rs.RECORD_SALARY_KEY] = extract_salary(details_text) or record.get(rs.RECORD_CARD_SALARY_KEY) or ""


def apply_preference_result(record: dict, profile: dict) -> tuple[bool, str]:
    ok_pref, pref_reason = passes_preference_filters(record, profile)
    if not ok_pref:
        print(f"REJECTED (preference gate) [{pref_reason}] {record.get(rs.RECORD_TITLE_KEY)} @ {record.get(rs.RECORD_COMPANY_KEY)}")
        return False, pref_reason
    return True, "OK"


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


def apply_fit_summary_enrichment(record: dict, details_text: str, profile: dict, title_reason: str) -> None:
    record[rs.RECORD_ROLE_SNAPSHOT_KEY] = build_role_summary(record, details_text, profile)
    record[rs.RECORD_FIT_HIGHLIGHTS_KEY] = build_fit_highlights(record, details_text, profile)
    record[rs.RECORD_SOFT_RISK_REASONS_KEY], record[rs.RECORD_MISSING_EVIDENCE_KEY] = build_risk_and_missing_evidence(
        details_text, title_reason, profile, competitive_signals=record[rs.RECORD_COMPETITIVE_SIGNALS_KEY]
    )


def apply_fit_review_result(record: dict, fit_eval: dict) -> None:
    record.update(fit_eval)


def _process_seek_job_details(record: dict, detail_page, profile: dict, title_reason: str) -> tuple[bool, str]:
    details_payload = fetch_job_details_payload(detail_page, record[rs.RECORD_URL_KEY])
    details_text = str(details_payload.get("text") or "")
    details_status = str(details_payload.get("status") or ("ok" if details_text else "empty"))

    ok, reason = apply_detail_payload_to_record(record, details_payload, details_text, details_status)
    if not ok:
        return False, reason

    source_metadata, raw_source_payload = _seek_source_metadata(detail_page, details_payload)
    apply_source_metadata_to_record(record, source_metadata, details_text)

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

    ok, reason = apply_content_filter_result(record, details_text, profile, title_reason)
    if not ok:
        return False, reason

    apply_competitive_signal_enrichment(record, details_text, profile)

    ok, reason = apply_hard_block_result(record, details_text, profile)
    if not ok:
        return False, reason

    apply_learning_signal_enrichment(record, details_text, profile)

    ok, reason = apply_preference_result(record, profile)
    if not ok:
        return False, reason

    apply_work_mode_enrichment(record, raw_source_payload, details_text)
    apply_fit_summary_enrichment(record, details_text, profile, title_reason)
    return True, "OK"


def _evaluate_job_fit(record: dict, profile: dict, llm_cache: dict) -> dict:
    deterministic_review = deterministic_review_outcome(
        record, profile, record["fit_highlights"], record["missing_evidence"], record["soft_risk_reasons"]
    )
    record["llm_learning_candidates"] = []

    if deterministic_review is not None:
        review = deterministic_review
        source = "rule"
        if has_high_value_ambiguous_learning_candidate(record.get("ad_learning_signals") or []):
            payload = resolve_llm_review_payload(
                record,
                llm_cache,
                learning_only=True,
            )
            record["llm_learning_candidates"] = payload.get("learning_candidates") or []
            if record["llm_learning_candidates"]:
                source = "rule+learning"
    else:
        payload = resolve_llm_review_payload(
            record,
            llm_cache,
        )
        review = payload["fit_review"]
        record["llm_learning_candidates"] = payload.get("learning_candidates") or []
        source = str(payload.get("payload_source") or "llm")

    return {
        "llm_decision": review["decision"],
        "llm_fit_grade": review["grade"],
        "review_source": source,
        "decision": "KEEP" if review["decision"] != "REJECT" else "REJECT",
    }


def seek_scrape_to_records(
    profile: dict,
    search_targets: List[dict],
    job_history: Dict[str, dict],
    llm_cache: Dict[str, Any],
    applied_job_keys: Set[str],
    hidden_job_keys: Set[str],
    run_iso: str,
    configured_date_range: int,
    enforce_posted_age_limit: bool,
    configured_seek_max_pages: int,
    playwright_viewport_width: int,
    playwright_viewport_height: int,
    playwright_selector_timeout: int,
    headless: bool,
) -> tuple:
    audit_rows: List[dict] = []
    kept_records: List[dict] = []
    skill_observations: List[dict] = []

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
            seen_urls: Set[str] = set()
            for search_target in search_targets:
                base_search_url = search_target["url"]
                search_location = search_target["location"]
                search_keywords = search_target["keywords"]
                classification_ids = ",".join(search_target.get("classification_ids", []))
                current_page_num = 1

                print(f"Location: {search_location}")
                print(f"Keywords: {search_keywords}")
                print(f"classification_ids: {classification_ids}")

                while current_page_num <= configured_seek_max_pages:
                    page_url = set_page_param(base_search_url, current_page_num) if current_page_num > 1 else base_search_url

                    print(f"\n=== {search_location} | Page {current_page_num} ===")
                    print("URL:", page_url)

                    try:
                        list_page.goto(page_url, wait_until="domcontentloaded")
                        list_page.wait_for_selector(SELECTOR_CARDS, timeout=playwright_selector_timeout)
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

                    filter_state = extract_seek_filter_panel_state(list_page)
                    page_has_fresh_card = False

                    for card in job_cards:
                        try:
                            record = build_seek_card_record(card, search_target, run_iso, current_page_num, filter_state)
                            title, company = record[rs.RECORD_TITLE_KEY], record[rs.RECORD_COMPANY_KEY]
                            posted_age_days = record[rs.RECORD_POSTED_AGE_DAYS_KEY]
                            if posted_age_days is None or posted_age_days <= configured_date_range:
                                page_has_fresh_card = True

                            title_analysis = analyze_title_filters(title, profile)
                            ok_title = bool(title_analysis.get("ok"))
                            title_reason = str(title_analysis.get("reason") or "")
                            apply_title_match_result(record, title_analysis, title_reason)
                            if not ok_title:
                                print(f"REJECTED (title) [{title_reason}] {title}")
                                apply_reject_result(record, title_reason)
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if not record[rs.RECORD_URL_KEY]:
                                print(f"REJECTED (card) [NO_URL] {title} @ {company}")
                                apply_reject_result(record, "NO_URL")
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            job_key = record[rs.RECORD_JOB_KEY]
                            if job_key in applied_job_keys:
                                print(f"SKIP (applied) {title} @ {company}")
                                apply_skip_result(record, "ALREADY_APPLIED")
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if job_key in hidden_job_keys:
                                print(f"SKIP (hidden) {title} @ {company}")
                                apply_skip_result(record, "MANUALLY_HIDDEN")
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if enforce_posted_age_limit and posted_age_days is not None and posted_age_days > configured_date_range:
                                print(f"REJECTED (posted) [POSTED_TOO_OLD:{configured_date_range}] {title} @ {company}")
                                apply_reject_result(record, f"POSTED_TOO_OLD:{configured_date_range}")
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            if record[rs.RECORD_URL_KEY] in seen_urls:
                                print(f"SKIP (duplicate) {title} @ {company}")
                                apply_skip_result(record, "DUPLICATE_URL")
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue
                            seen_urls.add(record[rs.RECORD_URL_KEY])

                            ok_card, card_reason = passes_quick_card_filters(
                                title=title,
                                teaser=record[rs.RECORD_TEASER_KEY],
                                company=company,
                                location=record[rs.RECORD_LOCATION_KEY],
                                work_mode=record[rs.RECORD_WORK_MODE_KEY],
                                work_type=record[rs.RECORD_WORK_TYPE_KEY],
                                salary=record.get(rs.RECORD_CARD_SALARY_KEY) or "",
                            )
                            if not ok_card:
                                print(f"REJECTED (card gate) [{card_reason}] {title} @ {company}")
                                apply_reject_result(record, card_reason)
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            history_entry = job_history.get(job_key or "", {})
                            if can_reuse_kept_job(history_entry, record, profile):
                                record = apply_kept_job_reuse(record, history_entry)
                                finalize_record(job_history, audit_rows, record, run_iso)
                                kept_records.append(record)
                                print(f"KEPT (history reuse): {title} @ {company}")
                                continue

                            ok_details, reject_reason = _process_seek_job_details(record, detail_page, profile, title_reason)
                            if not ok_details:
                                print(f"REJECTED (details/content) [{reject_reason}] {title} @ {company}")
                                apply_reject_result(record, reject_reason)
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            fit_eval = _evaluate_job_fit(record, profile, llm_cache)
                            apply_fit_review_result(record, fit_eval)

                            if WORKSPACE_DEBUG_MODE:
                                score = fit_score(record, profile)
                                breakdown = fit_score_breakdown(record, profile)
                                print(f"[DEBUG][SCORE] {score}/100 | {record[rs.RECORD_TITLE_KEY]} @ {record[rs.RECORD_COMPANY_KEY]} | Grade: {record.get('llm_fit_grade')} ({record.get('review_source')})")
                                for entry in breakdown:
                                    print(f"    {entry['label']}: {entry['value']:+d}")

                            if record[rs.RECORD_DECISION_KEY] == "REJECT":
                                print(f"REJECTED ({record['review_source']}) {title} @ {company}")
                                apply_reject_result(record, "LLM_REJECT" if record["review_source"] == "llm" else "DET_REJECT")
                                finalize_record(job_history, audit_rows, record, run_iso)
                                continue

                            skill_observations.extend(record.get("skill_observations") or [])
                            pending_signals = merge_pending_learning_signals(
                                record.get("ad_learning_signals") or [],
                                record.get("llm_learning_candidates") or [],
                            )
                            register_pending_learning_signals(pending_signals)
                            record.pop("skill_observations", None)
                            record.pop("ad_learning_signals", None)
                            record.pop("llm_learning_candidates", None)
                            finalize_record(job_history, audit_rows, record, run_iso)
                            kept_records.append(record)
                            print(f"KEPT: {title} @ {company} | {'SEEN_BEFORE' if record.get('seen_before') else 'NEW'}")

                        except Exception as exc:
                            apply_reject_result(record, f"CARD_EXCEPTION:{type(exc).__name__}")
                            print(f"REJECTED (card) [CARD_EXCEPTION:{type(exc).__name__}] {title} @ {company}\n{traceback.format_exc()}")
                            finalize_record(job_history, audit_rows, record, run_iso)

                    if enforce_posted_age_limit and not page_has_fresh_card:
                        print(
                            f"All cards for {search_location} on page {current_page_num} "
                            f"were older than {configured_date_range} day(s). Stopping this target."
                        )
                        break

                    current_page_num += 1
        finally:
            context.close()

    return kept_records, audit_rows, skill_observations
