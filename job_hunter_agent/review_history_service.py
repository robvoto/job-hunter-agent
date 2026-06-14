"""Review history service.

This module manages the persistence and retrieval of job-level review history and audit records.
It provides services to track user feedback actions (such as hiding, applying, or blocking
jobs) and retrieves job descriptions from history or cached search results to support
consistent review signals across sessions.
"""

import json
import re
from datetime import datetime
from typing import Any

from job_hunter_agent.filters import (
    build_title_block_rule,
    normalize_title_block_phrase,
    suggest_title_block_phrase,
)
from job_hunter_agent.io_utils import load_job_history, save_job_history
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.paths import OUTPUT_DIR
from job_hunter_agent.profile_store import load_profile, save_profile
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_FIRST_APPLIED_AT_KEY,
    RECORD_FIRST_HIDDEN_AT_KEY,
    RECORD_FIRST_SEEN_AT_KEY,
    RECORD_FIRST_VIEWED_AT_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_IS_HIDDEN_KEY,
    RECORD_JOB_KEY,
    RECORD_LAST_APPLIED_AT_KEY,
    RECORD_LAST_BLOCK_TITLE_AT_KEY,
    RECORD_LAST_HIDDEN_AT_KEY,
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_LAST_NOT_FOR_ME_AT_KEY,
    RECORD_LAST_SEEN_AT_KEY,
    RECORD_LAST_UNAPPLIED_AT_KEY,
    RECORD_LAST_UNHIDDEN_AT_KEY,
    RECORD_LAST_VIEWED_AT_KEY,
    RECORD_REJECT_TITLE_RULES_KEY,
    RECORD_REVIEW_EVENTS_KEY,
    RECORD_TEASER_KEY,
    RECORD_TIMES_BLOCK_TITLE_KEY,
    RECORD_TIMES_NOT_FOR_ME_KEY,
    RECORD_TIMES_VIEWED_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
)
from job_hunter_agent.workspace_refresh_service import rebuild_workspace_after_rule_change


def _normalize_requirement_blocker(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    return cleaned[:80]


def _normalize_description_block_phrase(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return cleaned[:120]


def get_job_description(job_id: str) -> str:
    history = load_job_history()
    normalized_key = normalize_job_key(job_id)
    entry = history.get(normalized_key) if isinstance(history, dict) else None
    if isinstance(entry, dict):
        snap = entry.get(RECORD_LAST_KEPT_SNAPSHOT_KEY) or {}
        desc = snap.get(RECORD_FULL_DESCRIPTION_KEY) or snap.get(RECORD_FIT_SOURCE_TEXT_KEY) or ""
        if desc:
            return desc

    seek_path = OUTPUT_DIR / "seek_results.json"
    if seek_path.exists():
        try:
            rows = json.loads(seek_path.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                for row in rows:
                    if normalize_job_key(str(row.get(RECORD_JOB_KEY) or "")) == normalized_key:
                        return (
                            row.get(RECORD_FULL_DESCRIPTION_KEY)
                            or row.get(RECORD_FIT_SOURCE_TEXT_KEY)
                            or ""
                        )
        except Exception as exc:
            print(f"[REVIEW_HISTORY][WARN] Failed to read job description from seek_results: {exc}")
    return ""


def _append_review_event(
    entry: dict,
    action: str,
    job_key: str,
    occurred_at: str,
    title: str = "",
    company: str = "",
    url: str = "",
    teaser: str = "",
    extra: dict | None = None,
) -> None:
    snapshot = entry.get(RECORD_LAST_KEPT_SNAPSHOT_KEY)
    if not isinstance(snapshot, dict):
        snapshot = {}

    event: dict[str, Any] = {
        "action": action,
        RECORD_JOB_KEY: job_key,
        "timestamp": occurred_at,
    }
    resolved_title = title or entry.get(RECORD_TITLE_KEY) or snapshot.get(RECORD_TITLE_KEY) or ""
    resolved_company = (
        company or entry.get(RECORD_COMPANY_KEY) or snapshot.get(RECORD_COMPANY_KEY) or ""
    )
    resolved_url = url or entry.get(RECORD_URL_KEY) or snapshot.get(RECORD_URL_KEY) or ""
    resolved_teaser = (
        teaser or snapshot.get(RECORD_TEASER_KEY) or entry.get(RECORD_TEASER_KEY) or ""
    )

    if resolved_title:
        event[RECORD_TITLE_KEY] = resolved_title
    if resolved_company:
        event[RECORD_COMPANY_KEY] = resolved_company
    if resolved_url:
        event[RECORD_URL_KEY] = resolved_url
    if resolved_teaser:
        event[RECORD_TEASER_KEY] = resolved_teaser

    if isinstance(extra, dict):
        for k, v in extra.items():
            if v in (None, "", [], {}):
                continue
            event[k] = v

    events = entry.get(RECORD_REVIEW_EVENTS_KEY)
    if not isinstance(events, list):
        events = []
    events.append(event)
    entry[RECORD_REVIEW_EVENTS_KEY] = events[-50:]


def persist_review_event(
    action: str,
    job_key: str,
    url: str = "",
    title: str = "",
    company: str = "",
    teaser: str = "",
    extra: dict | None = None,
) -> None:
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        return

    history = load_job_history()
    entry = history.get(normalized, {})
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

    entry[RECORD_JOB_KEY] = normalized
    if not entry.get(RECORD_FIRST_SEEN_AT_KEY):
        entry[RECORD_FIRST_SEEN_AT_KEY] = now_iso
    entry[RECORD_LAST_SEEN_AT_KEY] = now_iso
    if title:
        entry[RECORD_TITLE_KEY] = title
    if company:
        entry[RECORD_COMPANY_KEY] = company
    if url:
        entry[RECORD_URL_KEY] = url

    if action == "hidden":
        entry[RECORD_IS_HIDDEN_KEY] = True
        if not entry.get(RECORD_FIRST_HIDDEN_AT_KEY):
            entry[RECORD_FIRST_HIDDEN_AT_KEY] = now_iso
        entry[RECORD_LAST_HIDDEN_AT_KEY] = now_iso
    elif action == "unhide":
        entry[RECORD_IS_HIDDEN_KEY] = False
        entry[RECORD_LAST_UNHIDDEN_AT_KEY] = now_iso
    elif action == "applied":
        if not entry.get(RECORD_FIRST_APPLIED_AT_KEY):
            entry[RECORD_FIRST_APPLIED_AT_KEY] = now_iso
        entry[RECORD_LAST_APPLIED_AT_KEY] = now_iso
    elif action == "unapply":
        entry[RECORD_LAST_UNAPPLIED_AT_KEY] = now_iso
    elif action == "not_for_me":
        entry[RECORD_LAST_NOT_FOR_ME_AT_KEY] = now_iso
        entry[RECORD_TIMES_NOT_FOR_ME_KEY] = int(entry.get(RECORD_TIMES_NOT_FOR_ME_KEY, 0) or 0) + 1
    elif action in ("block_similar", "block_title"):
        entry[RECORD_LAST_BLOCK_TITLE_AT_KEY] = now_iso
        entry[RECORD_TIMES_BLOCK_TITLE_KEY] = (
            int(entry.get(RECORD_TIMES_BLOCK_TITLE_KEY, 0) or 0) + 1
        )

    _append_review_event(
        entry,
        action,
        normalized,
        now_iso,
        title=title,
        company=company,
        url=url,
        teaser=teaser,
        extra=extra,
    )

    history[normalized] = entry
    save_job_history(history)


def append_review_key(
    action: str,
    job_key: str,
    url: str = "",
    title: str = "",
    company: str = "",
    teaser: str = "",
) -> dict:
    normalized = normalize_job_key(job_key)
    if not normalized:
        raise ValueError("Missing job key")

    profile = load_profile()
    review_controls = profile.setdefault("review_controls", {})

    list_name = {
        "applied": "applied_job_keys",
        "hidden": "hidden_job_keys",
    }.get(action)
    if not list_name:
        raise ValueError("Unsupported review action")

    existing = [
        normalize_job_key(value)
        for value in review_controls.get(list_name, [])
        if normalize_job_key(value)
    ]
    if normalized not in existing:
        existing.append(normalized)
    review_controls[list_name] = existing
    save_profile(profile)
    persist_review_event(action, normalized, url=url, title=title, company=company, teaser=teaser)
    rebuild_workspace_after_rule_change(f"review action saved: {action}")
    return {
        "ok": True,
        "action": action,
        "job_key": normalized,
        "saved_count": len(existing),
        "reload_workspace": True,
    }


def remove_review_key(
    action: str,
    job_key: str,
    url: str = "",
    title: str = "",
    company: str = "",
    teaser: str = "",
) -> dict:
    normalized = normalize_job_key(job_key)
    if not normalized and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(job_key or "").strip().lower()):
        normalized = str(job_key).strip().lower()
    if not normalized:
        raise ValueError("Missing job key")

    profile = load_profile()
    review_controls = profile.setdefault("review_controls", {})

    list_name = {
        "unapply": "applied_job_keys",
        "unhide": "hidden_job_keys",
    }.get(action)
    if not list_name:
        raise ValueError("Unsupported review action")

    existing = [
        normalize_job_key(value)
        for value in review_controls.get(list_name, [])
        if normalize_job_key(value)
    ]
    updated = [value for value in existing if value != normalized]
    review_controls[list_name] = updated
    save_profile(profile)
    persist_review_event(action, normalized, url=url, title=title, company=company, teaser=teaser)
    rebuild_workspace_after_rule_change(f"review action saved: {action}")
    return {
        "ok": True,
        "action": action,
        "job_key": normalized,
        "saved_count": len(updated),
        "reload_workspace": True,
    }


def record_job_view(job_key: str, url: str = "", title: str = "") -> dict:
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        raise ValueError("Missing job key")

    history = load_job_history()
    entry = history.get(normalized, {})
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

    entry[RECORD_JOB_KEY] = normalized
    if not entry.get(RECORD_FIRST_SEEN_AT_KEY):
        entry[RECORD_FIRST_SEEN_AT_KEY] = now_iso
    entry[RECORD_LAST_SEEN_AT_KEY] = now_iso
    if title and not entry.get(RECORD_TITLE_KEY):
        entry[RECORD_TITLE_KEY] = title
    if url:
        entry[RECORD_URL_KEY] = url
    entry[RECORD_TIMES_VIEWED_KEY] = int(entry.get(RECORD_TIMES_VIEWED_KEY, 0) or 0) + 1
    if not entry.get(RECORD_FIRST_VIEWED_AT_KEY):
        entry[RECORD_FIRST_VIEWED_AT_KEY] = now_iso
    entry[RECORD_LAST_VIEWED_AT_KEY] = now_iso

    history[normalized] = entry
    save_job_history(history)
    return {
        "ok": True,
        "action": "viewed",
        "job_key": normalized,
        RECORD_TIMES_VIEWED_KEY: entry[RECORD_TIMES_VIEWED_KEY],
        RECORD_LAST_VIEWED_AT_KEY: entry[RECORD_LAST_VIEWED_AT_KEY],
    }


def save_not_for_me_feedback(
    job_key: str,
    url: str = "",
    title: str = "",
    company: str = "",
    teaser: str = "",
) -> dict:
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        raise ValueError("Missing job key")
    persist_review_event(
        "not_for_me", normalized, url=url, title=title, company=company, teaser=teaser
    )
    return {
        "ok": True,
        "action": "not_for_me",
        "job_key": normalized,
        "message": "Saved as Not For Me. This is stored as learning feedback, not a permanent title block.",
    }


def save_block_similar_feedback(
    job_key: str,
    url: str = "",
    title: str = "",
    company: str = "",
    teaser: str = "",
    block_phrases: list[str] | None = None,
) -> dict:
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        raise ValueError("Missing job key")

    raw_phrases = [p for p in (block_phrases or []) if str(p).strip()]
    resolved: list[str] = [normalize_title_block_phrase(p) for p in raw_phrases]
    resolved = [p for p in resolved if p]
    if not resolved:
        fallback = suggest_title_block_phrase(title)
        if not fallback:
            raise ValueError("Could not suggest a title keyword to block from this title yet")
        resolved = [fallback]

    profile = load_profile()
    existing = list(profile.get("reject_title_rules", []))
    existing_patterns = {str(item.get("pattern") or "").strip() for item in existing}

    added_rules: list[dict] = []
    skipped_phrases: list[str] = []
    for phrase in resolved:
        rule = build_title_block_rule(phrase)
        if rule["pattern"] not in existing_patterns:
            existing.append(rule)
            existing_patterns.add(rule["pattern"])
            added_rules.append(rule)
        else:
            skipped_phrases.append(phrase)

    if added_rules:
        profile["reject_title_rules"] = existing
        save_profile(profile)
        rebuild_workspace_after_rule_change(f"title block added for {', '.join(resolved)}")

    persist_review_event(
        "block_title",
        normalized,
        url=url,
        title=title,
        company=company,
        teaser=teaser,
        extra={
            "extracted_phrases": resolved,
            "rules_added": [r["pattern"] for r in added_rules],
            "rules_skipped": skipped_phrases,
        },
    )

    added_labels = "', '".join(
        r["reason"].split("'")[1] if "'" in r["reason"] else r["pattern"] for r in added_rules
    )
    if added_rules and skipped_phrases:
        message = f"Blocked '{added_labels}'. {len(skipped_phrases)} pattern(s) already existed."
    elif added_rules:
        message = (
            f"Blocked {len(added_rules)} pattern(s). Similar jobs will be filtered in future runs."
        )
    else:
        message = "All selected patterns already existed as title block rules."

    return {
        "ok": True,
        "action": "block_similar",
        "job_key": normalized,
        "block_phrase": resolved[0],
        "block_phrases": resolved,
        "rules_added": added_rules,
        "message": message,
    }


def save_description_block_feedback(
    job_key: str,
    url: str = "",
    title: str = "",
    company: str = "",
    teaser: str = "",
    block_phrases: list[str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        raise ValueError("Missing job key")

    resolved: list[str] = []
    seen_phrases: set[str] = set()
    for raw in block_phrases or []:
        phrase = _normalize_description_block_phrase(raw)
        if len(phrase) < 3 or phrase in seen_phrases:
            continue
        seen_phrases.add(phrase)
        resolved.append(phrase)
    if not resolved:
        raise ValueError("At least one description block phrase is required")

    profile = load_profile()
    existing = list(profile.get("reject_description_phrase_rules", []))
    existing_phrases = {
        _normalize_description_block_phrase(str(item.get("phrase") or ""))
        for item in existing
        if isinstance(item, dict)
    }

    added_rules: list[dict[str, str]] = []
    skipped_phrases: list[str] = []
    for phrase in resolved:
        if phrase in existing_phrases:
            skipped_phrases.append(phrase)
            continue
        existing_phrases.add(phrase)
        added_rules.append({"phrase": phrase, "reason": f"DESC_REJECT:{phrase}"})

    if added_rules:
        profile["reject_description_phrase_rules"] = existing + added_rules
        save_profile(profile)
        rebuild_workspace_after_rule_change(
            f"description phrase rule added for {', '.join(resolved)}"
        )

    persist_review_event(
        "block_description",
        normalized,
        url=url,
        title=title,
        company=company,
        teaser=teaser,
        extra={
            "description_phrases_added": [rule["phrase"] for rule in added_rules],
            "description_phrases_skipped": skipped_phrases,
        },
    )

    if added_rules and skipped_phrases:
        message = f"Added {len(added_rules)} description block phrase(s). {len(skipped_phrases)} already existed."
    elif added_rules:
        message = f"Added {len(added_rules)} description block phrase(s)."
    else:
        message = "All selected description block phrases already existed."

    return {
        "ok": True,
        "action": "block_description",
        "job_key": normalized,
        "block_phrases": resolved,
        "rules_added": added_rules,
        "message": message,
    }
