"""Helpers for workspace rebuild service."""

from __future__ import annotations

from datetime import datetime

from job_hunter_agent import workspace_service
from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_DATE_RANGE_DAYS,
    KEY_SORT_NEWEST_FIRST,
)
from job_hunter_agent.io_utils import (
    configure_console_output,
    load_audit_rows,
    load_job_history,
    load_run_stats,
    write_run_stats,
)
from job_hunter_agent.paths import get_workspace_results_path
from job_hunter_agent.posting_utils import get_manual_skip_sets, parse_timestamp
from job_hunter_agent.profile_store import get_search_settings, load_profile
from job_hunter_agent.user_context import get_user_id_for_runtime


def rebuild_workspace_results(
    reason: str = "Manual --rebuild-workspace command",
) -> str:

    configure_console_output()

    get_user_id_for_runtime()

    profile = load_profile()

    search_settings = get_search_settings(profile)

    configured_date_range = int(
        search_settings.get(KEY_DATE_RANGE_DAYS, DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS])
        or DEFAULT_SEARCH_SETTINGS[KEY_DATE_RANGE_DAYS]
    )

    sort_newest_first = bool(
        search_settings.get(KEY_SORT_NEWEST_FIRST, DEFAULT_SEARCH_SETTINGS[KEY_SORT_NEWEST_FIRST])
    )

    run_stats = load_run_stats()

    run_started_at = parse_timestamp(run_stats.get("run_started_at")) or datetime.now().astimezone()
    run_finished_at = parse_timestamp(run_stats.get("run_finished_at")) or datetime.now().astimezone()

    reference_time = datetime.now().astimezone()

    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)

    job_history = load_job_history()

    kept_records = workspace_service.load_last_kept_records()
    saved_workspace_records = workspace_service.load_saved_workspace_pool()
    render_records = saved_workspace_records or kept_records
    audit_rows = load_audit_rows()

    if audit_rows:
        refreshed_run_stats = workspace_service.build_run_stats(
            audit_rows,
            kept_records,
            run_started_at,
            run_finished_at,
            configured_date_range,
            sort_newest_first,
            int(run_stats.get("seek_max_pages") or 1),
        )
        run_stats = {**run_stats, **refreshed_run_stats}
        write_run_stats(run_stats)

    print(
        f"[WORKSPACE REBUILD] {reason} "
        f"(records={len(render_records)}, history={len(job_history)}, "
        f"applied={len(applied_job_keys)}, hidden={len(hidden_job_keys)})"
    )

    workspace_path = get_workspace_results_path()

    workspace_service.render_html(
        workspace_path,
        render_records,
        run_started_at,
        configured_date_range,
        sort_newest_first,
        run_stats,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
    )

    print(f"Workspace results rebuilt at {workspace_path}")

    return str(workspace_path)
