"""Local workspace export helpers for Telegram-driven job handoff."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from job_hunter_agent import workspace_service
from job_hunter_agent.fit_scoring import fit_score_displayed
from job_hunter_agent.history import is_new_to_you
from job_hunter_agent.io_utils import load_job_history, load_run_stats
from job_hunter_agent.posting_utils import (
    get_manual_skip_sets,
    parse_timestamp,
    posted_age_badge_threshold,
)
from job_hunter_agent.profile_store import load_profile
from job_hunter_agent.role_analysis import posting_channel_evidence_is_current
from job_hunter_agent.source_registry import get_source_display_label
from job_hunter_agent.system_warnings import make_system_warning_fingerprint, record_system_warning
from job_hunter_agent.text_processing import dedupe_preserve_order
from job_hunter_agent.user_settings import get_workspace_minimum_score
from job_hunter_agent.workspace_renderer import ARCHIVE_LABEL, _workspace_label

logger = logging.getLogger(__name__)

EXPORT_JSON_FILENAME = "job-hunter-jobs.json"
EXPORT_MD_FILENAME = "job-hunter-jobs.md"
DEFAULT_EXPORT_DIRNAME = "Job Hunter Workspace"


def get_workspace_export_dir() -> Path:
    configured = str(os.environ.get("JOB_HUNTER_WORKSPACE_EXPORT_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / DEFAULT_EXPORT_DIRNAME


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _score_total(record: dict, profile: dict[str, Any]) -> int:
    try:
        return fit_score_displayed(record, profile)
    except Exception:
        return _safe_int(record.get("fit_score"), 0)


def _match_label(record: dict, score: int, profile: dict[str, Any]) -> str:
    label = str(record.get("fit_label") or "").strip()
    if label:
        return label
    try:
        from job_hunter_agent.match_labels import score_to_match_label

        return score_to_match_label(score, profile)
    except Exception:
        return ""


def _first_non_empty(*values: Any, default: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return default


def _build_badges(
    record: dict,
    workspace_state: str,
    new_to_you_cutoff: datetime | None,
) -> list[str]:
    badges: list[str] = []

    if workspace_state == "applied":
        badges.append("Applied")
    elif workspace_state == "hidden":
        badges.append("Hidden")
    elif workspace_state == "archive":
        badges.append(ARCHIVE_LABEL)
    elif is_new_to_you(record, new_to_you_cutoff):
        badges.append("New To You")
    else:
        badges.append("Viewed")

    posted_age_threshold = posted_age_badge_threshold(record)
    if posted_age_threshold is not None:
        badges.append(f"{posted_age_threshold}+ Days Old")

    details_status = str(record.get("details_status") or "").strip().lower()
    if details_status and details_status not in {"ok", "n/a"}:
        badges.append("Description Issue")

    badges.append(get_source_display_label(str(record.get("source") or "unknown")))

    if workspace_state == "current" and record.get("is_reposted") is True:
        badges.append(_workspace_label("workspace_card_labels", "reposted_badge"))

    channel_signal = record.get("posting_channel_evidence")
    if not posting_channel_evidence_is_current(channel_signal):
        channel_signal = {}
    channel_kind = str(channel_signal.get("kind") or "").strip().lower()
    if channel_kind == "agency_or_recruiter":
        if channel_signal.get("needs_review"):
            badges.append(
                _workspace_label(
                    "workspace_card_labels",
                    "posting_channel_likely_recruiter_badge",
                )
            )
        else:
            badges.append(
                _workspace_label(
                    "workspace_card_labels",
                    "posting_channel_agency_recruiter_badge",
                )
            )
    elif channel_kind == "direct_employer":
        badges.append(
            _workspace_label("workspace_card_labels", "posting_channel_direct_employer_badge")
        )
    elif channel_kind:
        badges.append(
            _workspace_label("workspace_card_labels", "posting_channel_unknown_badge")
        )

    duplicate_links = record.get("duplicate_links")
    if isinstance(duplicate_links, list) and duplicate_links:
        badges.append("Duplicate in workspace")

    potential_duplicate_links = record.get("potential_duplicate_links")
    if isinstance(potential_duplicate_links, list) and potential_duplicate_links:
        badges.append("Related cards")

    hard_block_reasons = [str(item).strip() for item in record.get("hard_block_reasons") or []]
    if hard_block_reasons:
        badges.append("Hard blocked")

    for signal in record.get("job_quality_signals") or []:
        if not isinstance(signal, dict):
            continue
        label = str(signal.get("label") or "").strip()
        if label:
            badges.append(label)

    cand_hist = record.get("candidate_application_history")
    if isinstance(cand_hist, dict):
        status = str(cand_hist.get("llm_application_status") or "").strip().lower()
        confidence = str(cand_hist.get("llm_confidence") or "").strip().lower()
        badges.append(
            "Rejected before"
            if status == "rejection" and confidence != "low"
            else "Possible previous application"
        )
        if cand_hist.get("llm_needs_review"):
            badges.append("Needs review")

    return dedupe_preserve_order([badge for badge in badges if badge])


def _build_export_job(
    record: dict,
    workspace_state: str,
    profile: dict[str, Any],
    new_to_you_cutoff: datetime | None,
) -> dict[str, Any]:
    score_total = _score_total(record, profile)
    export_job = {
        "job_key": _first_non_empty(record.get("job_key")),
        "workspace_state": workspace_state,
        "source": _first_non_empty(record.get("source"), default="unknown"),
        "title": _first_non_empty(record.get("title"), default="Untitled"),
        "company": _first_non_empty(record.get("company"), default="N/A"),
        "location": _first_non_empty(record.get("location"), default="N/A"),
        "url": _first_non_empty(record.get("url"), default="#"),
        "score_total": score_total,
        "match_label": _match_label(record, score_total, profile),
        "posted": _first_non_empty(record.get("posted"), default="N/A"),
        "salary": _first_non_empty(record.get("salary"), default="N/A"),
        "work_mode": _first_non_empty(record.get("work_mode"), default="N/A"),
        "work_type": _first_non_empty(record.get("work_type"), default="N/A"),
        "teaser": _first_non_empty(record.get("teaser"), default=""),
        "search_location": _first_non_empty(record.get("search_location"), default="N/A"),
        "search_keywords": _first_non_empty(record.get("search_keywords"), default=""),
        "badges": _build_badges(record, workspace_state, new_to_you_cutoff),
        "fit_highlights": list(record.get("fit_highlights") or []),
        "hard_block_reasons": list(record.get("hard_block_reasons") or []),
        "soft_risk_reasons": list(record.get("soft_risk_reasons") or []),
        "missing_profile_support": list(record.get("missing_profile_support") or []),
        "missing_clearance_support": list(record.get("missing_clearance_support") or []),
        "competitive_signals": list(record.get("competitive_signals") or []),
        "job_quality_signals": list(record.get("job_quality_signals") or []),
        "title_reason": _first_non_empty(record.get("title_reason")),
        "content_reason": _first_non_empty(record.get("content_reason")),
        "llm_decision": _first_non_empty(record.get("llm_decision")),
        "llm_fit_grade": _first_non_empty(record.get("llm_fit_grade")),
        "details_status": _first_non_empty(record.get("details_status")),
        "posting_channel_evidence": record.get("posting_channel_evidence") or {},
        "source_provenance": record.get("source_provenance") or [],
        "candidate_application_history": record.get("candidate_application_history") or {},
        "last_seen_at": record.get("last_seen_at"),
        "last_viewed_at": record.get("last_viewed_at"),
        "last_kept_at": record.get("last_kept_at"),
        "last_applied_at": record.get("last_applied_at"),
        "last_hidden_at": record.get("last_hidden_at"),
    }
    return export_job


def _workspace_sections(workspace_records: dict[str, list[dict]]) -> list[tuple[str, str]]:
    return [
        ("current", "current_records"),
        ("archive", "recent_archive_records"),
        ("archive", "stale_archive_records"),
        ("applied", "applied_records"),
        ("hidden", "hidden_records"),
    ]


def build_workspace_export_jobs(
    workspace_records: dict[str, list[dict]],
    profile: dict[str, Any],
    new_to_you_cutoff: datetime | None,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for workspace_state, records_key in _workspace_sections(workspace_records):
        for record in workspace_records.get(records_key, []):
            job_key = str(record.get("job_key") or "").strip()
            if not job_key or job_key in seen_keys:
                continue
            seen_keys.add(job_key)
            jobs.append(_build_export_job(record, workspace_state, profile, new_to_you_cutoff))

    jobs.sort(
        key=lambda item: (
            -_safe_int(item.get("score_total"), 0),
            str(item.get("title") or "").lower(),
            str(item.get("company") or "").lower(),
            str(item.get("job_key") or ""),
        )
    )
    return jobs


def _build_markdown_summary(payload: dict[str, Any]) -> str:
    jobs = payload.get("jobs", [])
    lines = [
        "# Job Hunter job export",
        "",
        f"Updated: {payload.get('exported_at', '')}",
        f"Mode: {payload.get('mode', '')}",
        f"Jobs: {payload.get('job_count', 0)}",
        "",
    ]
    for job in jobs:
        if not isinstance(job, dict):
            continue
        badges = ", ".join(str(value) for value in job.get("badges", []) if str(value).strip())
        lines.append(
            f"- {job.get('score_total', 0)} | {job.get('match_label', '')} | {job.get('title', '')} | "
            f"{job.get('company', '')} | {job.get('location', '')} | {job.get('url', '')}"
        )
        if badges:
            lines.append(f"  - Badges: {badges}")
    lines.append("")
    return "\n".join(lines)


def _load_existing_jobs(json_path: Path) -> list[dict[str, Any]]:
    if not json_path.exists():
        return []
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Existing workspace export at %s is unreadable: %s", json_path, exc)
        record_system_warning(
            severity="warning",
            category="workspace_export_corruption",
            source="_load_existing_jobs",
            message=f"Existing workspace export at {json_path} could not be parsed: {exc}",
            fingerprint=make_system_warning_fingerprint("workspace_export_corruption", str(json_path)),
            context={"path": str(json_path), "error": str(exc)},
        )
        return []
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    return [job for job in jobs if isinstance(job, dict)] if isinstance(jobs, list) else []


def _merge_jobs(existing_jobs: list[dict[str, Any]], new_jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for job in existing_jobs:
        job_key = str(job.get("job_key") or "").strip()
        if not job_key:
            continue
        merged[job_key] = dict(job)
        order.append(job_key)

    for job in new_jobs:
        job_key = str(job.get("job_key") or "").strip()
        if not job_key:
            continue
        if job_key not in merged:
            merged[job_key] = dict(job)
            order.append(job_key)
            continue
        updated = dict(merged[job_key])
        updated.update(job)
        merged[job_key] = updated

    merged_jobs = [merged[key] for key in order]
    merged_jobs.sort(
        key=lambda item: (
            -_safe_int(item.get("score_total"), 0),
            str(item.get("title") or "").lower(),
            str(item.get("company") or "").lower(),
            str(item.get("job_key") or ""),
        )
    )
    return merged_jobs


def export_workspace_jobs(*, mode: str = "merge") -> dict[str, Any]:
    normalized_mode = str(mode or "merge").strip().lower()
    if normalized_mode not in {"merge", "fresh"}:
        raise ValueError("Export mode must be 'merge' or 'fresh'")

    profile = load_profile()
    run_stats = load_run_stats()
    job_history = load_job_history()
    kept_records = workspace_service.load_last_kept_records()
    reference_time = (
        parse_timestamp(str(run_stats.get("run_finished_at") or run_stats.get("run_started_at") or ""))
        or datetime.now().astimezone()
    )
    applied_job_keys, hidden_job_keys = get_manual_skip_sets(profile)
    workspace_records = workspace_service.build_workspace_record_sets(
        kept_records,
        job_history,
        applied_job_keys,
        hidden_job_keys,
        reference_time,
        profile,
        get_workspace_minimum_score(),
    )

    export_dir = get_workspace_export_dir()
    export_dir.mkdir(parents=True, exist_ok=True)
    json_path = export_dir / EXPORT_JSON_FILENAME
    md_path = export_dir / EXPORT_MD_FILENAME

    new_to_you_cutoff = parse_timestamp(str(run_stats.get("run_started_at") or ""))
    jobs = build_workspace_export_jobs(workspace_records, profile, new_to_you_cutoff)
    if normalized_mode == "merge":
        jobs = _merge_jobs(_load_existing_jobs(json_path), jobs)

    payload = {
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": normalized_mode,
        "export_dir": str(export_dir),
        "job_count": len(jobs),
        "workspace": {
            "minimum_score": get_workspace_minimum_score(),
            "current": len(workspace_records.get("current_records", [])),
            "archive": len(workspace_records.get("archive_records", [])),
            "applied": len(workspace_records.get("applied_records", [])),
            "hidden": len(workspace_records.get("hidden_records", [])),
        },
        "run_stats": {
            "run_started_at": run_stats.get("run_started_at"),
            "run_finished_at": run_stats.get("run_finished_at"),
        },
        "jobs": jobs,
    }

    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_build_markdown_summary(payload), encoding="utf-8")

    return {
        "mode": normalized_mode,
        "export_dir": str(export_dir),
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "job_count": len(jobs),
        "workspace_counts": payload["workspace"],
    }
