"""Helpers for workspace rebuild service."""

from __future__ import annotations

from datetime import datetime

from job_hunter_agent import workspace_service
from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.global_settings import (
    DEFAULT_SEARCH_SETTINGS,
    KEY_DATE_RANGE_DAYS,
    KEY_SORT_NEWEST_FIRST,
)
from job_hunter_agent.history import TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING
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

CONSOLE_BANNER_WIDTH = 60

WORKSPACE_DEBUG_MODE = DEBUG_MODE


def rebuild_workspace_results(
    reason: str = "Manual --rebuild-workspace command",
) -> str:

    configure_console_output()

    get_user_id_for_runtime()

    print("=" * CONSOLE_BANNER_WIDTH)

    print("  JOB HUNTER AGENT - WORKSPACE RESULTS REBUILD")

    print("=" * CONSOLE_BANNER_WIDTH)

    print(f"  Trigger            : {reason}")

    print("  Action             : re-render saved results only")

    print("  Fresh scrape       : NO")

    print("  AI review          : NO")

    print(f"  Debug mode         : {'ON (--debug)' if WORKSPACE_DEBUG_MODE else 'OFF'}")

    print(
        f"  Reset New To You   : {'YES (--reset-new-to-you)' if TREAT_ALL_JOBS_AS_NEW_TO_YOU_FOR_TESTING else 'NO'}"
    )

    print("=" * CONSOLE_BANNER_WIDTH)

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

    print(f"  Saved kept records : {len(kept_records)}")

    print(f"  Job history records: {len(job_history)}")

    print(f"  Applied keys       : {len(applied_job_keys)}")

    print(f"  Hidden keys        : {len(hidden_job_keys)}")

    print("=" * CONSOLE_BANNER_WIDTH)

    workspace_path = get_workspace_results_path()

    workspace_service.render_html(
        workspace_path,
        kept_records,
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
