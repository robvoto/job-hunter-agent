"""Route handlers for workspace api."""

from pathlib import Path

from fastapi import APIRouter
from starlette.responses import Response

from job_hunter_agent import server_helpers as srv
from job_hunter_agent import workspace_renderer, workspace_service
from job_hunter_agent.io_utils import load_job_history, load_review_data, load_run_stats
from job_hunter_agent.paths import RESULTS_TEMPLATE_PATH, UI_LABELS_PATH, get_workspace_results_path
from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.run_control import get_run_progress, request_run_stop, run_stop_requested
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results

router = APIRouter()


def _progress_with_elapsed(progress: str | None, elapsed_text: str) -> str | None:
    progress_text = str(progress or "").strip()
    elapsed_value = str(elapsed_text or "").strip()
    if not elapsed_value:
        return progress_text or None
    if not progress_text:
        return f"elapsed {elapsed_value}"
    lines = [line.strip() for line in progress_text.splitlines() if line.strip()]
    if lines and lines[-1].lower().startswith("elapsed "):
        return progress_text
    return f"{progress_text}\nelapsed {elapsed_value}"


def _workspace_render_source_paths() -> tuple[Path, ...]:
    """Return source files whose changes invalidate a saved workspace snapshot."""
    return (
        RESULTS_TEMPLATE_PATH,
        UI_LABELS_PATH,
        Path(workspace_renderer.__file__),
        Path(workspace_service.__file__),
    )


def _workspace_results_are_stale(results_path: Path) -> bool:
    """Detect generated HTML that predates the renderer or its display inputs."""
    try:
        generated_at = results_path.stat().st_mtime_ns
    except OSError:
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
        print(f"[WORKSPACE][WARN] Last run error: {last_error}")

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


@router.get("/api/run-stats")
def api_run_stats():  # type: ignore[no-untyped-def]

    payload = load_run_stats()

    if isinstance(payload, dict) and payload:
        return json_response(payload)

    return json_response({})


@router.get("/api/run-status")
def api_run_status():  # type: ignore[no-untyped-def]

    last_run = srv._read_last_run_timestamp()
    running = srv._is_run_in_progress()
    stopping = running and run_stop_requested()
    elapsed_text = srv._format_current_run_elapsed()
    elapsed_seconds = srv._current_run_elapsed_seconds()
    progress = _progress_with_elapsed(get_run_progress(), elapsed_text)
    scheduler = srv._read_scheduler_status()
    if running or stopping:
        scheduler["active"] = True

    return json_response(
        {
            "ok": True,
            "status": "stopping" if stopping else "running" if running else "idle",
            "stop_requested": stopping,
            "progress": progress or None,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_text": elapsed_text or None,
            "last_run_at": last_run,
            "has_run": last_run is not None,
            "scheduler": scheduler,
        },
    )


@router.post("/api/run/stop")
def api_run_stop():  # type: ignore[no-untyped-def]

    if not srv._is_run_in_progress():
        return json_response({"ok": True, "status": "idle", "stop_requested": False})

    request_run_stop()
    last_run = srv._read_last_run_timestamp()
    elapsed_text = srv._format_current_run_elapsed()
    elapsed_seconds = srv._current_run_elapsed_seconds()
    progress = _progress_with_elapsed(get_run_progress(), elapsed_text)

    return json_response(
        {
            "ok": True,
            "status": "stopping",
            "stop_requested": True,
            "progress": progress or None,
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
        return json_response(payload)

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
