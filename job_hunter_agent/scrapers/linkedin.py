"""LinkedIn source connector using python-jobspy."""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import List
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

import sys

from job_hunter_agent.fit_scoring import fit_score_and_breakdown_displayed
from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_DATE_RANGE_DAYS,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_SORT_NEWEST_FIRST,
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
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.profile_store import get_search_settings
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EASY_APPLY,
    APPLY_METHOD_EXTERNAL_APPLY,
    APPLY_METHOD_UNKNOWN,
    RECORD_APPLY_METHOD_KEY,
    RECORD_COMPANY_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_JOB_KEY,
    RECORD_JOB_QUALITY_SIGNALS_KEY,
    RECORD_LOCATION_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_SALARY_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
)
from job_hunter_agent.run_control import run_stop_requested, set_run_progress
from job_hunter_agent.runtime_helpers import CLI_FLAG_DEBUG, has_cli_flag
from job_hunter_agent.salary import load_salary
from job_hunter_agent.scrapers.base import BaseJobScraper, normalize_jobspy_record
from job_hunter_agent.scrapers.location_adapters import to_jobspy
from job_hunter_agent.source_registry import SOURCE_LINKEDIN
from job_hunter_agent.source_errors import PartialSourceResultsError
from job_hunter_agent.posting_utils import parse_visible_posted_age_days
from job_hunter_agent.work_mode_extraction import (
    WORK_MODE_UNKNOWN,
    extract_from_text,
    log_work_mode_result,
)

WORKSPACE_DEBUG_MODE = has_cli_flag(sys.argv, CLI_FLAG_DEBUG)


salary_rules = load_salary()
job_type_rules = load_job_type()


def _fetch_job_html(record: dict) -> str:
    raw_fields = record.get("source_metadata", {}).get("raw_source_fields", {})
    if not isinstance(raw_fields, dict):
        raw_fields = {}
    url = str(
        raw_fields.get("job_url_direct") or raw_fields.get("job_url") or record.get("url") or ""
    ).strip()
    if not url:
        return ""
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, ValueError):
        return ""


def _extract_linkedin_posted_age_days(html: str, run_date) -> float | None:
    if not html:
        return None

    visible_text = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", html, flags=re.I | re.S)
    visible_text = re.sub(r"<[^>]+>", " ", visible_text)
    visible_text = re.sub(r"\s+", " ", visible_text).strip().lower()
    return parse_visible_posted_age_days(visible_text, run_date)


def _backfill_linkedin_posted_age(record: dict, run_iso: str) -> None:
    if record.get(RECORD_POSTED_AGE_DAYS_KEY) is not None:
        return

    html = _fetch_job_html(record)
    if not html:
        return

    run_date = datetime.fromisoformat(run_iso).date()
    posted_age_days = _extract_linkedin_posted_age_days(html, run_date)
    if posted_age_days is not None:
        record[RECORD_POSTED_AGE_DAYS_KEY] = posted_age_days


def classify_linkedin_apply_method(apply_url: str, canonical_url: str) -> str:
    """Classify LinkedIn's apply signal into a normalised apply_method value.

    jobspy's ``easy_apply`` field is not reliably populated for LinkedIn results,
    so this uses ``apply_url`` (LinkedIn's external ATS link) as the proxy:
    present and different from the canonical job URL means an external apply;
    absent means LinkedIn's own UI only exposed Easy Apply.
    """
    apply_url = str(apply_url or "").strip()
    canonical_url = str(canonical_url or "").strip()
    if apply_url and apply_url != canonical_url:
        return APPLY_METHOD_EXTERNAL_APPLY
    if not apply_url:
        return APPLY_METHOD_EASY_APPLY
    return APPLY_METHOD_UNKNOWN


class LinkedInScraper(BaseJobScraper):
    source_name = SOURCE_LINKEDIN

    def scrape(self) -> tuple:
        kept_records: List[dict] = []
        audit_rows: List[dict] = []
        skill_observations: List[dict] = []

        search_settings = get_search_settings(self.profile)
        date_range_days = int(
            search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
            or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]
        )
        targets = self._build_search_targets(search_settings)
        if not targets:
            logger.info("[LinkedIn] no search targets configured; skipping")
            return kept_records, audit_rows, skill_observations

        review_context = ReviewPipelineContext(
            profile=self.profile,
            job_history=self.job_history,
            audit_rows=audit_rows,
            llm_cache=self.llm_cache,
            applied_job_keys=self.applied_job_keys,
            hidden_job_keys=self.hidden_job_keys,
            run_iso=self.run_iso,
            date_range_days=date_range_days,
            source_name="LinkedIn",
        )

        total_targets = len(targets)
        try:
            for target_index, target in enumerate(targets, start=1):
                target_tag = f"[LinkedIn target {target_index}/{total_targets}]"
                set_run_progress(f"LinkedIn search {target_index}/{total_targets}")
                logger.info(
                    "%s search_term=%s | location=%s | results_wanted=%d",
                    target_tag,
                    target["search_term"] or "(unset)",
                    target["location"] or "(all)",
                    target["results_wanted"],
                )
                try:
                    fetch_started_at = time.monotonic()
                    logger.info(
                        "%s jobspy fetch start | search_term=%r | location=%r | results_wanted=%d | hours_old=%d | easy_apply=%r | sort_newest_first=%s",
                        target_tag,
                        target["search_term"] or "(unset)",
                        target["location"] or "(all)",
                        target["results_wanted"],
                        target["hours_old"],
                        target.get("easy_apply"),
                        target["sort_newest_first"],
                    )
                    rows = self._fetch_jobspy(target)
                    logger.info(
                        "%s jobspy fetch done | elapsed_ms=%d | rows=%s",
                        target_tag,
                        int((time.monotonic() - fetch_started_at) * 1000),
                        "none" if rows is None else len(rows),
                    )
                except Exception as exc:
                    logger.warning("%s jobspy call failed: %s: %s", target_tag, type(exc).__name__, exc)
                    continue

                if rows is None or len(rows) == 0:
                    logger.info("%s no results", target_tag)
                    continue

                if target.get("sort_newest_first"):
                    try:
                        rows = rows.sort_values(
                            by="date_posted",
                            ascending=False,
                            na_position="last",
                        )
                    except Exception:
                        pass

                logger.info("%s rows=%d", target_tag, len(rows))

                for _, row in rows.iterrows():
                    if run_stop_requested():
                        logger.info("[LinkedIn] stop requested; ending scrape")
                        break
                    record = normalize_jobspy_record(
                        row,
                        source=self.source_name,
                        search_keywords=target["search_term"],
                        search_location=target["location"],
                        run_iso=self.run_iso,
                        salary_rules=salary_rules,
                        job_type_rules=job_type_rules,
                    )
                    _backfill_linkedin_posted_age(record, self.run_iso)
                    record[RECORD_DESCRIPTION_SOURCE_KEY] = "linkedin_full_description"
                    record[RECORD_DETAILS_TEXT_KEY] = str(record.get(RECORD_DETAILS_TEXT_KEY) or "")
                    logger.info(
                        "[PIPELINE][CARD_NORMALIZED] source=LINKEDIN job_key=%s title=%r company=%r url=%r description_chars=%d",
                        record.get(RECORD_JOB_KEY),
                        record.get(RECORD_TITLE_KEY),
                        record.get(RECORD_COMPANY_KEY),
                        record.get(RECORD_URL_KEY),
                        len(record[RECORD_DETAILS_TEXT_KEY]),
                    )

                    closed_signals = self._detect_closed_job_signals(record)
                    if closed_signals:
                        record[RECORD_JOB_QUALITY_SIGNALS_KEY] = closed_signals
                        logger.info(
                            "%s closed listing detected; will reject before detail review",
                            target_tag,
                        )

                    pre_outcome, record, _, should_fetch_details = review_pre_detail_normalized_job(
                        record, review_context
                    )
                    if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
                        continue

                    hooks = self._build_review_hooks()
                    outcome, record, record_skill_observations = review_post_detail_normalized_job(
                        record, review_context, hooks=hooks
                    )
                    if outcome["decision"] != "KEEP":
                        continue
                    skill_observations.extend(record_skill_observations)
                    kept_records.append(record)
                    _li_score, _li_breakdown = fit_score_and_breakdown_displayed(record, self.profile)
                    logger.info(
                        "%s KEPT %s @ %s | %s | %s | %s | %s",
                        target_tag,
                        record.get(RECORD_TITLE_KEY),
                        record.get(RECORD_COMPANY_KEY),
                        record.get("posted"),
                        record.get(RECORD_LOCATION_KEY),
                        record.get("work_type"),
                        record.get(RECORD_SALARY_KEY) or "N/A",
                    )
                    print_job_human_summary(
                        record, self.profile, score=_li_score, breakdown=_li_breakdown
                    )
        except Exception as exc:
            raise PartialSourceResultsError(
                self.source_name,
                kept_records=kept_records,
                audit_rows=audit_rows,
                skill_observations=skill_observations,
                original_error=exc,
            ) from exc

        logger.info("[LinkedIn] done | kept=%d audit=%d", len(kept_records), len(audit_rows))
        set_run_progress("LinkedIn complete")
        return kept_records, audit_rows, skill_observations

    def _build_search_targets(self, search_settings: dict) -> List[dict]:
        keywords = str(search_settings.get("keywords") or "").strip()
        locations = [
            str(loc).strip() for loc in search_settings.get("locations", []) if str(loc).strip()
        ]
        hours_old = int(
            search_settings.get(
                KEY_LINKEDIN_HOURS_OLD, DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
            )
            or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
        )
        results_wanted = int(
            search_settings.get(
                KEY_LINKEDIN_RESULTS_PER_SEARCH,
                DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH],
            )
            or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH]
        )
        sort_newest_first = bool(
            search_settings.get(
                KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST]
            )
        )
        easy_apply = search_settings.get(KEY_LINKEDIN_EASY_APPLY_ONLY)

        targets = []
        for raw_loc in locations:
            location = resolve_location(raw_loc)
            jobspy_location = to_jobspy(location)
            targets.append(
                {
                    "search_term": keywords,
                    "location": jobspy_location,
                    "hours_old": hours_old,
                    "results_wanted": results_wanted,
                    "sort_newest_first": sort_newest_first,
                    "easy_apply": easy_apply,
                }
            )
        return targets

    def _build_review_hooks(self) -> ReviewPipelineHooks:
        def _after_description_loaded(current_record: dict, context: ReviewPipelineContext) -> None:
            if DEBUG_CAPTURE_SOURCE_PAYLOADS:
                try:
                    write_source_payload_debug(
                        "linkedin",
                        str(
                            current_record.get(RECORD_JOB_KEY)
                            or current_record.get(RECORD_URL_KEY)
                            or "unknown"
                        ),
                        raw_html=_fetch_job_html(current_record),
                        raw_json=current_record.get("source_metadata", {}).get(
                            "raw_source_fields", {}
                        ),
                        normalized_record=current_record,
                    )
                except Exception:
                    pass

        def _before_preference_filters(
            current_record: dict, context: ReviewPipelineContext
        ) -> None:
            from job_hunter_agent.job_quality import (  # noqa: PLC0415
                detect_broad_engagement_signal,
                detect_cv_farming_signals,
                detect_external_date_signals,
                fetch_external_html,
                load_dodgy_job_rules,
            )

            details_text = str(
                current_record.get(RECORD_DETAILS_TEXT_KEY)
                or current_record.get("full_description")
                or ""
            )
            rules = load_dodgy_job_rules()
            signals: list = [
                signal
                for signal in (current_record.get(RECORD_JOB_QUALITY_SIGNALS_KEY) or [])
                if isinstance(signal, dict)
            ]
            signals.extend(detect_cv_farming_signals(details_text, rules))
            signals.extend(detect_broad_engagement_signal(current_record))

            raw_fields = current_record.get("source_metadata", {}).get("raw_source_fields", {})
            is_easy_apply = bool(raw_fields.get("easy_apply"))
            apply_url = str(
                current_record.get("source_metadata", {}).get("apply_url") or ""
            ).strip()
            linkedin_url = str(current_record.get(RECORD_URL_KEY) or "").strip()
            current_record[RECORD_APPLY_METHOD_KEY] = classify_linkedin_apply_method(
                apply_url, linkedin_url
            )
            if not is_easy_apply and apply_url and apply_url != linkedin_url:
                ext_html = fetch_external_html(apply_url)
                run_date = datetime.fromisoformat(context.run_iso).date()
                signals.extend(
                    detect_external_date_signals(
                        ext_html,
                        current_record.get(RECORD_POSTED_AGE_DAYS_KEY),
                        rules,
                        run_date,
                    )
                )

            current_record["job_quality_signals"] = signals
            if current_record.get(RECORD_WORK_MODE_KEY) in (WORK_MODE_UNKNOWN, "", None):
                text_result = extract_from_text(details_text)
                if text_result["work_mode"] != WORK_MODE_UNKNOWN:
                    current_record[RECORD_WORK_MODE_KEY] = text_result["work_mode"]
                    current_record["work_mode_source"] = text_result["work_mode_source"]
                    current_record["work_mode_evidence"] = text_result["work_mode_evidence"]
                    current_record["work_mode_needs_review"] = text_result["work_mode_needs_review"]
            log_work_mode_result(
                str(current_record.get(RECORD_JOB_KEY) or ""), "linkedin", current_record
            )

        return ReviewPipelineHooks(
            after_description_loaded=_after_description_loaded,
            before_preference_filters=_before_preference_filters,
        )

    def _detect_closed_job_signals(self, record: dict) -> list[dict]:
        from job_hunter_agent.job_quality import (  # noqa: PLC0415
            SIGNAL_KIND_JOB_CLOSED,
            detect_external_date_signals,
            fetch_external_html,
            load_dodgy_job_rules,
        )

        page_url = str(record.get(RECORD_URL_KEY) or "").strip()
        if not page_url:
            return []

        page_html = fetch_external_html(page_url)
        if not page_html:
            return []

        rules = load_dodgy_job_rules()
        run_date = datetime.fromisoformat(self.run_iso).date()
        signals = detect_external_date_signals(page_html, None, rules, run_date)
        return [signal for signal in signals if signal.get("kind") == SIGNAL_KIND_JOB_CLOSED]

    def _fetch_jobspy(self, target: dict):
        from jobspy import scrape_jobs  # noqa: PLC0415

        search_params = {
            "site_name": ["linkedin"],
            "search_term": target["search_term"],
            "location": target["location"],
            "results_wanted": target["results_wanted"],
            "hours_old": target["hours_old"],
            "country_indeed": "Australia",
            "linkedin_fetch_description": True,
            "verbose": 0,
        }
        if target.get("easy_apply") is not None:
            search_params["easy_apply"] = target["easy_apply"]
        return scrape_jobs(**search_params)
