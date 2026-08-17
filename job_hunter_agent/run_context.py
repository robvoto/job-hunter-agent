"""Helpers for run context."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from job_hunter_agent.global_settings import (
    DEFAULT_PLAYWRIGHT_SETTINGS,
    DEFAULT_SEARCH_SETTINGS,
    get_globally_enabled_sources,
    KEY_DATE_RANGE_DAYS,
    KEY_PLAYWRIGHT_SELECTOR_TIMEOUT,
    KEY_PLAYWRIGHT_VIEWPORT_HEIGHT,
    KEY_PLAYWRIGHT_VIEWPORT_WIDTH,
    KEY_SEEK_MAX_PAGES,
    KEY_SEEK_PARALLEL_DETAIL_WORKERS,
    KEY_SORT_NEWEST_FIRST,
)
from job_hunter_agent.history import TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING
from job_hunter_agent.io_utils import (
    load_audit_rows,
    load_job_history,
    load_llm_cache,
    load_run_stats,
    write_run_attempt,
)
from job_hunter_agent.posting_utils import get_manual_skip_sets
from job_hunter_agent.profile_store import get_search_settings, load_profile
from job_hunter_agent.runtime_helpers import (
    CLI_FLAG_DEBUG,
    CLI_FLAG_FORCE_REFRESH,
    CLI_FLAG_NO_LLM,
    has_cli_flag,
)
from job_hunter_agent.user_settings import get_workspace_minimum_score


@dataclass
class ScrapeRunContext:
    profile: dict[str, Any]

    search_settings: dict[str, Any]

    dashboard_min_score: int

    configured_seek_max_pages: int

    configured_date_range: int

    sort_newest_first: bool

    playwright_viewport_width: int

    playwright_viewport_height: int

    playwright_selector_timeout: int

    seek_parallel_detail_workers: int

    applied_job_keys: set[str]

    hidden_job_keys: set[str]

    run_started_at: datetime

    run_iso: str

    previous_audit_rows: list[dict[str, Any]]

    previous_run_stats: dict[str, Any]

    llm_cache: dict[str, Any]

    job_history: dict[str, dict[str, Any]]

    enabled_sources: list[str]

    no_llm_mode: bool

    dashboard_debug_mode: bool

    reset_new_to_you: bool

    headless: bool = False

    force_source_refresh: bool = False

    source_cache_stats: dict[str, dict[str, Any]] | None = None


def build_scrape_run_context(argv: list[str] | None = None) -> ScrapeRunContext:

    active_argv = argv if argv is not None else sys.argv

    profile = load_profile()

    search_settings = get_search_settings(profile)

    dashboard_min_score = get_workspace_minimum_score()

    configured_seek_max_pages = int(
        search_settings.get(KEY_SEEK_MAX_PAGES, DEFAULT_SEARCH_SETTINGS[KEY_SEEK_MAX_PAGES])
        or DEFAULT_SEARCH_SETTINGS[KEY_SEEK_MAX_PAGES]
    )

    configured_date_range = int(
        search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
        or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]
    )

    sort_newest_first = bool(
        search_settings.get(KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST])
    )

    playwright_viewport_width = int(
        search_settings.get(
            KEY_PLAYWRIGHT_VIEWPORT_WIDTH,
            DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH],
        )
        or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH]
    )

    playwright_viewport_height = int(
        search_settings.get(
            KEY_PLAYWRIGHT_VIEWPORT_HEIGHT,
            DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT],
        )
        or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT]
    )

    playwright_selector_timeout = int(
        search_settings.get(
            KEY_PLAYWRIGHT_SELECTOR_TIMEOUT,
            DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT],
        )
        or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT]
    )

    seek_parallel_detail_workers = max(
        1, int(DEFAULT_PLAYWRIGHT_SETTINGS.get(KEY_SEEK_PARALLEL_DETAIL_WORKERS, 3) or 3)
    )

    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)

    run_started_at = datetime.now().astimezone()

    run_iso = run_started_at.isoformat(timespec="seconds")

    write_run_attempt(run_started_at)

    globally_enabled_sources = set(get_globally_enabled_sources())
    profile_enabled_sources = [s.lower().strip() for s in (profile.get("enabled_sources") or [])]
    enabled_sources = [
        source for source in profile_enabled_sources if source and source in globally_enabled_sources
    ]

    return ScrapeRunContext(
        profile=profile,
        search_settings=search_settings,
        dashboard_min_score=dashboard_min_score,
        configured_seek_max_pages=configured_seek_max_pages,
        configured_date_range=configured_date_range,
        sort_newest_first=sort_newest_first,
        playwright_viewport_width=playwright_viewport_width,
        playwright_viewport_height=playwright_viewport_height,
        playwright_selector_timeout=playwright_selector_timeout,
        seek_parallel_detail_workers=seek_parallel_detail_workers,
        applied_job_keys=applied_job_keys,
        hidden_job_keys=hidden_job_keys,
        run_started_at=run_started_at,
        run_iso=run_iso,
        previous_audit_rows=load_audit_rows(),
        previous_run_stats=load_run_stats(),
        llm_cache=load_llm_cache(),
        job_history=load_job_history(),
        enabled_sources=enabled_sources,
        no_llm_mode=has_cli_flag(active_argv, CLI_FLAG_NO_LLM),
        dashboard_debug_mode=has_cli_flag(active_argv, CLI_FLAG_DEBUG),
        reset_new_to_you=TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING,
        force_source_refresh=has_cli_flag(active_argv, CLI_FLAG_FORCE_REFRESH),
    )
