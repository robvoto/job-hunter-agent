from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sys
from typing import Any

from job_hunter_agent.global_settings import (
    DEFAULT_PLAYWRIGHT_SETTINGS,
    DEFAULT_SEARCH_SETTINGS,
    KEY_DATE_RANGE_DAYS,
    KEY_ENFORCE_POSTED_AGE_LIMIT,
    KEY_PLAYWRIGHT_SELECTOR_TIMEOUT,
    KEY_PLAYWRIGHT_VIEWPORT_HEIGHT,
    KEY_PLAYWRIGHT_VIEWPORT_WIDTH,
    KEY_SEEK_MAX_PAGES,
    KEY_SORT_NEWEST_FIRST,
)
from job_hunter_agent.history import TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING
from job_hunter_agent.io_utils import (
    load_json_dict,
    load_json_list,
    load_job_history,
    load_llm_cache,
    write_run_attempt,
)
from job_hunter_agent.paths import (
    get_audit_records_path,
    get_run_stats_path,
)
from job_hunter_agent.profile_store import get_search_settings, load_profile
from job_hunter_agent.posting_utils import get_manual_skip_sets
from job_hunter_agent.runtime_helpers import (
    CLI_FLAG_DEBUG,
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
    enforce_posted_age_limit: bool
    sort_newest_first: bool
    playwright_viewport_width: int
    playwright_viewport_height: int
    playwright_selector_timeout: int
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


def build_scrape_run_context(argv: list[str] | None = None) -> ScrapeRunContext:
    active_argv = argv if argv is not None else sys.argv
    profile = load_profile()
    search_settings = get_search_settings(profile)
    dashboard_min_score = get_workspace_minimum_score()
    configured_seek_max_pages = int(search_settings.get(KEY_SEEK_MAX_PAGES, DEFAULT_SEARCH_SETTINGS[KEY_SEEK_MAX_PAGES]) or DEFAULT_SEARCH_SETTINGS[KEY_SEEK_MAX_PAGES])
    configured_date_range = int(search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]) or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
    enforce_posted_age_limit = bool(search_settings.get(KEY_ENFORCE_POSTED_AGE_LIMIT, DEFAULT_SEARCH_SETTINGS[KEY_ENFORCE_POSTED_AGE_LIMIT]))
    sort_newest_first = bool(search_settings.get(KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST]))
    playwright_viewport_width = int(search_settings.get(KEY_PLAYWRIGHT_VIEWPORT_WIDTH, DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH]) or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_WIDTH])
    playwright_viewport_height = int(search_settings.get(KEY_PLAYWRIGHT_VIEWPORT_HEIGHT, DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT]) or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_VIEWPORT_HEIGHT])
    playwright_selector_timeout = int(search_settings.get(KEY_PLAYWRIGHT_SELECTOR_TIMEOUT, DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT]) or DEFAULT_PLAYWRIGHT_SETTINGS[KEY_PLAYWRIGHT_SELECTOR_TIMEOUT])
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)

    run_started_at = datetime.now().astimezone()
    run_iso = run_started_at.isoformat(timespec="seconds")
    write_run_attempt(run_started_at)

    return ScrapeRunContext(
        profile=profile,
        search_settings=search_settings,
        dashboard_min_score=dashboard_min_score,
        configured_seek_max_pages=configured_seek_max_pages,
        configured_date_range=configured_date_range,
        enforce_posted_age_limit=enforce_posted_age_limit,
        sort_newest_first=sort_newest_first,
        playwright_viewport_width=playwright_viewport_width,
        playwright_viewport_height=playwright_viewport_height,
        playwright_selector_timeout=playwright_selector_timeout,
        applied_job_keys=applied_job_keys,
        hidden_job_keys=hidden_job_keys,
        run_started_at=run_started_at,
        run_iso=run_iso,
        previous_audit_rows=load_json_list(get_audit_records_path()),
        previous_run_stats=load_json_dict(get_run_stats_path()),
        llm_cache=load_llm_cache(),
        job_history=load_job_history(),
        enabled_sources=[s.lower().strip() for s in (profile.get("enabled_sources") or [])],
        no_llm_mode=has_cli_flag(active_argv, CLI_FLAG_NO_LLM),
        dashboard_debug_mode=has_cli_flag(active_argv, CLI_FLAG_DEBUG),
        reset_new_to_you=TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING,
    )
