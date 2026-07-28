"""Route handlers for profile materials."""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.auth import auth_required_response, is_admin
from job_hunter_agent.config import GLOBAL_SETTINGS_PATH
from job_hunter_agent.global_settings import save_global_settings
from job_hunter_agent.knowledge_sync_roundtrip import sync_knowledge_roundtrip
from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.scraper_health import run_scraper_configuration_validation
from job_hunter_agent.source_documents import refresh_role_history_from_saved_cv
from job_hunter_agent.system_warnings import (
    list_system_warnings,
    update_system_warning_status,
)

router = APIRouter()


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

        updated = srv.patch_profile(patch)

        if srv.SettingsHandler._matching_rules_changed(current, updated):
            srv.rebuild_workspace_after_rule_change("profile matching rules saved")

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

    return json_response(srv.load_source_materials(create_if_missing=True))


@router.put("/api/source-materials")
def api_source_materials_put(body: dict = Body(...)):  # type: ignore[no-untyped-def]

    try:
        updated = srv.save_source_materials(body)

    except Exception as exc:
        return json_response({"error": str(exc)}, 400)

    return json_response(updated)


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
        warnings = list_system_warnings()
        return json_response({"warnings": warnings})
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
