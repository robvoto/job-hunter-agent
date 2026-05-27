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

import argparse
import sys

from dotenv import load_dotenv
load_dotenv()

from job_hunter_agent.user_settings import get_workspace_minimum_score
from job_hunter_agent.runtime_helpers import (
    CLI_FLAG_DEBUG,
    CLI_FLAG_NO_LLM,
    CLI_FLAG_REBUILD_WORKSPACE,
    has_cli_flag,
)
from job_hunter_agent.profile_store import (
    load_profile,
)
from job_hunter_agent.io_utils import configure_console_output

from job_hunter_agent.run_context import build_scrape_run_context
from job_hunter_agent.scrape_finalize import finalize_scrape_run
from job_hunter_agent.source_runner import run_enabled_sources
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results
from job_hunter_agent.user_context import get_user_id_for_runtime, set_user_id

NO_LLM_MODE = has_cli_flag(sys.argv, CLI_FLAG_NO_LLM)
WORKSPACE_DEBUG_MODE = has_cli_flag(sys.argv, CLI_FLAG_DEBUG)
CONSOLE_BANNER_WIDTH = 60


def scrape_jobs_direct(headless: bool = False) -> str:
    from job_hunter_agent.llm_gate import get_llm_model, reset_session_cost
    get_user_id_for_runtime()
    context = build_scrape_run_context(sys.argv)
    reset_session_cost()
    search_keywords = str(context.search_settings.get("keywords") or "").strip()
    search_locations = [
        str(value).strip()
        for value in context.search_settings.get("locations", [])
        if str(value).strip()
    ]
    print("=" * CONSOLE_BANNER_WIDTH)
    print("  JOB HUNTER AGENT - SCRAPE RUN")
    print("=" * CONSOLE_BANNER_WIDTH)
    print("  Trigger            : manual scrape command")
    print("  Action             : scrape fresh jobs, review them, rebuild workspace")
    print(f"  Enabled sources    : {', '.join(context.enabled_sources) or '(none)'}")
    print("  Search params")
    print(f"    Keywords         : {search_keywords or '(unset)'}")
    print(f"    Locations        : {', '.join(search_locations) or '(unset)'}")
    print(f"    SEEK pages       : 1..{context.configured_seek_max_pages}")
    print(f"    Date range       : {context.configured_date_range} day(s)")
    print("  Fresh scrape       : YES")
    print(f"  Workspace debug    : {'ON (--debug)' if context.dashboard_debug_mode else 'OFF'}")
    print(f"  LLM Disabled       : {'YES (--no-llm)' if context.no_llm_mode else 'NO'}")
    if context.no_llm_mode:
        print("  LLM Model          : disabled")
    else:
        print(f"  LLM Model          : {get_llm_model()}")
    print(f"  Score Floor        : {context.dashboard_min_score}")
    print(f"  Reset New To You   : {'YES (--reset-new-to-you)' if context.reset_new_to_you else 'NO'}")
    print("=" * CONSOLE_BANNER_WIDTH)

    context.headless = headless
    kept_records, audit_rows, skill_observations = run_enabled_sources(context)
    return finalize_scrape_run(context, kept_records, audit_rows, skill_observations)


if __name__ == "__main__":
    from job_hunter_agent.database import init_db
    from job_hunter_agent.global_settings import seed_global_settings_from_file
    from job_hunter_agent.knowledge_store import upgrade_knowledge_from_dir
    from job_hunter_agent.paths import REPO_ROOT as _REPO_ROOT
    init_db()
    seed_global_settings_from_file()
    for _subdir in ("knowledge", "signals"):
        upgrade_knowledge_from_dir(_REPO_ROOT / "data" / _subdir)

    parser = argparse.ArgumentParser(description="Job Hunter Agent source connector")
    parser.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="Explicit user id for CLI runs that need a per-user workspace.",
    )
    args, _ = parser.parse_known_args()
    if not args.user_id:
        raise RuntimeError("--user-id is required for CLI runs.")
    set_user_id(str(args.user_id).strip())
    try:
        if has_cli_flag(sys.argv, CLI_FLAG_REBUILD_WORKSPACE):
            rebuild_workspace_results(user_id=args.user_id)
        else:
            scrape_jobs_direct()
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(2) from exc
