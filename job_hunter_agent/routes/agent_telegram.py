from fastapi import APIRouter, Body

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.agent_settings import load_agent_settings, save_agent_settings

from job_hunter_agent.routes.responses import json_response

router = APIRouter()


@router.get("/api/llm-costs")
def api_llm_costs():  # type: ignore[no-untyped-def]
    from job_hunter_agent.llm_gate import get_cost_summary

    return json_response(get_cost_summary())


@router.get("/api/agent-settings")
def api_agent_settings_get():  # type: ignore[no-untyped-def]
    return json_response(
        srv.SettingsHandler._public_agent_settings_payload(load_agent_settings(create_if_missing=True)),
    )


@router.patch("/api/agent-settings")
def api_agent_settings_patch(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        current = load_agent_settings(create_if_missing=True)
        patch = srv.SettingsHandler._sanitize_agent_settings_payload(body)
        telegram_patch = patch.get("telegram", {})
        if not str(telegram_patch.get("bot_token") or "").strip():
            telegram_patch.pop("bot_token", None)
        current.setdefault("workspace", {}).update(patch.get("workspace", {}))
        current.setdefault("telegram", {}).update(telegram_patch)
        current.setdefault("llm", {}).update(patch.get("llm", {}))
        current.setdefault("schedule", {}).update(patch.get("schedule", {}))
        updated = save_agent_settings(current)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(srv.SettingsHandler._public_agent_settings_payload(updated))


@router.get("/api/telegram/connect-link")
def api_telegram_connect_link():  # type: ignore[no-untyped-def]
    try:
        settings = load_agent_settings(create_if_missing=True)
        link = srv.build_telegram_connect_link(settings["telegram"])
        save_agent_settings(settings)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(
        {
            "ok": True,
            "connect_link": link,
            "bot_username": str(settings["telegram"].get("bot_username") or "").strip(),
        },
    )


@router.post("/api/telegram/sync")
def api_telegram_sync():  # type: ignore[no-untyped-def]
    try:
        settings = load_agent_settings(create_if_missing=True)
        result = srv.sync_telegram_subscribers(settings["telegram"])
        updated = save_agent_settings(settings)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(
        {
            "ok": True,
            "message": f"Telegram sync complete. {result['total_subscribers']} connected Telegram account(s) found.",
            "result": result,
            "settings": srv.SettingsHandler._public_agent_settings_payload(updated),
        },
    )


@router.post("/api/telegram/test-message")
def api_telegram_test_message(body: dict = Body(default_factory=dict)):  # type: ignore[no-untyped-def]
    try:
        settings = load_agent_settings(create_if_missing=True)
        message_text = "Job Hunter test alert. Telegram is connected correctly."
        result = srv.send_telegram_notification(message_text, "", settings["telegram"])
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(
        {
            "ok": True,
            "message": "Telegram test message sent.",
            "result": result,
        },
    )
