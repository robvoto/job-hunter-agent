import hashlib
import json
import re

from fastapi import APIRouter, Body, Query

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.review_history_service import (
    append_review_key,
    record_job_view,
    remove_review_key,
    save_block_similar_feedback,
    save_not_for_me_feedback,
)

from job_hunter_agent.routes.responses import json_response

router = APIRouter()


@router.get("/api/rejection-suggestions")
def api_rejection_suggestions(job_id: str = Query("")):  # type: ignore[no-untyped-def]
    job_id = job_id.strip()
    if not job_id:
        return json_response({"error": "job_id is required"}, 400)
    description = srv.get_job_description(job_id)
    if not description:
        return json_response({})
    description_hash = hashlib.sha1(description.encode("utf-8")).hexdigest()
    cached = srv._rejection_suggestions_cache.get(job_id)
    if isinstance(cached, dict) and cached.get("description_hash") == description_hash:
        suggestions = cached.get("suggestions") or []
        if not isinstance(cached.get("approval_tokens"), dict):
            cached["approval_tokens"] = srv.SettingsHandler._issue_rejection_suggestion_approval_tokens(
                job_id,
                suggestions,
            )
        print(f"[LLM][REJECTION_SUGGESTIONS][CACHE_HIT] job_id={job_id} suggestions={suggestions}")
    else:
        suggestions = srv.llm_suggest_rejection_blockers(description)
        approval_tokens = srv.SettingsHandler._issue_rejection_suggestion_approval_tokens(job_id, suggestions)
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
            "message": "Capability tuning suggestions applied to profile.json.",
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
    return json_response({"ok": True, "message": f"Phrase rule added: {phrase}", "profile": updated})


@router.post("/api/rejection-feedback/mandatory-blockers")
def api_rejection_feedback_mandatory_blockers(body: dict = Body(...)):  # type: ignore[no-untyped-def]
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
        titles: list[str] = []
        if srv.AUDIT_RECORDS_PATH.exists():
            try:
                rows = json.loads(srv.AUDIT_RECORDS_PATH.read_text(encoding="utf-8"))
                if isinstance(rows, list):
                    titles = [str(r.get("title") or "").lower() for r in rows if r.get("title")]
            except Exception:
                pass
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
    try:
        action = str(body.get("action", "")).strip().lower()
        job_key = str(body.get("job_key") or body.get("url") or "").strip()
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
        return json_response({"error": str(exc)}, 400)
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
