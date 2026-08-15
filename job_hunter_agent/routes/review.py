"""Route handlers for review."""

import hashlib
import logging
import re

from fastapi import APIRouter, Body, Query

from job_hunter_agent import llm_gate
from job_hunter_agent import server_helpers as srv
from job_hunter_agent.io_utils import load_job_history
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES,
    LLM_PROFILE_RESOLUTION_EXISTING,
    LLM_PROFILE_RESOLUTION_NEW,
)
from job_hunter_agent.profile_gaps import (
    STATUS_CONFIRMED_DO_NOT_HAVE,
    STATUS_CONFIRMED_HAVE,
    classify_requirement_status,
)
from job_hunter_agent.profile_item_names import normalize_profile_item_name
from job_hunter_agent.profile_store import CAPABILITY_ICON_GENERIC
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_CAPABILITIES,
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_ELIGIBILITY_FACTS,
    KEY_CANDIDATE_QUALIFICATIONS,
)
from job_hunter_agent.eligibility_profile import prepare_eligibility_fact
from job_hunter_agent.record_schema import (
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)
from job_hunter_agent.review_history_service import (
    append_review_key,
    get_job_description,
    record_job_view,
    remove_review_key,
    save_block_similar_feedback,
    save_not_for_me_feedback,
)
from job_hunter_agent.routes.responses import json_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/rejection-suggestions")
def api_rejection_suggestions(job_id: str = Query("")):  # type: ignore[no-untyped-def]
    job_id = job_id.strip()
    if not job_id:
        return json_response({"error": "job_id is required"}, 400)
    description = get_job_description(job_id)
    if not description:
        return json_response({})
    description_hash = hashlib.sha1(description.encode("utf-8")).hexdigest()
    cached = srv._rejection_suggestions_cache.get(job_id)
    if isinstance(cached, dict) and cached.get("description_hash") == description_hash:
        suggestions = cached.get("suggestions") or []
        if not isinstance(cached.get("approval_tokens"), dict):
            cached["approval_tokens"] = (
                srv.SettingsHandler._issue_rejection_suggestion_approval_tokens(
                    job_id,
                    suggestions,
                )
            )
        logger.debug("Rejection suggestions cache hit: job_id=%s suggestions=%s", job_id, suggestions)
    else:
        suggestions = llm_gate.llm_suggest_rejection_blockers(description)
        approval_tokens = srv.SettingsHandler._issue_rejection_suggestion_approval_tokens(
            job_id, suggestions
        )
        srv._rejection_suggestions_cache[job_id] = {
            "description_hash": description_hash,
            "suggestions": list(suggestions),
            "approval_tokens": approval_tokens,
        }
    approval_tokens = {}
    if isinstance(srv._rejection_suggestions_cache.get(job_id), dict):
        approval_tokens = srv._rejection_suggestions_cache[job_id].get("approval_tokens") or {}
    if suggestions:
        return json_response({"other": suggestions, "approval_tokens": approval_tokens})
    return json_response({})


@router.post("/api/tuning-decisions")
@router.post("/api/skill-decisions")
def api_tuning_decisions(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        decisions = body.get("decisions", [])
        if not isinstance(decisions, list):
            raise ValueError("decisions must be a list")
        profile = srv.load_profile()
        updated = srv.apply_capability_tuning_decisions(profile, decisions)
        srv.save_profile(updated)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(
        {
            "ok": True,
            "message": "Capability tuning decision saved.",
            "profile": updated,
        },
    )


@router.post("/api/rule/phrase")
def api_rule_phrase(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        phrase = str(body.get("phrase") or "").strip().lower()
        reason = str(body.get("reason") or "").strip()
        if not phrase:
            raise ValueError("phrase is required")
        profile = srv.load_profile()
        existing = list(profile.get("reject_description_phrase_rules", []))
        if not any(str(r.get("phrase") or "").strip().lower() == phrase for r in existing):
            existing.append({"phrase": phrase, "reason": reason or f"DESC_REJECT:{phrase}"})
            profile["reject_description_phrase_rules"] = existing
            updated = srv.save_profile(profile)
            srv.rebuild_workspace_after_rule_change(f"description phrase rule added for {phrase}")
        else:
            updated = profile
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(
        {"ok": True, "message": f"Phrase rule added: {phrase}", "profile": updated}
    )


@router.post("/api/rejection-feedback/required-blockers")
def api_rejection_feedback_required_blockers(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        blockers = body.get("blockers", [])
        title_block_phrases = body.get("title_block_phrases", [])
        description_block_phrases = body.get("description_block_phrases", [])
        approved_suggestion_tokens = body.get("approved_suggestion_tokens") or {}
        if not isinstance(blockers, list):
            raise ValueError("blockers must be a list")
        if title_block_phrases is None:
            title_block_phrases = []
        if description_block_phrases is None:
            description_block_phrases = []
        if not isinstance(title_block_phrases, list):
            raise ValueError("title_block_phrases must be a list")
        if not isinstance(description_block_phrases, list):
            raise ValueError("description_block_phrases must be a list")
        if not isinstance(approved_suggestion_tokens, dict):
            raise ValueError("approved_suggestion_tokens must be an object")
        resolved_job_id = str(body.get("job_id") or body.get("job_key") or "").strip()
        srv.SettingsHandler._validate_llm_suggestion_approvals(
            resolved_job_id,
            [str(item or "") for item in blockers],
            approved_suggestion_tokens=approved_suggestion_tokens,
        )
        result = srv.save_requirement_blockers_feedback(
            resolved_job_id,
            url=str(body.get("url") or "").strip(),
            title=str(body.get("job_title") or body.get("title") or "").strip(),
            company=str(body.get("company") or "").strip(),
            teaser=str(body.get("teaser") or "").strip(),
            blockers=[str(item or "") for item in blockers],
            title_block_phrases=[str(item or "") for item in title_block_phrases],
            description_block_phrases=[str(item or "") for item in description_block_phrases],
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(result)


@router.post("/api/title-block-preview")
def api_title_block_preview(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        phrases = [str(p).strip() for p in (body.get("phrases") or []) if str(p).strip()]
        from job_hunter_agent.io_utils import load_audit_rows

        rows = load_audit_rows()
        titles = [str(r.get("title") or "").lower() for r in rows if r.get("title")]
        counts: dict[str, int] = {}
        for phrase in phrases:
            norm = re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
            tokens = [t for t in norm.split() if t]
            if not tokens:
                counts[phrase] = 0
                continue
            pattern = r"\b" + r"\s+".join(re.escape(t) for t in tokens[:3]) + r"\b"
            counts[phrase] = sum(1 for t in titles if re.search(pattern, t))
        matched_titles: set[str] = set()
        for phrase in phrases:
            norm = re.sub(r"[^a-z0-9]+", " ", phrase.lower()).strip()
            tokens = [t for t in norm.split() if t]
            if not tokens:
                continue
            pattern = r"\b" + r"\s+".join(re.escape(t) for t in tokens[:3]) + r"\b"
            for t in titles:
                if re.search(pattern, t):
                    matched_titles.add(t)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"counts": counts, "total": len(matched_titles)})


@router.post("/api/review")
def api_review(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    action = str(body.get("action", "")).strip().lower()
    job_key = str(body.get("job_key") or body.get("url") or "").strip()
    logger.info("api_review entry: action=%s job_key=%s", action, job_key)
    try:
        url = str(body.get("url") or "").strip()
        title = str(body.get("title") or "").strip()
        company = str(body.get("company") or "").strip()
        teaser = str(body.get("teaser") or "").strip()
        if action == "viewed":
            result = record_job_view(job_key, url, title)
        elif action == "not_for_me":
            result = save_not_for_me_feedback(job_key, url, title, company, teaser)
        elif action == "block_similar":
            raw = body.get("block_phrases")
            if isinstance(raw, list) and raw:
                phrases_arg = [str(p).strip() for p in raw if str(p).strip()]
            else:
                single = str(body.get("block_phrase") or "").strip()
                phrases_arg = [single] if single else []
            result = save_block_similar_feedback(
                job_key,
                url,
                title,
                company,
                teaser,
                block_phrases=phrases_arg or None,
            )
        elif action in {"unapply", "unhide"}:
            result = remove_review_key(action, job_key, url, title, company, teaser)
        else:
            result = append_review_key(action, job_key, url, title, company, teaser)
    except Exception as exc:
        logger.exception("api_review failed: action=%s job_key=%s", action, job_key)
        return json_response({"error": str(exc)}, 400)
    logger.info("api_review success: action=%s job_key=%s", action, job_key)
    return json_response(result)


@router.delete("/api/rule/title-block")
def api_rule_title_block_delete(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        pattern = str(body.get("pattern") or "").strip()
        if not pattern:
            raise ValueError("pattern is required")
        profile = srv.load_profile()
        existing = list(profile.get("reject_title_rules", []))
        updated_rules = [r for r in existing if str(r.get("pattern") or "").strip() != pattern]
        if len(updated_rules) == len(existing):
            return json_response({"error": "Rule not found"}, 404)
        profile["reject_title_rules"] = updated_rules
        saved = srv.save_profile(profile)
        srv.rebuild_workspace_after_rule_change(f"title block rule removed: {pattern}")
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"ok": True, "reject_title_rules": saved.get("reject_title_rules", [])})


_PROFILE_GAP_VALID_ACTIONS = frozenset({"confirm_have", "confirm_do_not_have"})
_PROFILE_GAP_CONFIRMABLE_STATUSES = frozenset({"not_shown", "mismatch", "invalid"})


def _profile_gap_name_key(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _profile_gap_requirement_coverage(job_key: str) -> list[dict]:
    normalized_job_key = normalize_job_key(job_key)
    if not normalized_job_key:
        return []
    history = load_job_history()
    entry = history.get(normalized_job_key)
    if not isinstance(entry, dict):
        return []
    coverage = entry.get(RECORD_REQUIREMENT_COVERAGE_KEY)
    if not isinstance(coverage, list):
        snapshot = entry.get(RECORD_LAST_KEPT_SNAPSHOT_KEY)
        if isinstance(snapshot, dict):
            coverage = snapshot.get(RECORD_REQUIREMENT_COVERAGE_KEY)
    if not isinstance(coverage, list):
        return []
    return [item for item in coverage if isinstance(item, dict)]


def _profile_gap_coverage_name(item: dict) -> str:
    """Return the display/lookup name for a confirmable coverage item.

    canonical_requirement is the one field guaranteed non-empty whenever
    profile_action_allowed is True (see llm_gate.normalize_llm_requirement_coverage);
    matched_candidate_fact/capability_name/eligibility_name are blanked on the
    common not_shown path, so they must not be tried first.
    """
    return str(
        item.get("canonical_requirement")
        or item.get("matched_candidate_fact")
        or item.get("profile_name")
        or item.get("capability_name")
        or item.get("eligibility_name")
        or ""
    ).strip()


def _profile_gap_confirmable_item(job_key: str, value: str) -> dict:
    target_name = _profile_gap_name_key(value)
    if not target_name:
        return {}
    for item in _profile_gap_requirement_coverage(job_key):
        if str(item.get("status") or "").strip().lower() not in _PROFILE_GAP_CONFIRMABLE_STATUSES:
            continue
        if item.get("profile_action_allowed") is not True:
            continue
        raw_requirement_type = str(item.get("requirement_type") or "").strip().lower()
        if raw_requirement_type and raw_requirement_type not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            continue
        coverage_name = _profile_gap_coverage_name(item)
        if _profile_gap_name_key(coverage_name) != target_name:
            continue
        return dict(item)
    return {}


def _profile_gap_eligibility_index(profile: dict) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for idx, item in enumerate(profile.get(KEY_CANDIDATE_ELIGIBILITY, []) or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        normalized = _profile_gap_name_key(name)
        if normalized:
            lookup[normalized] = idx
    return lookup


def _profile_gap_qualification_index(profile: dict) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for idx, item in enumerate(profile.get(KEY_CANDIDATE_QUALIFICATIONS, []) or []):
        if not isinstance(item, dict):
            continue
        name = _profile_gap_name_key(item.get("name"))
        if name:
            lookup[name] = idx
    return lookup


def _matches_managed_clearance(name: str) -> bool:
    target = _profile_gap_name_key(name)
    return any(
        target in {
            _profile_gap_name_key(option.get("value")),
            _profile_gap_name_key(option.get("label")),
            *(_profile_gap_name_key(alias) for alias in (option.get("aliases") or [])),
        }
        for option in srv.load_clearance_ui_options()
        if isinstance(option, dict)
    )


def _resolve_and_confirm_requirement(canonical_item: dict, profile: dict) -> dict:
    """Turn a user-confirmed job requirement into a candidate profile write.

    Delegates the existing/new/unresolved storage decision to the dedicated
    click-time LLM resolver (llm_gate.llm_resolve_profile_storage) rather than
    blindly appending a new top-level profile item. Raises ValueError with a
    user-facing message on unresolved or failed resolution — the caller must
    not fall back to a blind append. Reloading the profile on every call and
    resolving `existing` to a no-op (or an idempotent aliases merge) makes
    repeating the same confirmation safe to call more than once.
    """
    requirement_type = str(canonical_item.get("requirement_type") or "capability").strip().lower()
    try:
        resolved = llm_gate.llm_resolve_profile_storage(canonical_item, profile)
    except llm_gate.LLMCallError as exc:
        raise ValueError(f"Could not confirm this requirement: {exc}") from exc

    resolution = resolved["resolution"]
    profile_target = resolved["profile_target"]

    if resolution == LLM_PROFILE_RESOLUTION_EXISTING:
        related_terms = resolved.get("related_terms") or []
        if requirement_type == "capability" and related_terms:
            capabilities = list(profile.get(KEY_CANDIDATE_CAPABILITIES) or [])
            target_key = normalize_profile_item_name(profile_target).casefold()
            for idx, item in enumerate(capabilities):
                if not isinstance(item, dict):
                    continue
                if normalize_profile_item_name(item.get("name")).casefold() != target_key:
                    continue
                existing_aliases = list(item.get("aliases") or [])
                seen_aliases = {
                    normalize_profile_item_name(alias).casefold() for alias in existing_aliases
                }
                merged_aliases = list(existing_aliases)
                for term in related_terms:
                    term_key = normalize_profile_item_name(term).casefold()
                    if not term_key or term_key in seen_aliases:
                        continue
                    seen_aliases.add(term_key)
                    merged_aliases.append(term)
                merged = dict(item)
                merged["aliases"] = merged_aliases
                capabilities[idx] = merged
                profile[KEY_CANDIDATE_CAPABILITIES] = capabilities
                srv.save_profile(profile)
                break
        return {"ok": True, "resolution": resolution, "profile_target": profile_target}

    if resolution == LLM_PROFILE_RESOLUTION_NEW:
        if requirement_type == "qualification":
            qualifications = list(profile.get(KEY_CANDIDATE_QUALIFICATIONS) or [])
            qualifications.append(
                {
                    "name": profile_target,
                    "value": True,
                    "aliases": [],
                    "evidence": [str(canonical_item.get("matched_job_text") or "").strip()]
                    if str(canonical_item.get("matched_job_text") or "").strip()
                    else [],
                    "needs_review": False,
                }
            )
            profile[KEY_CANDIDATE_QUALIFICATIONS] = qualifications
        elif requirement_type == "eligibility":
            eligibility_key = (
                KEY_CANDIDATE_ELIGIBILITY
                if _matches_managed_clearance(profile_target)
                else KEY_CANDIDATE_ELIGIBILITY_FACTS
            )
            eligibility = list(profile.get(eligibility_key) or [])
            eligibility.append(
                {
                    "name": profile_target,
                    "value": True,
                    "evidence": [str(canonical_item.get("matched_job_text") or "").strip()]
                    if str(canonical_item.get("matched_job_text") or "").strip()
                    else [],
                    "needs_review": False,
                }
            )
            if eligibility_key == KEY_CANDIDATE_ELIGIBILITY_FACTS:
                eligibility, _ = prepare_eligibility_fact(
                    profile.get(KEY_CANDIDATE_ELIGIBILITY_FACTS) or [],
                    name=profile_target,
                    value=True,
                    evidence=[str(canonical_item.get("matched_job_text") or "").strip()]
                    if str(canonical_item.get("matched_job_text") or "").strip()
                    else [],
                )
            profile[eligibility_key] = eligibility
        else:
            capabilities = list(profile.get(KEY_CANDIDATE_CAPABILITIES) or [])
            capabilities.append(
                {
                    "name": profile_target,
                    "level": "working",
                    "fit": "supporting",
                    "aliases": [],
                    "icon_key": CAPABILITY_ICON_GENERIC,
                }
            )
            profile[KEY_CANDIDATE_CAPABILITIES] = capabilities
        srv.save_profile(profile)
        return {"ok": True, "resolution": resolution, "profile_target": profile_target}

    raise ValueError("This requirement is not specific enough to safely add to your profile.")


@router.post("/api/profile-gap")
def api_profile_gap(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    """Record a user response to a 'Needs confirmation' gap on a job card.

    confirm_have        → add the canonical profile item to the matching profile bucket
    confirm_do_not_have → add the canonical negative profile signal to the matching bucket
    """
    try:
        action = str(body.get("action", "")).strip()
        capability_name = str(body.get("capability_name", "")).strip()
        job_key = str(body.get("job_key", "")).strip()
        if action not in _PROFILE_GAP_VALID_ACTIONS:
            raise ValueError(f"invalid action: {action!r}")

        if not job_key:
            raise ValueError("job_key is required")
        if not capability_name:
            raise ValueError("capability_name is required")

        canonical_item = _profile_gap_confirmable_item(job_key, capability_name)
        if not canonical_item:
            raise ValueError(
                "capability_name is not a confirmable requirement coverage item for this job"
            )
        canonical_item_name = _profile_gap_coverage_name(canonical_item)
        requirement_type = str(canonical_item.get("requirement_type") or "capability").strip().lower()
        if requirement_type == "qualification" and not str(
            canonical_item.get("canonical_requirement") or ""
        ).strip():
            # matched_candidate_fact is not vetted for a single-concept name (only
            # canonical_requirement is, gated by profile_action_allowed — see
            # llm_gate.normalize_llm_requirement_coverage). _profile_gap_confirmable_item
            # already requires profile_action_allowed is True, so canonical_requirement
            # should always be resolved here. No fallback to the unvetted name: a
            # stale or malformed historical job record missing canonical_requirement
            # must be rejected, not silently trusted.
            raise ValueError(
                "qualification requirement coverage item is missing a resolved canonical_requirement"
            )

        profile = srv.load_profile()
        current_status = classify_requirement_status(
            canonical_item_name,
            profile.get("candidate_capabilities") or [],
            profile.get("must_not_require_skills") or [],
            profile.get(KEY_CANDIDATE_ELIGIBILITY) or [],
            profile.get(KEY_CANDIDATE_ELIGIBILITY_FACTS) or [],
            requirement_type=requirement_type,
            candidate_qualifications=profile.get(KEY_CANDIDATE_QUALIFICATIONS) or [],
        )

        if action == "confirm_have":
            if current_status == STATUS_CONFIRMED_HAVE:
                return json_response({"ok": True})
            if requirement_type == "capability" and current_status == STATUS_CONFIRMED_DO_NOT_HAVE:
                raise ValueError("capability_name is already saved as must_not_require_skills")
            result = _resolve_and_confirm_requirement(canonical_item, profile)
            return json_response(result)

        elif action == "confirm_do_not_have":
            if current_status == STATUS_CONFIRMED_DO_NOT_HAVE:
                return json_response({"ok": True})
            if requirement_type == "qualification":
                qualifications = list(profile.get(KEY_CANDIDATE_QUALIFICATIONS) or [])
                lookup = _profile_gap_qualification_index(profile)
                item_value = {
                    "name": canonical_item_name,
                    "value": False,
                    "aliases": [],
                    "evidence": [str(canonical_item.get("matched_job_text") or "").strip()]
                    if str(canonical_item.get("matched_job_text") or "").strip()
                    else [],
                    "needs_review": False,
                }
                normalized_name = _profile_gap_name_key(canonical_item_name)
                if normalized_name in lookup:
                    qualifications[lookup[normalized_name]] = item_value
                else:
                    qualifications.append(item_value)
                profile[KEY_CANDIDATE_QUALIFICATIONS] = qualifications
                srv.save_profile(profile)
            elif requirement_type == "eligibility":
                eligibility_key = (
                    KEY_CANDIDATE_ELIGIBILITY
                    if _matches_managed_clearance(canonical_item_name)
                    else KEY_CANDIDATE_ELIGIBILITY_FACTS
                )
                eligibility = list(profile.get(eligibility_key) or [])
                lookup = _profile_gap_eligibility_index(profile)
                normalized_name = _profile_gap_name_key(canonical_item_name)
                item_value = {
                    "name": canonical_item_name,
                    "value": False,
                    "evidence": [str(canonical_item.get("matched_job_text") or "").strip()]
                    if str(canonical_item.get("matched_job_text") or "").strip()
                    else [],
                    "needs_review": False,
                }
                if normalized_name in lookup:
                    eligibility[lookup[normalized_name]] = item_value
                else:
                    eligibility.append(item_value)
                if eligibility_key == KEY_CANDIDATE_ELIGIBILITY_FACTS:
                    eligibility, _ = prepare_eligibility_fact(
                        profile.get(KEY_CANDIDATE_ELIGIBILITY_FACTS) or [],
                        name=canonical_item_name,
                        value=False,
                        evidence=[str(canonical_item.get("matched_job_text") or "").strip()]
                        if str(canonical_item.get("matched_job_text") or "").strip()
                        else [],
                    )
                profile[eligibility_key] = eligibility
                srv.save_profile(profile)
            else:
                if current_status == STATUS_CONFIRMED_HAVE:
                    raise ValueError("capability_name is already saved as a candidate capability")
                skills = list(profile.get("must_not_require_skills") or [])
                if canonical_item_name not in skills:
                    skills.append(canonical_item_name)
                    profile["must_not_require_skills"] = skills
                    srv.save_profile(profile)

    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"ok": True})
