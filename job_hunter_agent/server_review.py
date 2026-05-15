import json
import re
from typing import Any

from job_hunter_agent.filters import build_title_block_rule, normalize_title_block_phrase
from job_hunter_agent.review_history_service import (
    _load_audit_rows,
    _normalize_description_block_phrase,
    _normalize_requirement_blocker,
    load_job_history,
    persist_review_event,
    save_block_similar_feedback,
    save_description_block_feedback,
)
from job_hunter_agent.profile_store import load_profile, save_profile
from job_hunter_agent.record_schema import (
    RECORD_TITLE_KEY,
    RECORD_COMPANY_KEY,
    RECORD_REJECT_TITLE_RULES_KEY,
)


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
    if not normalized and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(job_key or "").strip().lower()):
        normalized = str(job_key).strip().lower()
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
