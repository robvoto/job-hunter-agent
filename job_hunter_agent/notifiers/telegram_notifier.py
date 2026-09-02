"""Telegram bot delivery for the local job agent."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from urllib import parse, request
from urllib.error import HTTPError

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.fit_scoring import fit_score_displayed
from job_hunter_agent.history import viewed_by_user
from job_hunter_agent.io_utils import load_job_history, load_run_stats
from job_hunter_agent.match_labels import score_to_match_label
from job_hunter_agent.posting_utils import get_manual_skip_sets, parse_timestamp
from job_hunter_agent.profile_store import load_profile
from job_hunter_agent.run_control import clear_run_stop_request
from job_hunter_agent.user_context import set_user_id
from job_hunter_agent.user_settings import get_workspace_minimum_score, load_user_settings
from job_hunter_agent.workspace_export import export_workspace_jobs, get_workspace_export_dir
from job_hunter_agent.workspace_service import build_workspace_record_sets, load_last_kept_records

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


def _send_telegram_message(
    bot_token: str, chat_id: str, text: str, *, parse_mode: str | None = None
) -> dict:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return _telegram_api_request(bot_token, "sendMessage", payload)


def _parse_telegram_command(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if not raw.startswith("/"):
        return "", ""
    command_line = raw.split(None, 1)[0]
    command = command_line.split("@", 1)[0].strip().lower()
    args = raw[len(command_line) :].strip()
    return command, args


def _telegram_actor_label(sender: dict, chat_id: str) -> str:
    username = str(sender.get("username") or "").strip()
    first_name = str(sender.get("first_name") or "").strip()
    last_name = str(sender.get("last_name") or "").strip()
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    if username and full_name:
        return f"{full_name} (@{username}) chat_id={chat_id}"
    if username:
        return f"@{username} chat_id={chat_id}"
    if full_name:
        return f"{full_name} chat_id={chat_id}"
    return f"chat_id={chat_id}"


def _telegram_help_text() -> str:
    return (
        "Job Hunter commands:\n"
        "/status - shows the desktop app status\n"
        "/filters - show the active search settings\n"
        "/summary - show the latest job summary\n"
        "/latest - same as /summary\n"
        "/run - start a new search with the app's default settings\n"
        "/export - export the current workspace job list\n"
        "/help - show this list"
    )


def _telegram_status_text() -> str:
    lines = [
        "Job Hunter is running and Telegram is available while the desktop app is open.",
    ]
    configured_export_dir = str(os.environ.get("JOB_HUNTER_WORKSPACE_EXPORT_DIR") or "").strip()
    if configured_export_dir:
        lines.append(f"Workspace export folder: {get_workspace_export_dir()}")
    lines.append("Use /filters, /summary, /run, /export, or /help.")
    return "\n".join(lines)


def _telegram_start_text() -> str:
    return (
        "Job Hunter is connected.\n"
        "Use /status, /filters, /summary, /latest, /run, /export, or /help."
    )


def _telegram_export_text(result: dict, mode: str) -> str:
    return (
        f"Exported {result.get('job_count', 0)} jobs to {result.get('json_path', '')}.\n"
        "This exported the current workspace for cowork. Use /run to fetch fresh jobs."
    )


def _telegram_export_usage_text() -> str:
    return (
        "/export only writes the current workspace to the cowork handoff file.\n"
        "It does not run a new search.\n"
        "Use /run to fetch fresh jobs, then /export to hand them off."
    )


def _telegram_run_text() -> str:
    return "Search started using the app's default configured parameters."


def _build_search_settings_text() -> str:
    profile = load_profile()
    search_settings = profile.get("search_settings", {}) if isinstance(profile, dict) else {}
    sources = profile.get("enabled_sources", []) if isinstance(profile, dict) else []
    target_roles = profile.get("target_roles", []) if isinstance(profile, dict) else []
    alternative_roles = profile.get("also_consider_roles", []) if isinstance(profile, dict) else []
    salary_preferences = profile.get("salary_preferences", {}) if isinstance(profile, dict) else {}
    match_preferences = profile.get("match_preferences", {}) if isinstance(profile, dict) else {}
    settings = load_user_settings(None, create_if_missing=False)
    workspace_settings = settings.get("workspace", {}) if isinstance(settings, dict) else {}

    locations = [str(value).strip() for value in search_settings.get("locations", []) if str(value).strip()]
    source_labels = [str(value).strip().upper() for value in sources if str(value).strip()]
    roles = []
    seen_roles = set()
    for value in [*target_roles, *alternative_roles]:
        role = str(value).strip()
        role_key = role.casefold()
        if role and role_key not in seen_roles:
            seen_roles.add(role_key)
            roles.append(role)
    home_location = str(match_preferences.get("home_location") or "").strip() or "not set"
    work_modes = [str(value).strip() for value in match_preferences.get("work_mode_preference", []) if str(value).strip()]
    engagement_types = [str(value).strip() for value in match_preferences.get("engagement_type", []) if str(value).strip()]
    sector_values = [str(value).strip() for value in match_preferences.get("prefer_sector", []) if str(value).strip()]
    yearly_salary = int(salary_preferences.get("minimum_salary_yearly", 0) or 0)
    daily_rate = int(salary_preferences.get("minimum_daily_rate", 0) or 0)
    lines = [
        "Active search settings",
        "",
        "Search",
        f"Roles: {', '.join(roles) if roles else 'not set'}",
        f"Locations: {', '.join(locations) if locations else 'not set'}",
        f"Sources: {', '.join(source_labels) if source_labels else 'not set'}",
        f"Date range: last {int(search_settings.get('date_range_days', 0) or 0)} day(s)",
        f"SEEK pages: {int(search_settings.get('seek_max_pages', 0) or 0)}",
        f"LinkedIn age: last {int(search_settings.get('linkedin_hours_old', 0) or 0)} hour(s)",
        f"LinkedIn results/search: {int(search_settings.get('linkedin_results_per_search', 0) or 0)}",
        "",
        "Targets",
        f"Target roles: {', '.join(roles[:5]) if roles else 'not set'}",
        f"Home location: {home_location}",
        f"Work modes: {', '.join(work_modes) if work_modes else 'not set'}",
        f"Engagement types: {', '.join(engagement_types) if engagement_types else 'not set'}",
        f"Sector preference: {', '.join(sector_values) if sector_values else 'any'}",
        "",
        "Thresholds",
        f"Workspace minimum score: {int(workspace_settings.get('minimum_score', 0) or 0)}",
        f"Minimum salary: ${yearly_salary:,}/year" if yearly_salary > 0 else "Minimum salary: not set",
        f"Minimum daily rate: ${daily_rate:,}/day" if daily_rate > 0 else "Minimum daily rate: not set",
    ]
    return "\n".join(lines)


def _latest_summary_context() -> tuple[dict, dict, dict[str, list[dict]], list[dict]]:
    profile = load_profile()
    run_stats = load_run_stats()
    kept_records = load_last_kept_records()
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    run_reference = (
        parse_timestamp(
            str(run_stats.get("run_finished_at") or run_stats.get("run_started_at") or "")
        )
        or datetime.now().astimezone()
    )
    workspace_records = build_workspace_record_sets(
        kept_records,
        load_job_history(),
        applied_job_keys,
        hidden_job_keys,
        run_reference,
        profile,
        get_workspace_minimum_score(profile),
    )
    current_records = list(workspace_records.get("current_records", []))
    return profile, run_stats, workspace_records, current_records


def _format_latest_summary_job(record: dict, index: int, profile: dict) -> str:
    title = str(record.get("title") or "Untitled")
    company = str(record.get("company") or "N/A")
    location = str(record.get("location") or "N/A")
    posted = str(record.get("posted") or "N/A")
    source = str(record.get("source") or "N/A").upper()
    url = str(record.get("url") or "").strip()
    score = fit_score_displayed(record, profile)
    match_label = score_to_match_label(score, profile.get("match_levels", []))
    lines = [
        f"{index}. {title} - {company}",
        f"{score}/100 ({match_label}) | {source} | {posted} | {location}",
    ]
    if url:
        lines.append(url)
    return "\n".join(lines)


def _build_latest_summary_text() -> str:
    profile, run_stats, workspace_records, current_records = _latest_summary_context()
    run_started_at = str(run_stats.get("run_started_at") or "").strip()
    run_finished_at = str(run_stats.get("run_finished_at") or "").strip()
    saved_records = (
        list(workspace_records.get("recent_archive_records", []))
        + list(workspace_records.get("stale_archive_records", []))
    )
    unopened_records = [
        record for record in [*workspace_records.get("current_records", []), *saved_records] if not viewed_by_user(record)
    ]

    lines = [
        "Latest Job Summary",
    ]
    if run_started_at:
        lines.append(f"Last collection started: {run_started_at}")
    else:
        lines.append("Last collection started: not available yet")
    if run_finished_at:
        lines.append(f"Last collection finished: {run_finished_at}")
    else:
        lines.append("Last collection finished: not available yet")
    lines.append(f"Current matches: {len(current_records)}")
    lines.append(
        f"Saved from earlier: {len(saved_records)} | Unopened on workspace: {len(unopened_records)}"
    )
    lines.append("")

    if current_records:
        lines.append("Top current matches:")
        top_records = sorted(
            current_records,
            key=lambda record: (
                -fit_score_displayed(record, profile),
                str(record.get("title") or "").lower(),
                str(record.get("company") or "").lower(),
            ),
        )[:3]
        for index, record in enumerate(top_records, start=1):
            lines.append(_format_latest_summary_job(record, index, profile))
    else:
        lines.append("No current matches yet.")

    configured_export_dir = str(os.environ.get("JOB_HUNTER_WORKSPACE_EXPORT_DIR") or "").strip()
    if configured_export_dir:
        lines.append("")
        lines.append(f"Workspace export folder: {get_workspace_export_dir()}")
    return "\n".join(lines).strip()


def _start_default_search(user_id: str) -> str:
    clean_user_id = str(user_id or "").strip()
    if not clean_user_id:
        raise ValueError("A signed-in account is required to start a search.")

    if not srv._try_mark_run_started():
        return "A search is already running."

    clear_run_stop_request()

    def _run() -> None:
        set_user_id(clean_user_id)
        try:
            srv._run_scrape_job()
        finally:
            set_user_id(None)

    threading.Thread(target=_run, daemon=True, name=f"telegram-run-{clean_user_id}").start()
    return _telegram_run_text()


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
    return f"https://web.telegram.org/k/#@{bot_username}"


def sync_telegram_subscribers(settings: dict, *, user_id: str | None = None) -> dict:
    bot_token = str(settings.get("bot_token") or "").strip()
    if not bot_token:
        raise ValueError("Telegram bot token is missing")

    if user_id:
        set_user_id(user_id)

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
    command_results: list[dict[str, str]] = []
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
        command, args = _parse_telegram_command(text)
        actor_label = _telegram_actor_label(sender, chat_id)
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
        elif command != "/start":
            continue

        if command == "/start" and chat_id not in subscribers:
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

        if command:
            logger.info(
                "[TELEGRAM] command requested: %s via bot @%s by %s",
                command,
                username or str(settings.get("bot_username") or "").strip().lstrip("@") or "unknown",
                actor_label,
            )

        reply_text = ""
        try:
            if command == "/start":
                reply_text = _telegram_start_text()
            elif command == "/help":
                reply_text = _telegram_help_text()
            elif command in {"/filters", "/search"}:
                reply_text = _build_search_settings_text()
            elif command == "/status":
                reply_text = _telegram_status_text()
            elif command in {"/summary", "/latest"}:
                reply_text = _build_latest_summary_text()
            elif command == "/export":
                if args.strip():
                    reply_text = _telegram_export_usage_text()
                else:
                    export_result = export_workspace_jobs(mode="merge")
                    reply_text = _telegram_export_text(export_result, "merge")
            elif command == "/run":
                if not user_id:
                    raise ValueError("Telegram /run requires a signed-in account.")
                reply_text = _start_default_search(user_id)
        except Exception as exc:
            logger.warning(
                "[TELEGRAM][WARN] Failed to process %s for chat %s: %s",
                command or "/start",
                chat_id,
                exc,
            )
            reply_text = f"Telegram command {command or '/start'} failed: {exc}"

        if reply_text:
            try:
                _send_telegram_message(bot_token, chat_id, reply_text)
                command_results.append({"chat_id": chat_id, "command": command or "/start"})
            except Exception as exc:
                logger.warning(
                    "[TELEGRAM][WARN] Failed to send %s reply to chat %s: %s",
                    command or "/start",
                    chat_id,
                    exc,
                )
                command_results.append(
                    {
                        "chat_id": chat_id,
                        "command": command or "/start",
                        "status": "send_failed",
                    }
                )

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
        "command_results": command_results,
        "commands_processed": len(command_results),
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
