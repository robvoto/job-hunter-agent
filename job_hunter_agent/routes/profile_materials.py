"""Route handlers for profile materials."""

from __future__ import annotations

import copy

from fastapi import APIRouter, Body, Request

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.eligibility_profile import prepare_eligibility_fact
from job_hunter_agent.qualification_profile import normalize_qualifications
from job_hunter_agent.auth import auth_required_response, is_admin
from job_hunter_agent.config import GLOBAL_SETTINGS_PATH
from job_hunter_agent.global_settings import save_global_settings
from job_hunter_agent.knowledge_sync_roundtrip import sync_knowledge_roundtrip
from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.scraper_health import run_scraper_configuration_validation
from job_hunter_agent.source_documents import (
    load_source_materials,
    refresh_role_history_from_saved_cv,
    save_source_materials,
)
from job_hunter_agent.profile_store import KEY_CANDIDATE_ELIGIBILITY_FACTS, KEY_CANDIDATE_QUALIFICATIONS
from job_hunter_agent.system_warnings import (
    is_actionable_system_warning,
    list_system_warnings,
    update_system_warning_status,
)

router = APIRouter()


def _save_generic_eligibility_fact(
    profile: dict,
    body: dict,
) -> dict:
    """Apply one fact through the shared service used by settings and results."""

    name = str(body.get("name") or "").strip().casefold()
    managed_clearance_terms = {
        str(term or "").strip().casefold()
        for option in srv.load_clearance_ui_options()
        for term in [option.get("value"), option.get("label"), *(option.get("aliases") or [])]
    }
    if name in managed_clearance_terms:
        raise ValueError("Managed clearances must be recorded in the Clearances section")

    facts, fact = prepare_eligibility_fact(
        profile.get(KEY_CANDIDATE_ELIGIBILITY_FACTS, []),
        name=str(body.get("name") or ""),
        value=body.get("value", True),
        evidence=body.get("evidence"),
    )
    profile[KEY_CANDIDATE_ELIGIBILITY_FACTS] = facts
    return fact


@router.get("/api/profile")
def api_profile_get():  # type: ignore[no-untyped-def]

    return json_response(srv.load_profile())


@router.get("/api/profile/status")
def api_profile_status_get():  # type: ignore[no-untyped-def]

    try:
        return json_response(srv.profile_review_status())

    except Exception as exc:
        return json_response({"error": str(exc)}, 400)


@router.patch("/api/profile")
def api_profile_patch(body: dict = Body(...)):  # type: ignore[no-untyped-def]

    try:
        current = srv.load_profile()

        patch = srv.SettingsHandler._normalize_profile_patch_for_save(current, body)
        if KEY_CANDIDATE_ELIGIBILITY_FACTS in body:
            generic_facts = body.get(KEY_CANDIDATE_ELIGIBILITY_FACTS)
            if not isinstance(generic_facts, list):
                raise ValueError(f"{KEY_CANDIDATE_ELIGIBILITY_FACTS} must be a list")
            prepared_profile = dict(current)
            prepared_profile[KEY_CANDIDATE_ELIGIBILITY_FACTS] = []
            for item in generic_facts:
                if not isinstance(item, dict):
                    continue
                _save_generic_eligibility_fact(prepared_profile, dict(item))
            patch[KEY_CANDIDATE_ELIGIBILITY_FACTS] = prepared_profile[
                KEY_CANDIDATE_ELIGIBILITY_FACTS
            ]
        if KEY_CANDIDATE_QUALIFICATIONS in body:
            qualifications = body.get(KEY_CANDIDATE_QUALIFICATIONS)
            if not isinstance(qualifications, list):
                raise ValueError(f"{KEY_CANDIDATE_QUALIFICATIONS} must be a list")
            patch[KEY_CANDIDATE_QUALIFICATIONS] = normalize_qualifications(qualifications)

        updated = srv.patch_profile(patch)

        changed_rule_keys = srv.SettingsHandler._changed_matching_rule_keys(current, updated)
        if changed_rule_keys:
            srv.rebuild_workspace_after_rule_change(
                f"profile matching rules saved: {', '.join(sorted(changed_rule_keys))}"
            )

    except Exception as exc:
        return json_response({"error": str(exc)}, 400)

    return json_response(updated)


@router.put("/api/profile")
def api_profile_put(body: dict = Body(...)):  # type: ignore[no-untyped-def]

    try:
        updated = srv.save_profile(body)

    except Exception as exc:
        return json_response({"error": str(exc)}, 400)

    return json_response(updated)


@router.get("/api/source-materials")
def api_source_materials_get():  # type: ignore[no-untyped-def]

    return json_response(load_source_materials(create_if_missing=True))


@router.put("/api/source-materials")
def api_source_materials_put(body: dict = Body(...)):  # type: ignore[no-untyped-def]

    try:
        updated = save_source_materials(body)

    except Exception as exc:
        return json_response({"error": str(exc)}, 400)

    return json_response(updated)


@router.post("/api/profile/eligibility")
def api_profile_eligibility_save(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    """Add or edit one generic eligibility fact through the shared save path."""

    try:
        before = srv.load_profile()
        profile = copy.deepcopy(before)
        fact = _save_generic_eligibility_fact(profile, body)
        updated = srv.save_profile(profile)
        if srv.SettingsHandler._matching_rules_changed(before, updated):
            srv.rebuild_workspace_after_rule_change("generic eligibility fact saved")
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)

    saved_fact = next(
        item
        for item in updated.get(KEY_CANDIDATE_ELIGIBILITY_FACTS, [])
        if item.get("name") == fact.get("name")
    )
    return json_response(
        {
            "ok": True,
            "eligibility_fact": saved_fact,
            "profile": updated,
        }
    )


@router.post("/api/profile/qualification")
def api_profile_qualification_save(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    """Add or edit one qualification through the shared profile save path."""

    try:
        before = srv.load_profile()
        profile = copy.deepcopy(before)
        existing = list(profile.get(KEY_CANDIDATE_QUALIFICATIONS) or [])
        name = str(body.get("name") or "").strip()
        if not name:
            raise ValueError("Qualification name is required")
        item = {
            "name": name,
            "value": body.get("value", True),
            "aliases": body.get("aliases") or [],
            "evidence": body.get("evidence") or [],
        }
        normalized = normalize_qualifications([*existing, item])
        saved = next((row for row in normalized if row.get("name", "").casefold() == name.casefold()), None)
        if saved is None:
            raise ValueError("Qualification name could not be saved after normalization")
        profile[KEY_CANDIDATE_QUALIFICATIONS] = normalized
        updated = srv.save_profile(profile)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"ok": True, "qualification": saved, "profile": updated})


@router.post("/api/profile/refresh-role-history-from-saved-cv")
def api_profile_refresh_role_history_from_saved_cv():  # type: ignore[no-untyped-def]
    try:
        return json_response(refresh_role_history_from_saved_cv())
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)


@router.get("/api/global-settings")
def api_global_settings_get(request: Request):  # type: ignore[no-untyped-def]

    if not is_admin(request):
        return auth_required_response(GLOBAL_SETTINGS_PATH, False)

    return json_response(srv.load_global_settings())


@router.patch("/api/global-settings")
def api_global_settings_patch(request: Request, body: dict = Body(...)):  # type: ignore[no-untyped-def]

    try:
        if not is_admin(request):
            return auth_required_response(GLOBAL_SETTINGS_PATH, False)

        updated = save_global_settings(body)

    except Exception as exc:
        return json_response({"error": str(exc)}, 400)

    return json_response(updated)


@router.post("/api/admin/knowledge-sync")
async def api_admin_knowledge_sync(
    request: Request,
):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response(GLOBAL_SETTINGS_PATH, False)
    try:
        sync_knowledge_roundtrip()
        return json_response({"ok": True, "message": "Synced knowledge with AWS."})
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)


@router.post("/api/admin/rejection-history-sync")
async def api_admin_rejection_history_sync(
    request: Request,
):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/api/admin/rejection-history-sync", False)
    try:
        from job_hunter_agent.candidate_application_history import (
            import_candidate_rejections_from_sheet,
        )

        summary = import_candidate_rejections_from_sheet()
        added = summary.get("records_added", 0)
        total = summary.get("records_total", 0)
        return json_response(
            {"ok": True, "message": f"Synced rejection history: {added} new, {total} total."}
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)


@router.post("/api/admin/clear-runtime-caches")
def api_admin_clear_runtime_caches(request: Request):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/api/admin/clear-runtime-caches", False)
    try:
        return json_response(srv.clear_runtime_caches())
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)


@router.post("/api/admin/clear-current-user-search-state")
def api_admin_clear_current_user_search_state(
    request: Request,
):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/api/admin/clear-current-user-search-state", False)
    try:
        return json_response(srv.clear_current_user_search_state())
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)


@router.post("/api/admin/scraper-config-validation")
def api_admin_scraper_config_validation(request: Request):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/api/admin/scraper-config-validation", False)
    try:
        return json_response(run_scraper_configuration_validation())
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)


@router.get("/api/admin/system-warnings")
def api_admin_system_warnings_get(request: Request):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/api/admin/system-warnings", False)
    try:
        unresolved_warnings = list_system_warnings()
        actionable_warnings = [
            warning for warning in unresolved_warnings if is_actionable_system_warning(warning)
        ]
        return json_response(
            {
                "warnings": actionable_warnings,
                "summary": {
                    "total_unresolved": len(unresolved_warnings),
                    "visible_actionable": len(actionable_warnings),
                    "hidden_diagnostics": len(unresolved_warnings) - len(actionable_warnings),
                },
            }
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)


@router.patch("/api/admin/system-warnings/{warning_id}")
def api_admin_system_warnings_patch(
    request: Request,
    warning_id: int,
    body: dict = Body(...),
):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/api/admin/system-warnings", False)
    try:
        status = str(body.get("status") or "").strip().lower()
        updated = update_system_warning_status(warning_id, status)
        return json_response({"ok": True, "warning": updated})
    except LookupError as exc:
        return json_response({"error": str(exc)}, 404)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
