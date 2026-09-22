"""Route handlers for workspace api."""

import logging
import time
from pathlib import Path

from fastapi import APIRouter
from starlette.responses import Response

from job_hunter_agent import server_helpers as srv
from job_hunter_agent import workspace_renderer, workspace_service
from job_hunter_agent.io_utils import load_job_history, load_review_data, load_run_stats
from job_hunter_agent.paths import RESULTS_TEMPLATE_PATH, UI_LABELS_PATH, get_workspace_results_path
from job_hunter_agent.review_insights import filter_resolved_suggested_tuning
from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.run_control import (
    get_run_progress,
    get_run_progress_by_source,
    get_run_progress_detail,
    request_run_stop,
)
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results
from job_hunter_agent.workspace_refresh_service import workspace_refresh_status

logger = logging.getLogger(__name__)
_WORKSPACE_API_STARTED_AT_NS = time.time_ns()

router = APIRouter()



def _workspace_render_source_paths() -> tuple[Path, ...]:
    """Return source files whose changes invalidate a saved workspace snapshot."""
    return (
        RESULTS_TEMPLATE_PATH,
        UI_LABELS_PATH,
        Path(workspace_renderer.__file__),
        Path(workspace_service.__file__),
    )


def _workspace_results_are_stale(results_path: Path) -> bool:
    """Detect HTML rendered by an older process or older display inputs."""
    try:
        generated_at = results_path.stat().st_mtime_ns
    except OSError:
        return True

    # A previous long-running process can render after the source files changed,
    # making mtime-only invalidation think stale HTML is fresh. Any snapshot that
    # predates this process gets one rebuild on first access.
    if generated_at < _WORKSPACE_API_STARTED_AT_NS:
        return True

    return any(
        source_path.exists() and source_path.stat().st_mtime_ns > generated_at
        for source_path in _workspace_render_source_paths()
    )


@router.get("/api/results-html")
def api_results_html():  # type: ignore[no-untyped-def]

    results_path = get_workspace_results_path()

    run_stats = load_run_stats()

    last_error = str((run_stats or {}).get("last_run_error") or "").strip()

    if last_error:
        logger.warning("Last run error: %s", last_error)

        return json_response({"error": last_error}, 503)

    if not results_path.exists():
        try:
            rebuild_workspace_results(reason="no results file — generating empty workspace")

        except Exception:
            pass
    elif _workspace_results_are_stale(results_path):
        try:
            rebuild_workspace_results(reason="workspace renderer changed — refreshing saved HTML")
        except Exception as exc:
            return json_response({"error": f"{type(exc).__name__}: {exc}"}, 500)

    try:
        body = results_path.read_bytes()

    except Exception as exc:
        return json_response({"error": str(exc)}, 500)

    return Response(
        content=body,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/api/health")
def api_health():  # type: ignore[no-untyped-def]

    return json_response({"ok": True})


@router.get("/api/workspace-refresh/{refresh_id}")
def api_workspace_refresh(refresh_id: str):  # type: ignore[no-untyped-def]
    status = workspace_refresh_status(refresh_id)
    if status == "unknown":
        return json_response({"error": "Workspace refresh was not found"}, 404)
    return json_response({"ok": status != "error", "status": status, "ready": status == "ready"})


@router.get("/api/run-stats")
def api_run_stats():  # type: ignore[no-untyped-def]

    payload = load_run_stats()

    if isinstance(payload, dict) and payload:
        return json_response(payload)

    return json_response({})




def _prioritize_verification_progress(
    progress: str,
    progress_detail: dict | None,
    progress_by_source: dict[str, dict],
) -> tuple[str, dict | None]:
    """Keep any active human-verification prompt visible over routine source updates."""
    for source in sorted(progress_by_source):
        snapshot = progress_by_source.get(source) or {}
        detail = snapshot.get("progress_detail")
        if isinstance(detail, dict) and str(detail.get("stage") or "").strip() == "verification":
            return str(snapshot.get("progress") or "").strip(), dict(detail)
    return progress, progress_detail

@router.get("/api/run-status")
def api_run_status():  # type: ignore[no-untyped-def]
    """Return the current run lifecycle and independently structured progress fields.

    ``progress`` remains human-readable text for logs and simple consumers;
    ``progress_detail`` and elapsed fields are the canonical UI inputs.
    """
    last_run = srv._read_last_run_timestamp()
    status = srv._current_run_status()
    elapsed_text = srv._format_current_run_elapsed()
    elapsed_seconds = srv._current_run_elapsed_seconds()
    progress = get_run_progress()
    progress_detail = get_run_progress_detail()
    progress_by_source = get_run_progress_by_source()
    if status == srv.RUN_STATUS_RUNNING:
        progress, progress_detail = _prioritize_verification_progress(
            progress, progress_detail, progress_by_source
        )
    scheduler = srv._read_scheduler_status()

    return json_response(
        {
            "ok": True,
            "status": status,
            "stop_requested": status == srv.RUN_STATUS_STOPPING,
            "progress": progress or None,
            "progress_detail": progress_detail,
            "progress_by_source": progress_by_source,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_text": elapsed_text or None,
            "last_run_at": last_run,
            "has_run": last_run is not None,
            "scheduler": scheduler,
        },
    )


@router.post("/api/run/stop")
def api_run_stop():  # type: ignore[no-untyped-def]
    """Request a cooperative stop and return the same progress contract as run status."""
    if not srv._is_run_in_progress():
        return json_response(
            {
                "ok": True,
                "status": srv._current_run_status(),
                "stop_requested": False,
                "progress": get_run_progress() or None,
                "progress_detail": get_run_progress_detail(),
                "progress_by_source": get_run_progress_by_source(),
                "elapsed_seconds": srv._current_run_elapsed_seconds(),
                "elapsed_text": srv._format_current_run_elapsed() or None,
            }
        )

    request_run_stop()
    last_run = srv._read_last_run_timestamp()
    elapsed_text = srv._format_current_run_elapsed()
    elapsed_seconds = srv._current_run_elapsed_seconds()
    progress = get_run_progress()

    return json_response(
        {
            "ok": True,
            "status": "stopping",
            "stop_requested": True,
            "progress": progress or None,
            "progress_detail": get_run_progress_detail(),
            "progress_by_source": get_run_progress_by_source(),
            "elapsed_seconds": elapsed_seconds,
            "elapsed_text": elapsed_text or None,
            "last_run_at": last_run,
            "has_run": last_run is not None,
        },
    )


@router.get("/api/review-data")
def api_review_data():  # type: ignore[no-untyped-def]

    payload = load_review_data()

    if isinstance(payload, dict) and payload:
        return json_response(filter_resolved_suggested_tuning(payload, srv.load_profile()))

    return json_response({})


@router.get("/api/job-history")
def api_job_history():  # type: ignore[no-untyped-def]

    history = load_job_history()

    slim_history: dict[str, dict] = {}

    for job_key, entry in history.items():
        if not isinstance(entry, dict):
            continue

        slim_history[str(job_key)] = {
            "times_viewed": int(entry.get("times_viewed", 0) or 0),
            "first_viewed_at": entry.get("first_viewed_at"),
            "last_viewed_at": entry.get("last_viewed_at"),
        }

    return json_response({"jobs": slim_history})
