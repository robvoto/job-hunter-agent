import json
import re
import threading
from datetime import datetime
from typing import Any

from job_hunter_agent.filters import build_title_block_rule, normalize_title_block_phrase, suggest_title_block_phrase
from job_hunter_agent.paths import (
    OUTPUT_DIR,
    get_audit_records_path,
    get_dashboard_path,
    get_job_history_path,
    get_run_stats_path,
)
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.profile_store import load_profile, save_profile
from job_hunter_agent.source_connector import rebuild_html_dashboard
from job_hunter_agent.record_schema import (
    RECORD_JOB_KEY,
    RECORD_TITLE_KEY,
    RECORD_COMPANY_KEY,
    RECORD_URL_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_TIMES_VIEWED_KEY,
    RECORD_FIRST_VIEWED_AT_KEY,
    RECORD_LAST_VIEWED_AT_KEY,
    RECORD_TEASER_KEY,
    RECORD_REVIEW_EVENTS_KEY,
    RECORD_IS_HIDDEN_KEY,
    RECORD_FIRST_HIDDEN_AT_KEY,
    RECORD_LAST_HIDDEN_AT_KEY,
    RECORD_LAST_UNHIDDEN_AT_KEY,
    RECORD_FIRST_APPLIED_AT_KEY,
    RECORD_LAST_APPLIED_AT_KEY,
    RECORD_LAST_UNAPPLIED_AT_KEY,
    RECORD_LAST_NOT_FOR_ME_AT_KEY,
    RECORD_TIMES_NOT_FOR_ME_KEY,
    RECORD_LAST_BLOCK_TITLE_AT_KEY,
    RECORD_TIMES_BLOCK_TITLE_KEY,
    RECORD_REJECT_TITLE_RULES_KEY,
)


def rebuild_dashboard_after_rule_change(reason: str = "matching rule change") -> None:
    if not get_dashboard_path().exists() and not get_run_stats_path().exists() and not get_audit_records_path().exists():
        return

    def _rebuild() -> None:
        try:
            rebuild_html_dashboard(reason=f"{reason}; applying saved filters to current dashboard")
        except Exception as exc:
            print(f"[DASHBOARD][WARN] Could not rebuild after rule change: {type(exc).__name__}: {exc}")

    threading.Thread(
        target=_rebuild,
        daemon=True,
        name="job-hunter-dashboard-rebuild",
    ).start()


def load_job_history() -> dict:
    job_history_path = get_job_history_path()
    if not job_history_path.exists():
        return {}
    try:
        payload = json.loads(job_history_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return {}


def save_job_history(history: dict) -> None:
    job_history_path = get_job_history_path()
    job_history_path.parent.mkdir(parents=True, exist_ok=True)
    job_history_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_audit_rows() -> list[dict[str, Any]]:
    audit_records_path = get_audit_records_path()
    if not audit_records_path.exists():
        return []
    try:
        data = json.loads(audit_records_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _normalize_requirement_blocker(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip())
    return cleaned[:80]


def _normalize_description_block_phrase(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "").strip().lower())
    return cleaned[:120]


def get_job_description(job_id: str) -> str:
    history = load_job_history()
    # Standardize the ID before lookup to ensure it matches the namespaced keys in history
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
                    # Check against the normalized ID
                    if normalize_job_key(str(row.get(RECORD_JOB_KEY) or "")) == normalized_key:
                        return row.get(RECORD_FULL_DESCRIPTION_KEY) or row.get(RECORD_FIT_SOURCE_TEXT_KEY) or ""
        except Exception:
            pass
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
    resolved_company = company or entry.get(RECORD_COMPANY_KEY) or snapshot.get(RECORD_COMPANY_KEY) or ""
    resolved_url = url or entry.get(RECORD_URL_KEY) or snapshot.get(RECORD_URL_KEY) or ""
    resolved_teaser = teaser or snapshot.get(RECORD_TEASER_KEY) or entry.get(RECORD_TEASER_KEY) or ""

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
        entry[RECORD_TIMES_BLOCK_TITLE_KEY] = int(entry.get(RECORD_TIMES_BLOCK_TITLE_KEY, 0) or 0) + 1

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
    rebuild_dashboard_after_rule_change(f"review action saved: {action}")
    return {
        "ok": True,
        "action": action,
        "job_key": normalized,
        "saved_count": len(existing),
        "reload_dashboard": True,
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
    rebuild_dashboard_after_rule_change(f"review action saved: {action}")
    return {
        "ok": True,
        "action": action,
        "job_key": normalized,
        "saved_count": len(updated),
        "reload_dashboard": True,
    }


def record_job_view(job_key: str, url: str = "", title: str = "") -> dict:
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        raise ValueError("Missing job key")

    history = load_job_history()
    entry = history.get(normalized, {})
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")

    entry[RECORD_JOB_KEY] = normalized
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


def build_title_block_followups(blockers: list[str]) -> list[dict[str, Any]]:
    profile = load_profile()
    existing_patterns = {
        str(rule.get("pattern") or "").strip()
        for rule in profile.get(RECORD_REJECT_TITLE_RULES_KEY, [])
        if isinstance(rule, dict)
    }
    audit_rows = _load_audit_rows()
    history = load_job_history()
    suggestions: list[dict[str, Any]] = []
    seen_phrases: set[str] = set()

    for blocker in blockers:
        phrase = normalize_title_block_phrase(blocker)
        if not phrase or phrase in seen_phrases:
            continue
        seen_phrases.add(phrase)
        rule = build_title_block_rule(phrase)
        if rule["pattern"] in existing_patterns:
            continue

        matcher = re.compile(rule["pattern"], re.IGNORECASE)
        rejected_keys: set[str] = set()
        kept_keys: set[str] = set()
        rejected_examples: list[dict[str, str]] = []
        kept_examples: list[dict[str, str]] = []

        for row in audit_rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get(RECORD_TITLE_KEY) or "").strip()
            if not title or not matcher.search(title.lower()):
                continue
            job_key = normalize_job_key(str(row.get(RECORD_JOB_KEY) or row.get(RECORD_URL_KEY) or title))
            item = {
                RECORD_TITLE_KEY: title,
                RECORD_COMPANY_KEY: str(row.get(RECORD_COMPANY_KEY) or "").strip(),
            }
            if str(row.get("decision") or "").strip().upper() == "KEEP":
                if job_key and job_key in kept_keys:
                    continue
                if job_key:
                    kept_keys.add(job_key)
                if len(kept_examples) < 3:
                    kept_examples.append(item)
                continue
            if job_key and job_key in rejected_keys:
                continue
            if job_key:
                rejected_keys.add(job_key)
            if len(rejected_examples) < 3:
                rejected_examples.append(item)

        for raw_key, entry in history.items():
            if not isinstance(entry, dict):
                continue
            if int(entry.get("times_kept", 0) or 0) <= 0:
                continue
            job_key = normalize_job_key(str(raw_key))
            if job_key and job_key in kept_keys:
                continue
            snapshot = entry.get("last_kept_snapshot") if isinstance(entry.get("last_kept_snapshot"), dict) else {}
            title = str(snapshot.get(RECORD_TITLE_KEY) or entry.get(RECORD_TITLE_KEY) or "").strip()
            if not title or not matcher.search(title.lower()):
                continue
            if job_key:
                kept_keys.add(job_key)
            if len(kept_examples) < 3:
                kept_examples.append({
                    RECORD_TITLE_KEY: title,
                    RECORD_COMPANY_KEY: str(snapshot.get(RECORD_COMPANY_KEY) or entry.get(RECORD_COMPANY_KEY) or "").strip(),
                })

        rejected_count = len(rejected_keys) or len(rejected_examples)
        kept_count = len(kept_keys) or len(kept_examples)
        if rejected_count < 2 or kept_count > 0:
            continue

        suggestions.append({
            "phrase": phrase,
            "matched_rejected_count": rejected_count,
            "matched_kept_count": kept_count,
            "sample_rejected_titles": rejected_examples,
            "sample_kept_titles": kept_examples,
        })

    suggestions.sort(key=lambda item: (
        -int(item.get("matched_rejected_count", 0) or 0),
        str(item.get("phrase") or ""),
    ))
    return suggestions[:4]


def build_description_block_followups(blockers: list[str]) -> list[dict[str, Any]]:
    profile = load_profile()
    existing_phrases = {
        _normalize_description_block_phrase(str(rule.get("phrase") or ""))
        for rule in profile.get("reject_description_phrase_rules", [])
        if isinstance(rule, dict)
    }
    audit_rows = _load_audit_rows()
    history = load_job_history()
    suggestions: list[dict[str, Any]] = []
    seen_phrases: set[str] = set()

    for blocker in blockers:
        phrase = _normalize_description_block_phrase(blocker)
        if len(phrase) < 3 or phrase in seen_phrases or phrase in existing_phrases:
            continue
        seen_phrases.add(phrase)

        rejected_keys: set[str] = set()
        kept_keys: set[str] = set()
        rejected_examples: list[dict[str, str]] = []
        kept_examples: list[dict[str, str]] = []

        for row in audit_rows:
            if not isinstance(row, dict):
                continue
            details_text = str(row.get("full_description") or row.get("fit_source_text") or "").strip().lower()
            if not details_text or phrase not in details_text:
                continue
            job_key = normalize_job_key(str(row.get("job_key") or row.get("url") or row.get("title") or phrase))
            item = {
                "title": str(row.get("title") or "").strip(),
                "company": str(row.get("company") or "").strip(),
            }
            if str(row.get("decision") or "").strip().upper() == "KEEP":
                if job_key and job_key in kept_keys:
                    continue
                if job_key:
                    kept_keys.add(job_key)
                if len(kept_examples) < 3:
                    kept_examples.append(item)
                continue
            if job_key and job_key in rejected_keys:
                continue
            if job_key:
                rejected_keys.add(job_key)
            if len(rejected_examples) < 3:
                rejected_examples.append(item)

        for raw_key, entry in history.items():
            if not isinstance(entry, dict):
                continue
            if int(entry.get("times_kept", 0) or 0) <= 0:
                continue
            snapshot = entry.get("last_kept_snapshot") if isinstance(entry.get("last_kept_snapshot"), dict) else {}
            details_text = str(snapshot.get("full_description") or snapshot.get("fit_source_text") or "").strip().lower()
            if not details_text or phrase not in details_text:
                continue
            job_key = normalize_job_key(str(raw_key))
            if job_key and job_key in kept_keys:
                continue
            if job_key:
                kept_keys.add(job_key)
            if len(kept_examples) < 3:
                kept_examples.append({
                    "title": str(snapshot.get("title") or entry.get("title") or "").strip(),
                    "company": str(snapshot.get("company") or entry.get("company") or "").strip(),
                })

        rejected_count = len(rejected_keys) or len(rejected_examples)
        kept_count = len(kept_keys) or len(kept_examples)
        if rejected_count < 2 or kept_count > 0:
            continue

        suggestions.append({
            "phrase": phrase,
            "matched_rejected_count": rejected_count,
            "matched_kept_count": kept_count,
            "sample_rejected_titles": rejected_examples,
            "sample_kept_titles": kept_examples,
        })

    suggestions.sort(key=lambda item: (
        -int(item.get("matched_rejected_count", 0) or 0),
        str(item.get("phrase") or ""),
    ))
    return suggestions[:4]


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
    persist_review_event("not_for_me", normalized, url=url, title=title, company=company, teaser=teaser)
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
        rebuild_dashboard_after_rule_change(f"title block added for {', '.join(resolved)}")

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
        message = f"Blocked {len(added_rules)} pattern(s). Similar jobs will be filtered in future runs."
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
        rebuild_dashboard_after_rule_change(f"description phrase rule added for {', '.join(resolved)}")

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


def save_requirement_blockers_feedback(
    job_key: str,
    url: str = "",
    title: str = "",
    company: str = "",
    teaser: str = "",
    blockers: list[str] | None = None,
    title_block_phrases: list[str] | None = None,
    description_block_phrases: list[str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        raise ValueError("Missing job key")

    cleaned_blockers: list[str] = []
    seen_blockers: set[str] = set()
    for raw in blockers or []:
        cleaned = _normalize_requirement_blocker(str(raw or ""))
        normalized_blocker = cleaned.lower()
        if len(cleaned) < 2 or normalized_blocker in seen_blockers:
            continue
        seen_blockers.add(normalized_blocker)
        cleaned_blockers.append(cleaned)

    if not cleaned_blockers:
        raise ValueError("At least one blocker is required")

    profile = load_profile()
    existing_blockers = list(profile.get("must_not_require_skills", []))
    existing_lookup = {
        _normalize_requirement_blocker(str(item or "")).lower()
        for item in existing_blockers
        if _normalize_requirement_blocker(str(item or ""))
    }
    added_blockers: list[str] = []
    skipped_blockers: list[str] = []
    for blocker in cleaned_blockers:
        blocker_key = blocker.lower()
        if blocker_key in existing_lookup:
            skipped_blockers.append(blocker)
            continue
        existing_lookup.add(blocker_key)
        existing_blockers.append(blocker)
        added_blockers.append(blocker)

    if added_blockers:
        profile["must_not_require_skills"] = existing_blockers
        save_profile(profile)

    applied_title_block_phrases: list[str] = []
    applied_description_block_phrases: list[str] = []
    if title_block_phrases:
        title_result = save_block_similar_feedback(
            normalized, url=url, title=title, company=company, teaser=teaser,
            block_phrases=title_block_phrases,
        )
        applied_title_block_phrases = list(title_result.get("block_phrases") or [])
    if description_block_phrases:
        description_result = save_description_block_feedback(
            normalized, url=url, title=title, company=company, teaser=teaser,
            block_phrases=description_block_phrases,
        )
        applied_description_block_phrases = list(description_result.get("block_phrases") or [])

    if added_blockers:
        persist_review_event(
            "block_requirement", normalized, url=url, title=title, company=company, teaser=teaser,
            extra={
                "blockers_added": added_blockers,
                "title_block_phrases": applied_title_block_phrases,
                "description_block_phrases": applied_description_block_phrases,
            },
        )
    elif skipped_blockers:
        persist_review_event(
            "block_requirement", normalized, url=url, title=title, company=company, teaser=teaser,
            extra={
                "blockers_skipped": skipped_blockers,
                "title_block_phrases": applied_title_block_phrases,
                "description_block_phrases": applied_description_block_phrases,
            },
        )

    title_block_suggestions = (
        [] if applied_title_block_phrases else build_title_block_followups(cleaned_blockers)
    )
    description_block_suggestions = (
        [] if applied_description_block_phrases else build_description_block_followups(cleaned_blockers)
    )

    message_bits: list[str] = []
    if added_blockers:
        noun = "blocker" if len(added_blockers) == 1 else "blockers"
        message_bits.append(
            f"Added {len(added_blockers)} mandatory requirement {noun}. "
            "Future runs will only reject when those terms look required."
        )
    elif skipped_blockers:
        noun = "blocker" if len(skipped_blockers) == 1 else "blockers"
        message_bits.append(f"{len(skipped_blockers)} mandatory requirement {noun} already existed.")

    if applied_title_block_phrases:
        noun = "title block" if len(applied_title_block_phrases) == 1 else "title blocks"
        message_bits.append(f"Added {len(applied_title_block_phrases)} {noun} for stronger early filtering.")
    if applied_description_block_phrases:
        noun = "description block" if len(applied_description_block_phrases) == 1 else "description blocks"
        message_bits.append(f"Added {len(applied_description_block_phrases)} hard {noun} for future runs.")
    followup_count = len(title_block_suggestions) + len(description_block_suggestions)
    if followup_count:
        noun = "extra block" if followup_count == 1 else "extra blocks"
        message_bits.append(f"{followup_count} optional {noun} also has strong evidence from past rejections.")

    return {
        "ok": True,
        "job_key": normalized,
        "added_blockers": added_blockers,
        "skipped_blockers": skipped_blockers,
        "title_block_suggestions": title_block_suggestions,
        "description_block_suggestions": description_block_suggestions,
        "applied_title_block_phrases": applied_title_block_phrases,
        "applied_description_block_phrases": applied_description_block_phrases,
        "message": " ".join(message_bits).strip() or "Requirement blockers saved.",
    }
