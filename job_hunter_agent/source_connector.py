"""
Main job-source connector and workspace builder.

Main goals:
- fetch current job listings from all enabled source implementations
- apply deterministic filtering and optional LLM fit review
- persist audit data, run stats, review insights, and workspace HTML

Notes:
- this file orchestrates individual source connectors (e.g. SEEK, LinkedIn)
- the normalized record shape is intended to be reusable for additional sources
"""

import logging
import sys

from job_hunter_agent.runtime_helpers import load_repo_dotenv

load_repo_dotenv()

from job_hunter_agent.profile_store import (
    load_profile,
    require_profile_ready_for_review,
)
from job_hunter_agent.run_control import (
    RunInterruptedError,
    begin_run_progress_scope,
    clear_run_progress,
    clear_run_stop_request,
    enable_step_through,
    end_run_progress_scope,
    run_control_scope_active,
    run_shutdown_requested,
    step_through_enabled,
)
from job_hunter_agent.runtime_helpers import (
    CLI_FLAG_DEBUG,
    CLI_FLAG_FORCE_REFRESH,
    CLI_FLAG_NO_LLM,
    CLI_FLAG_REBUILD_WORKSPACE,
    CLI_FLAG_STEP,
    has_cli_flag,
)

logger = logging.getLogger(__name__)

from job_hunter_agent.run_context import build_scrape_run_context
from job_hunter_agent.scrape_finalize import finalize_scrape_run
from job_hunter_agent.source_runner import run_enabled_sources
from job_hunter_agent.user_context import get_user_id_for_runtime
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results

NO_LLM_MODE = has_cli_flag(sys.argv, CLI_FLAG_NO_LLM)
WORKSPACE_DEBUG_MODE = has_cli_flag(sys.argv, CLI_FLAG_DEBUG)
CONSOLE_BANNER_WIDTH = 60
LOGIN_REQUIRED_MESSAGE = (
    "No signed-in user is available. Log in to the app and run the scrape "
    "from the authenticated session."
)
LLM_RUNTIME_MISSING_PROVIDER_KEY_MESSAGE = (
    "Search requires LLM review, but no provider key is configured for this runtime."
)


def _format_role_list(values: object) -> str:
    if not isinstance(values, list):
        return "(none)"
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return ", ".join(cleaned) if cleaned else "(none)"


def _log_search_plan(context) -> None:
    from job_hunter_agent.scrapers.linkedin import build_linkedin_search_targets

    profile = context.profile if isinstance(context.profile, dict) else {}
    preferred_roles = _format_role_list(profile.get("target_roles"))
    alternative_roles = _format_role_list(profile.get("also_consider_roles"))

    logger.info(
        "\n%s\nSEARCH PLAN\n"
        "Preferred roles   : %s\n"
        "Alternative roles : %s",
        "=" * CONSOLE_BANNER_WIDTH,
        preferred_roles,
        alternative_roles,
    )

    if "linkedin" in context.enabled_sources:
        linkedin_targets = build_linkedin_search_targets(context.search_settings, context.profile)
        logger.info("LinkedIn targets   : %d", len(linkedin_targets))
        if linkedin_targets:
            for index, target in enumerate(linkedin_targets, start=1):
                logger.info(
                    "  [%d/%d] term=%r | location=%s | scope=%s | distance=%s | results=%s | hours_old=%s",
                    index,
                    len(linkedin_targets),
                    str(target.get("search_term") or ""),
                    str(target.get("location") or "(all)"),
                    str(target.get("scope") or "n/a"),
                    str(target.get("distance") if target.get("distance") is not None else "n/a"),
                    str(target.get("results_wanted") or ""),
                    str(target.get("hours_old") or ""),
                )

    logger.info("%s", "=" * CONSOLE_BANNER_WIDTH)


def ensure_llm_runtime_ready(*, no_llm_mode: bool) -> None:
    if no_llm_mode:
        return
    from job_hunter_agent.llm_gate import client  # noqa: PLC0415

    if client is None:
        logger.warning("[RUN][ABORT] %s", LLM_RUNTIME_MISSING_PROVIDER_KEY_MESSAGE)
        raise RuntimeError(LLM_RUNTIME_MISSING_PROVIDER_KEY_MESSAGE)

if has_cli_flag(sys.argv, CLI_FLAG_STEP):
    enable_step_through()


def scrape_jobs_direct(
    *, trigger_label: str = "manual scrape command", force_refresh: bool = False
) -> str:
    """Run one scrape inside an isolated control scope in every execution mode."""
    if run_control_scope_active():
        return _scrape_jobs_direct_scoped(
            trigger_label=trigger_label, force_refresh=force_refresh
        )

    progress_scope = begin_run_progress_scope()
    try:
        return _scrape_jobs_direct_scoped(
            trigger_label=trigger_label, force_refresh=force_refresh
        )
    finally:
        end_run_progress_scope(progress_scope)


def _scrape_jobs_direct_scoped(*, trigger_label: str, force_refresh: bool = False) -> str:
    from job_hunter_agent.global_settings import (
        get_playwright_browser_mode,
        get_playwright_headless,
    )
    from job_hunter_agent.llm_gate import get_llm_model, reset_session_cost
    from job_hunter_agent.source_learning import reset_llm_truncation_count

    get_user_id_for_runtime()
    if run_shutdown_requested():
        raise RunInterruptedError("Server shutdown interrupted before source collection started.")
    clear_run_progress()
    context = build_scrape_run_context(sys.argv)
    context.force_source_refresh = bool(force_refresh or has_cli_flag(sys.argv, CLI_FLAG_FORCE_REFRESH))
    if step_through_enabled():
        # Step-through is intentionally single-file so each job can be reviewed
        # before the next detail fetch starts.
        context.seek_parallel_detail_workers = 1
    require_profile_ready_for_review(load_profile())
    ensure_llm_runtime_ready(no_llm_mode=context.no_llm_mode)
    reset_session_cost()
    reset_llm_truncation_count()
    search_keywords = str(context.search_settings.get("keywords") or "").strip()
    search_locations = [
        str(value).strip()
        for value in context.search_settings.get("locations", [])
        if str(value).strip()
    ]
    llm_model_line = (
        "  LLM Model          : disabled"
        if context.no_llm_mode
        else f"  LLM Model          : {get_llm_model()}"
    )
    logger.info(
        "\n%s\n  JOB HUNTER AGENT - SCRAPE RUN\n%s\n"
        "  Trigger            : %s\n"
        "  Action             : scrape fresh jobs, review them, rebuild workspace\n"
        "  Enabled sources    : %s\n"
        "  Search params\n"
        "    Keywords         : %s\n"
        "    Locations        : %s\n"
        "    SEEK pages       : 1..%d\n"
        "    Date range       : %d day(s)\n"
        "  Fresh scrape       : YES\n"
        "  Workspace debug    : %s\n"
        "  LLM Disabled       : %s\n"
        "%s\n"
        "  Score Floor        : %d\n"
        "  Reset New To You   : %s\n"
        "  Step-through debug : %s\n"
        "%s",
        "=" * CONSOLE_BANNER_WIDTH,
        "=" * CONSOLE_BANNER_WIDTH,
        trigger_label,
        ", ".join(context.enabled_sources) or "(none)",
        search_keywords or "(unset)",
        ", ".join(search_locations) or "(unset)",
        context.configured_seek_max_pages,
        context.configured_date_range,
        "ON (--debug)" if context.dashboard_debug_mode else "OFF",
        "YES (--no-llm)" if context.no_llm_mode else "NO",
        llm_model_line,
        context.dashboard_min_score,
        "YES (--reset-new-to-you)" if context.reset_new_to_you else "NO",
        "ON (--step)" if has_cli_flag(sys.argv, CLI_FLAG_STEP) else "OFF",
        "=" * CONSOLE_BANNER_WIDTH,
    )

    browser_mode = get_playwright_browser_mode()
    context.headless = False if browser_mode == "persistent" else get_playwright_headless()
    logger.info(
        "Playwright browser mode=%s | headless=%s",
        browser_mode,
        context.headless,
    )
    _log_search_plan(context)
    kept_records, audit_rows, skill_observations = run_enabled_sources(context)
    if run_shutdown_requested():
        raise RunInterruptedError("Server shutdown interrupted source collection.")
    workspace_result = finalize_scrape_run(context, kept_records, audit_rows, skill_observations)
    if context.source_failure_message:
        # The stop event was raised internally to halt sibling source workers.
        # Clear it before raising so the server records a failed run rather than
        # misreporting the source failure as a user-requested cancellation.
        clear_run_stop_request()
        raise RuntimeError(context.source_failure_message)
    return workspace_result


if __name__ == "__main__":
    from job_hunter_agent.config import DEBUG_MODE
    from job_hunter_agent.logging_utils import setup_logging

    setup_logging(debug=DEBUG_MODE)
    from job_hunter_agent.database import init_db
    from job_hunter_agent.global_settings import seed_global_settings_from_file
    from job_hunter_agent.knowledge_store import upgrade_knowledge_from_dir
    from job_hunter_agent.paths import REPO_ROOT as _REPO_ROOT
    from job_hunter_agent.runtime_seed_manifest import (
        APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
        APPROVED_SIGNAL_JSON_REL_PATHS,
        resolve_seed_json_paths,
    )

    init_db()
    seed_global_settings_from_file()
    upgrade_knowledge_from_dir(
        _REPO_ROOT / "data" / "knowledge",
        json_files=resolve_seed_json_paths(
            _REPO_ROOT / "data" / "knowledge",
            APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
        ),
    )
    upgrade_knowledge_from_dir(
        _REPO_ROOT / "data" / "signals",
        json_files=resolve_seed_json_paths(
            _REPO_ROOT / "data" / "signals",
            APPROVED_SIGNAL_JSON_REL_PATHS,
        ),
    )

    from job_hunter_agent.user_context import set_user_context_from_admin_env

    set_user_context_from_admin_env()
    try:
        if has_cli_flag(sys.argv, CLI_FLAG_REBUILD_WORKSPACE):
            rebuild_workspace_results()
        else:
            scrape_jobs_direct()
    except RuntimeError as exc:
        if "No signed-in user is available" in str(exc):
            raise SystemExit(LOGIN_REQUIRED_MESSAGE) from exc
        logger.error("ERROR: %s", exc)
        raise SystemExit(2) from exc
