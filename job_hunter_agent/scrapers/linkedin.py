"""LinkedIn source connector using python-jobspy."""

from __future__ import annotations

from datetime import datetime
from typing import List
from urllib.error import URLError
from urllib.request import Request, urlopen

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
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
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
from job_hunter_agent.salary import load_salary
from job_hunter_agent.job_types import load_job_type
from job_hunter_agent.scrapers.base import BaseJobScraper, normalize_jobspy_record
from job_hunter_agent.source_registry import SOURCE_LINKEDIN
from job_hunter_agent.work_mode_extraction import WORK_MODE_UNKNOWN, extract_from_text, log_work_mode_result
from job_hunter_agent.fit_scoring import fit_score, fit_score_breakdown

from job_hunter_agent.locations import resolve_location
from job_hunter_agent.scrapers.location_adapters import to_jobspy


salary_rules = load_salary()
job_type_rules = load_job_type()


def _fetch_job_html(record: dict) -> str:
    raw_fields = record.get("source_metadata", {}).get("raw_source_fields", {})
    if not isinstance(raw_fields, dict):
        raw_fields = {}
    url = str(
        raw_fields.get("job_url_direct")
        or raw_fields.get("job_url")
        or record.get("url")
        or ""
    ).strip()
    if not url:
        return ""
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except (URLError, TimeoutError, ValueError):
        return ""


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
            print("[LinkedIn] no search targets configured; skipping")
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
        for target_index, target in enumerate(targets, start=1):
            target_tag = f"[LinkedIn target {target_index}/{total_targets}]"
            print(
                f"{target_tag} search_term={target['search_term'] or '(unset)'} | "
                f"location={target['location'] or '(all)'} | "
                f"results_wanted={target['results_wanted']}"
            )
            try:
                rows = self._fetch_jobspy(target)
            except Exception as exc:
                print(f"{target_tag} jobspy call failed: {type(exc).__name__}: {exc}")
                continue

            if rows is None or len(rows) == 0:
                print(f"{target_tag} no results")
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

            print(f"{target_tag} rows={len(rows)}")

            for _, row in rows.iterrows():
                record = normalize_jobspy_record(
                    row,
                    source=self.source_name,
                    search_keywords=target["search_term"],
                    search_location=target["location"],
                    run_iso=self.run_iso,
                    salary_rules=salary_rules,
                    job_type_rules=job_type_rules,
                )
                record[RECORD_DESCRIPTION_SOURCE_KEY] = "linkedin_full_description"
                record[RECORD_DETAILS_TEXT_KEY] = str(record.get(RECORD_DETAILS_TEXT_KEY) or "")

                pre_outcome, record, _, should_fetch_details = review_pre_detail_normalized_job(record, review_context)
                if pre_outcome["decision"] != "KEEP" or not should_fetch_details:
                    continue

                hooks = self._build_review_hooks()
                outcome, record, record_skill_observations = review_post_detail_normalized_job(record, review_context, hooks=hooks)
                if outcome["decision"] != "KEEP":
                    continue
                skill_observations.extend(record_skill_observations)
                kept_records.append(record)
                if WORKSPACE_DEBUG_MODE:
                    score = fit_score(record, self.profile)
                    breakdown = fit_score_breakdown(record, self.profile)
                    print(
                        f"{target_tag} [DEBUG][SCORE] {score}/100 | "
                        f"{record.get(RECORD_TITLE_KEY)} @ {record.get(RECORD_COMPANY_KEY)} | "
                        f"Grade: {record.get('llm_fit_grade')} ({record.get('review_source')}) | "
                        f"{record.get(RECORD_URL_KEY, '')}"
                    )
                    for entry in breakdown:
                        print(f"{target_tag}   {entry['label']}: {entry['value']:+d}")

                print(
                    f"{target_tag} KEPT {record.get(RECORD_TITLE_KEY)} @ {record.get(RECORD_COMPANY_KEY)} | "
                    f"{record.get('posted')} | {record.get(RECORD_LOCATION_KEY)} | "
                    f"{record.get('work_type')} | {record.get(RECORD_SALARY_KEY) or 'N/A'}"
                )

        print(f"[LinkedIn] done | kept={len(kept_records)} audit={len(audit_rows)}")
        return kept_records, audit_rows, skill_observations

    def _build_search_targets(self, search_settings: dict) -> List[dict]:
        keywords = str(search_settings.get("keywords") or "").strip()
        locations = [
            str(loc).strip()
            for loc in search_settings.get("locations", [])
            if str(loc).strip()
        ]
        hours_old = int(
            search_settings.get(KEY_LINKEDIN_HOURS_OLD, DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD])
            or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]
        )
        results_wanted = int(
            search_settings.get(KEY_LINKEDIN_RESULTS_PER_SEARCH, DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH])
            or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH]
        )
        sort_newest_first = bool(search_settings.get(KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST]))
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
                        str(current_record.get(RECORD_JOB_KEY) or current_record.get(RECORD_URL_KEY) or "unknown"),
                        raw_html=_fetch_job_html(current_record),
                        raw_json=current_record.get("source_metadata", {}).get("raw_source_fields", {}),
                        normalized_record=current_record,
                    )
                except Exception:
                    pass

        def _before_preference_filters(current_record: dict, context: ReviewPipelineContext) -> None:
            from job_hunter_agent.job_quality import (  # noqa: PLC0415
                detect_broad_engagement_signal,
                detect_cv_farming_signals,
                detect_external_date_signals,
                fetch_external_html,
                load_dodgy_job_rules,
            )

            details_text = str(current_record.get(RECORD_DETAILS_TEXT_KEY) or current_record.get("full_description") or "")
            rules = load_dodgy_job_rules()
            signals: list = []
            signals.extend(detect_cv_farming_signals(details_text, rules))
            signals.extend(detect_broad_engagement_signal(current_record))

            raw_fields = current_record.get("source_metadata", {}).get("raw_source_fields", {})
            is_easy_apply = bool(raw_fields.get("easy_apply"))
            apply_url = str(current_record.get("source_metadata", {}).get("apply_url") or "").strip()
            linkedin_url = str(current_record.get(RECORD_URL_KEY) or "").strip()
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
            log_work_mode_result(str(current_record.get(RECORD_JOB_KEY) or ""), "linkedin", current_record)

        return ReviewPipelineHooks(
            after_description_loaded=_after_description_loaded,
            before_preference_filters=_before_preference_filters,
        )

    def _fetch_jobspy(self, target: dict):
        from jobspy import scrape_jobs  # noqa: PLC0415

        kwargs = {
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
            kwargs["easy_apply"] = target["easy_apply"]
        return scrape_jobs(**kwargs)
