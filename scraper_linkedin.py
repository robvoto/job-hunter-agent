"""LinkedIn source connector using python-jobspy.

Scrapes LinkedIn public job listings (no login required) via the jobspy library.
Returns normalized records in the same shape as the SEEK connector so the shared
filtering, enrichment, LLM gate, and dashboard rendering pipeline works unchanged.
"""

import re
import sys
from typing import List, Set

from filters import passes_content_filters, passes_quick_card_filters, passes_title_filters
from llm_gate import build_llm_cache_key, llm_is_enabled, llm_should_consider, normalize_llm_review
from profile_store import get_search_settings
from review_insights import extract_detected_skills
from scraper_base import BaseJobScraper, normalize_jobspy_record
from utils import extract_salary, extract_work_mode


class LinkedInScraper(BaseJobScraper):
    """Scrape LinkedIn job listings using python-jobspy."""

    source_name = "linkedin"

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def scrape(self) -> tuple:
        """Run the LinkedIn scrape pipeline.

        Returns:
            (kept_records, audit_rows, skill_observations)
        """
        # Lazy import to avoid circular dependency with scraper_direct.py
        # (scraper_direct imports LinkedInScraper; scraper_linkedin needs
        # enrichment functions defined in scraper_direct)
        from scraper_direct import (  # noqa: PLC0415
            MAX_LLM_CHARS,
            build_fit_highlights,
            build_role_summary,
            build_watchout_entries,
            can_reuse_kept_job,
            apply_kept_job_reuse,
            compact_whitespace,
            detect_competitive_signals,
            deterministic_review_outcome,
            evaluate_competitive_signal_alignment,
            finalize_record,
            hard_block_entries,
            hard_block_reasons,
        )

        kept_records: List[dict] = []
        audit_rows: List[dict] = []
        skill_observations: List[dict] = []

        targets = self._build_search_targets()
        if not targets:
            print("[LinkedIn] No search targets configured. Skipping.")
            return kept_records, audit_rows, skill_observations

        for target in targets:
            print(f"\n[LinkedIn] Searching: {target['search_term']} | {target['location']}")
            try:
                rows = self._fetch_jobspy(target)
            except Exception as exc:
                print(f"[LinkedIn] jobspy call failed for {target['location']}: {type(exc).__name__}: {exc}")
                continue

            if rows is None or len(rows) == 0:
                print(f"[LinkedIn] No results for {target['location']}")
                continue

            print(f"[LinkedIn] {len(rows)} results from jobspy")

            for _, row in rows.iterrows():
                record = normalize_jobspy_record(
                    row,
                    search_keywords=target["search_term"],
                    search_location=target["location"],
                    run_iso=self.run_iso,
                )

                title = record.get("title", "")
                company = record.get("company", "N/A")

                if not record.get("job_key"):
                    record["reject_reason"] = "NO_JOB_KEY"
                    audit_rows.append(record)
                    continue

                if not record.get("url"):
                    record["reject_reason"] = "NO_URL"
                    audit_rows.append(record)
                    continue

                # Title filter
                ok_title, title_reason = passes_title_filters(title)
                record["title_reason"] = title_reason
                if not ok_title:
                    print(f"[LinkedIn] REJECTED (title) [{title_reason}] {title}")
                    record["reject_reason"] = title_reason
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                # Applied / hidden skip
                job_key = record["job_key"]
                bare_key = job_key.split(":", 1)[-1] if ":" in job_key else job_key
                if bare_key in self.applied_job_keys or job_key in self.applied_job_keys:
                    record["decision"] = "SKIP"
                    record["reject_reason"] = "ALREADY_APPLIED"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue
                if bare_key in self.hidden_job_keys or job_key in self.hidden_job_keys:
                    record["decision"] = "SKIP"
                    record["reject_reason"] = "MANUALLY_HIDDEN"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                # Date window check
                search_settings = get_search_settings(self.profile)
                date_range_days = int(search_settings.get("date_range_days", 3) or 3)
                posted_age = record.get("posted_age_days")
                enforce_limit = bool(search_settings.get("enforce_posted_age_limit", True))
                if enforce_limit and posted_age is not None and posted_age > date_range_days:
                    record["reject_reason"] = f"POSTED_TOO_OLD:{date_range_days}"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                # Quick card gate
                ok_card, card_reason = passes_quick_card_filters(
                    title=title,
                    teaser=record.get("teaser", ""),
                    company=company,
                    location=record.get("location", ""),
                    work_mode=record.get("work_mode", ""),
                    work_type=record.get("work_type", ""),
                    salary=record.get("salary", ""),
                )
                if not ok_card:
                    print(f"[LinkedIn] REJECTED (card gate) [{card_reason}] {title} @ {company}")
                    record["reject_reason"] = card_reason
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

                details_text = record.get("details_text", "")
                if not details_text:
                    record["reject_reason"] = "NO_DETAILS"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue
                record["fit_source_text"] = details_text
                record["details_status"] = "ok"

                # Skill observations
                for skill in extract_detected_skills(details_text):
                    skill_observations.append({
                        "skill": skill,
                        "title": title,
                        "company": company,
                        "url": record.get("url", ""),
                        "search_location": target["location"],
                    })

                # Content filter
                ok_desc, desc_reason = passes_content_filters(details_text, record.get("location", ""))
                record["content_reason"] = desc_reason
                if not ok_desc:
                    print(f"[LinkedIn] REJECTED (content) [{desc_reason}] {title} @ {company}")
                    record["reject_reason"] = desc_reason
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                # Enrich from full description text
                salary = extract_salary(details_text)
                if salary == "N/A":
                    salary = record.get("salary", "N/A")
                record["salary"] = salary

                detail_work_mode = extract_work_mode(details_text)
                if detail_work_mode != "N/A":
                    record["work_mode"] = detail_work_mode

                raw_signals = detect_competitive_signals(details_text, self.profile)
                record["competitive_signals"] = [
                    evaluate_competitive_signal_alignment(s, self.profile) for s in raw_signals
                ]
                hard_block_matches = hard_block_entries(
                    {
                        "fit_source_text": details_text,
                        "competitive_signals": record.get("competitive_signals"),
                    },
                    self.profile,
                )
                record["hard_block_reasons"] = [entry["text"] for entry in hard_block_matches]
                if record["hard_block_reasons"]:
                    hard_block_category = hard_block_matches[0].get("category") or "hard_block"
                    record["content_reason"] = f"DESC_HARD_BLOCK:{hard_block_category}"
                    record["reject_reason"] = record["content_reason"]
                    print(
                        f"[LinkedIn] REJECTED (hard block) [{record['content_reason']}] {title} @ {company} | "
                        f"{'; '.join(record['hard_block_reasons'])}"
                    )
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue
                record["role_snapshot"] = build_role_summary(record, details_text, self.profile)
                record["fit_highlights"] = build_fit_highlights(record, details_text, self.profile)
                record["fit_watchout_meta"] = build_watchout_entries(
                    details_text,
                    record.get("title_reason"),
                    self.profile,
                    competitive_signals=record.get("competitive_signals"),
                )
                record["fit_watchouts"] = [e["text"] for e in record["fit_watchout_meta"]]

                # LLM gate
                deterministic_review = deterministic_review_outcome(
                    record, record["fit_highlights"], record["fit_watchout_meta"]
                )
                if deterministic_review is not None:
                    llm_review = deterministic_review
                    print(f"[LinkedIn][LLM][SKIP] {llm_review['decision']}|{llm_review['grade']} {title} @ {company}")
                else:
                    llm_input = compact_whitespace(details_text)[:MAX_LLM_CHARS]
                    llm_fp = build_llm_cache_key(llm_input)

                    if not llm_is_enabled():
                        llm_review = normalize_llm_review(None)
                        print(f"[LinkedIn][LLM][DISABLED] {llm_review['decision']}|{llm_review['grade']} {title}")
                    elif llm_fp in self.llm_cache:
                        llm_review = normalize_llm_review(self.llm_cache[llm_fp])
                        print(f"[LinkedIn][LLM][CACHE] {llm_review['decision']}|{llm_review['grade']} {title}")
                    else:
                        llm_review = normalize_llm_review(llm_should_consider(llm_input))
                        self.llm_cache[llm_fp] = llm_review
                        print(f"[LinkedIn][LLM] {llm_review['decision']}|{llm_review['grade']} {title}")

                record["llm_decision"] = llm_review["decision"]
                record["llm_fit_grade"] = llm_review["grade"]

                if llm_review["decision"] == "REJECT":
                    print(f"[LinkedIn] REJECTED (llm) {title} @ {company}")
                    record["reject_reason"] = "LLM_REJECT"
                    finalize_record(self.job_history, audit_rows, record, self.run_iso)
                    continue

                record["decision"] = "KEEP"
                finalize_record(self.job_history, audit_rows, record, self.run_iso)
                kept_records.append(record)
                print(
                    f"[LinkedIn] KEPT: {title} @ {company} | {record.get('posted')} | "
                    f"{record.get('location')} | {record.get('work_type')} | {salary}"
                )

        print(
            f"\n[LinkedIn] Done — kept {len(kept_records)} / {len(audit_rows)} total records"
        )
        return kept_records, audit_rows, skill_observations

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _build_search_targets(self) -> List[dict]:
        search_settings = get_search_settings(self.profile)
        keywords = str(search_settings.get("keywords") or "").strip()
        locations = [
            str(loc).strip()
            for loc in search_settings.get("locations", [])
            if str(loc).strip()
        ]
        date_range_days = int(search_settings.get("date_range_days", 3) or 3)
        hours_old = int(search_settings.get("linkedin_hours_old", 24) or 24)
        results_wanted = int(search_settings.get("linkedin_results_per_search", 25) or 25)
        easy_apply = search_settings.get("linkedin_easy_apply_only")  # None / True / False
        test_scrape_mode = "--test-scrape-mode" in set(sys.argv[1:])
        if test_scrape_mode:
            hours_old = max(hours_old, max(date_range_days, 3) * 24)
            results_wanted = max(results_wanted, 40)

        targets = []
        for raw_loc in locations:
            jobspy_location = _normalize_location_for_jobspy(raw_loc)
            targets.append({
                "search_term": keywords,
                "location": jobspy_location,
                "hours_old": hours_old,
                "results_wanted": results_wanted,
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


def _normalize_location_for_jobspy(seek_location: str) -> str:
    """Convert SEEK-style location strings to jobspy-friendly city strings.

    Examples:
        'All Sydney NSW'  → 'Sydney, Australia'
        'All Canberra ACT' → 'Canberra, Australia'
        'Sydney NSW'      → 'Sydney, Australia'
    """
    text = re.sub(r"^all\s+", "", seek_location.strip(), flags=re.IGNORECASE)
    # Strip trailing state abbreviation if present (e.g. "Sydney NSW" → "Sydney")
    text = re.sub(r"\s+[A-Z]{2,3}$", "", text.strip())
    text = text.strip()
    if text and not text.lower().endswith("australia"):
        text = f"{text}, Australia"
    return text or seek_location
