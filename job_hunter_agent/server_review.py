import re
from typing import Any, Callable

from job_hunter_agent.filters import (
    build_title_block_rule,
    normalize_title_block_phrase,
    suggest_title_block_phrase,
)
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.review_history_service import (
    _load_audit_rows,
    _normalize_description_block_phrase,
    _normalize_requirement_blocker,
    load_job_history,
    persist_review_event,
)
from job_hunter_agent.profile_store import load_profile, save_profile
from job_hunter_agent.record_schema import (
    RECORD_TITLE_KEY,
    RECORD_COMPANY_KEY,
    RECORD_JOB_KEY,
    RECORD_URL_KEY,
    RECORD_REJECT_TITLE_RULES_KEY,
    RECORD_REJECT_DESCRIPTION_PHRASE_RULES_KEY,
)
from job_hunter_agent.workspace_refresh_service import rebuild_workspace_after_rule_change


def _save_feedback_rules_generic(
    job_id: str,
    url: str,
    title: str,
    company: str,
    teaser: str,
    phrases: list[str],
    rules_key: str,
    rule_builder: Callable[[str], dict],
    existing_match_fn: Callable[[dict, str], bool],
    action: str,
    rebuild_reason_tmpl: str,
    extra_key: str,
    skipped_key: str,
) -> dict[str, Any]:
    """Generic engine for adding rules to profile and persisting review events."""
    profile = load_profile()
    existing = list(profile.get(rules_key, []))
    added_rules: list[dict] = []
    skipped: list[str] = []

    for phrase in phrases:
        if any(existing_match_fn(r, phrase) for r in existing):
            skipped.append(phrase)
            continue
        rule = rule_builder(phrase)
        existing.append(rule)
        added_rules.append(rule)

    if added_rules:
        profile[rules_key] = existing
        save_profile(profile)
        rebuild_workspace_after_rule_change(rebuild_reason_tmpl.format(phrases=", ".join(phrases)))

    persist_review_event(
        action,
        job_id,
        url=url,
        title=title,
        company=company,
        teaser=teaser,
        extra={
            "extracted_phrases": phrases,
            extra_key: [r.get("pattern") or r.get("phrase") for r in added_rules],
            skipped_key: skipped,
        },
    )
    return {"block_phrases": phrases, "rules_added": added_rules, "skipped": skipped}


def _save_block_similar_feedback_impl(
    job_key: str, url: str = "", title: str = "", company: str = "", teaser: str = "", block_phrases: list[str] | None = None,
) -> dict:
    """Saves feedback to block similar jobs based on title.

    Args:
        job_key: The unique identifier for the job.
        url: The URL of the job posting.
        title: The title of the job.
        company: The company offering the job.
        teaser: A short description or teaser of the job.
        block_phrases: A list of phrases to use for blocking similar job titles.

    Returns:
        A dictionary indicating the success of the operation and details of the blocked phrases.
    """
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        raise ValueError("Missing job key")

    resolved = [p for p in (normalize_title_block_phrase(p) for p in (block_phrases or [])) if p]
    if not resolved:
        fallback = suggest_title_block_phrase(title)
        if not fallback:
            raise ValueError("Could not suggest a title keyword to block from this title yet")
        resolved = [fallback]

    res = _save_feedback_rules_generic(
        normalized, url, title, company, teaser, resolved,
        rules_key=RECORD_REJECT_TITLE_RULES_KEY,
        rule_builder=build_title_block_rule,
        existing_match_fn=lambda r, p: str(r.get("pattern", "")).strip() == build_title_block_rule(p)["pattern"],
        action="block_title",
        rebuild_reason_tmpl="title block added for {phrases}",
        extra_key="rules_added",
        skipped_key="rules_skipped"
    )

    added, skipped = res["rules_added"], res["skipped"]
    if added and skipped:
        labels = "', '".join(r["reason"].split("'")[1] if "'" in r["reason"] else r["pattern"] for r in added)
        message = f"Blocked '{labels}'. {len(skipped)} pattern(s) already existed."
    elif added:
        message = f"Blocked {len(added)} pattern(s). Similar jobs will be filtered in future runs."
    else:
        message = "All selected patterns already existed as title block rules."

    return {"ok": True, "action": "block_similar", "job_key": normalized, "block_phrase": resolved[0],
            "block_phrases": resolved, "rules_added": added, "message": message}


def _save_description_block_feedback_impl(
    job_key: str, url: str = "", title: str = "", company: str = "", teaser: str = "", block_phrases: list[str] | None = None,
) -> dict[str, Any]:
    """Saves feedback to block jobs based on phrases found in their description.

    Args:
        job_key: The unique identifier for the job.
        url: The URL of the job posting.
        title: The title of the job.
        company: The company offering the job.
        teaser: A short description or teaser of the job.
        block_phrases: A list of phrases to use for blocking jobs by description.

    Returns:
        A dictionary indicating the success of the operation and details of the blocked phrases.
    """
    normalized = normalize_job_key(job_key or url)
    if not normalized:
        raise ValueError("Missing job key")

    resolved, seen = [], set()
    for p in (block_phrases or []):
        phrase = _normalize_description_block_phrase(p)
        if len(phrase) >= 3 and phrase not in seen:
            seen.add(phrase)
            resolved.append(phrase)

    if not resolved:
        raise ValueError("At least one description block phrase is required")

    res = _save_feedback_rules_generic(
        normalized, url, title, company, teaser, resolved,
        rules_key=RECORD_REJECT_DESCRIPTION_PHRASE_RULES_KEY,
        rule_builder=lambda p: {"phrase": p, "reason": f"DESC_REJECT:{p}"},
        existing_match_fn=lambda r, p: _normalize_description_block_phrase(str(r.get("phrase") or "")) == p,
        action="block_description",
        rebuild_reason_tmpl="description phrase rule added for {phrases}",
        extra_key="description_phrases_added",
        skipped_key="description_phrases_skipped"
    )

    added, skipped = res["rules_added"], res["skipped"]
    if added and skipped:
        labels = "', '".join(r["phrase"] for r in added)
        message = f"Blocked '{labels}'. {len(skipped)} phrase(s) already existed."
    elif added:
        message = f"Blocked {len(added)} phrase(s). Similar jobs will be filtered in future runs."
    else:
        message = "All selected phrases already existed as description block rules."

    return {"ok": True, "action": "block_description", "job_key": normalized, "block_phrases": resolved,
            "rules_added": added, "message": message}


def _collect_blocker_samples(
    matcher_fn: Callable[[dict], bool],
    audit_rows: list[dict],
    history: dict[str, dict]
) -> tuple[int, int, list[dict], list[dict]]:
    """Scan audit rows and history to find rejected and kept examples matching a condition."""
    rejected_keys: set[str] = set()
    kept_keys: set[str] = set()
    rejected_examples: list[dict[str, str]] = []
    kept_examples: list[dict[str, str]] = []

    def _add_example(row, keys_set, examples_list):
        job_key = normalize_job_key(str(row.get(RECORD_JOB_KEY) or row.get(RECORD_URL_KEY) or row.get(RECORD_TITLE_KEY) or ""))
        if not job_key or job_key in keys_set:
            return
        keys_set.add(job_key)
        if len(examples_list) < 3:
            examples_list.append({
                RECORD_TITLE_KEY: str(row.get(RECORD_TITLE_KEY) or "").strip(),
                RECORD_COMPANY_KEY: str(row.get(RECORD_COMPANY_KEY) or "").strip(),
            })

    for row in audit_rows:
        if not isinstance(row, dict) or not matcher_fn(row):
            continue
        if str(row.get("decision") or "").strip().upper() == "KEEP":
            _add_example(row, kept_keys, kept_examples)
        else:
            _add_example(row, rejected_keys, rejected_examples)

    for raw_key, entry in history.items():
        if not isinstance(entry, dict) or int(entry.get("times_kept", 0) or 0) <= 0:
            continue
        snapshot = entry.get("last_kept_snapshot") or {}
        combined = {**entry, **snapshot}
        if not matcher_fn(combined):
            continue
        _add_example({**combined, RECORD_JOB_KEY: raw_key}, kept_keys, kept_examples)

    return len(rejected_keys), len(kept_keys), rejected_examples, kept_examples


def _build_block_followups_generic(
    blockers: list[str],
    audit_rows: list[dict],
    history: dict[str, dict],
    existing_patterns: set[str],
    normalize_fn: Callable[[str], str],
    matcher_builder: Callable[[str], Callable[[dict], bool]],
    skip_phrase_fn: Callable[[str], bool] = lambda p: False,
) -> list[dict[str, Any]]:
    """Generic logic to identify blockers with high rejection signal in history."""
    suggestions: list[dict[str, Any]] = []
    seen_phrases: set[str] = set()

    for blocker in blockers:
        phrase = normalize_fn(blocker)
        if not phrase or phrase in seen_phrases or skip_phrase_fn(phrase) or phrase in existing_patterns:
            continue
        seen_phrases.add(phrase)

        matcher_fn = matcher_builder(phrase)
        rej_count, kept_count, rej_ex, kept_ex = _collect_blocker_samples(matcher_fn, audit_rows, history)

        if rej_count >= 2 and kept_count == 0:
            suggestions.append({
                "phrase": phrase,
                "matched_rejected_count": rej_count,
                "matched_kept_count": kept_count,
                "sample_rejected_titles": rej_ex,
                "sample_kept_titles": kept_ex,
            })

    suggestions.sort(key=lambda item: (-int(item.get("matched_rejected_count", 0)), str(item.get("phrase") or "")))
    return suggestions[:4]


def build_title_block_followups(blockers: list[str]) -> list[dict[str, Any]]:
    """Builds suggestions for title block rules based on historical rejections.

    Analyzes past rejected jobs containing the given blockers and suggests title
    block phrases that would have filtered those jobs.

    Args:
        blockers: A list of phrases that were identified as reasons for rejection.

    Returns: A list of dictionaries, each suggesting a title block phrase and its impact."""
    profile = load_profile()
    existing_phrases = {
        normalize_title_block_phrase(str(rule.get("reason") or "").split("TITLE_BAD_KEYWORD:")[-1])
        for rule in profile.get(RECORD_REJECT_TITLE_RULES_KEY, [])
        if isinstance(rule, dict) and "TITLE_BAD_KEYWORD:" in str(rule.get("reason") or "")
    }

    def title_matcher(p: str):
        pattern = build_title_block_rule(p)["pattern"]
        matcher = re.compile(pattern, re.IGNORECASE)
        return lambda r: bool(matcher.search(str(r.get(RECORD_TITLE_KEY) or "").strip()))

    return _build_block_followups_generic(
        blockers, _load_audit_rows(), load_job_history(), existing_phrases,
        normalize_fn=lambda b: normalize_title_block_phrase(b),
        matcher_builder=title_matcher
    )


def build_description_block_followups(blockers: list[str]) -> list[dict[str, Any]]:
    """Builds suggestions for description block rules based on historical rejections.

    Analyzes past rejected jobs containing the given blockers and suggests description
    block phrases that would have filtered those jobs.

    Args:
        blockers: A list of phrases that were identified as reasons for rejection.

    Returns: A list of dictionaries, each suggesting a description block phrase and its impact."""
    profile = load_profile()
    existing_phrases = {
        _normalize_description_block_phrase(str(rule.get("phrase") or ""))
        for rule in profile.get(RECORD_REJECT_DESCRIPTION_PHRASE_RULES_KEY, [])
        if isinstance(rule, dict)
    }

    def desc_matcher(p: str):
        return lambda r: p in str(r.get("full_description") or r.get("fit_source_text") or "").strip().lower()

    return _build_block_followups_generic(
        blockers, _load_audit_rows(), load_job_history(), existing_phrases,
        normalize_fn=_normalize_description_block_phrase,
        matcher_builder=desc_matcher,
        skip_phrase_fn=lambda p: len(p) < 3
    )


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
    """Saves feedback for mandatory requirement blockers and optionally applies title/description blocks.

    This function processes user feedback on job requirements that are considered blockers.
    It adds these blockers to the user's profile and can optionally apply immediate title
    or description blocking rules based on the provided phrases. It also suggests further
    blocking rules based on historical rejection data.

    Args:
        job_key: The unique identifier for the job.
        url: The URL of the job posting.
        title: The title of the job.
        company: The company offering the job.
        teaser: A short description or teaser of the job.
        blockers: A list of mandatory requirement phrases to block.
        title_block_phrases: Optional list of phrases to immediately apply as title block rules.
        description_block_phrases: Optional list of phrases to immediately apply as description block rules.
    """
    normalized = normalize_job_key(job_key or url)
    if not normalized and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", str(job_key or "").strip().lower()):
        normalized = str(job_key).strip().lower()
    if not normalized:
        raise ValueError("Missing job key")

    cleaned_blockers, seen_blockers = [], set()
    for raw in blockers or []:
        c = _normalize_requirement_blocker(str(raw or ""))
        if len(c) >= 2 and c.lower() not in seen_blockers:
            seen_blockers.add(c.lower())
            cleaned_blockers.append(c)

    if not cleaned_blockers:
        raise ValueError("At least one blocker is required")

    profile = load_profile()
    current_blockers = list(profile.get("must_not_require_skills", []))
    existing_norm = {_normalize_requirement_blocker(str(i)).lower() for i in current_blockers if i}
    added_blockers, skipped_blockers = [], []
    for b in cleaned_blockers:
        if b.lower() in existing_norm:
            skipped_blockers.append(b)
        else:
            current_blockers.append(b)
            added_blockers.append(b)
            existing_norm.add(b.lower())

    if added_blockers:
        profile["must_not_require_skills"] = current_blockers
        save_profile(profile)

    applied_titles = list(_save_block_similar_feedback_impl(normalized, url, title, company, teaser, title_block_phrases).get("block_phrases", [])) if title_block_phrases else []
    applied_descs = list(_save_description_block_feedback_impl(normalized, url, title, company, teaser, description_block_phrases).get("block_phrases", [])) if description_block_phrases else []

    if added_blockers or skipped_blockers:
        persist_review_event("block_requirement", normalized, url=url, title=title, company=company, teaser=teaser,
                             extra={"blockers_added": added_blockers, "blockers_skipped": skipped_blockers, "title_block_phrases": applied_titles, "description_block_phrases": applied_descs})

    title_sugg = [] if applied_titles else build_title_block_followups(cleaned_blockers)
    desc_sugg = [] if applied_descs else build_description_block_followups(cleaned_blockers)

    bits = []
    if added_blockers:
        bits.append(f"Added {len(added_blockers)} mandatory requirement {'blocker' if len(added_blockers)==1 else 'blockers'}.")
    elif skipped_blockers:
        bits.append(f"{len(skipped_blockers)} mandatory requirement blocker(s) already existed.")

    if applied_titles:
        bits.append(f"Added {len(applied_titles)} title block(s).")
    if applied_descs:
        bits.append(f"Added {len(applied_descs)} description block(s).")

    follow_count = len(title_sugg) + len(desc_sugg)
    if follow_count:
        bits.append(f"{follow_count} optional extra block(s) also have strong evidence.")

    return {"ok": True, "job_key": normalized, "added_blockers": added_blockers, "skipped_blockers": skipped_blockers,
            "title_block_suggestions": title_sugg, "description_block_suggestions": desc_sugg,
            "applied_title_block_phrases": applied_titles, "applied_description_block_phrases": applied_descs,
            "message": " ".join(bits).strip() or "Requirement blockers saved."}
