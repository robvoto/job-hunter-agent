from __future__ import annotations

from datetime import datetime

from job_hunter_agent import workspace_service
from job_hunter_agent.job_identity import deduplicate_across_sources
from job_hunter_agent.paths import (
    get_audit_records_path,
    get_job_history_path,
    get_review_data_path,
    get_run_stats_path,
    get_workspace_pool_path,
    get_workspace_results_path,
)
from job_hunter_agent.io_utils import (
    load_json_list,
    save_job_history,
    save_llm_cache,
    write_debug_json,
    write_review_data,
    write_run_stats,
)
from job_hunter_agent.review_insights import build_review_data
from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.posting_utils import parse_timestamp


def _load_workspace_pool() -> list[dict]:
    pool_path = get_workspace_pool_path()
    if not pool_path.exists():
        return []
    return load_json_list(pool_path)


def _save_workspace_pool(records: list[dict]) -> None:
    import json
    pool_path = get_workspace_pool_path()
    pool_path.parent.mkdir(parents=True, exist_ok=True)
    pool_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _merge_into_pool(pool: list[dict], new_records: list[dict]) -> list[dict]:
    existing_keys = {str(r.get("job_key") or "") for r in pool if r.get("job_key")}
    added = [r for r in new_records if str(r.get("job_key") or "") and str(r.get("job_key")) not in existing_keys]
    return pool + added


def _format_issue_flag_summary(run_stats: dict) -> str:
    flags = run_stats.get("issue_flag_summary") or []
    if not flags:
        return "none"
    flag_meanings = {
        "reviewed_signal_matches": "reviewed signal matches on the card",
        "soft_risk_reasons": "soft risk notes",
        "missing_evidence": "missing or incomplete evidence",
        "hard_block_reasons": "explicit blocker notes",
        "job_quality_signals": "job quality warning notes",
    }
    parts = [
        f"- {item.get('flag', 'unknown')}={item.get('count', 0)}"
        f" ({flag_meanings.get(item.get('flag', 'unknown'), 'flagged notes')})"
        for item in flags[:5]
    ]
    return "\n" + "\n".join(parts)


def _format_workspace_counts(workspace_records: dict[str, list[dict]], minimum_score: int) -> str:
    return (
        f"shortlist={len(workspace_records.get('shortlist_records', []))} "
        f"(current={len(workspace_records.get('current_records', []))}, "
        f"archive={len(workspace_records.get('archive_records', []))}, "
        f"applied={len(workspace_records.get('applied_records', []))}, "
        f"hidden={len(workspace_records.get('hidden_records', []))}, "
        f"min_score={minimum_score})"
    )


def _print_run_summary(run_stats: dict) -> None:
    print("\nRun summary:")
    print(f"  pages={run_stats.get('page_count', 0)}")
    print(f"  cards_seen={run_stats.get('cards_seen', 0)}")
    print(f"  cards_read={run_stats.get('cards_read', run_stats.get('detail_fetches', 0))}")
    print(f"  kept={run_stats.get('kept_count', 0)}")
    print(f"  rejected={run_stats.get('rejected_count', 0)}")
    print(
        "  cards_with_flags="
        f"{run_stats.get('cards_with_flags_count', 0)} "
        "(kept cards can still count if they carry review flags)"
    )
    print(f"  total_llm_cost=${float(run_stats.get('llm_total_cost_usd', 0.0) or 0.0):.6f}")
    print(f"  flag_breakdown:{_format_issue_flag_summary(run_stats)}")


def finalize_scrape_run(
    context: ScrapeRunContext,
    kept_records: list[dict],
    audit_rows: list[dict],
    skill_observations: list[dict],
) -> str:
    """Persist scrape outputs and rebuild the workspace HTML."""
    from job_hunter_agent.llm_gate import get_session_cost_usd

    kept_records = deduplicate_across_sources(kept_records)
    pool = _load_workspace_pool()
    pool_was_empty = len(pool) == 0

    if not audit_rows and context.previous_audit_rows:
        run_stats = {
            "page_count": 0,
            "cards_seen": 0,
            "cards_read": 0,
            "kept_count": 0,
            "rejected_count": 0,
            "cards_with_flags_count": 0,
            "issue_flag_summary": [],
            "llm_total_cost_usd": round(get_session_cost_usd(), 6),
        }
        _print_run_summary(run_stats)
        workspace_service.render_html(
            get_workspace_results_path(),
            pool if pool else workspace_service.load_last_kept_records(
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
            context.previous_audit_rows,
            context.dashboard_debug_mode,
        )
        save_llm_cache(context.llm_cache)
        save_job_history(context.job_history)
        workspace_path = get_workspace_results_path()
        print("\nNo fresh cards were captured in this run, so the previous workspace state was preserved.")
        print(f"Workspace results preserved at {workspace_path}")
        return str(workspace_path)

    merged_pool = _merge_into_pool(pool, kept_records)
    _save_workspace_pool(merged_pool)
    new_count = len(merged_pool) - len(pool)
    print(f"[Pool] {len(pool)} existing + {new_count} new = {len(merged_pool)} total records")

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
    run_stats["llm_total_cost_usd"] = round(get_session_cost_usd(), 6)
    run_stats["pool_was_empty_before_run"] = pool_was_empty
    workspace_records = workspace_service.build_workspace_record_sets(
        merged_pool,
        context.job_history,
        context.applied_job_keys,
        context.hidden_job_keys,
        context.run_started_at,
        context.profile,
        context.dashboard_min_score,
    )

    workspace_path = get_workspace_results_path()
    workspace_service.render_html(
        workspace_path,
        merged_pool,
        context.run_started_at,
        context.configured_date_range,
        context.sort_newest_first,
        run_stats,
        context.job_history,
        context.applied_job_keys,
        context.hidden_job_keys,
        context.run_started_at,
        audit_rows,
        context.dashboard_debug_mode,
    )
    save_llm_cache(context.llm_cache)
    save_job_history(context.job_history)
    write_debug_json(audit_rows)
    write_run_stats(run_stats)
    write_review_data(build_review_data(audit_rows, skill_observations, context.profile))
    _print_run_summary(run_stats)
    print(f"  workspace_visible={_format_workspace_counts(workspace_records, context.dashboard_min_score)}")
    print(f"\nSaved {len(kept_records)} jobs to {workspace_path}")
    print(f"Saved {len(audit_rows)} audit rows to {get_audit_records_path()}")
    print(f"Saved run stats to {get_run_stats_path()}")
    print(f"Saved review data to {get_review_data_path()}")
    print(f"Saved history for {len(context.job_history)} jobs to {get_job_history_path()}")
    return str(workspace_path)
