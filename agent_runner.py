"""Daily local agent runner.

Main goals:
- run the current job-source connector on a schedule or on demand
- build a compact daily digest from the latest results
- send that digest through configured local notification channels
"""

import argparse
import html
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_settings import (
    ROOT_DIR,
    load_agent_settings,
    load_agent_state,
    save_agent_state,
)
from config import OUTPUT_HTML
from notifiers.email_notifier import send_email_notification
from notifiers.telegram_notifier import send_telegram_notification, sync_telegram_subscribers
from agent_settings import save_agent_settings
from profile_store import load_profile
from source_connector import (
    RUN_STATS_PATH,
    build_dashboard_record_sets,
    fit_score,
    get_manual_skip_sets,
    load_json_dict,
    load_job_history,
    load_last_kept_records,
    parse_timestamp,
    rebuild_html_dashboard,
    scrape_jobs_direct,
    viewed_by_user,
)


OUTPUT_DIR = ROOT_DIR / "output"
AGENT_SUMMARY_PATH = OUTPUT_DIR / "agent_last_summary.txt"


def configure_console_output() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _job_key(record: dict) -> str:
    return str(record.get("job_key") or record.get("url") or "").strip()


def build_dashboard_reference(settings: dict[str, Any]) -> str:
    dashboard_url = str(settings.get("dashboard_url") or "").strip()
    if dashboard_url:
        return dashboard_url
    return f"http://127.0.0.1:8765/dashboard ({ROOT_DIR / OUTPUT_HTML})"


def load_latest_run_stats() -> dict[str, Any]:
    payload = load_json_dict(RUN_STATS_PATH)
    return payload if isinstance(payload, dict) else {}


def _resolve_collection_timestamps(run_stats: dict[str, Any]) -> tuple[str, str]:
    run_started_at = parse_timestamp(str(run_stats.get("run_started_at") or ""))
    run_finished_at = parse_timestamp(str(run_stats.get("run_finished_at") or ""))
    fallback = datetime.now().astimezone().isoformat(timespec="seconds")
    started_text = run_started_at.isoformat(timespec="seconds") if run_started_at else fallback
    finished_text = run_finished_at.isoformat(timespec="seconds") if run_finished_at else started_text
    return started_text, finished_text


def _format_summary_timestamp(value: str) -> str:
    return value.replace("T", " ").replace("+10:00", " AEST").replace("+11:00", " AEDT")


def build_digest_payload(
    previous_records: list[dict],
    current_records: list[dict],
    dashboard_records: dict[str, list[dict]],
    settings: dict[str, Any],
    run_stats: dict[str, Any],
) -> dict[str, Any]:
    previous_keys = {_job_key(record) for record in previous_records if _job_key(record)}
    current_keys = {_job_key(record) for record in current_records if _job_key(record)}
    new_records = [record for record in current_records if _job_key(record) and _job_key(record) not in previous_keys]
    saved_records = dashboard_records.get("recent_archive_records", []) + dashboard_records.get("stale_archive_records", [])
    visible_dashboard_records = dashboard_records.get("current_records", []) + saved_records
    dashboard_unopened_records = [record for record in visible_dashboard_records if not viewed_by_user(record)]
    minimum_fit_score = int(settings["notification_rules"]["minimum_fit_score"])
    max_jobs = int(settings["notification_rules"]["max_jobs_in_digest"])
    run_started_at, run_finished_at = _resolve_collection_timestamps(run_stats)

    strongest_records = sorted(
        [record for record in current_records if fit_score(record) >= minimum_fit_score],
        key=lambda record: (-fit_score(record), record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999),
    )[:max_jobs]
    featured_records = new_records[:max_jobs]
    featured_heading = "New matches"

    return {
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "digest_created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "current_count": len(current_records),
        "saved_count": len(saved_records),
        "dashboard_count": len(visible_dashboard_records),
        "new_count": len(new_records),
        "dashboard_unopened_count": len(dashboard_unopened_records),
        "new_records": new_records[:max_jobs],
        "strongest_records": strongest_records,
        "featured_records": featured_records,
        "featured_heading": featured_heading,
        "status_message": (
            "No new strong matches found this run. Your dashboard was refreshed and kept current."
            if not new_records
            else ""
        ),
        "dashboard_reference": build_dashboard_reference(settings),
        "current_keys": sorted(current_keys),
    }


def format_job_line(record: dict, index: int | None = None) -> str:
    posted = str(record.get("posted") or "N/A")
    company = str(record.get("company") or "N/A")
    title = str(record.get("title") or "Untitled")
    location = str(record.get("location") or "N/A")
    score = fit_score(record)
    url = str(record.get("url") or "").strip()
    prefix = f"{index}. " if index is not None else "- "
    lines = [
        f"{prefix}{title} - {company}",
        f"   {score}/100 | {posted} | {location}",
    ]
    if url:
        lines.append(f"   {url}")
    return "\n".join(lines)


def format_job_html(record: dict, index: int | None = None) -> str:
    posted = html.escape(str(record.get("posted") or "N/A"))
    company = html.escape(str(record.get("company") or "N/A"))
    title = html.escape(str(record.get("title") or "Untitled"))
    location = html.escape(str(record.get("location") or "N/A"))
    score = fit_score(record)
    url = str(record.get("url") or "").strip()
    prefix = f"{index}. " if index is not None else ""
    detail_line = f"{score}/100 | {posted} | {location}"
    link_line = f'\n<a href="{html.escape(url)}">View role</a>' if url else ""
    return f"<b>{html.escape(prefix)}{title}</b> - {company}\n{detail_line}{link_line}"


def format_daily_summary(payload: dict[str, Any]) -> str:
    run_started_at = str(payload.get("run_started_at", "Unknown"))
    run_finished_at = str(payload.get("run_finished_at", run_started_at))
    lines = [
        "Daily Job Summary",
        f"Collection started: {_format_summary_timestamp(run_started_at)}",
        f"Collection finished: {_format_summary_timestamp(run_finished_at)}",
        f"Matches this run: {payload.get('current_count', 0)} | New this run: {payload.get('new_count', 0)}",
        f"Saved from earlier: {payload.get('saved_count', 0)} | Unopened on dashboard: {payload.get('dashboard_unopened_count', 0)}",
        "",
    ]

    featured_records = payload.get("featured_records", [])
    if featured_records:
        lines.append(f"{payload.get('featured_heading', 'Top current matches')}:")
        lines.extend(format_job_line(record, index + 1) for index, record in enumerate(featured_records))
        lines.append("")
    elif payload.get("status_message"):
        lines.append(str(payload.get("status_message")))
        lines.append("")

    lines.append(f"Dashboard: {payload.get('dashboard_reference', '')}")
    return "\n".join(lines).strip()


def format_daily_summary_html(payload: dict[str, Any]) -> str:
    run_started_at = html.escape(_format_summary_timestamp(str(payload.get("run_started_at", "Unknown"))))
    run_finished_at = html.escape(
        _format_summary_timestamp(str(payload.get("run_finished_at", payload.get("run_started_at", "Unknown"))))
    )
    summary_line = (
        f"Matches this run: <b>{payload.get('current_count', 0)}</b> | "
        f"New this run: <b>{payload.get('new_count', 0)}</b>"
    )
    dashboard_line = (
        f"Saved from earlier: <b>{payload.get('saved_count', 0)}</b> | "
        f"Unopened on dashboard: <b>{payload.get('dashboard_unopened_count', 0)}</b>"
    )
    parts = [
        "<b>Daily Job Summary</b>",
        f"Collection started: {run_started_at}",
        f"Collection finished: {run_finished_at}",
        summary_line,
        dashboard_line,
    ]

    featured_records = payload.get("featured_records", [])
    if featured_records:
        parts.append("")
        parts.append(f"<b>{html.escape(str(payload.get('featured_heading', 'Top current matches')))}:</b>")
        parts.extend(format_job_html(record, index + 1) for index, record in enumerate(featured_records))
    elif payload.get("status_message"):
        parts.append("")
        parts.append(html.escape(str(payload.get("status_message") or "")))

    dashboard_reference = str(payload.get("dashboard_reference", "")).strip()
    if dashboard_reference:
        if dashboard_reference.startswith("http://") or dashboard_reference.startswith("https://"):
            parts.append("")
            parts.append(f'<a href="{html.escape(dashboard_reference)}">Open dashboard</a>')
        else:
            parts.append("")
            parts.append(f"Dashboard: {html.escape(dashboard_reference)}")
    return "\n".join(part for part in parts if part is not None)


def write_last_summary(summary_text: str) -> None:
    AGENT_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_SUMMARY_PATH.write_text(summary_text, encoding="utf-8")


def send_daily_notifications(summary_text: str, summary_html: str, settings: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    subject_prefix = str(settings["email"].get("subject_prefix") or "[Job Hunter]").strip()
    subject = f"{subject_prefix} Daily Job Summary"

    if settings["email"].get("enabled"):
        results.append(send_email_notification(subject, summary_text, summary_html, settings["email"]))
    if settings["telegram"].get("enabled"):
        results.append(send_telegram_notification(summary_text, summary_html, settings["telegram"]))
    return results


def should_send_digest(payload: dict[str, Any], settings: dict[str, Any]) -> bool:
    if not settings["notification_rules"].get("only_if_new_matches", False):
        return True
    return int(payload.get("new_count", 0)) > 0


def run_agent_once(skip_collection: bool = False, notify: bool = True) -> dict[str, Any]:
    settings = load_agent_settings(create_if_missing=True)
    state = load_agent_state()
    previous_records = load_last_kept_records()

    if skip_collection:
        print("Rebuilding dashboard from current local state...")
        rebuild_html_dashboard()
    else:
        print("Starting job collection...")
        scrape_jobs_direct()
        print("Job collection finished.")

    current_records = load_last_kept_records()
    run_stats = load_latest_run_stats()
    profile = load_profile()
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    dashboard_records = build_dashboard_record_sets(
        current_records,
        load_job_history(),
        applied_job_keys,
        hidden_job_keys,
        parse_timestamp(str(run_stats.get("run_finished_at") or run_stats.get("run_started_at") or "")) or datetime.now().astimezone(),
        profile,
    )
    print("Building daily digest...")
    payload = build_digest_payload(previous_records, current_records, dashboard_records, settings, run_stats)
    summary_text = format_daily_summary(payload)
    summary_html = format_daily_summary_html(payload)
    write_last_summary(summary_text)

    notification_results: list[dict[str, Any]] = []
    if not notify:
        print("Notifications skipped because --no-notify was used.")
    elif should_send_digest(payload, settings):
        if settings["telegram"].get("enabled") and settings["telegram"].get("bot_token"):
            try:
                sync_result = sync_telegram_subscribers(settings["telegram"])
                save_agent_settings(settings)
                print(f"Telegram subscribers synced: {sync_result['total_subscribers']}")
            except Exception as exc:
                print(f"Telegram subscriber sync skipped: {exc}")
        print("Sending notifications...")
        notification_results = send_daily_notifications(summary_text, summary_html, settings)
        print(f"Notifications sent: {len(notification_results)} channel(s).")
    else:
        print("Notifications skipped because there were no new matches to send.")

    state.update({
        "last_agent_run_at": payload["run_finished_at"],
        "last_notified_run_at": payload["run_finished_at"] if notification_results else state.get("last_notified_run_at"),
        "last_current_keys": payload["current_keys"],
        "last_summary_path": str(AGENT_SUMMARY_PATH),
        "last_dashboard_reference": payload["dashboard_reference"],
    })
    save_agent_state(state)

    return {
        "ok": True,
        "summary": payload,
        "summary_text": summary_text,
        "notifications": notification_results,
        "summary_path": str(AGENT_SUMMARY_PATH),
    }


def should_run_now(state: dict[str, Any], daily_time_local: str, now: datetime) -> bool:
    try:
        hour_text, minute_text = daily_time_local.split(":", 1)
        scheduled_hour = int(hour_text)
        scheduled_minute = int(minute_text)
    except Exception:
        scheduled_hour = 8
        scheduled_minute = 30

    last_run_at = str(state.get("last_agent_run_at") or "")
    last_run_day = last_run_at[:10]
    today = now.date().isoformat()
    after_window = (now.hour, now.minute) >= (scheduled_hour, scheduled_minute)
    return after_window and last_run_day != today


def run_agent_loop() -> None:
    settings = load_agent_settings(create_if_missing=True)
    sleep_seconds = int(settings["schedule"]["loop_sleep_seconds"])
    daily_time_local = str(settings["schedule"]["daily_time_local"] or "08:30").strip()
    print(f"Daily agent loop started. Scheduled local time: {daily_time_local}")

    while True:
        now = datetime.now().astimezone()
        state = load_agent_state()
        if should_run_now(state, daily_time_local, now):
            result = run_agent_once(skip_collection=False, notify=True)
            print(result["summary_text"])
            print(f"Summary saved to {result['summary_path']}")
        time.sleep(sleep_seconds)


def main() -> None:
    configure_console_output()
    parser = argparse.ArgumentParser(description="Run the local daily job agent.")
    parser.add_argument("--loop", action="store_true", help="Keep running and trigger once per day at the configured local time.")
    parser.add_argument("--skip-collection", action="store_true", help="Do not fetch new jobs; just rebuild the dashboard and send a digest from current local state.")
    parser.add_argument("--no-notify", action="store_true", help="Build the digest without sending email or Telegram notifications.")
    args = parser.parse_args()

    if args.loop:
        run_agent_loop()
        return

    result = run_agent_once(skip_collection=args.skip_collection, notify=not args.no_notify)
    print(result["summary_text"])
    print("")
    print(json.dumps({
        "summary_path": result["summary_path"],
        "notifications": result["notifications"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
