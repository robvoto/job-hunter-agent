"""Telegram bot delivery for the local job agent."""

import json
import logging
from datetime import datetime
from urllib import parse, request
from urllib.error import HTTPError

logger = logging.getLogger(__name__)


def _telegram_api_request(
    bot_token: str, method: str, payload: dict | None = None, timeout: int = 30
) -> dict:
    if not bot_token:
        raise ValueError("Telegram bot token is missing")

    form_fields = {key: value for key, value in (payload or {}).items() if value not in (None, "")}
    encoded = parse.urlencode(form_fields).encode("utf-8")
    endpoint = f"https://api.telegram.org/bot{bot_token}/{method}"
    req = request.Request(endpoint, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
            if not data.get("ok"):
                logger.warning(
                    "[TELEGRAM][WARN] Telegram API returned a non-ok response for %s.", method
                )
                raise ValueError(f"Telegram API error: {data}")
            return data
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            logger.warning(
                "[TELEGRAM][WARN] Failed to read Telegram HTTP error body for %s; falling back to the exception text.",
                method,
            )
            body = str(exc)
        raise ValueError(f"Telegram HTTP error {exc.code}: {body}") from exc


def get_telegram_bot_profile(settings: dict) -> dict:
    bot_token = str(settings.get("bot_token") or "").strip()
    payload = _telegram_api_request(bot_token, "getMe")
    result = payload.get("result") or {}
    if isinstance(result, dict):
        return result
    logger.warning(
        "[TELEGRAM][WARN] Telegram getMe returned a missing or non-dict result; returning an empty profile."
    )
    return {}


def build_telegram_connect_link(settings: dict) -> str:
    bot_username = str(settings.get("bot_username") or "").strip().lstrip("@")
    if not bot_username:
        profile = get_telegram_bot_profile(settings)
        bot_username = str(profile.get("username") or "").strip().lstrip("@")
        if bot_username:
            settings["bot_username"] = bot_username
    if not bot_username:
        raise ValueError("Telegram bot username is missing. Save a valid bot token first.")
    return f"https://t.me/{bot_username}?start=connect"


def sync_telegram_subscribers(settings: dict) -> dict:
    bot_token = str(settings.get("bot_token") or "").strip()
    if not bot_token:
        raise ValueError("Telegram bot token is missing")

    profile = get_telegram_bot_profile(settings)
    username = str(profile.get("username") or "").strip().lstrip("@")
    if username:
        settings["bot_username"] = username

    last_update_id = max(0, int(settings.get("last_update_id", 0) or 0))
    payload = _telegram_api_request(
        bot_token,
        "getUpdates",
        {
            "offset": last_update_id + 1 if last_update_id else None,
            "timeout": 0,
            "allowed_updates": json.dumps(["message"]),
        },
    )
    updates = payload.get("result") or []
    if not isinstance(updates, list):
        logger.warning(
            "[TELEGRAM][WARN] Telegram getUpdates returned a non-list result; returning an empty update list."
        )
        updates = []

    subscribers = {
        str(item.get("chat_id") or "").strip(): dict(item)
        for item in settings.get("subscribers", [])
        if isinstance(item, dict) and str(item.get("chat_id") or "").strip()
    }
    new_subscribers: list[dict] = []
    now_text = datetime.now().astimezone().isoformat(timespec="seconds")

    for update in updates:
        if not isinstance(update, dict):
            continue
        update_id = int(update.get("update_id", 0) or 0)
        if update_id > last_update_id:
            last_update_id = update_id

        message = update.get("message")
        if not isinstance(message, dict):
            continue
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        if str(chat.get("type") or "") != "private":
            continue
        if bool(sender.get("is_bot")):
            continue

        chat_id = str(chat.get("id") or "").strip()
        if not chat_id:
            continue

        text = str(message.get("text") or "").strip()
        existing = subscribers.get(chat_id)
        if existing:
            existing["username"] = str(
                sender.get("username") or existing.get("username") or ""
            ).strip()
            existing["first_name"] = str(
                sender.get("first_name") or existing.get("first_name") or ""
            ).strip()
            existing["last_name"] = str(
                sender.get("last_name") or existing.get("last_name") or ""
            ).strip()
            existing["last_seen_at"] = now_text
            continue

        if not text.lower().startswith("/start"):
            continue

        subscriber = {
            "chat_id": chat_id,
            "username": str(sender.get("username") or "").strip(),
            "first_name": str(sender.get("first_name") or "").strip(),
            "last_name": str(sender.get("last_name") or "").strip(),
            "connected_at": now_text,
            "last_seen_at": now_text,
        }
        subscribers[chat_id] = subscriber
        new_subscribers.append(subscriber)

    settings["last_update_id"] = last_update_id
    settings["subscribers"] = sorted(
        subscribers.values(),
        key=lambda item: (str(item.get("connected_at") or ""), str(item.get("chat_id") or "")),
    )
    return {
        "bot_username": settings.get("bot_username", ""),
        "new_subscribers": new_subscribers,
        "total_subscribers": len(settings["subscribers"]),
        "last_update_id": last_update_id,
        "subscribers": settings["subscribers"],
    }


def send_telegram_notification(message_text: str, message_html: str, settings: dict) -> dict:
    bot_token = str(settings.get("bot_token") or "").strip()
    chat_id = str(settings.get("chat_id") or "").strip()
    subscriber_ids = [
        str(item.get("chat_id") or "").strip()
        for item in settings.get("subscribers", [])
        if isinstance(item, dict) and str(item.get("chat_id") or "").strip()
    ]
    target_chat_ids = []
    for candidate in [*subscriber_ids, chat_id]:
        cleaned = str(candidate or "").strip()
        if cleaned and cleaned not in target_chat_ids:
            target_chat_ids.append(cleaned)
    if not bot_token or not target_chat_ids:
        raise ValueError("Telegram notifier is missing bot_token and at least one subscriber chat")

    text_payload = message_html or message_text
    sent_chat_ids: list[str] = []
    for target_chat_id in target_chat_ids:
        payload = {
            "chat_id": target_chat_id,
            "text": text_payload,
            "disable_web_page_preview": bool(settings.get("disable_link_preview", False)),
        }
        if message_html:
            payload["parse_mode"] = "HTML"
        _telegram_api_request(bot_token, "sendMessage", payload)
        sent_chat_ids.append(target_chat_id)

    return {
        "channel": "telegram",
        "sent": True,
        "chat_ids": sent_chat_ids,
        "subscriber_count": len(sent_chat_ids),
    }
