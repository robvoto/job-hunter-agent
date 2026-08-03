"""Helpers for scrape finalize."""

from __future__ import annotations

import logging
from datetime import datetime

from job_hunter_agent import workspace_service
from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.logging_utils import (
    format_log_block,
    get_human_logger,
    render_board_final_block,
)

logger = logging.getLogger(__name__)

from job_hunter_agent.io_utils import (
    load_ui_labels,
    save_job_history,
    save_llm_cache,
    prune_llm_cache_for_current_profile,
    write_debug_json,
    write_review_data,
    write_run_stats,
)
from job_hunter_agent.job_identity import deduplicate_across_sources
from job_hunter_agent.llm_review_state import has_complete_llm_keep_data
from job_hunter_agent.paths import OUTPUT_DIR, get_workspace_results_path
from job_hunter_agent.posting_utils import parse_timestamp
from job_hunter_agent.review_insights import build_review_data
from job_hunter_agent.run_context import ScrapeRunContext
from job_hunter_agent.run_control import run_stop_requested, set_run_progress_state
from job_hunter_agent.source_registry import get_source_display_label
from job_hunter_agent.system_warnings import (
    make_system_warning_fingerprint,
    record_system_warning,
)

NO_FRESH_CARDS_ERROR = "No fresh cards were captured in this run."
RUN_SUMMARY_PATH = OUTPUT_DIR / "last_run_summary.txt"


def _load_workspace_pool() -> list[dict]:

    import json as _json

    from job_hunter_agent.database import db_conn
    from job_hunter_agent.paths import get_active_user_id

    user_id = get_active_user_id()

    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM workspace_pool WHERE user_id = ?", (user_id,)
        ).fetchone()

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


def _run_summary_labels() -> dict[str, str]:
    labels = load_ui_labels().get("run_summary_labels")
    if not isinstance(labels, dict):
        raise ValueError("ui_labels.json is missing run_summary_labels")
    required = (
        "reviewed_keep_candidates",
        "visible_shortlist",
        "below_minimum_score",
    )
    missing = [key for key in required if not str(labels.get(key) or "").strip()]
    if missing:
        raise ValueError(
            f"ui_labels.json is missing run_summary_labels values: {', '.join(missing)}"
        )
    return {key: str(labels[key]).strip() for key in required}


def _count_below_workspace_minimum(
    records: list[dict], profile: dict, workspace_minimum_score: int
) -> int:
    return sum(
        1
        for record in records
        if has_complete_llm_keep_data(record)
        if workspace_service.fit_score_displayed(record, profile) < workspace_minimum_score
    )


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
_DETAIL_ERROR_CODES = frozenset(
    {
        "NO_DETAILS",
        "DETAILS_CHALLENGE_PAGE",
        "DETAILS_BLOCKED_PAGE",
        "DETAILS_NAVIGATION_ERROR",
        "NO_DESCRIPTION_TRUST",
    }
)


def _derive_run_summary_metrics(audit_rows: list[dict]) -> dict[str, int | dict[str, int]]:
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

    return {
        "source_counts": source_counts,
        "title_rejected": title_rejected,
        "onet_far_rejected": onet_far_rejected,
        "card_rejected": card_rejected,
        "detail_fetch_errors": detail_fetch_errors,
        "llm_calls": llm_calls,
        "llm_errors": llm_errors,
        "llm_cache_hits": llm_cache_hits,
        "final_review": final_review,
    }


def _build_source_breakdown(
    enabled_sources: list[str] | tuple[str, ...] | None,
    audit_rows: list[dict],
) -> list[dict[str, int | str]]:
    source_metrics: dict[str, dict[str, object]] = {}

    for source in enabled_sources or []:
        source_key = str(source or "").strip().lower()
        if not source_key or source_key in source_metrics:
            continue
        source_metrics[source_key] = {
            "source": get_source_display_label(source_key).upper(),
            "seen": 0,
            "read": 0,
            "pages": set(),
            "kept": 0,
            "rejected": 0,
        }

    for row in audit_rows:
        source_key = str(row.get("source") or "unknown").strip().lower()
        if source_key not in source_metrics:
            source_metrics[source_key] = {
                "source": get_source_display_label(source_key).upper(),
                "seen": 0,
                "read": 0,
                "pages": set(),
                "kept": 0,
                "rejected": 0,
            }
        source_metrics[source_key]["seen"] += 1
        if _audit_row_has_details(row):
            source_metrics[source_key]["read"] += 1
        page_num = row.get("page")
        if page_num is not None:
            page_marker = (
                str(row.get("search_location") or "Unknown"),
                int(page_num),
            )
            source_metrics[source_key]["pages"].add(page_marker)
        decision = str(row.get("decision") or "").strip().upper()
        if decision == "KEEP":
            source_metrics[source_key]["kept"] += 1
        elif decision in {"REJECT", "FILTERED"}:
            source_metrics[source_key]["rejected"] += 1

    return [
        {
            "source": str(metrics["source"]),
            "seen": int(metrics["seen"]),
            "read": int(metrics["read"]),
            "pages": len(metrics["pages"]),
            "kept": int(metrics["kept"]),
            "rejected": int(metrics["rejected"]),
        }
        for metrics in source_metrics.values()
    ]


def _log_source_final_stats(run_stats: dict) -> None:
    source_breakdown = run_stats.get("source_breakdown") or []
    human_logger = get_human_logger()
    for item in source_breakdown:
        source_name = str(item.get("source") or "UNKNOWN").strip().upper()
        human_logger.info(
            render_board_final_block(
                source_name,
                seen=int(item.get("seen", 0) or 0),
                read=int(item.get("read", 0) or 0),
                pages=int(item.get("pages", 0) or 0),
                kept=int(item.get("kept", 0) or 0),
                rejected=int(item.get("rejected", 0) or 0),
            )
        )


def _log_run_summary(run_stats: dict, audit_rows: list[dict]) -> None:
    metrics = _derive_run_summary_metrics(audit_rows)

    elapsed_seconds = 0
    try:
        started = parse_timestamp(str(run_stats.get("run_started_at") or ""))
        finished = parse_timestamp(str(run_stats.get("run_finished_at") or ""))
        if started and finished:
            elapsed_seconds = int((finished - started).total_seconds())
    except Exception:
        pass

    logger.info(
        format_log_block(
            "PIPELINE][RUN_SUMMARY",
            {
                "run_id": str(run_stats.get("last_run_attempt_at") or ""),
                "source_counts": metrics["source_counts"],
                "cards_seen": run_stats.get("cards_seen", 0),
                "title_rejected": metrics["title_rejected"],
                "onet_far_rejected": metrics["onet_far_rejected"],
                "card_rejected": metrics["card_rejected"],
                "detail_fetches": run_stats.get("cards_read", run_stats.get("detail_fetches", 0)),
                "detail_fetch_errors": metrics["detail_fetch_errors"],
                "llm_calls": metrics["llm_calls"],
                "llm_errors": metrics["llm_errors"],
                "llm_cache_hits": metrics["llm_cache_hits"],
                "llm_truncations": run_stats.get("llm_truncation_count", 0),
                "final_keep": run_stats.get("kept_count", 0),
                "final_review": metrics["final_review"],
                "final_reject": run_stats.get("rejected_count", 0),
                "elapsed_seconds": elapsed_seconds,
            },
        )
    )


def _print_run_summary(run_stats: dict) -> None:
    import sys
    
    run_id = str(run_stats.get("last_run_attempt_at") or "").strip()
    source_breakdown = run_stats.get("source_breakdown") or []
    
    # Calculate pages from source_breakdown if not explicitly set
    pages = run_stats.get("page_count", 0)
    if pages == 0 and source_breakdown:
        pages = sum(item.get("pages", 0) for item in source_breakdown)
    
    seen = run_stats.get("cards_seen", 0)
    read = run_stats.get("cards_read", run_stats.get("detail_fetches", 0))
    kept = run_stats.get("kept_count", 0)
    visible_shortlist = run_stats.get("visible_shortlist_count")
    below_minimum_score = run_stats.get("below_minimum_score_count")
    rejected = run_stats.get("rejected_count", 0)
    flagged = run_stats.get("cards_with_flags_count", 0)
    onet_far_rejected = int(run_stats.get("onet_far_rejected", 0) or 0)
    llm_cost = float(run_stats.get("llm_total_cost_usd", 0.0) or 0.0)
    llm_truncations = int(run_stats.get("llm_truncation_count", 0) or 0)
    duration = _format_duration(run_stats)

    bar = "=" * 52
    lines = [f"\n{bar}", "  Run complete", f"  Pages read: {pages}"]
    if run_id:
        lines.append(f"  Run ID:     {run_id}")
    lines.append(f"  Jobs seen:  {seen}  →  descriptions read: {read}  |  rejected: {rejected}")
    if visible_shortlist is not None and below_minimum_score is not None:
        labels = _run_summary_labels()
        lines.append(f"  {labels['reviewed_keep_candidates']}: {kept}")
        lines.append(f"  {labels['visible_shortlist']}: {visible_shortlist}")
        lines.append(f"  {labels['below_minimum_score']}: {below_minimum_score}")
    lines.append(f"  O*NET rejects: {onet_far_rejected}")
    if source_breakdown:
        lines.append("  Final stats by platform:")
        for item in source_breakdown:
            source_name = str(item.get("source") or "unknown").strip().upper()
            seen_count = item.get("seen", 0)
            read_count = item.get("read", 0)
            pages_count = item.get("pages", 0)
            kept_count = item.get("kept", 0)
            rejected_count = item.get("rejected", 0)
            lines.append(
                f"    - {source_name}: seen={seen_count} read={read_count} pages={pages_count} reviewed_keep_candidates={kept_count} rejected={rejected_count}"
            )
    if flagged:
        lines.append(f"  Flagged:    {flagged}  (review suggestions available)")
    lines.append(f"  Total LLM cost: ${llm_cost:.4f}")
    lines.append(f"  LLM truncations: {llm_truncations}")
    if duration:
        lines.append(f"  Duration:   {duration}")
    flags = _format_issue_flag_summary(run_stats)
    if flags.strip():
        lines.append(f"  Flags:     {flags}")
    errors = [str(item).strip() for item in run_stats.get("errors", []) if str(item).strip()]
    if run_stats.get("last_run_error"):
        errors.append(str(run_stats.get("last_run_error")).strip())
    if errors:
        lines.append("  Errors:")
        for error in errors:
            lines.append(f"    - {error}")
    warnings = [str(item).strip() for item in run_stats.get("warnings", []) if str(item).strip()]
    if warnings:
        lines.append("  Warnings:")
        for warning in warnings:
            lines.append(f"    - {warning}")
    if DEBUG_MODE:
        lines.append(
            f"  (debug) pages_read={pages} cards_seen={seen} cards_read={read} kept={kept} rejected={rejected} flags={flagged} truncations={llm_truncations} cost=${llm_cost:.6f}"
        )
    lines.append(bar)
    summary_text = "\n".join(lines)
    RUN_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_SUMMARY_PATH.write_text(summary_text + "\n", encoding="utf-8")
    logger.info(
        "[RUN_SUMMARY] run_id=%s pages=%s seen=%s read=%s reviewed_keep_candidates=%s "
        "visible_shortlist=%s below_minimum_score=%s rejected=%s summary_path=%s",
        run_id or "(none)",
        pages,
        seen,
        read,
        kept,
        visible_shortlist,
        below_minimum_score,
        rejected,
        RUN_SUMMARY_PATH,
    )
    
    # Print to stderr with visual markers so it stands out
    marker = "\n" + ("★" * 60) + "\n"
    sys.stderr.write(marker + summary_text + "\n" + ("★" * 60) + "\n")
    sys.stderr.flush()


def _record_run_stats_warnings(run_stats: dict) -> None:
    warnings = [str(item).strip() for item in run_stats.get("warnings", []) if str(item).strip()]
    if not warnings:
        return
    run_id = str(run_stats.get("last_run_attempt_at") or "").strip()
    for warning in warnings:
        record_system_warning(
            severity="warning",
            category="run_stats_warning",
            source="run_stats",
            message=warning,
            fingerprint=make_system_warning_fingerprint("run_stats_warning", warning),
            run_id=run_id,
            context={
                "warning": warning,
            },
        )


def _audit_row_has_details(row: dict) -> bool:
    return int(row.get("details_length") or 0) > 0


def finalize_scrape_run(
    context: ScrapeRunContext,
    kept_records: list[dict],
    audit_rows: list[dict],
    skill_observations: list[dict],
) -> str:
    """Persist outputs, rebuild the workspace, and publish indeterminate internal stages."""

    from job_hunter_agent.logging_utils import get_human_logger
    from job_hunter_agent.llm_gate import get_session_cost_usd
    from job_hunter_agent.source_learning import get_llm_truncation_count

    human_logger = get_human_logger()
    # Internal stages have no reliable total, so they remain indeterminate.
    set_run_progress_state(
        "Finalising results\nSource collection complete",
        stage="finalising",
        source="generic",
        headline="Finalising results",
        detail="Source collection complete",
        determinate=False,
    )
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
            "llm_truncation_count": get_llm_truncation_count(),
            "last_run_attempt_at": context.run_iso,
        }

        if not run_was_stopped:
            run_stats["last_run_error"] = NO_FRESH_CARDS_ERROR
        run_stats["source_breakdown"] = _build_source_breakdown(context.enabled_sources, [])

        _log_run_summary(run_stats, [])
        _log_source_final_stats(run_stats)
        _print_run_summary(run_stats)

        workspace_service.render_html(
            get_workspace_results_path(),
            pool
            if pool
            else workspace_service.load_last_kept_records(
                context.previous_audit_rows,
                deduplicate_across_sources_fn=deduplicate_across_sources,
            ),
            parse_timestamp(context.previous_run_stats.get("run_started_at"))
            or context.run_started_at,
            context.configured_date_range,
            context.sort_newest_first,
            run_stats,
            context.job_history,
            context.applied_job_keys,
            context.hidden_job_keys,
            datetime.now().astimezone(),
            context.previous_audit_rows,
            context.dashboard_debug_mode,
        )

        context.llm_cache, pruned_llm_cache_count = prune_llm_cache_for_current_profile(
            context.llm_cache
        )
        if pruned_llm_cache_count:
            logger.info(
                "[LLM][CACHE] pruned %d stale cache entries for the active profile fingerprint",
                pruned_llm_cache_count,
            )

        save_llm_cache(context.llm_cache)

        save_job_history(context.job_history)

        if run_was_stopped:
            logger.info("Run stopped before any fresh cards were captured.")
        else:
            logger.error("[RUN][ERROR] %s", NO_FRESH_CARDS_ERROR)

        write_review_data(build_review_data(context.previous_audit_rows, [], context.profile))

        _record_run_stats_warnings(run_stats)
        write_run_stats(run_stats)

        workspace_path = get_workspace_results_path()

        logger.info("The previous workspace state was preserved.")

        logger.info("Workspace results preserved at %s", workspace_path)

        return str(workspace_path)

    merged_pool = _merge_into_pool(pool, kept_records)
    set_run_progress_state(
        "Saving merged results\nPreparing workspace data",
        stage="saving",
        source="generic",
        headline="Saving merged results",
        detail="Preparing workspace data",
        determinate=False,
    )

    _save_workspace_pool(merged_pool)

    new_count = len(merged_pool) - len(pool)

    logger.info(
        "[Pool] %d existing + %d new = %d total records", len(pool), new_count, len(merged_pool)
    )

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
    run_stats["llm_truncation_count"] = get_llm_truncation_count()
    run_stats.update(_derive_run_summary_metrics(audit_rows))

    run_stats["pool_was_empty_before_run"] = pool_was_empty

    if no_fresh_cards:
        run_stats["last_run_error"] = NO_FRESH_CARDS_ERROR

    run_stats["source_breakdown"] = _build_source_breakdown(context.enabled_sources, audit_rows)

    workspace_records = workspace_service.build_workspace_record_sets(
        merged_pool,
        context.job_history,
        context.applied_job_keys,
        context.hidden_job_keys,
        context.run_started_at,
        context.profile,
        context.dashboard_min_score,
    )
    set_run_progress_state(
        "Building workspace\nRendering refreshed results",
        stage="finalising",
        source="generic",
        headline="Building workspace",
        detail="Rendering refreshed results",
        determinate=False,
    )

    visible_current_records = len(workspace_records.get("current_records", []))
    run_stats["visible_shortlist_count"] = len(workspace_records.get("shortlist_records", []))
    run_stats["below_minimum_score_count"] = _count_below_workspace_minimum(
        kept_records,
        context.profile,
        context.dashboard_min_score,
    )
    if kept_records and visible_current_records == 0 and not context.dashboard_debug_mode:
        human_logger.info(
            "Shortlist result: 0 visible jobs. %d kept job(s) were hidden because they did not meet the workspace minimum score of %d.",
            len(kept_records),
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
        workspace_records=workspace_records,
    )

    context.llm_cache, pruned_llm_cache_count = prune_llm_cache_for_current_profile(
        context.llm_cache
    )
    if pruned_llm_cache_count:
        logger.info(
            "[LLM][CACHE] pruned %d stale cache entries for the active profile fingerprint",
            pruned_llm_cache_count,
        )

    save_llm_cache(context.llm_cache)

    save_job_history(context.job_history)

    write_debug_json(audit_rows)

    _record_run_stats_warnings(run_stats)
    write_run_stats(run_stats)

    set_run_progress_state(
        "Saving run summary\nWriting review data",
        stage="saving",
        source="generic",
        headline="Saving run summary",
        detail="Writing review data",
        determinate=False,
    )
    write_review_data(build_review_data(audit_rows, skill_observations, context.profile))

    _log_run_summary(run_stats, audit_rows)
    _log_source_final_stats(run_stats)
    _print_run_summary(run_stats)

    if no_fresh_cards:
        logger.error("[RUN][ERROR] %s", NO_FRESH_CARDS_ERROR)

    logger.info(
        "  workspace_visible=%s",
        _format_workspace_counts(workspace_records, context.dashboard_min_score),
    )

    logger.info("Saved %d jobs to %s", len(kept_records), workspace_path)

    logger.info("Saved %d audit rows to DB", len(audit_rows))

    logger.info("Saved run stats to DB")

    logger.info("Saved review data to DB")

    logger.info("Saved per-job history snapshots for %d jobs to DB", len(context.job_history))

    return str(workspace_path)
