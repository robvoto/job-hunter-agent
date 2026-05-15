import contextvars
import threading

from job_hunter_agent.paths import get_audit_records_path, get_run_stats_path, get_workspace_results_path
from job_hunter_agent.source_connector import rebuild_workspace_results


def rebuild_workspace_after_rule_change(reason: str = "matching rule change") -> None:
    if not get_workspace_results_path().exists() and not get_run_stats_path().exists() and not get_audit_records_path().exists():
        return

    def _rebuild() -> None:
        try:
            rebuild_workspace_results(reason=f"{reason}; applying saved filters to current results")
        except Exception as exc:
            print(f"[WORKSPACE][WARN] Could not rebuild after rule change: {type(exc).__name__}: {exc}")

    ctx = contextvars.copy_context()
    threading.Thread(
        target=ctx.run,
        args=(_rebuild,),
        daemon=True,
        name="job-hunter-workspace-rebuild",
    ).start()
