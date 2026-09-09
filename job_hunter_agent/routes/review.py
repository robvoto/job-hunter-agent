"""Route handlers for review."""

import hashlib
import logging
import re

from fastapi import APIRouter, Body, Query

from job_hunter_agent import llm_gate
from job_hunter_agent import server_helpers as srv
from job_hunter_agent.eligibility_profile import prepare_eligibility_fact
from job_hunter_agent.experience_requirements import extract_required_experience_months
from job_hunter_agent.io_utils import load_job_history
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.llm_protocol import (
    LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES,
    LLM_PROFILE_RESOLUTION_EXISTING,
    LLM_PROFILE_RESOLUTION_NEW,
    LLM_REQUIREMENT_KIND_PROFESSIONAL,
)
from job_hunter_agent.profile_fact_audit import record_profile_fact_confirmation
from job_hunter_agent.profile_gaps import (
    CONFIRMABLE_REQUIREMENT_STATUSES,
    STATUS_CONFIRMED_DO_NOT_HAVE,
    STATUS_CONFIRMED_HAVE,
    classify_requirement_status,
    list_custom_blocker_candidates,
    resolve_custom_blocker,
)
from job_hunter_agent.profile_item_names import normalize_profile_item_name
from job_hunter_agent.profile_store import (
    CAPABILITY_ICON_GENERIC,
    KEY_CANDIDATE_CAPABILITIES,
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_ELIGIBILITY_FACTS,
    KEY_CANDIDATE_QUALIFICATIONS,
    VALID_CAPABILITY_RULE_LEVELS,
)
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
from job_hunter_agent.review_insights import apply_capability_tuning_decisions
from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.server_review import save_requirement_blockers_feedback
from job_hunter_agent.workspace_renderer import render_custom_blocker_preview

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

    # The job's own mandatory, profile-actionable requirements. These are the
    # exact terms resolve_custom_blocker() accepts, so the panel can show them as
    # tick boxes instead of asking for a blind free-text term. Anything already
    # covered by an LLM suggestion is dropped so it is only offered once.
    suggestion_phrases_norm = {
        srv._normalize_suggestion_phrase(str(item or "")) for item in suggestions
    }
    suggestion_phrases_norm.discard("")
    required_terms = [
        candidate
        for candidate in list_custom_blocker_candidates(
            _profile_gap_requirement_coverage(job_id)
        )
        if srv._normalize_suggestion_phrase(candidate["term"]) not in suggestion_phrases_norm
    ]

    if suggestions or required_terms:
        return json_response(
            {
                "other": list(suggestions),
                "approval_tokens": approval_tokens,
                "required_terms": required_terms,
            }
        )
    return json_response({})


@router.post("/api/tuning-decisions")
@router.post("/api/skill-decisions")
def api_tuning_decisions(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        decisions = body.get("decisions", [])
        if not isinstance(decisions, list):
            raise ValueError("decisions must be a list")
        profile = srv.load_profile()
        factual_absence_items = [
            {
                "name": str(item.get("skill") or "").strip(),
                "level": "basic",
                "aliases": [],
            }
            for item in decisions
            if isinstance(item, dict)
            and str(item.get("choice") or "").strip().lower() in {"do_not_have", "dont_have"}
            and str(item.get("skill") or "").strip()
        ]
        if factual_absence_items:
            judgements = llm_gate.llm_validate_profile_capability_atomicity(factual_absence_items)
            rejected = [
                str(item.get("name") or "").strip()
                for item, atomic in zip(factual_absence_items, judgements, strict=True)
                if not atomic
            ]
            if rejected:
                raise ValueError(
                    "Only one clear professional capability can be confirmed at a time: "
                    + ", ".join(rejected)
                )
        updated = apply_capability_tuning_decisions(profile, decisions)
        srv.save_profile(updated)
        for item in decisions:
            if not isinstance(item, dict):
                continue
            skill = str(item.get("skill") or "").strip()
            choice = str(item.get("choice") or "").strip().lower()
            if not skill or choice not in {"strong", "working", "basic", "do_not_have", "dont_have"}:
                continue
            aliases = item.get("aliases") or []
            record_profile_fact_confirmation(
                fact=skill,
                requirement_type="capability",
                has_fact=choice in {"strong", "working", "basic"},
                source="suggested_tuning",
                action=choice,
                evidence=", ".join(str(alias).strip() for alias in aliases if str(alias).strip())
                if isinstance(aliases, list)
                else "",
            )
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
        raw_blockers = [str(item or "") for item in blockers]
        srv.SettingsHandler._validate_llm_suggestion_approvals(
            resolved_job_id,
            raw_blockers,
            approved_suggestion_tokens=approved_suggestion_tokens,
        )
        suggested_phrases_norm = set()
        cached_suggestions = srv._rejection_suggestions_cache.get(resolved_job_id)
        if isinstance(cached_suggestions, dict):
            for phrase in cached_suggestions.get("suggestions") or []:
                suggested_phrases_norm.add(srv._normalize_suggestion_phrase(str(phrase or "")))
        coverage = _profile_gap_requirement_coverage(resolved_job_id)
        resolved_blockers: list[str] = []
        rejected_custom_blockers: list[dict] = []
        for raw_blocker in raw_blockers:
            if srv._normalize_suggestion_phrase(raw_blocker) in suggested_phrases_norm:
                # Already approved via _validate_llm_suggestion_approvals above.
                resolved_blockers.append(raw_blocker)
                continue
            resolution = resolve_custom_blocker(raw_blocker, coverage)
            if resolution["ok"]:
                resolved_blockers.append(resolution["canonical_requirement"])
            else:
                rejected_custom_blockers.append(
                    {"input": resolution["raw_input"], "reason": resolution["reason_code"]}
                )
        if raw_blockers and not resolved_blockers:
            raise ValueError(
                "No blockers were saved: custom terms could not be matched to a required "
                "requirement for this job."
            )
        result = save_requirement_blockers_feedback(
            resolved_job_id,
            url=str(body.get("url") or "").strip(),
            title=str(body.get("job_title") or body.get("title") or "").strip(),
            company=str(body.get("company") or "").strip(),
            teaser=str(body.get("teaser") or "").strip(),
            blockers=resolved_blockers,
            title_block_phrases=[str(item or "") for item in title_block_phrases],
            description_block_phrases=[str(item or "") for item in description_block_phrases],
        )
        if rejected_custom_blockers:
            result["rejected_custom_blockers"] = rejected_custom_blockers
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(result)


@router.get("/api/rejection-feedback/custom-blocker-preview")
def api_rejection_feedback_custom_blocker_preview(
    job_id: str = Query(""), term: str = Query("")
):  # type: ignore[no-untyped-def]
    job_id = job_id.strip()
    term = term.strip()
    if not job_id:
        return json_response({"error": "job_id is required"}, 400)
    coverage = _profile_gap_requirement_coverage(job_id)
    resolution = resolve_custom_blocker(term, coverage)
    preview_html = render_custom_blocker_preview(resolution, debug_mode=srv.DEBUG_MODE)
    return json_response(
        {
            "ok": resolution["ok"],
            "reason_code": resolution["reason_code"],
            "canonical_requirement": resolution["canonical_requirement"],
            "requirement_type": resolution["requirement_type"],
            "importance": resolution["importance"],
            "preview_html": preview_html,
        }
    )


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
        elif action in {"unapply", "unhide", "unreject", "un_no_response"}:
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
# Owned by profile_gaps.CONFIRMABLE_REQUIREMENT_STATUSES. A partially_supported row is
# confirmable too: api_profile_gap re-checks classify_requirement_status below and
# returns already_present when the canonical fact is present, so an already-covered
# partial cannot double-add.
_PROFILE_GAP_CONFIRMABLE_STATUSES = CONFIRMABLE_REQUIREMENT_STATUSES


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
        or ""
    ).strip()


def _profile_gap_confirmable_item(job_key: str, value: str) -> dict:
    target_name = _profile_gap_name_key(value)
    if not target_name:
        return {}
    for item in _profile_gap_requirement_coverage(job_key):
        row_status = str(item.get("status") or "").strip().lower()
        raw_requirement_type = str(item.get("requirement_type") or "").strip().lower()
        if raw_requirement_type and raw_requirement_type not in LLM_ALLOWED_COVERAGE_REQUIREMENT_TYPES:
            continue
        decomposition = item.get("decomposition")
        decomposition_operator = (
            str(decomposition.get("operator") or "").strip().lower()
            if isinstance(decomposition, dict)
            else ""
        )
        is_or_row = decomposition_operator == "or"
        is_compound_capability_row = decomposition_operator in {"and", "or"}
        if row_status not in _PROFILE_GAP_CONFIRMABLE_STATUSES and not (
            is_or_row and row_status in {"supported", "partially_supported"}
        ):
            continue
        canonical_requirement = str(item.get("canonical_requirement") or "").strip()
        if item.get("profile_action_allowed") is True and canonical_requirement:
            capability_kind = str(item.get("requirement_kind") or "").strip().lower()
            if (
                raw_requirement_type != "capability"
                or capability_kind == LLM_REQUIREMENT_KIND_PROFESSIONAL
            ) and _profile_gap_name_key(canonical_requirement) == target_name:
                return dict(item)

        # JH-300/JH-285: OR alternatives and AND children keep their original
        # grouped job-fit meaning, while one named professional capability atom can
        # be confirmed independently. Build a synthetic single-atom view only for
        # the click-time storage resolver; persisted coverage remains unchanged.
        if (
            not is_compound_capability_row
            or raw_requirement_type != "capability"
            or str(item.get("requirement_kind") or "").strip().lower()
            != LLM_REQUIREMENT_KIND_PROFESSIONAL
        ):
            continue
        elements = decomposition.get("elements")
        if not isinstance(elements, list):
            continue
        for element in elements:
            if not isinstance(element, dict):
                continue
            if element.get("element_profile_action_allowed") is not True:
                continue
            if str(element.get("capability_judgement") or "").strip().lower() != "capability":
                continue
            if element.get("canonical_fact_resolved") is not True:
                continue
            element_status = str(element.get("status") or "").strip().lower()
            if element_status not in _PROFILE_GAP_CONFIRMABLE_STATUSES:
                continue
            element_concept = str(element.get("canonical_concept") or "").strip()
            if not element_concept or _profile_gap_name_key(element_concept) != target_name:
                continue
            branch = dict(item)
            branch["requirement"] = str(element.get("text") or element_concept).strip()
            branch["status"] = element_status
            branch["canonical_requirement"] = element_concept
            branch["capability_name"] = element_concept
            branch["matched_candidate_fact"] = str(
                element.get("matched_candidate_fact") or ""
            ).strip()
            branch["profile_action_allowed"] = True
            branch["decomposition"] = {
                "operator": "single",
                "elements": [dict(element)],
            }
            return branch
    return {}


def _profile_gap_named_item_index(items: list[dict]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = _profile_gap_name_key(item.get("name"))
        if name:
            lookup[name] = idx
    return lookup


def _set_boolean_profile_fact(
    profile: dict,
    *,
    requirement_type: str,
    canonical_name: str,
    value: bool,
    evidence: str = "",
) -> bool:
    """Set one existing/new qualification or eligibility fact in its authoritative bucket."""
    evidence_items = [evidence] if evidence else []
    if requirement_type == "qualification":
        key = KEY_CANDIDATE_QUALIFICATIONS
        items = list(profile.get(key) or [])
        lookup = _profile_gap_named_item_index(items)
        normalized = _profile_gap_name_key(canonical_name)
        if normalized in lookup:
            existing = dict(items[lookup[normalized]])
            changed = existing.get("value") is not value
            existing["value"] = value
            existing["needs_review"] = False
            if evidence_items and evidence not in (existing.get("evidence") or []):
                existing["evidence"] = [*(existing.get("evidence") or []), evidence]
                changed = True
            items[lookup[normalized]] = existing
        else:
            items.append(
                {
                    "name": canonical_name,
                    "value": value,
                    "aliases": [],
                    "evidence": evidence_items,
                    "needs_review": False,
                }
            )
            changed = True
        profile[key] = items
        return changed

    if requirement_type != "eligibility":
        raise ValueError("boolean profile facts are limited to eligibility and qualification")
    key = (
        KEY_CANDIDATE_ELIGIBILITY
        if _matches_managed_clearance(canonical_name)
        else KEY_CANDIDATE_ELIGIBILITY_FACTS
    )
    if key == KEY_CANDIDATE_ELIGIBILITY_FACTS:
        before = list(profile.get(key) or [])
        items, _ = prepare_eligibility_fact(
            before,
            name=canonical_name,
            value=value,
            evidence=evidence_items,
        )
        profile[key] = items
        return items != before

    items = list(profile.get(key) or [])
    lookup = _profile_gap_named_item_index(items)
    normalized = _profile_gap_name_key(canonical_name)
    if normalized in lookup:
        existing = dict(items[lookup[normalized]])
        changed = existing.get("value") is not value
        existing["value"] = value
        existing["needs_review"] = False
        if evidence_items and evidence not in (existing.get("evidence") or []):
            existing["evidence"] = [*(existing.get("evidence") or []), evidence]
            changed = True
        items[lookup[normalized]] = existing
    else:
        items.append(
            {
                "name": canonical_name,
                "value": value,
                "evidence": evidence_items,
                "needs_review": False,
            }
        )
        changed = True
    profile[key] = items
    return changed


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


def _resolve_and_confirm_requirement(
    canonical_item: dict, profile: dict, *, capability_level: str = ""
) -> dict:
    """Persist exactly one user-confirmed canonical fact in the resolved destination."""
    requirement_type = str(canonical_item.get("requirement_type") or "capability").strip().lower()
    confirmed_fact = normalize_profile_item_name(canonical_item.get("canonical_requirement"))
    if not confirmed_fact:
        raise ValueError("This requirement does not have one resolved profile fact to confirm.")
    # candidate_capabilities never stores a duration: the years/months a job asks
    # for are compared against captured role_experience (refreshed from the CV /
    # onboarding), not frozen into the profile as a derived capability. Reject a
    # canonical fact that carries a duration token and send it back for review
    # rather than persisting "5 Years Business Analysis".
    if (
        requirement_type == "capability"
        and extract_required_experience_months(confirmed_fact) is not None
    ):
        raise ValueError(
            "This looks like a years-of-experience requirement. Confirm the "
            "underlying skill or domain instead — the duration is checked "
            "against your role history and is not saved to your profile."
        )
    try:
        resolved = llm_gate.llm_resolve_profile_storage(canonical_item, profile)
    except llm_gate.LLMCallError as exc:
        raise ValueError(f"Could not confirm this requirement: {exc}") from exc

    resolution = resolved["resolution"]
    profile_target = resolved["profile_target"]

    if resolution == LLM_PROFILE_RESOLUTION_NEW and requirement_type == "capability":
        # The candidate confirmed canonical fact is the sole authoritative value
        # for a new capability. The storage LLM may choose the destination, but
        # it cannot rename or expand the fact into a different capability.
        normalized_target = normalize_profile_item_name(profile_target)
        if not normalized_target or normalized_target.casefold() != confirmed_fact.casefold():
            raise ValueError(
                "A new capability must be saved as the confirmed canonical fact."
            )
        profile_target = confirmed_fact

    if resolution == LLM_PROFILE_RESOLUTION_EXISTING:
        if requirement_type != "capability":
            changed = _set_boolean_profile_fact(
                profile,
                requirement_type=requirement_type,
                canonical_name=profile_target,
                value=True,
                evidence=str(canonical_item.get("matched_job_text") or "").strip(),
            )
            if changed:
                srv.save_profile(profile)
            return {
                "ok": True,
                "resolution": resolution,
                "profile_target": profile_target,
                "confirmed_fact": confirmed_fact,
                "change_kind": "negative_reversed" if changed else "already_present",
            }

        capabilities = list(profile.get(KEY_CANDIDATE_CAPABILITIES) or [])
        target_key = normalize_profile_item_name(profile_target).casefold()
        fact_key = confirmed_fact.casefold()
        for idx, item in enumerate(capabilities):
            if not isinstance(item, dict):
                continue
            if normalize_profile_item_name(item.get("name")).casefold() != target_key:
                continue
            existing_aliases = list(item.get("aliases") or [])
            existing_keys = {normalize_profile_item_name(alias).casefold() for alias in existing_aliases}
            if fact_key == target_key or fact_key in existing_keys:
                return {
                    "ok": True,
                    "resolution": resolution,
                    "profile_target": profile_target,
                    "confirmed_fact": confirmed_fact,
                    "change_kind": "already_present",
                }
            merged = dict(item)
            merged["aliases"] = [*existing_aliases, confirmed_fact]
            capabilities[idx] = merged
            profile[KEY_CANDIDATE_CAPABILITIES] = capabilities
            srv.save_profile(
                profile,
                prevalidated_capability_names={profile_target},
            )
            return {
                "ok": True,
                "resolution": resolution,
                "profile_target": profile_target,
                "confirmed_fact": confirmed_fact,
                "change_kind": "related_skill_added",
            }
        raise ValueError("Resolved profile target is no longer present in the candidate profile.")

    if resolution == LLM_PROFILE_RESOLUTION_NEW:
        if requirement_type in {"qualification", "eligibility"}:
            _set_boolean_profile_fact(
                profile,
                requirement_type=requirement_type,
                canonical_name=profile_target,
                value=True,
                evidence=str(canonical_item.get("matched_job_text") or "").strip(),
            )
        else:
            selected_level = str(capability_level or "").strip().lower()
            if not selected_level:
                return {
                    "ok": True,
                    "resolution": resolution,
                    "profile_target": profile_target,
                    "confirmed_fact": confirmed_fact,
                    "change_kind": "capability_level_required",
                    "requires_capability_level": True,
                    "allowed_capability_levels": sorted(VALID_CAPABILITY_RULE_LEVELS),
                }
            if selected_level not in VALID_CAPABILITY_RULE_LEVELS:
                raise ValueError("capability_level must be strong, working, or basic")
            capabilities = list(profile.get(KEY_CANDIDATE_CAPABILITIES) or [])
            capabilities.append(
                {
                    "name": profile_target,
                    "level": selected_level,
                    "fit": "supporting",
                    "aliases": [],
                    "icon_key": CAPABILITY_ICON_GENERIC,
                }
            )
            profile[KEY_CANDIDATE_CAPABILITIES] = capabilities
        if requirement_type == "capability":
            srv.save_profile(
                profile,
                prevalidated_capability_names={profile_target},
            )
        else:
            srv.save_profile(profile)
        return {
            "ok": True,
            "resolution": resolution,
            "profile_target": profile_target,
            "confirmed_fact": confirmed_fact,
            "change_kind": "new_item_added",
        }

    raise ValueError("This requirement is not specific enough to safely add to your profile.")


@router.post("/api/profile-gap")
def api_profile_gap(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    """Record a profile-learning response from an actionable requirement row.

    confirm_have        → add the canonical profile item to the matching profile bucket
    confirm_do_not_have → add the canonical negative profile signal to the matching bucket
    """
    try:
        action = str(body.get("action", "")).strip()
        capability_name = str(body.get("capability_name", "")).strip()
        job_key = str(body.get("job_key", "")).strip()
        capability_level = str(body.get("capability_level", "")).strip().lower()
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
        canonical_item_name = str(canonical_item["canonical_requirement"]).strip()
        requirement_type = str(canonical_item.get("requirement_type") or "capability").strip().lower()

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
                return json_response(
                    {
                        "ok": True,
                        "confirmed_fact": canonical_item_name,
                        "change_kind": "already_present",
                    }
                )
            reversing_exact_negative = False
            if requirement_type == "capability" and current_status == STATUS_CONFIRMED_DO_NOT_HAVE:
                canonical_key = _profile_gap_name_key(canonical_item_name)
                negative_skills = list(profile.get("must_not_require_skills") or [])
                if not any(_profile_gap_name_key(skill) == canonical_key for skill in negative_skills):
                    raise ValueError(
                        "This fact conflicts with a broader saved requirement exclusion. "
                        "Review that exclusion in Settings before confirming this fact."
                    )
                profile["must_not_require_skills"] = [
                    skill for skill in negative_skills if _profile_gap_name_key(skill) != canonical_key
                ]
                reversing_exact_negative = True
            result = _resolve_and_confirm_requirement(
                canonical_item, profile, capability_level=capability_level
            )
            if (
                reversing_exact_negative
                and not result.get("requires_capability_level")
                and result.get("change_kind") == "already_present"
            ):
                srv.save_profile(profile)
                result["change_kind"] = "negative_reversed"
            if not result.get("requires_capability_level") and result.get("change_kind") != "already_present":
                record_profile_fact_confirmation(
                    fact=canonical_item_name,
                    requirement_type=requirement_type,
                    has_fact=True,
                    source="workspace_requirement",
                    action=action,
                    job_key=job_key,
                    evidence=str(canonical_item.get("matched_job_text") or "").strip(),
                )
            return json_response(result)

        elif action == "confirm_do_not_have":
            if current_status == STATUS_CONFIRMED_DO_NOT_HAVE:
                return json_response(
                    {
                        "ok": True,
                        "confirmed_fact": canonical_item_name,
                        "change_kind": "negative_already_present",
                    }
                )
            if requirement_type in {"qualification", "eligibility"}:
                _set_boolean_profile_fact(
                    profile,
                    requirement_type=requirement_type,
                    canonical_name=canonical_item_name,
                    value=False,
                    evidence=str(canonical_item.get("matched_job_text") or "").strip(),
                )
                srv.save_profile(profile)
            else:
                if current_status == STATUS_CONFIRMED_HAVE:
                    raise ValueError("capability_name is already saved as a candidate capability")
                skills = list(profile.get("must_not_require_skills") or [])
                if canonical_item_name not in skills:
                    skills.append(canonical_item_name)
                    profile["must_not_require_skills"] = skills
                    srv.save_profile(profile)
            record_profile_fact_confirmation(
                fact=canonical_item_name,
                requirement_type=requirement_type,
                has_fact=False,
                source="workspace_requirement",
                action=action,
                job_key=job_key,
                evidence=str(canonical_item.get("matched_job_text") or "").strip(),
            )
            return json_response(
                {
                    "ok": True,
                    "confirmed_fact": canonical_item_name,
                    "change_kind": "negative_saved",
                }
            )

    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"ok": True})
