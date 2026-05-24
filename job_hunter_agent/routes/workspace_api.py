from fastapi import APIRouter
from starlette.responses import Response

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.io_utils import load_review_data, load_run_stats
from job_hunter_agent.paths import get_workspace_results_path
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results

from job_hunter_agent.routes.responses import json_response

router = APIRouter()


@router.get("/api/results-html")
def api_results_html():  # type: ignore[no-untyped-def]
    results_path = get_workspace_results_path()
    if not results_path.exists():
        try:
            rebuild_workspace_results(reason="no results file — generating empty workspace")
        except Exception:
            pass
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
    return json_response(
        {
            "ok": True,
            "status": "running" if srv._is_run_in_progress() else "idle",
            "last_run_at": last_run,
            "has_run": last_run is not None,
        },
    )


@router.get("/api/review-data")
def api_review_data():  # type: ignore[no-untyped-def]
    payload = load_review_data()
    if isinstance(payload, dict) and payload:
        payload["suggested_tuning"] = srv.build_suggested_tuning_from_saved_review(
            payload,
            srv.load_profile(),
        )
        return json_response(payload)
    return json_response({})


@router.get("/api/job-history")
def api_job_history():  # type: ignore[no-untyped-def]
    history = srv.load_job_history()
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
