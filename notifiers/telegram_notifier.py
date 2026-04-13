"""Telegram bot delivery for the local job agent."""

import json
from urllib import parse, request


def send_telegram_notification(message_text: str, message_html: str, settings: dict) -> dict:
    bot_token = str(settings.get("bot_token") or "").strip()
    chat_id = str(settings.get("chat_id") or "").strip()
    if not bot_token or not chat_id:
        raise ValueError("Telegram notifier is missing bot_token or chat_id")

    text_payload = message_html or message_text
    payload = {
        "chat_id": chat_id,
        "text": text_payload,
        "disable_web_page_preview": bool(settings.get("disable_link_preview", False)),
    }
    if message_html:
        payload["parse_mode"] = "HTML"
    encoded = parse.urlencode(payload).encode("utf-8")
    endpoint = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    req = request.Request(endpoint, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8", errors="ignore") or "{}")
        if not data.get("ok"):
            raise ValueError(f"Telegram API error: {data}")

    return {
        "channel": "telegram",
        "sent": True,
        "chat_id": chat_id,
    }
