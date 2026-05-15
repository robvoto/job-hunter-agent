"""LinkedIn source connector using python-jobspy.

Scrapes LinkedIn public job listings (no login required) via the jobspy library.
Returns normalized records in the same shape as the SEEK connector so the shared
filtering, enrichment, LLM gate, and workspace rendering pipeline works unchanged.
"""

import re
from typing import List
from urllib.error import URLError
from urllib.request import Request, urlopen

from job_hunter_agent.filters import analyze_title_filters, passes_content_filters, passes_quick_card_filters
from job_hunter_agent.record_schema import (
    RECORD_JOB_KEY, RECORD_URL_KEY, RECORD_TITLE_KEY, RECORD_COMPANY_KEY,
    RECORD_DECISION_KEY, RECORD_REJECT_REASON_KEY, RECORD_TITLE_REASON_KEY,
    RECORD_TITLE_MATCH_METADATA_KEY, RECORD_LOCATION_KEY, RECORD_WORK_MODE_KEY,
    RECORD_WORK_TYPE_KEY, RECORD_SALARY_KEY, RECORD_TEASER_KEY, RECORD_DETAILS_TEXT_KEY,
    RECORD_DETAILS_STATUS_KEY, RECORD_DESCRIPTION_SOURCE_KEY, RECORD_FIT_CONFIDENCE_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY, RECORD_FULL_DESCRIPTION_KEY, RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_CONTENT_REASON_KEY, RECORD_COMPETITIVE_SIGNALS_KEY, RECORD_SOURCE_METADATA_KEY,
    RECORD_POSTED_AGE_DAYS_KEY, RECORD_WORK_MODE_SOURCE_KEY, RECORD_WORK_MODE_EVIDENCE_KEY,
    RECORD_WORK_MODE_NEEDS_REVIEW_KEY, DETAILS_STATUS_OK, CONFIDENCE_HIGH,
    CONFIDENCE_LOW, RECORD_JOB_QUALITY_SIGNALS_KEY,
)
from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_DATE_RANGE_DAYS,
    KEY_LINKEDIN_EASY_APPLY_ONLY,
    KEY_LINKEDIN_HOURS_OLD,
    KEY_LINKEDIN_RESULTS_PER_SEARCH,
    KEY_SORT_NEWEST_FIRST,
)
from job_hunter_agent.description_trust import get_min_trusted_description_length, get_trusted_sources
from job_hunter_agent.io_utils import DEBUG_CAPTURE_SOURCE_PAYLOADS, write_source_payload_debug
from job_hunter_agent.profile_store import get_search_settings
from job_hunter_agent.source_registry import SOURCE_LINKEDIN
from job_hunter_agent.scrapers.base import BaseJobScraper, keywords_to_search_string, normalize_jobspy_record
from job_hunter_agent.utils import extract_salary
from job_hunter_agent.work_mode_extraction import (
    extract_from_text,
    log_work_mode_result,
    WORK_MODE_UNKNOWN,
)
from job_hunter_agent.locations import resolve_location
from job_hunter_agent.scrapers.location_adapters import to_jobspy

from job_hunter_agent.salary import load_salary
from job_hunter_agent.job_types import load_job_type
from job_hunter_agent.role_analysis import infer_posting_channel

#Load once
salary_rules = load_salary()
job_type_rules = load_job_type()


def _normalize_location_for_jobspy(raw: str) -> str:
    """Map raw profile/search location text to python-jobspy's location string."""
    location = resolve_location(str(raw).strip())
    return to_jobspy(location)


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
    """Scrape LinkedIn job listings using python-jobspy."""

    source_name = SOURCE_LINKEDIN

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def scrape(self) -> tuple:
        """Run the LinkedIn scrape pipeline.

        Returns:
            (kept_records, audit_rows, skill_observations)
        """
        # Lazy imports keep the scraper decoupled from heavier review helpers.
        from job_hunter_agent.capability_matching import build_risk_and_missing_evidence  # noqa: PLC0415
        from job_hunter_agent.fit_scoring import build_fit_highlights  # noqa: PLC0415
        from job_hunter_agent.hard_blocker_rules import find_hard_block_matches  # noqa: PLC0415
        from job_hunter_agent.history import apply_kept_job_reuse, can_reuse_kept_job, finalize_record  # noqa: PLC0415
        from job_hunter_agent.signal_detection import (  # noqa: PLC0415
            detect_competitive_signals,
            evaluate_competitive_signal_alignment,
            extract_skill_observations,
            hard_block_entries,
            hard_block_reasons,
        )
        from job_hunter_agent.source_learning import (  # noqa: PLC0415
            has_high_value_ambiguous_learning_candidate,
            merge_pending_learning_signals,
            register_pending_learning_signals,
            resolve_llm_review_payload,
            build_ad_learning_signals,
            deterministic_review_outcome,
            register_hard_blocker_learning_from_rejection,
        )
        from job_hunter_agent.text_processing import build_role_summary, compact_whitespace  # noqa: PLC0415
        min_trusted_description_length = get_min_trusted_description_length()

        kept_records: List[dict] = []
        audit_rows: List[dict] = []
        skill_observations: List[dict] = []

        targets = self._build_search_targets()
        if not targets:
            print("[LinkedIn] No search targets configured. Skipping.")
            return kept_records, audit_rows, skill_observations

        for target in targets:
            print(f"\n[LinkedIn] Searching: {target['search_term']} | {target['location']} (Targeting up to {target['results_wanted']} results)")
            try:
                rows = self._fetch_jobspy(target)
            except Exception as exc:
                print(f"[LinkedIn] jobspy call failed for {target['location']}: {type(exc).__name__}: {exc}")
                continue

            if rows is None or len(rows) == 0:
                print(f"[LinkedIn] No results for {target['location']}")
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

            print(f"[LinkedIn] Fetched {len(rows)} raw listings. Starting filter and score pipeline...")

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

                title = record.get(RECORD_TITLE_KEY) or ""
                company = record.get(RECORD_COMPANY_KEY) or "N/A"

                if not record.get(RECORD_JOB_KEY):
                    record[RECORD_REJECT_REASON_KEY] = "NO_JOB_KEY"
                    audit_rows.append(record)
                    continue

                if not record.get(RECORD_URL_KEY):
                    record[RECORD_REJECT_REASON_KEY] = "NO_URL"
                    audit_rows.append(record)
                    continue

                # Title filter
                title_analysis = analyze_title_filters(title, self.profile)
                ok_title = bool(title_analysis.get("ok"))
                title_reason = str(title_analysis.get("reason") or "")
                record[RECORD_TITLE_REASON_KEY] = title_reason
                record[RECORD_TITLE_MATCH_METADATA_KEY] = title_analysis
                if not ok_title:
                    print(f"[LinkedIn] REJECTED (title) [{title_reason}] {title}")
                    record[RECORD_REJECT_REASON_KEY] = title_reason
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                # Applied / hidden skip
                job_key = record[RECORD_JOB_KEY]
                if job_key in self.applied_job_keys:
                    record[RECORD_DECISION_KEY] = "SKIP"
                    record[RECORD_REJECT_REASON_KEY] = "ALREADY_APPLIED"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue
                if job_key in self.hidden_job_keys:
                    record[RECORD_DECISION_KEY] = "SKIP"
                    record[RECORD_REJECT_REASON_KEY] = "MANUALLY_HIDDEN"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                # Date window check
                search_settings = get_search_settings(self.profile)
                date_range_days = int(search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]) or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
                posted_age = record.get(RECORD_POSTED_AGE_DAYS_KEY)
                enforce_limit = bool(search_settings.get("enforce_posted_age_limit", DEFAULT_SEARCH_SETTINGS["enforce_posted_age_limit"]))
                if enforce_limit and posted_age is not None and posted_age > date_range_days:
                    record[RECORD_REJECT_REASON_KEY] = f"POSTED_TOO_OLD:{date_range_days}"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                # Quick card gate
                ok_card, card_reason = passes_quick_card_filters(
                    title=title,
                    teaser=record.get(RECORD_TEASER_KEY) or "",
                    company=company,
                    location=record.get(RECORD_LOCATION_KEY) or "",
                    work_mode=record.get(RECORD_WORK_MODE_KEY) or "",
                    work_type=record.get(RECORD_WORK_TYPE_KEY) or "",
                    salary=record.get(RECORD_SALARY_KEY) or "",
                )
                if not ok_card:
                    print(f"[LinkedIn] REJECTED (card gate) [{card_reason}] {title} @ {company}")
                    record[RECORD_REJECT_REASON_KEY] = card_reason
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                # History reuse check
                history_entry = self.job_history.get(job_key, {})
                if can_reuse_kept_job(history_entry, record, self.profile):
                    record = apply_kept_job_reuse(record, history_entry)
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    kept_records.append(record)
                    print(f"[LinkedIn] KEPT (history reuse): {title} @ {company}")
                    continue

                details_text = record.get(RECORD_DETAILS_TEXT_KEY) or ""
                if not details_text:
                    record[RECORD_REJECT_REASON_KEY] = "NO_DETAILS"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue
                record[RECORD_FIT_SOURCE_TEXT_KEY] = details_text
                record[RECORD_FULL_DESCRIPTION_KEY] = details_text
                record[RECORD_DESCRIPTION_SOURCE_KEY] = "linkedin_full_description"
                source = str(record.get(RECORD_DESCRIPTION_SOURCE_KEY) or "").strip().lower()
                is_trusted = source in get_trusted_sources() and len(details_text) >= min_trusted_description_length
                record[RECORD_FIT_CONFIDENCE_KEY] = CONFIDENCE_HIGH if is_trusted else CONFIDENCE_LOW
                record[RECORD_DETAILS_STATUS_KEY] = DETAILS_STATUS_OK

                # Content filter
                ok_desc, desc_reason = passes_content_filters(
                    details_text,
                    record.get(RECORD_LOCATION_KEY) or "",
                    record.get(RECORD_TITLE_REASON_KEY) or "",
                )
                record[RECORD_CONTENT_REASON_KEY] = desc_reason
                if not ok_desc:
                    if desc_reason.startswith("DESC_HARD_BLOCK_RULE"):
                        record[RECORD_HARD_BLOCK_REASONS_KEY] = [
                            match.get("value") or match.get("matched_term") or ""
                            for match in find_hard_block_matches(details_text, self.profile.get("must_not_require_skills", []))
                        ]
                    register_hard_blocker_learning_from_rejection(record, desc_reason, details_text, profile=self.profile)
                    print(f"[LinkedIn] REJECTED (content) [{desc_reason}] {title} @ {company}")
                    record[RECORD_REJECT_REASON_KEY] = desc_reason
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue
                # Job quality signals (evidence only — do not reject based on these)
                _job_quality_signals: list = []
                try:
                    from datetime import datetime as _dt  # noqa: PLC0415
                    from job_hunter_agent.job_quality import (  # noqa: PLC0415
                        load_dodgy_job_rules,
                        fetch_external_html,
                        detect_external_date_signals,
                        detect_cv_farming_signals,
                    )
                    _dodgy_rules = load_dodgy_job_rules()
                    _job_quality_signals.extend(detect_cv_farming_signals(details_text, _dodgy_rules))
                    _raw_fields = record.get(RECORD_SOURCE_METADATA_KEY, {}).get("raw_source_fields", {})
                    _is_easy_apply = bool(_raw_fields.get("easy_apply"))
                    _apply_url = str(record.get(RECORD_SOURCE_METADATA_KEY, {}).get("apply_url") or "").strip()
                    _linkedin_url = str(record.get(RECORD_URL_KEY) or "").strip()
                    if not _is_easy_apply and _apply_url and _apply_url != _linkedin_url:
                        _ext_html = fetch_external_html(_apply_url)
                        _run_date = _dt.fromisoformat(self.run_iso).date()
                        _job_quality_signals.extend(
                            detect_external_date_signals(
                                _ext_html,
                                record.get(RECORD_POSTED_AGE_DAYS_KEY),
                                _dodgy_rules,
                                _run_date,
                            )
                        )
                except Exception as _qe:
                    print(f"[LinkedIn] Job quality check skipped: {type(_qe).__name__}: {_qe}")
                record[RECORD_JOB_QUALITY_SIGNALS_KEY] = _job_quality_signals
                if _job_quality_signals:
                    _kinds = ", ".join(s.get("kind", "?") for s in _job_quality_signals)
                    print(f"[LinkedIn] Quality signals [{_kinds}]: {title} @ {company}")

                # Enrich from full description text
                salary = extract_salary(details_text)
                if salary == "N/A":
                    salary = record.get(RECORD_SALARY_KEY) or "N/A"
                record[RECORD_SALARY_KEY] = salary

                # Upgrade work mode via text inference only if structured metadata found nothing.
                if record.get(RECORD_WORK_MODE_KEY) in (WORK_MODE_UNKNOWN, "", None):
                    text_result = extract_from_text(details_text)
                    if text_result["work_mode"] != WORK_MODE_UNKNOWN:
                        record[RECORD_WORK_MODE_KEY] = text_result["work_mode"]
                        record[RECORD_WORK_MODE_SOURCE_KEY] = text_result["work_mode_source"]
                        record[RECORD_WORK_MODE_EVIDENCE_KEY] = text_result["work_mode_evidence"]
                        record[RECORD_WORK_MODE_NEEDS_REVIEW_KEY] = text_result["work_mode_needs_review"]
                log_work_mode_result(str(record.get(RECORD_JOB_KEY) or ""), "linkedin", record)

                raw_signals = detect_competitive_signals(details_text, self.profile)
                record[RECORD_COMPETITIVE_SIGNALS_KEY] = [
                    evaluate_competitive_signal_alignment(s, self.profile) for s in raw_signals
                ]
                hard_block_matches = hard_block_entries(
                    {
                        RECORD_FIT_SOURCE_TEXT_KEY: details_text,
                        RECORD_COMPETITIVE_SIGNALS_KEY: record.get(RECORD_COMPETITIVE_SIGNALS_KEY),
                    },
                    self.profile,
                )
                record[RECORD_HARD_BLOCK_REASONS_KEY] = [entry["text"] for entry in hard_block_matches]
                if record["hard_block_reasons"]:
                    hard_block_term = compact_whitespace(record["hard_block_reasons"][0]).lower()
                    hard_block_category = re.sub(r"[^a-z0-9]+", "_", hard_block_term).strip("_") or "hard_block"
                    record["content_reason"] = f"DESC_HARD_BLOCK_RULE:{hard_block_category}"
                    record["reject_reason"] = record["content_reason"]
                    register_hard_blocker_learning_from_rejection(
                        record,
                        record["content_reason"],
                        details_text,
                        hard_block_matches,
                        profile=self.profile,
                    )
                    print(
                        f"[LinkedIn] REJECTED (hard block) [{record['content_reason']}] {title} @ {company} | "
                        f"{'; '.join(record['hard_block_reasons'])}"
                    )
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue
                record_skill_observations = extract_skill_observations(record, self.profile)
                skill_observations.extend(record_skill_observations)
                record["skill_observations"] = record_skill_observations
                record["ad_learning_signals"] = build_ad_learning_signals(record, details_text, self.profile)
                record["role_snapshot"] = build_role_summary(record, details_text, self.profile)
                record["fit_highlights"] = build_fit_highlights(record, details_text, self.profile)
                soft_risk_reasons, missing_evidence = build_risk_and_missing_evidence(
                    details_text,
                    record.get("title_reason"),
                    self.profile,
                    competitive_signals=record.get("competitive_signals"),
                )
                record["soft_risk_reasons"] = soft_risk_reasons
                record["missing_evidence"] = missing_evidence
                record["fit_watchout_meta"] = []
                record["fit_watchouts"] = []
                channel_signal = infer_posting_channel(record, details_text)
                record["posting_channel_evidence"] = {
                    "trusted_metadata": list(channel_signal.get("trusted_metadata") or []),
                    "weak_text_matches": list(channel_signal.get("weak_text_matches") or []),
                    "needs_review": bool(channel_signal.get("needs_review")),
                }
                if DEBUG_CAPTURE_SOURCE_PAYLOADS:
                    try:
                        write_source_payload_debug(
                            "linkedin",
                            str(record.get("job_key") or record.get("url") or "unknown"),
                            raw_html=_fetch_job_html(record),
                            raw_json=record.get("source_metadata", {}).get("raw_source_fields", {}),
                            normalized_record=record,
                        )
                    except Exception:
                        pass

                # LLM gate
                deterministic_review = deterministic_review_outcome(
                    record, record["fit_highlights"], missing_evidence, soft_risk_reasons
                )
                if deterministic_review is not None:
                    llm_review = deterministic_review
                    print(f"[LinkedIn][LLM][SKIP] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                    if has_high_value_ambiguous_learning_candidate(record.get("ad_learning_signals") or []):
                        payload = resolve_llm_review_payload(
                            record,
                            self.llm_cache,
                            learning_only=True,
                        )
                        record["llm_learning_candidates"] = payload.get("learning_candidates") or []
                else:
                    payload = resolve_llm_review_payload(
                        record,
                        self.llm_cache,
                    )
                    llm_review = payload["fit_review"]
                    print(f"[LinkedIn][LLM][{payload.get('payload_source', 'llm').upper()}] {llm_review['decision']}|{llm_review['grade']} {title}")

                record["llm_decision"] = llm_review["decision"]
                record["llm_fit_grade"] = llm_review["grade"]

                if llm_review["decision"] == "REJECT":
                    print(f"[LinkedIn] REJECTED (llm) {title} @ {company}")
                    record["reject_reason"] = "LLM_REJECT"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                record["decision"] = "KEEP"
                pending_signals = merge_pending_learning_signals(
                    record.get("ad_learning_signals") or [],
                    record.get("llm_learning_candidates") or [],
                )
                register_pending_learning_signals(pending_signals)
                record.pop("skill_observations", None)
                record.pop("ad_learning_signals", None)
                record.pop("llm_learning_candidates", None)
                finalize_record(self.job_history, audit_rows, record, self.run_iso)
                kept_records.append(record)
                print(
                    f"[LinkedIn] KEPT: {title} @ {company} | {record.get('posted')} | "
                    f"{record.get('location')} | {record.get('work_type')} | {salary}"
                )

        print(
            f"\n[LinkedIn] Done - kept {len(kept_records)} / {len(audit_rows)} total records"
        )
        return kept_records, audit_rows, skill_observations

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _build_search_targets(self) -> List[dict]:
        search_settings = get_search_settings(self.profile)
        keywords = keywords_to_search_string(search_settings.get("keywords") or "")
        locations = [
            str(loc).strip()
            for loc in search_settings.get("locations", [])
            if str(loc).strip()
        ]
        date_range_days = int(search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]) or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
        hours_old = int(search_settings.get(KEY_LINKEDIN_HOURS_OLD, DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD]) or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_HOURS_OLD])
        results_wanted = int(search_settings.get(KEY_LINKEDIN_RESULTS_PER_SEARCH, DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH]) or DEFAULT_SEARCH_SETTINGS[KEY_LINKEDIN_RESULTS_PER_SEARCH])
        sort_newest_first = bool(search_settings.get(KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST]))
        easy_apply = search_settings.get(KEY_LINKEDIN_EASY_APPLY_ONLY)  # None / True / False

        targets = []
        for raw_loc in locations:
            location = resolve_location(raw_loc)
            jobspy_location = to_jobspy(location)

            targets.append({
                "search_term": keywords,
                "location": jobspy_location,
                "hours_old": hours_old,
                "results_wanted": results_wanted,
                "sort_newest_first": sort_newest_first,
                "easy_apply": easy_apply,
            })
        return targets

    def _fetch_jobspy(self, target: dict):
        """Call python-jobspy and return a DataFrame (or None on failure)."""
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

