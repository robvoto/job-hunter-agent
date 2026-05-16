from __future__ import annotations

from datetime import datetime

from job_hunter_agent import workspace_service
from job_hunter_agent.job_identity import deduplicate_across_sources
from job_hunter_agent.paths import (
    get_audit_records_path,
    get_job_history_path,
    get_review_data_path,
    get_run_stats_path,
    get_workspace_results_path,
)
from job_hunter_agent.io_utils import (
    save_job_history,
    save_llm_cache,
    write_debug_json,
    write_review_data,
    write_run_stats,
)
from job_hunter_agent.review_insights import build_review_data
from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.posting_utils import parse_timestamp


def finalize_scrape_run(
    context: ScrapeRunContext,
    kept_records: list[dict],
    audit_rows: list[dict],
    skill_observations: list[dict],
) -> str:
    """Persist scrape outputs and rebuild the workspace HTML."""
    kept_records = deduplicate_across_sources(kept_records)

    if not audit_rows and context.previous_audit_rows:
        workspace_service.render_html(
            get_workspace_results_path(),
            workspace_service.load_last_kept_records(
                context.previous_audit_rows,
                deduplicate_across_sources_fn=deduplicate_across_sources,
            ),
            parse_timestamp(context.previous_run_stats.get("run_started_at")) or context.run_started_at,
            context.configured_date_range,
            context.sort_newest_first,
            context.previous_run_stats or {},
            context.job_history,
            context.applied_job_keys,
            context.hidden_job_keys,
            datetime.now().astimezone(),
        )
        save_llm_cache(context.llm_cache)
        save_job_history(context.job_history)
        workspace_path = get_workspace_results_path()
        print("\nNo fresh cards were captured in this run, so the previous workspace state was preserved.")
        print(f"Workspace results preserved at {workspace_path}")
        return str(workspace_path)

    run_finished_at = datetime.now().astimezone()
    run_stats = workspace_service.build_run_stats(
        audit_rows,
        kept_records,
        context.run_started_at,
        run_finished_at,
        context.configured_date_range,
        context.sort_newest_first,
        context.configured_seek_max_pages,
    )
    run_stats["last_run_attempt_at"] = context.run_iso

    workspace_path = get_workspace_results_path()
    workspace_service.render_html(
        workspace_path,
        kept_records,
        context.run_started_at,
        context.configured_date_range,
        context.sort_newest_first,
        run_stats,
        context.job_history,
        context.applied_job_keys,
        context.hidden_job_keys,
        context.run_started_at,
    )
    save_llm_cache(context.llm_cache)
    save_job_history(context.job_history)
    write_debug_json(audit_rows)
    write_run_stats(run_stats)
    write_review_data(build_review_data(audit_rows, skill_observations, context.profile))
    print(f"\nSaved {len(kept_records)} jobs to {workspace_path}")
    print(f"Saved {len(audit_rows)} audit rows to {get_audit_records_path()}")
    print(f"Saved run stats to {get_run_stats_path()}")
    print(f"Saved review data to {get_review_data_path()}")
    print(f"Saved history for {len(context.job_history)} jobs to {get_job_history_path()}")
    return str(workspace_path)
