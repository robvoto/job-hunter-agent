"""Helpers for scrape finalize."""



from __future__ import annotations

import logging


from datetime import datetime



from job_hunter_agent import workspace_service
from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.logging_utils import format_log_block

logger = logging.getLogger(__name__)

from job_hunter_agent.job_identity import deduplicate_across_sources

from job_hunter_agent.paths import get_workspace_results_path

from job_hunter_agent.io_utils import (

    save_job_history,

    save_llm_cache,

    write_debug_json,

    write_review_data,

    write_run_stats,

)

from job_hunter_agent.review_insights import build_review_data

from job_hunter_agent.run_context import ScrapeRunContext

from job_hunter_agent.run_control import run_stop_requested

from job_hunter_agent.posting_utils import parse_timestamp



NO_FRESH_CARDS_ERROR = "No fresh cards were captured in this run."





def _load_workspace_pool() -> list[dict]:

    import json as _json

    from job_hunter_agent.database import db_conn

    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()

    with db_conn() as conn:

        row = conn.execute("SELECT data FROM workspace_pool WHERE user_id = ?", (user_id,)).fetchone()

    if row is None:

        return []

    data = _json.loads(row["data"])

    return data if isinstance(data, list) else []





def _save_workspace_pool(records: list[dict]) -> None:

    import json as _json

    from job_hunter_agent.database import db_conn, ensure_user_row

    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()

    ensure_user_row(user_id)

    with db_conn() as conn:

        conn.execute(

            """INSERT INTO workspace_pool (user_id, data, updated_at)

            VALUES (?, ?, datetime('now'))

            ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at""",

            (user_id, _json.dumps(records, ensure_ascii=False)),

        )





def _merge_into_pool(pool: list[dict], new_records: list[dict]) -> list[dict]:
    frozen_score_keys = {
        "fit_score",
        "fit_score_breakdown",
        "fit_label",
        "fit_tone_class",
    }
    merged_by_key: dict[str, dict] = {}
    ordered_keys: list[str] = []

    for record in pool:
        job_key = str(record.get("job_key") or "").strip()
        if not job_key:
            continue
        merged_by_key[job_key] = dict(record)
        ordered_keys.append(job_key)

    for record in new_records:
        job_key = str(record.get("job_key") or "").strip()
        if not job_key:
            continue
        existing = merged_by_key.get(job_key)
        if existing is None:
            merged_by_key[job_key] = dict(record)
            ordered_keys.append(job_key)
            continue
        updated = dict(existing)
        updated.update(record)
        for key in frozen_score_keys:
            if key in existing:
                updated[key] = existing[key]
        merged_by_key[job_key] = updated

    return [merged_by_key[job_key] for job_key in ordered_keys]





def _format_issue_flag_summary(run_stats: dict) -> str:

    flags = run_stats.get("issue_flag_summary") or []

    if not flags:

        return "none"

    flag_meanings = {

        "reviewed_signal_matches": "reviewed signal matches on the card",

        "soft_risk_reasons": "soft risk notes",

        "missing_profile_support": "missing or incomplete profile support",

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





def _format_duration(run_stats: dict) -> str:
    try:
        started = parse_timestamp(str(run_stats.get("run_started_at") or ""))
        finished = parse_timestamp(str(run_stats.get("run_finished_at") or ""))
        if started and finished:
            secs = int((finished - started).total_seconds())
            if secs >= 60:
                return f"{secs // 60}m {secs % 60}s"
            return f"{secs}s"
    except Exception:
        pass
    return ""


_TITLE_REJECT_CODES = frozenset({"TITLE_NOT_TARGET", "TITLE_EMPTY", "TITLE_BAD_KEYWORD"})
_DETAIL_ERROR_CODES = frozenset({
    "NO_DETAILS", "DETAILS_CHALLENGE_PAGE", "DETAILS_BLOCKED_PAGE",
    "DETAILS_NAVIGATION_ERROR", "NO_DESCRIPTION_TRUST",
})


def _log_run_summary(run_stats: dict, audit_rows: list[dict]) -> None:
    source_counts: dict[str, int] = {}
    title_rejected = onet_far_rejected = card_rejected = detail_fetch_errors = 0
    llm_calls = llm_errors = llm_cache_hits = final_review = 0
    for row in audit_rows:
        src = str(row.get("source") or "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
        reason = str(row.get("reject_reason") or "")
        if reason.split(":")[0] in _TITLE_REJECT_CODES:
            title_rejected += 1
        if reason == "ONET_FAR_OCCUPATION":
            onet_far_rejected += 1
        if row.get("_obs_card_rejected"):
            card_rejected += 1
        if reason in _DETAIL_ERROR_CODES:
            detail_fetch_errors += 1
        if row.get("_obs_llm_called"):
            llm_calls += 1
        if row.get("_obs_llm_error"):
            llm_errors += 1
        if row.get("_obs_llm_cache_hit"):
            llm_cache_hits += 1
        if row.get("review_source"):
            final_review += 1

    elapsed_seconds = 0
    try:
        started = parse_timestamp(str(run_stats.get("run_started_at") or ""))
        finished = parse_timestamp(str(run_stats.get("run_finished_at") or ""))
        if started and finished:
            elapsed_seconds = int((finished - started).total_seconds())
    except Exception:
        pass

    logger.info(format_log_block("PIPELINE][RUN_SUMMARY", {
        "run_id": str(run_stats.get("last_run_attempt_at") or ""),
        "source_counts": source_counts,
        "cards_seen": run_stats.get("cards_seen", 0),
        "title_rejected": title_rejected,
        "onet_far_rejected": onet_far_rejected,
        "card_rejected": card_rejected,
        "detail_fetches": run_stats.get("cards_read", run_stats.get("detail_fetches", 0)),
        "detail_fetch_errors": detail_fetch_errors,
        "llm_calls": llm_calls,
        "llm_errors": llm_errors,
        "llm_cache_hits": llm_cache_hits,
        "final_keep": run_stats.get("kept_count", 0),
        "final_review": final_review,
        "final_reject": run_stats.get("rejected_count", 0),
        "elapsed_seconds": elapsed_seconds,
    }))


def _print_run_summary(run_stats: dict) -> None:
    pages = run_stats.get("page_count", 0)
    seen = run_stats.get("cards_seen", 0)
    read = run_stats.get("cards_read", run_stats.get("detail_fetches", 0))
    kept = run_stats.get("kept_count", 0)
    rejected = run_stats.get("rejected_count", 0)
    flagged = run_stats.get("cards_with_flags_count", 0)
    llm_cost = float(run_stats.get("llm_total_cost_usd", 0.0) or 0.0)
    duration = _format_duration(run_stats)

    bar = "=" * 52
    lines = [f"\n{bar}", "  Run complete", f"  Pages read: {pages}"]
    lines.append(f"  Jobs seen:  {seen}  →  descriptions read: {read}  →  kept: {kept}  |  rejected: {rejected}")
    if flagged:
        lines.append(f"  Flagged:    {flagged}  (review suggestions available)")
    lines.append(f"  Total LLM cost: ${llm_cost:.4f}")
    if duration:
        lines.append(f"  Duration:   {duration}")
    flags = _format_issue_flag_summary(run_stats)
    if flags.strip():
        lines.append(f"  Flags:     {flags}")
    if DEBUG_MODE:
        lines.append(f"  (debug) pages_read={pages} cards_seen={seen} cards_read={read} kept={kept} rejected={rejected} flags={flagged} cost=${llm_cost:.6f}")
    lines.append(bar)
    logger.info("\n".join(lines))





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

    no_fresh_cards = not audit_rows



    if no_fresh_cards and context.previous_audit_rows:
        run_was_stopped = run_stop_requested()

        run_stats = {

            "page_count": 0,

            "cards_seen": 0,

            "cards_read": 0,

            "kept_count": 0,

            "rejected_count": 0,

            "cards_with_flags_count": 0,

            "issue_flag_summary": [],

            "llm_total_cost_usd": round(get_session_cost_usd(), 6),

            "last_run_attempt_at": context.run_iso,

        }

        _log_run_summary(run_stats, [])
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

        if run_was_stopped:
            logger.info("Run stopped before any fresh cards were captured.")
        else:
            run_stats["last_run_error"] = NO_FRESH_CARDS_ERROR
            logger.error("[RUN][ERROR] %s", NO_FRESH_CARDS_ERROR)

        write_review_data(build_review_data(context.previous_audit_rows, [], context.profile))

        write_run_stats(run_stats)

        workspace_path = get_workspace_results_path()

        logger.info("The previous workspace state was preserved.")

        logger.info("Workspace results preserved at %s", workspace_path)

        return str(workspace_path)



    merged_pool = _merge_into_pool(pool, kept_records)

    _save_workspace_pool(merged_pool)

    new_count = len(merged_pool) - len(pool)

    logger.info("[Pool] %d existing + %d new = %d total records", len(pool), new_count, len(merged_pool))



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

    if no_fresh_cards:

        run_stats["last_run_error"] = NO_FRESH_CARDS_ERROR

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

    _log_run_summary(run_stats, audit_rows)
    _print_run_summary(run_stats)

    if no_fresh_cards:

        logger.error("[RUN][ERROR] %s", NO_FRESH_CARDS_ERROR)

    logger.info("  workspace_visible=%s", _format_workspace_counts(workspace_records, context.dashboard_min_score))

    logger.info("Saved %d jobs to %s", len(kept_records), workspace_path)

    logger.info("Saved %d audit rows to DB", len(audit_rows))

    logger.info("Saved run stats to DB")

    logger.info("Saved review data to DB")

    logger.info("Saved history for %d jobs to DB", len(context.job_history))

    return str(workspace_path)

