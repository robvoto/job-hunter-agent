"""Global Admin routes for the application-level user approval directory."""

from __future__ import annotations

from fastapi import APIRouter, Body, Request

from job_hunter_agent.auth import auth_required_response, is_admin
from job_hunter_agent.config import USER_ACCESS_VERIFIED
from job_hunter_agent.database import list_users_with_access, update_user_access_status
from job_hunter_agent.routes.responses import json_response

router = APIRouter()


def _admin_email(request: Request) -> str | None:
    config = getattr(request.app.state, "auth_config", None)
    return getattr(config, "admin_email", None)


@router.get("/api/admin/user-access")
def api_user_access_list(request: Request):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/global-settings", False)
    admin_email = str(_admin_email(request) or "").strip().lower()
    users = [
        user
        for user in list_users_with_access()
        if str(user.get("access_status") or "").strip().lower() != USER_ACCESS_VERIFIED
    ]
    for user in users:
        user["is_admin"] = bool(admin_email and str(user.get("email") or "").lower() == admin_email)
    return json_response({"users": users})


@router.patch("/api/admin/user-access/{user_id}")
def api_user_access_update(
    request: Request,
    user_id: str,
    body: dict = Body(...),
):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/global-settings", False)
    try:
        status = str(body.get("status") or "").strip().lower()
        updated = update_user_access_status(user_id, status, _admin_email(request))
    except LookupError as exc:
        return json_response({"error": str(exc)}, 404)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"user": updated})
