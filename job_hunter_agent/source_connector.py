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
    clear_run_progress,
    clear_run_stop_request,
    enable_step_through,
    step_through_enabled,
)
from job_hunter_agent.runtime_helpers import (
    CLI_FLAG_DEBUG,
    CLI_FLAG_NO_LLM,
    CLI_FLAG_REBUILD_WORKSPACE,
    CLI_FLAG_STEP,
    has_cli_flag,
)
from job_hunter_agent.user_settings import get_workspace_minimum_score

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

if has_cli_flag(sys.argv, CLI_FLAG_STEP):
    enable_step_through()


def scrape_jobs_direct() -> str:
    from job_hunter_agent.global_settings import (
        get_playwright_browser_mode,
        get_playwright_headless,
    )
    from job_hunter_agent.llm_gate import get_llm_model, reset_session_cost
    from job_hunter_agent.source_learning import reset_llm_truncation_count

    get_user_id_for_runtime()
    clear_run_stop_request()
    clear_run_progress()
    context = build_scrape_run_context(sys.argv)
    if step_through_enabled():
        # Step-through is intentionally single-file so each job can be reviewed
        # before the next detail fetch starts.
        context.seek_parallel_detail_workers = 1
    require_profile_ready_for_review(load_profile())
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
        "  Trigger            : manual scrape command\n"
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
    kept_records, audit_rows, skill_observations = run_enabled_sources(context)
    return finalize_scrape_run(context, kept_records, audit_rows, skill_observations)


if __name__ == "__main__":
    from job_hunter_agent.logging_utils import setup_cli_logging

    setup_cli_logging()
    from job_hunter_agent.database import init_db
    from job_hunter_agent.global_settings import seed_global_settings_from_file
    from job_hunter_agent.knowledge_store import upgrade_knowledge_from_dir
    from job_hunter_agent.paths import REPO_ROOT as _REPO_ROOT

    init_db()
    seed_global_settings_from_file()
    for _subdir in ("knowledge", "signals"):
        upgrade_knowledge_from_dir(_REPO_ROOT / "data" / _subdir)

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
