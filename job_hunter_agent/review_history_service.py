"""Review history service.

This module manages the persistence and retrieval of job-level review history and audit records.
It provides services to track user feedback actions (such as hiding, applying, or blocking
jobs) and retrieves job descriptions from history or cached search results to support
consistent review signals across sessions.
"""

import logging
import re
import threading
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_REVIEW_STATE_LOCK = threading.Lock()

from job_hunter_agent.filters import (
    build_title_block_rule,
    normalize_title_block_phrase,
)
from job_hunter_agent import employer_outcome_store
from job_hunter_agent.io_utils import load_job_history, save_job_history
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.profile_store import load_profile, save_profile
from job_hunter_agent.user_context import get_user_id
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_FIRST_APPLIED_AT_KEY,
    RECORD_FIRST_HIDDEN_AT_KEY,
    RECORD_FIRST_NO_RESPONSE_AT_KEY,
    RECORD_FIRST_REJECTED_AT_KEY,
    RECORD_FIRST_SEEN_AT_KEY,
    RECORD_FIRST_VIEWED_AT_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_IS_HIDDEN_KEY,
    RECORD_JOB_KEY,
    RECORD_LAST_APPLIED_AT_KEY,
    RECORD_LAST_NO_RESPONSE_AT_KEY,
    RECORD_LAST_REJECTED_AT_KEY,
    RECORD_LAST_UNREJECTED_AT_KEY,
    RECORD_LAST_UN_NO_RESPONSE_AT_KEY,
    RECORD_LAST_BLOCK_TITLE_AT_KEY,
    RECORD_LAST_HIDDEN_AT_KEY,
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_LAST_NOT_FOR_ME_AT_KEY,
    RECORD_LAST_SEEN_AT_KEY,
    RECORD_LAST_UNAPPLIED_AT_KEY,
    RECORD_LAST_UNHIDDEN_AT_KEY,
    RECORD_LAST_VIEWED_AT_KEY,
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


def _record_first_party_outcome_event(
    event_type: str, job_key: str, company: str, title: str, occurred_at: str
) -> None:
    """Ledger a real, in-app outcome click against the employer rollup.

    This is the path that should eventually replace the rejection-sheet
    import entirely: no email, no LLM guess, just the candidate telling us
    what happened. Never lets a ledger problem break the click itself - if
    there is no employer to attribute this to, or the ledger write fails for
    any reason, the button still works and the job record still updates; only
    the aggregate employer count is skipped, and that is logged so it is not
    a silent gap.
    """
    employer = str(company or "").strip()
    if not employer:
        return
    user_id = get_user_id()
    if not user_id:
        return
    try:
        employer_outcome_store.record_application_event(
            user_id=user_id,
            employer_raw=employer,
            role_title=str(title or ""),
            event_type=event_type,
            event_date=occurred_at[:10],
            source=employer_outcome_store.SOURCE_JH_MANUAL_ACTION,
            evidence_ref=f"{job_key}:{event_type}",
            confidence="high",
            data={"job_key": job_key},
        )
        employer_outcome_store.rebuild_employer_outcomes(user_id)
    except Exception:
        logger.exception(
            "Failed to record first-party outcome event: type=%s job_key=%s", event_type, job_key
        )


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
        _record_first_party_outcome_event(
            employer_outcome_store.EVENT_APPLIED,
            normalized,
            entry.get(RECORD_COMPANY_KEY, ""),
            entry.get(RECORD_TITLE_KEY, ""),
            now_iso,
        )
    elif action == "unapply":
        entry[RECORD_LAST_UNAPPLIED_AT_KEY] = now_iso
    elif action == "rejected":
        # You clicked this yourself - it does not need an LLM to read an email
        # and guess. This is the real signal the rejection-sheet import exists
        # to approximate; once this is the normal way rejections get recorded,
        # that import should be retired rather than kept running alongside it.
        if not entry.get(RECORD_FIRST_REJECTED_AT_KEY):
            entry[RECORD_FIRST_REJECTED_AT_KEY] = now_iso
        entry[RECORD_LAST_REJECTED_AT_KEY] = now_iso
        _record_first_party_outcome_event(
            employer_outcome_store.EVENT_REJECTED,
            normalized,
            entry.get(RECORD_COMPANY_KEY, ""),
            entry.get(RECORD_TITLE_KEY, ""),
            now_iso,
        )
    elif action == "unreject":
        # Ledger events are append-only by design (see employer_outcome_store
        # module docstring) - undo does not delete the fact that you clicked
        # Rejected earlier, it only resets the button so you can re-record a
        # different outcome for this job. The employer's rejected count is
        # not decremented.
        entry[RECORD_LAST_UNREJECTED_AT_KEY] = now_iso
    elif action == "un_no_response":
        entry[RECORD_LAST_UN_NO_RESPONSE_AT_KEY] = now_iso
    elif action == "no_response":
        # Same idea as "rejected" above: you telling us "never heard back" is
        # a real, first-party fact. It does not need the silence-after-X-days
        # guess the sheet import makes, because there is no guessing involved
        # - you already know.
        if not entry.get(RECORD_FIRST_NO_RESPONSE_AT_KEY):
            entry[RECORD_FIRST_NO_RESPONSE_AT_KEY] = now_iso
        entry[RECORD_LAST_NO_RESPONSE_AT_KEY] = now_iso
        _record_first_party_outcome_event(
            employer_outcome_store.EVENT_NO_RESPONSE,
            normalized,
            entry.get(RECORD_COMPANY_KEY, ""),
            entry.get(RECORD_TITLE_KEY, ""),
            now_iso,
        )
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


def _review_state_response(
    action: str,
    normalized: str,
    saved_count: int,
    *,
    state_changed: bool,
    refresh_id: str | None = None,
) -> dict:
    return {
        "ok": True,
        "action": action,
        "job_key": normalized,
        "saved_count": saved_count,
        "state_changed": state_changed,
        "reload_workspace": bool(state_changed),
        "workspace_refresh_async": bool(state_changed),
        "workspace_refresh_id": refresh_id,
    }


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

    list_name = {
        "applied": "applied_job_keys",
        "hidden": "hidden_job_keys",
        "rejected": "rejected_job_keys",
        "no_response": "no_response_job_keys",
    }.get(action)
    if not list_name:
        raise ValueError("Unsupported review action")

    # FastAPI can execute duplicate clicks concurrently. Serialize the tiny
    # read/modify/write section so the second identical request observes the
    # first one's persisted state and becomes a true no-op instead of creating
    # a duplicate history event and a second expensive workspace rebuild.
    with _REVIEW_STATE_LOCK:
        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})
        existing = [
            normalize_job_key(value)
            for value in review_controls.get(list_name, [])
            if normalize_job_key(value)
        ]
        if normalized in existing:
            return _review_state_response(
                action, normalized, len(existing), state_changed=False
            )

        existing.append(normalized)
        review_controls[list_name] = existing
        save_profile(profile)
        persist_review_event(
            action, normalized, url=url, title=title, company=company, teaser=teaser
        )

    # Rebuild the cached snapshot in the background only. The client moves the
    # card between workspace tabs itself and must NOT full-page reload here.
    refresh_id = rebuild_workspace_after_rule_change(f"review action saved: {action}")
    return _review_state_response(
        action, normalized, len(existing), state_changed=True, refresh_id=refresh_id
    )


def remove_review_key(
    action: str,
    job_key: str,
    url: str = "",
    title: str = "",
    company: str = "",
    teaser: str = "",
) -> dict:
    normalized = normalize_job_key(job_key)
    if not normalized and re.fullmatch(
        r"[a-z0-9][a-z0-9_-]*", str(job_key or "").strip().lower()
    ):
        normalized = str(job_key).strip().lower()
    if not normalized:
        raise ValueError("Missing job key")

    list_name = {
        "unapply": "applied_job_keys",
        "unhide": "hidden_job_keys",
        "unreject": "rejected_job_keys",
        "un_no_response": "no_response_job_keys",
    }.get(action)
    if not list_name:
        raise ValueError("Unsupported review action")

    with _REVIEW_STATE_LOCK:
        profile = load_profile()
        review_controls = profile.setdefault("review_controls", {})
        existing = [
            normalize_job_key(value)
            for value in review_controls.get(list_name, [])
            if normalize_job_key(value)
        ]
        if normalized not in existing:
            return _review_state_response(
                action, normalized, len(existing), state_changed=False
            )

        updated = [value for value in existing if value != normalized]
        review_controls[list_name] = updated
        save_profile(profile)
        persist_review_event(
            action, normalized, url=url, title=title, company=company, teaser=teaser
        )

    refresh_id = rebuild_workspace_after_rule_change(f"review action saved: {action}")
    return _review_state_response(
        action, normalized, len(updated), state_changed=True, refresh_id=refresh_id
    )


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
    resolved: list[str] = []
    seen_phrases: set[str] = set()
    for raw in raw_phrases:
        phrase = normalize_title_block_phrase(raw)
        if not phrase or phrase in seen_phrases:
            continue
        seen_phrases.add(phrase)
        resolved.append(phrase)
    if not resolved:
        raise ValueError("At least one exact title block phrase is required")

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
