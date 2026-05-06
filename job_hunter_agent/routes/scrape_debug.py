import threading

from fastapi import APIRouter, Body

from job_hunter_agent import server_helpers as srv

from job_hunter_agent.routes.responses import json_response

router = APIRouter()


@router.post("/api/test/reset-user")
def api_test_reset_user():  # type: ignore[no-untyped-def]
    if not srv.DEBUG_MODE:
        return json_response({"error": "Test mode only"}, 403)
    try:
        result = srv.SettingsHandler._reset_current_user_state()
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(result)


@router.post("/api/test/reset-learning")
def api_test_reset_learning():  # type: ignore[no-untyped-def]
    if not srv.DEBUG_MODE:
        return json_response({"error": "Test mode only"}, 403)
    try:
        result = srv.SettingsHandler._reset_global_learning()
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(result)


def _browser_log_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return " ".join(text.split())


@router.post("/api/debug/browser-log")
def api_browser_log(body: dict = Body(default_factory=dict)):  # type: ignore[no-untyped-def]
    if not srv.DEBUG_MODE:
        return json_response({"error": "Debug mode only"}, 403)
    if not isinstance(body, dict):
        return json_response({"error": "Invalid log payload"}, 400)

    level = _browser_log_text(body.get("level")).upper() or "LOG"
    kind = _browser_log_text(body.get("kind"))
    source = _browser_log_text(body.get("source"))
    title = _browser_log_text(body.get("title"))
    href = _browser_log_text(body.get("href"))
    message = _browser_log_text(body.get("message"))
    args = body.get("args")
    timestamp = _browser_log_text(body.get("timestamp"))

    prefix = f"[BROWSER][{level}]"
    if kind:
        prefix += f"[{kind}]"
    if title:
        prefix += f" {title}"
    if href:
        prefix += f" {href}"
    if timestamp:
        prefix += f" @ {timestamp}"

    print(prefix if not message else f"{prefix} {message}", flush=True)

    if isinstance(args, list):
        for index, arg in enumerate(args, start=1):
            arg_text = _browser_log_text(arg)
            if arg_text:
                print(f"{prefix} arg{index}: {arg_text}", flush=True)

    if source or body.get("line") or body.get("column"):
        print(
            f"{prefix} source={source or 'n/a'} line={body.get('line') or 'n/a'} column={body.get('column') or 'n/a'}",
            flush=True,
        )

    stack = _browser_log_text(body.get("stack"))
    if stack:
        print(stack, flush=True)

    return json_response({"ok": True})


@router.post("/api/run")
def api_run(body: dict = Body(default_factory=dict)):  # type: ignore[no-untyped-def]
    try:
        search_settings = srv._normalize_search_settings_payload(body)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)

    if not srv._try_mark_run_started():
        last_run = srv._read_last_run_timestamp()
        return json_response(
            {
                "ok": True,
                "status": "running",
                "last_run_at": last_run,
                "has_run": last_run is not None,
            },
        )

    try:
        if search_settings:
            srv.patch_profile({"search_settings": search_settings})
        threading.Thread(target=srv._run_scrape_job, daemon=True).start()
    except Exception as exc:
        srv._set_run_in_progress(False)
        return json_response({"error": str(exc)}, 400)
    last_run = srv._read_last_run_timestamp()
    return json_response(
        {
            "ok": True,
            "status": "started",
            "last_run_at": last_run,
            "has_run": last_run is not None,
        },
    )
