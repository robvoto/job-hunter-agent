"""Workspace refresh service.

This module provides utilities for triggering background workspace rebuilds
after matching rules or user settings are updated. It ensures the dashboard
reflects recent changes to filtering logic without blocking the main
request-response loop.
"""

import contextvars
import secrets
import threading
from typing import Optional

from job_hunter_agent.paths import get_workspace_results_path
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results


_refresh_state_lock = threading.Lock()
_refresh_states: dict[str, str] = {}
_workspace_rebuild_lock = threading.Lock()


def workspace_refresh_status(refresh_id: str) -> str:
    with _refresh_state_lock:
        return _refresh_states.get(str(refresh_id or ""), "unknown")


def rebuild_workspace_after_rule_change(
    reason: str = "matching rule change", *, wait_for_completion: bool = False
) -> Optional[str]:
    """Re-render workspace results, optionally waiting for the snapshot.

    This function checks for existing workspace data and starts a daemon
    thread to execute the rebuild. It preserves the current ContextVar
    state (such as the active user ID) to ensure the thread operates in
    the correct user-scoped directory.

    Review actions can request completion because their response is followed
    immediately by a browser reload that must see the updated state.
    Args:
        reason: The trigger reason, logged in the rebuild summary.
        wait_for_completion: Join the rebuild thread before returning when the
            generated snapshot must be immediately readable.
    """
    from job_hunter_agent.io_utils import load_run_stats

    if not get_workspace_results_path().exists() and not load_run_stats():
        return None

    refresh_id = secrets.token_urlsafe(18)
    with _refresh_state_lock:
        _refresh_states[refresh_id] = "pending"

    def _rebuild() -> None:
        with _workspace_rebuild_lock:
            rebuild_workspace_results(reason=f"{reason}; applying saved filters to current results")

    def _run_rebuild() -> None:
        try:
            _rebuild()
        except Exception:
            with _refresh_state_lock:
                _refresh_states[refresh_id] = "error"
            raise
        else:
            with _refresh_state_lock:
                _refresh_states[refresh_id] = "ready"

    if wait_for_completion:
        _run_rebuild()
        return refresh_id

    ctx = contextvars.copy_context()
    rebuild_thread = threading.Thread(
        target=ctx.run,
        args=(_run_rebuild,),
        daemon=True,
        name="job-hunter-workspace-rebuild",
    )
    rebuild_thread.start()

    return refresh_id
