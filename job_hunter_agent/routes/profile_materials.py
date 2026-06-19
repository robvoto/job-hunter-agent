"""Route handlers for profile materials."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Request
from fastapi.responses import Response

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.auth import auth_required_response, is_admin
from job_hunter_agent.config import GLOBAL_SETTINGS_PATH
from job_hunter_agent.global_settings import save_global_settings
from job_hunter_agent.knowledge_sync import sync_shared_knowledge
from job_hunter_agent.paths import get_db_path
from job_hunter_agent.routes.responses import json_response

router = APIRouter()


def _merged_knowledge_download_name(source_filename: str) -> str:
    name = Path(source_filename or "knowledge-sync.db").name
    if name.endswith(".db"):
        return f"{name[:-3]}.merged.db"
    return f"{name}.merged.db"


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

    upload_name = str(request.headers.get("x-source-filename") or "").strip() or "upload.db"
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
            temp_path = Path(tmp.name)
            payload = await request.body()
            if not payload:
                raise ValueError("uploaded_db body is required")
            tmp.write(payload)

        updated = sync_shared_knowledge(temp_path, get_db_path())
        merged_bytes = temp_path.read_bytes()
        download_name = _merged_knowledge_download_name(upload_name)
        return Response(
            content=merged_bytes,
            media_type="application/x-sqlite3",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Content-Disposition": f'attachment; filename="{download_name}"',
                "X-Sync-Updated-Keys": json.dumps(updated),
                "X-Sync-Source-Filename": upload_name,
                "X-Sync-Download-Filename": download_name,
            },
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
