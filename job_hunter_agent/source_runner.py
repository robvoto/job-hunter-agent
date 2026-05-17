from __future__ import annotations

from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.source_registry import SOURCE_LINKEDIN, SOURCE_SEEK
from job_hunter_agent.scrapers.seek import build_seek_search_targets
from job_hunter_agent.scrapers.seek_runner import seek_scrape_to_records


def run_enabled_sources(context: ScrapeRunContext) -> tuple[list[dict], list[dict], list[dict]]:
    kept_records: list[dict] = []
    audit_rows: list[dict] = []
    skill_observations: list[dict] = []

    profile = context.profile
    configured_seek_max_pages = context.configured_seek_max_pages
    configured_date_range = context.configured_date_range
    sort_newest_first = context.sort_newest_first
    playwright_viewport_width = context.playwright_viewport_width
    playwright_viewport_height = context.playwright_viewport_height
    playwright_selector_timeout = context.playwright_selector_timeout
    applied_job_keys = context.applied_job_keys
    hidden_job_keys = context.hidden_job_keys
    run_iso = context.run_iso
    llm_cache = context.llm_cache
    job_history = context.job_history
    enabled_sources = context.enabled_sources
    headless = bool(getattr(context, "headless", False))

    if SOURCE_SEEK in enabled_sources:
        print("[Seek] enabled")
    else:
        print("[Seek] disabled in enabled_sources; skipping")

    if SOURCE_SEEK in enabled_sources:
        search_targets = build_seek_search_targets(profile, configured_date_range, sort_newest_first)
        s_kept, s_audit, s_skills = seek_scrape_to_records(
            profile=profile,
            search_targets=search_targets,
            job_history=job_history,
            llm_cache=llm_cache,
            applied_job_keys=applied_job_keys,
            hidden_job_keys=hidden_job_keys,
            run_iso=run_iso,
            configured_date_range=configured_date_range,
            configured_seek_max_pages=configured_seek_max_pages,
            playwright_viewport_width=playwright_viewport_width,
            playwright_viewport_height=playwright_viewport_height,
            playwright_selector_timeout=playwright_selector_timeout,
            headless=headless,
        )
        kept_records.extend(s_kept)
        audit_rows.extend(s_audit)
        skill_observations.extend(s_skills)
    if SOURCE_LINKEDIN in enabled_sources:
        print("[LinkedIn] enabled")
    else:
        print("[LinkedIn] disabled in enabled_sources; skipping")

    if SOURCE_LINKEDIN in enabled_sources:
        from job_hunter_agent.scrapers.linkedin import LinkedInScraper  # noqa: PLC0415

        try:
            li = LinkedInScraper(
                profile=profile,
                llm_cache=llm_cache,
                job_history=job_history,
                applied_job_keys=applied_job_keys,
                hidden_job_keys=hidden_job_keys,
                run_iso=run_iso,
            )
            li_kept, li_audit, li_skills = li.scrape()
            kept_records.extend(li_kept)
            audit_rows.extend(li_audit)
            skill_observations.extend(li_skills)
        except Exception as exc:
            print(f"[LinkedIn] Scraping failed: {type(exc).__name__}: {exc}")

    return kept_records, audit_rows, skill_observations
