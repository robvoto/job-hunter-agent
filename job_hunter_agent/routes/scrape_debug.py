"""Route handlers for scrape debug."""

import contextvars
import logging
import threading

from fastapi import APIRouter, Body

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.routes.responses import json_response

logger = logging.getLogger(__name__)
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


def _normalise_field(value: object) -> str:
    """Collapse a single-line metadata field (level, title, href, etc.) to one line."""
    text = str(value or "").strip()
    return " ".join(text.split()) if text else ""


def _format_arg(value: object) -> str:
    """Return a log argument preserving its formatting (JSON objects keep indentation)."""
    return str(value or "").strip()


@router.post("/api/debug/browser-log")
def api_browser_log(body: dict = Body(default_factory=dict)):  # type: ignore[no-untyped-def]
    if not srv.DEBUG_MODE:
        return json_response({"error": "Debug mode only"}, 403)
    if not isinstance(body, dict):
        return json_response({"error": "Invalid log payload"}, 400)

    level = _normalise_field(body.get("level")).upper() or "LOG"
    kind = _normalise_field(body.get("kind"))
    source = _normalise_field(body.get("source"))
    title = _normalise_field(body.get("title"))
    href = _normalise_field(body.get("href"))
    timestamp = _normalise_field(body.get("timestamp"))
    args = body.get("args")

    # Compact tag: level + optional event kind
    tag = f"[BROWSER][{level}]" + (f"[{kind}]" if kind else "")

    # One context line per request: page title | url | timestamp
    context_parts = [p for p in (title, href, f"@ {timestamp}" if timestamp else "") if p]
    logger.info("%s  %s", tag, " | ".join(context_parts))

    # Args: printed individually preserving JSON indentation.
    # message is skipped — it is just args joined, so printing both is redundant.
    if isinstance(args, list):
        for arg in args:
            text = _format_arg(arg)
            if text:
                logger.info("%s  %s", tag, text)
    elif body.get("message"):
        logger.info("%s  %s", tag, _normalise_field(body.get("message")))

    if source or body.get("line") or body.get("column"):
        logger.info(
            "%s  source=%s line=%s column=%s",
            tag,
            source or "n/a",
            body.get("line") or "n/a",
            body.get("column") or "n/a",
        )

    stack = _normalise_field(body.get("stack"))
    if stack:
        logger.info(stack)

    return json_response({"ok": True})


@router.post("/api/run")
def api_run(body: dict = Body(default_factory=dict)):  # type: ignore[no-untyped-def]
    try:
        search_settings = srv._normalize_search_settings_payload(body)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)

    if not srv._onboarding_complete():
        return json_response(
            {"error": "Onboarding is not complete. Please finish setup before running a search."},
            400,
        )

    try:
        srv.require_profile_ready_for_review()
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
        ctx = contextvars.copy_context()
        threading.Thread(target=ctx.run, args=(srv._run_scrape_job,), daemon=True).start()
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
