from fastapi import APIRouter, Body, Request

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.auth import auth_required_response, is_admin

from job_hunter_agent.routes.responses import json_response

router = APIRouter()


@router.get("/api/profile")
def api_profile_get():  # type: ignore[no-untyped-def]
    return json_response(srv.load_profile())


@router.patch("/api/profile")
def api_profile_patch(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        current = srv.load_profile()
        patch = srv.SettingsHandler._normalize_profile_patch_for_save(current, body)
        updated = srv.patch_profile(patch)
        if srv.SettingsHandler._patch_affects_matching_rules(patch):
            srv.rebuild_dashboard_after_rule_change("profile matching rules saved")
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


@router.get("/api/advance-settings")
def api_advance_settings_get(request: Request):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/admin", False)
    return json_response(srv.load_advance_settings())


@router.patch("/api/advance-settings")
def api_advance_settings_patch(request: Request, body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        if not is_admin(request):
            return auth_required_response("/admin", False)
        updated = srv.save_advance_settings(body)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response(updated)
