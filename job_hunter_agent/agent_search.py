"""JH-292: Agent-triggerable ad-hoc search entry point.

Lets an external agent (e.g. Claude via CLI/MCP shell access) run a one-off
Job Hunter search with custom keywords, salary floor, locations, and enabled
sources -- without ever mutating the real signed-in user's persisted
profile/settings.

How it stays safe: the existing pipeline (scrapers, LLM fit-review, scoring,
workspace persistence) already resolves "which user" via
job_hunter_agent.user_context's per-process ContextVar (see paths.py::
get_active_user_id). This module borrows that exact seam instead of adding a
parallel one: it reads the real user's profile once (read-only, for
candidate background/capability context the LLM needs), builds an
overridden copy with agent-supplied search parameters, and then points the
ContextVar at a separate deterministic "ephemeral" user_id before running
the unmodified scrape/review pipeline. Results land under that ephemeral
user_id's own workspace_pool row -- never merged into, or capable of
overwriting, the real user's normal saved results -- and the real user's
profile/settings row in the database is never written to at any point.

Local/CLI use only for now (JH-292). A proper authenticated HTTP endpoint
exposing the same capability is tracked separately as JH-293; do not add
routes here.
"""

from __future__ import annotations

# Environment-backed paths must be loaded before the ad-hoc command reaches
# the database-backed profile, source, or result helpers below.
import argparse
import copy
import json
import sys
from typing import Any

from job_hunter_agent.runtime_helpers import load_repo_dotenv

load_repo_dotenv()

AGENT_ADHOC_USER_SUFFIX = "::agent-adhoc"


def ephemeral_user_id(base_user_id: str) -> str:
    """Deterministic ephemeral user_id for a given real user's ad-hoc runs.

    Deterministic (not random/timestamped) so repeated ad-hoc runs for the
    same base user reuse one ephemeral profile/workspace row rather than
    growing a new one every call.
    """
    base = str(base_user_id or "").strip()
    if not base:
        raise ValueError("base_user_id must be a non-empty string")
    return f"{base}{AGENT_ADHOC_USER_SUFFIX}"


def build_ad_hoc_profile(
    base_profile: dict[str, Any],
    *,
    keywords: list[str],
    locations: list[str] | None = None,
    min_salary: int | None = None,
    sources: list[str] | None = None,
    date_range_days: int | None = None,
) -> dict[str, Any]:
    """Return a deep-copied override profile for a one-off ad-hoc search.

    Preserves candidate background/capability/eligibility data from
    base_profile (the LLM fit-review needs this to judge fit at all), but
    replaces search terms, locations, salary floor, date range, and enabled
    sources with the agent-supplied ad-hoc values. Never mutates
    base_profile in place -- callers must still avoid persisting base_profile
    itself under the ephemeral user_id.
    """
    if not keywords:
        raise ValueError("keywords must be a non-empty list for an ad-hoc search")

    override = copy.deepcopy(base_profile)

    # target_roles/also_consider_roles take priority over search_settings
    # .keywords in ordered_profile_search_terms() -- see search_terms.py.
    override["target_roles"] = [str(k).strip() for k in keywords if str(k).strip()]
    override["also_consider_roles"] = []

    search_settings = override.setdefault("search_settings", {})
    # Kept as a valid non-empty fallback/validation value; target_roles above
    # is what actually drives search-term generation when present.
    search_settings["keywords"] = override["target_roles"][0]

    if locations is not None:
        search_settings["locations"] = [str(loc).strip() for loc in locations if str(loc).strip()]

    if date_range_days is not None:
        search_settings["date_range_days"] = int(date_range_days)

    if sources is not None:
        normalized_sources = [str(s).strip().lower() for s in sources if str(s).strip()]
        override["enabled_sources"] = normalized_sources
        search_settings["seek_enabled"] = "seek" in normalized_sources
        search_settings["linkedin_enabled"] = "linkedin" in normalized_sources
        search_settings["apsjobs_enabled"] = "apsjobs" in normalized_sources

    salary_prefs = override.setdefault("salary_preferences", {})
    # 0 means no minimum (see JH-025); an explicit ad-hoc floor of 0 is how a
    # genuinely "any role, even low paid" search is expressed.
    salary_prefs["minimum_salary_yearly"] = int(min_salary) if min_salary else 0

    return override


def run_agent_ad_hoc_search(
    *,
    keywords: list[str],
    base_user_id: str,
    locations: list[str] | None = None,
    min_salary: int | None = None,
    sources: list[str] | None = None,
    date_range_days: int | None = None,
) -> dict[str, Any]:
    """Run a one-off Job Hunter search with agent-supplied parameters.

    Reuses the existing scrape/review pipeline (job_hunter_agent.
    source_connector.scrape_jobs_direct) completely unchanged, scoped to a
    separate ephemeral user_id. base_user_id's own profile/settings row is
    only ever read, never written, by this function.
    """
    from job_hunter_agent import user_context
    from job_hunter_agent.profile_store import (
        KEY_CANDIDATE_CAPABILITIES,
        KEY_NAME,
        load_profile,
        save_profile,
    )
    from job_hunter_agent.source_connector import scrape_jobs_direct

    target_user_id = ephemeral_user_id(base_user_id)

    # Read-only: load the real user's profile for background/capability
    # context. No write happens while user_context is scoped to base_user_id.
    user_context.set_user_id(base_user_id)
    base_profile = load_profile()
    # The ad-hoc profile is a deep copy, so base capability names are facts
    # already trusted for this one write under the isolated user. Only these
    # copied names bypass atomicity validation; later added or changed names do not.
    prevalidated_capability_names = {
        str(capability.get(KEY_NAME) or "").strip()
        for capability in base_profile.get(KEY_CANDIDATE_CAPABILITIES, [])
        if isinstance(capability, dict) and str(capability.get(KEY_NAME) or "").strip()
    }

    override_profile = build_ad_hoc_profile(
        base_profile,
        keywords=keywords,
        locations=locations,
        min_salary=min_salary,
        sources=sources,
        date_range_days=date_range_days,
    )

    # From here on, every read/write (save_profile, the scrape pipeline,
    # workspace_pool persistence) is scoped to the ephemeral user_id, not
    # base_user_id -- this is the safety boundary for JH-292 AC #2/#4/#5.
    user_context.set_user_id(target_user_id)
    try:
        save_profile(
            override_profile,
            prevalidated_capability_names=prevalidated_capability_names,
        )
        result_message = scrape_jobs_direct(
            trigger_label="agent ad-hoc search (JH-292)",
            force_refresh=True,
        )
    finally:
        # Always leave the process-level context pointed back at the real
        # user so any other code running later in the same process/session
        # does not stay scoped to the ephemeral profile.
        user_context.set_user_id(base_user_id)

    return {
        "ephemeral_user_id": target_user_id,
        "base_user_id": base_user_id,
        "result_message": result_message,
    }


def get_ad_hoc_results(base_user_id: str) -> list[dict[str, Any]]:
    """Read back the workspace_pool results from the most recent ad-hoc run.

    Read-only convenience helper. Returns [] if no ad-hoc run has completed
    yet for this base_user_id.
    """
    from job_hunter_agent.database import db_conn

    target_user_id = ephemeral_user_id(base_user_id)
    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM workspace_pool WHERE user_id = ?", (target_user_id,)
        ).fetchone()
    if row is None:
        return []
    data = json.loads(row["data"])
    return data if isinstance(data, list) else []


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m job_hunter_agent.agent_search",
        description=(
            "Run a one-off Job Hunter search with agent-supplied parameters "
            "(JH-292). Never modifies base_user_id's saved profile/settings; "
            "results are stored under a separate ephemeral user_id."
        ),
    )
    parser.add_argument(
        "--base-user-id",
        required=True,
        help="Real user_id to borrow candidate background/capability context from.",
    )
    parser.add_argument(
        "--keywords",
        required=True,
        nargs="+",
        help="One or more search keyword phrases, e.g. --keywords \"business analyst\" \"business support officer\"",
    )
    parser.add_argument("--locations", nargs="*", default=None)
    parser.add_argument(
        "--min-salary",
        type=int,
        default=None,
        help="Annual salary floor. Omit or pass 0 for no minimum (any role, any pay).",
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        default=None,
        choices=["seek", "linkedin", "apsjobs"],
    )
    parser.add_argument("--date-range-days", type=int, default=None)
    parser.add_argument(
        "--print-results",
        action="store_true",
        help="After the run, print the ephemeral workspace_pool contents as JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    result = run_agent_ad_hoc_search(
        keywords=args.keywords,
        base_user_id=args.base_user_id,
        locations=args.locations,
        min_salary=args.min_salary,
        sources=args.sources,
        date_range_days=args.date_range_days,
    )
    print(result["result_message"])
    print(f"Results stored under ephemeral user_id: {result['ephemeral_user_id']}")
    if args.print_results:
        print(json.dumps(get_ad_hoc_results(args.base_user_id), indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
