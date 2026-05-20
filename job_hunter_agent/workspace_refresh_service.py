"""Workspace refresh service.

This module provides utilities for triggering background workspace rebuilds
after matching rules or user settings are updated. It ensures the dashboard 
reflects recent changes to filtering logic without blocking the main 
request-response loop.
"""

import contextvars
import threading

from job_hunter_agent.paths import get_audit_records_path, get_run_stats_path, get_workspace_results_path
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results


def rebuild_workspace_after_rule_change(reason: str = "matching rule change") -> None:
    """Triggers a background thread to re-render the workspace results.

    This function checks for existing workspace data and starts a daemon 
    thread to execute the rebuild. It preserves the current ContextVar 
    state (such as the active user ID) to ensure the thread operates in 
    the correct user-scoped directory.

    Args:
        reason: The trigger reason, logged in the rebuild summary.
    """
    if not get_workspace_results_path().exists() and not get_run_stats_path().exists() and not get_audit_records_path().exists():
        return

    def _rebuild() -> None:
        rebuild_workspace_results(reason=f"{reason}; applying saved filters to current results")

    ctx = contextvars.copy_context()
    threading.Thread(
        target=ctx.run,
        args=(_rebuild,),
        daemon=True,
        name="job-hunter-workspace-rebuild",
    ).start()
