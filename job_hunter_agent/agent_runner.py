"""Daily local agent runner coordination and digest generation.

Main goals:
- run the current job-source connector on a schedule or on demand
- build a compact daily digest from the latest results
- send that digest through configured local notification channels

This module orchestrates the execution of job scrapers, processes the results
to build daily digests, and sends notifications via email or Telegram. It
manages the agent's scheduled runs, maintains runtime state, and ensures
consistent delivery of match summaries to the user.
"""

import argparse
import html
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from job_hunter_agent.runtime_helpers import load_repo_dotenv

load_repo_dotenv()

from job_hunter_agent.fit_scoring import fit_score_displayed
from job_hunter_agent.history import viewed_by_user
from job_hunter_agent.io_utils import configure_console_output, load_job_history, load_run_stats
from job_hunter_agent.job_identity import find_confirmed_duplicate, normalize_job_key
from job_hunter_agent.match_labels import score_to_match_label
from job_hunter_agent.notifiers.email_notifier import send_email_notification
from job_hunter_agent.notifiers.telegram_notifier import (
    send_telegram_notification,
    sync_telegram_subscribers,
)
from job_hunter_agent.paths import OUTPUT_DIR, get_workspace_results_path
from job_hunter_agent.posting_utils import get_manual_skip_sets, parse_timestamp
from job_hunter_agent.profile_store import load_profile
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_JOB_KEY,
    RECORD_LOCATION_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_POSTED_KEY,
    RECORD_SOURCE_KEY,
    RECORD_SOURCE_NAME_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
)
from job_hunter_agent.source_connector import (
    scrape_jobs_direct,
)
from job_hunter_agent.user_settings import (
    DEFAULT_DAILY_TIME_LOCAL,
    DEFAULT_SUBJECT_PREFIX,
    DEFAULT_WORKSPACE_URL,
    KEY_EMAIL,
    KEY_LLM,
    KEY_NOTIFICATION_RULES,
    KEY_ONLY_IF_NEW_MATCHES,
    KEY_TELEGRAM,
    load_agent_state,
    load_user_settings,
    save_agent_state,
    save_user_settings,
)
from job_hunter_agent.workspace_rebuild_service import rebuild_workspace_results
from job_hunter_agent.workspace_service import build_workspace_record_sets, load_last_kept_records

AGENT_SUMMARY_PATH = OUTPUT_DIR / "agent_last_summary.txt"

# Digest payload keys
KEY_DIGEST_NEW_RECORDS = "new_records"
KEY_DIGEST_STRONGEST_RECORDS = "strongest_records"
KEY_DIGEST_FEATURED_RECORDS = "featured_records"
KEY_DIGEST_FEATURED_HEADING = "featured_heading"
KEY_DIGEST_STATUS_MESSAGE = "status_message"
KEY_DIGEST_NEW_COUNT = "new_count"
KEY_DIGEST_CURRENT_COUNT = "current_count"
KEY_DIGEST_SAVED_COUNT = "saved_count"
KEY_DIGEST_WORKSPACE_COUNT = "workspace_count"
KEY_DIGEST_UNOPENED_COUNT = "workspace_unopened_count"
KEY_DIGEST_WORKSPACE_REF = "workspace_reference"

# Workspace record set keys (from build_workspace_record_sets)
KEY_DS_CURRENT = "current_records"
KEY_DS_APPLIED = "applied_records"
KEY_DS_RECENT_ARCHIVE = "recent_archive_records"
KEY_DS_STALE_ARCHIVE = "stale_archive_records"

# Summary labels
LABEL_NEW_MATCHES = "New matches"
LABEL_TOP_MATCHES = "Top current matches"
MSG_NO_NEW_MATCHES = (
    "No new strong matches found this run. Your workspace was refreshed and kept current."
)


def _job_key(record: dict) -> str:
    val = record.get(RECORD_JOB_KEY) or record.get(RECORD_URL_KEY)
    source = record.get(RECORD_SOURCE_KEY) or record.get(RECORD_SOURCE_NAME_KEY)
    return normalize_job_key(str(val or ""), source=source)


def _safe_job_key(record: dict) -> str | None:
    key = _job_key(record)
    return key if key else None


def build_workspace_reference(settings: dict[str, Any]) -> str:
    workspace_url = str(settings.get("workspace_url") or "").strip()
    if workspace_url:
        return workspace_url
    return f"{DEFAULT_WORKSPACE_URL} ({get_workspace_results_path()})"


def load_latest_run_stats() -> dict[str, Any]:
    payload = load_run_stats()
    return payload if isinstance(payload, dict) else {}


def _resolve_collection_timestamps(run_stats: dict[str, Any]) -> tuple[str, str]:
    run_started_at = parse_timestamp(str(run_stats.get("run_started_at") or ""))
    run_finished_at = parse_timestamp(str(run_stats.get("run_finished_at") or ""))
    fallback = datetime.now().astimezone().isoformat(timespec="seconds")
    started_text = run_started_at.isoformat(timespec="seconds") if run_started_at else fallback
    finished_text = (
        run_finished_at.isoformat(timespec="seconds") if run_finished_at else started_text
    )
    return started_text, finished_text


def _format_summary_timestamp(value: str) -> str:
    dt = parse_timestamp(value)
    if not dt:
        return value
    # Consistent human-readable output without hardcoded timezone strings
    return dt.strftime("%Y-%m-%d %H:%M %Z").strip()


def build_digest_payload(
    previous_records: list[dict],
    current_records: list[dict],
    workspace_records: dict[str, list[dict]],
    settings: dict[str, Any],
    run_stats: dict[str, Any],
) -> dict[str, Any]:
    previous_keys = {k for r in previous_records if (k := _safe_job_key(r))}
    current_keys_list = [k for r in current_records if (k := _safe_job_key(r))]
    current_keys = set(current_keys_list)

    new_records = [r for r in current_records if (k := _safe_job_key(r)) and k not in previous_keys]

    # Deduplication safety net: skip notifying for confirmed duplicates already known
    # (previous run, archive, applied) or repeated in this batch.
    existing_pool = (
        previous_records
        + workspace_records.get(KEY_DS_APPLIED, [])
        + workspace_records.get(KEY_DS_RECENT_ARCHIVE, [])
        + workspace_records.get(KEY_DS_STALE_ARCHIVE, [])
    )
    unique_new = []
    for record in new_records:
        if not find_confirmed_duplicate(record, existing_pool) and not find_confirmed_duplicate(
            record, unique_new
        ):
            unique_new.append(record)
    new_records = unique_new

    saved_records = workspace_records.get(KEY_DS_RECENT_ARCHIVE, []) + workspace_records.get(
        KEY_DS_STALE_ARCHIVE, []
    )
    visible_workspace_records = workspace_records.get(KEY_DS_CURRENT, []) + saved_records
    workspace_unopened_records = [
        record for record in visible_workspace_records if not viewed_by_user(record)
    ]
    minimum_fit_score = int(settings[KEY_NOTIFICATION_RULES]["minimum_fit_score"])
    max_jobs = int(settings[KEY_NOTIFICATION_RULES]["max_jobs_in_digest"])
    run_started_at, run_finished_at = _resolve_collection_timestamps(run_stats)

    strongest_records = sorted(
        [record for record in current_records if fit_score_displayed(record) >= minimum_fit_score],
        key=lambda record: (
            -fit_score_displayed(record),
            record.get(RECORD_POSTED_AGE_DAYS_KEY)
            if record.get(RECORD_POSTED_AGE_DAYS_KEY) is not None
            else 9999,
        ),
    )[:max_jobs]
    featured_records = new_records[:max_jobs]
    featured_heading = LABEL_NEW_MATCHES

    return {
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "digest_created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        KEY_DIGEST_CURRENT_COUNT: len(current_records),
        KEY_DIGEST_SAVED_COUNT: len(saved_records),
        KEY_DIGEST_WORKSPACE_COUNT: len(visible_workspace_records),
        KEY_DIGEST_NEW_COUNT: len(new_records),
        KEY_DIGEST_UNOPENED_COUNT: len(workspace_unopened_records),
        KEY_DIGEST_NEW_RECORDS: new_records[:max_jobs],
        KEY_DIGEST_STRONGEST_RECORDS: strongest_records,
        KEY_DIGEST_FEATURED_RECORDS: featured_records,
        KEY_DIGEST_FEATURED_HEADING: featured_heading,
        KEY_DIGEST_STATUS_MESSAGE: (MSG_NO_NEW_MATCHES if not new_records else ""),
        KEY_DIGEST_WORKSPACE_REF: build_workspace_reference(settings),
        "current_keys": sorted(current_keys),
    }


def format_job_line(record: dict, index: int | None = None) -> str:
    posted = str(record.get(RECORD_POSTED_KEY) or "N/A")
    company = str(record.get(RECORD_COMPANY_KEY) or "N/A")
    title = str(record.get(RECORD_TITLE_KEY) or "Untitled")
    location = str(record.get(RECORD_LOCATION_KEY) or "N/A")
    score = fit_score_displayed(record)
    score_label = score_to_match_label(score, load_profile().get("match_levels", []))
    source = str(record.get(RECORD_SOURCE_KEY) or "N/A").upper()
    url = str(record.get(RECORD_URL_KEY) or "").strip()
    prefix = f"{index}. " if index is not None else "- "
    lines = [
        f"{prefix}{title} - {company}",
        f"   {score}/100 ({score_label}) | {source} | {posted} | {location}",
    ]
    if url:
        lines.append(f"   {url}")
    return "\n".join(lines)


def format_job_html(record: dict, index: int | None = None) -> str:
    posted = html.escape(str(record.get(RECORD_POSTED_KEY) or "N/A"))
    company = html.escape(str(record.get(RECORD_COMPANY_KEY) or "N/A"))
    title = html.escape(str(record.get(RECORD_TITLE_KEY) or "Untitled"))
    location = html.escape(str(record.get(RECORD_LOCATION_KEY) or "N/A"))
    score = fit_score_displayed(record)
    score_label = html.escape(score_to_match_label(score, load_profile().get("match_levels", [])))
    source = html.escape(str(record.get(RECORD_SOURCE_KEY) or "N/A").upper())
    url = str(record.get(RECORD_URL_KEY) or "").strip()
    prefix = f"{index}. " if index is not None else ""
    detail_line = f"{score}/100 (<b>{score_label}</b>) | {source} | {posted} | {location}"
    link_line = f'\n<a href="{html.escape(url)}">View role</a>' if url else ""
    return f"<b>{html.escape(prefix)}{title}</b> - {company}\n{detail_line}{link_line}"


def format_daily_summary(payload: dict[str, Any]) -> str:
    run_started_at = str(payload.get("run_started_at", "Unknown"))
    run_finished_at = str(payload.get("run_finished_at", run_started_at))
    lines = [
        "Daily Job Summary",
        f"Collection started: {_format_summary_timestamp(run_started_at)}",
        f"Collection finished: {_format_summary_timestamp(run_finished_at)}",
        f"Matches this run: {payload.get(KEY_DIGEST_CURRENT_COUNT, 0)} | New this run: {payload.get(KEY_DIGEST_NEW_COUNT, 0)}",
        f"Saved from earlier: {payload.get(KEY_DIGEST_SAVED_COUNT, 0)} | Unopened on workspace: {payload.get(KEY_DIGEST_UNOPENED_COUNT, 0)}",
        "",
    ]

    featured_records = payload.get(KEY_DIGEST_FEATURED_RECORDS, [])
    if featured_records:
        lines.append(f"{payload.get(KEY_DIGEST_FEATURED_HEADING, LABEL_TOP_MATCHES)}:")
        lines.extend(
            format_job_line(record, index + 1) for index, record in enumerate(featured_records)
        )
        lines.append("")
    elif payload.get(KEY_DIGEST_STATUS_MESSAGE):
        lines.append(str(payload.get(KEY_DIGEST_STATUS_MESSAGE)))
        lines.append("")

    lines.append(f"Workspace: {payload.get(KEY_DIGEST_WORKSPACE_REF, '')}")
    return "\n".join(lines).strip()


def format_daily_summary_html(payload: dict[str, Any]) -> str:
    run_started_at = html.escape(
        _format_summary_timestamp(str(payload.get("run_started_at", "Unknown")))
    )
    run_finished_at = html.escape(
        _format_summary_timestamp(
            str(payload.get("run_finished_at", payload.get("run_started_at", "Unknown")))
        )
    )
    summary_line = (
        f"Matches last run: <b>{payload.get(KEY_DIGEST_CURRENT_COUNT, 0)}</b> | "
        f"New this run: <b>{payload.get(KEY_DIGEST_NEW_COUNT, 0)}</b>"
    )
    workspace_line = (
        f"Saved from earlier: <b>{payload.get(KEY_DIGEST_SAVED_COUNT, 0)}</b> | "
        f"Unopened on workspace: <b>{payload.get(KEY_DIGEST_UNOPENED_COUNT, 0)}</b>"
    )
    parts = [
        "<b>Daily Job Summary</b>",
        f"Collection started: {run_started_at}",
        f"Collection finished: {run_finished_at}",
        summary_line,
        workspace_line,
    ]

    featured_records = payload.get(KEY_DIGEST_FEATURED_RECORDS, [])
    if featured_records:
        parts.append("")
        parts.append(
            f"<b>{html.escape(str(payload.get(KEY_DIGEST_FEATURED_HEADING, LABEL_TOP_MATCHES)))}:</b>"
        )
        parts.extend(
            format_job_html(record, index + 1) for index, record in enumerate(featured_records)
        )
    elif payload.get(KEY_DIGEST_STATUS_MESSAGE):
        parts.append("")
        parts.append(html.escape(str(payload.get(KEY_DIGEST_STATUS_MESSAGE) or "")))

    workspace_reference = str(payload.get(KEY_DIGEST_WORKSPACE_REF, "")).strip()
    if workspace_reference:
        if workspace_reference.startswith("http://") or workspace_reference.startswith("https://"):
            parts.append("")
            parts.append(f'<a href="{html.escape(workspace_reference)}">Open workspace</a>')
        else:
            parts.append("")
            parts.append(f"Workspace: {html.escape(workspace_reference)}")
    return "\n".join(part for part in parts if part is not None)


def write_last_summary(summary_text: str) -> None:
    AGENT_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    AGENT_SUMMARY_PATH.write_text(summary_text, encoding="utf-8")


def send_daily_notifications(
    summary_text: str, summary_html: str, settings: dict[str, Any]
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    subject_prefix = str(
        settings[KEY_EMAIL].get("subject_prefix") or DEFAULT_SUBJECT_PREFIX
    ).strip()
    subject = f"{subject_prefix} Daily Job Summary"

    if settings[KEY_EMAIL].get("enabled"):
        results.append(
            send_email_notification(subject, summary_text, summary_html, settings[KEY_EMAIL])
        )
    if settings[KEY_TELEGRAM].get("enabled"):
        results.append(
            send_telegram_notification(summary_text, summary_html, settings[KEY_TELEGRAM])
        )
    return results


def should_send_digest(payload: dict[str, Any], settings: dict[str, Any]) -> bool:
    if not settings[KEY_NOTIFICATION_RULES].get(KEY_ONLY_IF_NEW_MATCHES, False):
        return True
    return int(payload.get(KEY_DIGEST_NEW_COUNT, 0)) > 0


def run_agent_once(no_scrape: bool = False, notify: bool = True) -> dict[str, Any]:
    settings = load_user_settings(None, create_if_missing=True)
    state = load_agent_state()
    previous_records = load_last_kept_records()

    if no_scrape:
        print("Rebuilding workspace from current local state...")
        rebuild_workspace_results(reason="agent runner --send-notification-no-scrape")
    else:
        print("Starting job collection...")
        scrape_jobs_direct()
        print("Job collection finished.")

    current_records = load_last_kept_records()
    run_stats = load_latest_run_stats()
    profile = load_profile()
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    workspace_records = build_workspace_record_sets(
        current_records,
        load_job_history(),
        applied_job_keys,
        hidden_job_keys,
        parse_timestamp(
            str(run_stats.get("run_finished_at") or run_stats.get("run_started_at") or "")
        )
        or datetime.now().astimezone(),
        profile,
    )
    print("Building daily digest...")
    payload = build_digest_payload(
        previous_records, current_records, workspace_records, settings, run_stats
    )
    summary_text = format_daily_summary(payload)
    summary_html = format_daily_summary_html(payload)
    write_last_summary(summary_text)

    notification_results: list[dict[str, Any]] = []
    if not notify:
        print("Notifications skipped because --no-notify was used.")
    elif should_send_digest(payload, settings):
        if settings[KEY_TELEGRAM].get("enabled") and settings[KEY_TELEGRAM].get("bot_token"):
            try:
                sync_result = sync_telegram_subscribers(settings[KEY_TELEGRAM])
                save_user_settings(None, settings)
                print(
                    f"[AGENT_RUNNER][INFO] Telegram subscribers synced: {sync_result['total_subscribers']}"
                )
            except Exception as exc:
                print(f"[AGENT_RUNNER][WARN] Telegram subscriber sync failed: {exc}")
        print("Sending notifications...")
        notification_results = send_daily_notifications(summary_text, summary_html, settings)
        print(f"Notifications sent: {len(notification_results)} channel(s).")
    else:
        print("Notifications skipped because there were no new matches to send.")

    state.update(
        {
            "last_agent_run_at": payload["run_finished_at"],
            "last_notified_run_at": payload["run_finished_at"]
            if notification_results
            else state.get("last_notified_run_at"),
            "last_current_keys": payload["current_keys"],
            "last_summary_path": str(AGENT_SUMMARY_PATH),
            "last_workspace_reference": payload[KEY_DIGEST_WORKSPACE_REF],
        }
    )
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
    except Exception as exc:
        print(
            f"[AGENT_RUNNER][WARN] Failed to parse scheduled time '{daily_time_local}', using default: {exc}"
        )
        hour_text, minute_text = DEFAULT_DAILY_TIME_LOCAL.split(":", 1)
        scheduled_hour = int(hour_text)
        scheduled_minute = int(minute_text)

    last_run_at = str(state.get("last_agent_run_at") or "")
    last_run_day = last_run_at[:10]
    today = now.date().isoformat()
    after_window = (now.hour, now.minute) >= (scheduled_hour, scheduled_minute)
    return after_window and last_run_day != today


def run_agent_loop() -> None:
    print("Daily agent loop started.")
    while True:
        settings = load_user_settings(None, create_if_missing=True)
        sleep_seconds = int(settings["schedule"]["loop_sleep_seconds"])
        daily_time_local = str(
            settings["schedule"]["daily_time_local"] or DEFAULT_DAILY_TIME_LOCAL
        ).strip()

        now = datetime.now().astimezone()
        state = load_agent_state()
        if should_run_now(state, daily_time_local, now):
            result = run_agent_once(no_scrape=False, notify=True)
            print(result["summary_text"])
            print(f"Summary saved to {result['summary_path']}")
        time.sleep(sleep_seconds)


def _set_admin_user_context() -> None:
    import os

    admin_email = os.getenv("JOB_HUNTER_ADMIN_EMAIL", "").strip().lower()
    if admin_email:
        from job_hunter_agent.auth import user_id_from_email
        from job_hunter_agent.user_context import set_user_id

        set_user_id(user_id_from_email(admin_email))


def main() -> None:
    from job_hunter_agent.database import init_db
    from job_hunter_agent.global_settings import seed_global_settings_from_file
    from job_hunter_agent.knowledge_store import upgrade_knowledge_from_dir
    from job_hunter_agent.paths import REPO_ROOT as _REPO_ROOT

    init_db()
    seed_global_settings_from_file()
    for _subdir in ("knowledge", "signals"):
        upgrade_knowledge_from_dir(_REPO_ROOT / "data" / _subdir)

    _set_admin_user_context()
    configure_console_output()
    parser = argparse.ArgumentParser(description="Run the local daily job agent.")
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Keep running and trigger once per day at the configured local time.",
    )
    parser.add_argument(
        "--send-notification-no-scrape",
        action="store_true",
        help="Do not fetch new jobs; just rebuild the workspace and send a digest from current local state.",
    )
    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Build the digest without sending email or Telegram notifications.",
    )
    args = parser.parse_args()

    if args.loop:
        run_agent_loop()
        return

    result = run_agent_once(no_scrape=args.send_notification_no_scrape, notify=not args.no_notify)
    print(result["summary_text"])
    print("")
    print(
        json.dumps(
            {
                "summary_path": result["summary_path"],
                "notifications": result["notifications"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
