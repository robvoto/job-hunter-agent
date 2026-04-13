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
from notifiers.telegram_notifier import send_telegram_notification
from scraper_direct import fit_score, load_last_kept_records, rebuild_html_dashboard, scrape_seek_jobs_direct, viewed_by_user


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


def build_digest_payload(previous_records: list[dict], current_records: list[dict], settings: dict[str, Any]) -> dict[str, Any]:
    previous_keys = {_job_key(record) for record in previous_records if _job_key(record)}
    current_keys = {_job_key(record) for record in current_records if _job_key(record)}
    new_records = [record for record in current_records if _job_key(record) and _job_key(record) not in previous_keys]
    unseen_records = [record for record in current_records if not viewed_by_user(record)]
    minimum_fit_score = int(settings["notification_rules"]["minimum_fit_score"])
    max_jobs = int(settings["notification_rules"]["max_jobs_in_digest"])

    strongest_records = sorted(
        [record for record in current_records if fit_score(record) >= minimum_fit_score],
        key=lambda record: (-fit_score(record), record.get("posted_age_days") if record.get("posted_age_days") is not None else 9999),
    )[:max_jobs]
    featured_records = new_records[:max_jobs]
    featured_heading = "New matches"

    return {
        "run_started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "current_count": len(current_records),
        "new_count": len(new_records),
        "unseen_count": len(unseen_records),
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
    link_line = f'<br><a href="{html.escape(url)}">View role</a>' if url else ""
    return f"<b>{html.escape(prefix)}{title}</b> - {company}<br>{detail_line}{link_line}"


def format_daily_summary(payload: dict[str, Any]) -> str:
    run_started_at = str(payload.get("run_started_at", "Unknown"))
    run_label = run_started_at.replace("T", " ").replace("+10:00", " AEST").replace("+11:00", " AEDT")
    lines = [
        "Daily Job Summary",
        run_label,
        f"Fresh: {payload.get('current_count', 0)} | New: {payload.get('new_count', 0)} | Unopened: {payload.get('unseen_count', 0)}",
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
    run_started_at = html.escape(str(payload.get("run_started_at", "Unknown")).replace("T", " "))
    summary_line = (
        f"Fresh: <b>{payload.get('current_count', 0)}</b> | "
        f"New: <b>{payload.get('new_count', 0)}</b> | "
        f"Unopened: <b>{payload.get('unseen_count', 0)}</b>"
    )
    parts = [
        "<b>Daily Job Summary</b>",
        run_started_at,
        summary_line,
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
    return "<br>".join(part for part in parts if part is not None)


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
        rebuild_html_dashboard()
    else:
        scrape_seek_jobs_direct()

    current_records = load_last_kept_records()
    payload = build_digest_payload(previous_records, current_records, settings)
    summary_text = format_daily_summary(payload)
    summary_html = format_daily_summary_html(payload)
    write_last_summary(summary_text)

    notification_results: list[dict[str, Any]] = []
    if notify and should_send_digest(payload, settings):
        notification_results = send_daily_notifications(summary_text, summary_html, settings)

    state.update({
        "last_agent_run_at": payload["run_started_at"],
        "last_notified_run_at": payload["run_started_at"] if notification_results else state.get("last_notified_run_at"),
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
