"""Route handlers for profile materials."""

from __future__ import annotations

import copy

from fastapi import APIRouter, Body, Request

from job_hunter_agent import server_helpers as srv
from job_hunter_agent.auth import auth_required_response, is_admin
from job_hunter_agent.config import GLOBAL_SETTINGS_PATH
from job_hunter_agent.eligibility_profile import (
    prepare_eligibility_fact,
    prepare_eligibility_facts_for_profile_save,
)
from job_hunter_agent.global_settings import save_global_settings
from job_hunter_agent.knowledge_sync_roundtrip import sync_knowledge_roundtrip
from job_hunter_agent.profile_learning import resolve_role_family
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_ELIGIBILITY_FACTS,
    KEY_CANDIDATE_QUALIFICATIONS,
)
from job_hunter_agent.qualification_profile import normalize_qualifications
from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.scraper_health import run_scraper_configuration_validation
from job_hunter_agent.source_documents import (
    load_source_materials,
    refresh_role_history_from_saved_cv,
    save_source_materials,
)
from job_hunter_agent.system_warnings import (
    aggregate_system_warning_diagnostics,
    classify_system_warning,
    is_actionable_system_warning,
    list_system_warnings,
    system_warning_operator_action,
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
            patch[KEY_CANDIDATE_ELIGIBILITY_FACTS] = prepare_eligibility_facts_for_profile_save(
                current.get(KEY_CANDIDATE_ELIGIBILITY_FACTS, []),
                generic_facts,
            )
        if KEY_CANDIDATE_QUALIFICATIONS in body:
            qualifications = body.get(KEY_CANDIDATE_QUALIFICATIONS)
            if not isinstance(qualifications, list):
                raise ValueError(f"{KEY_CANDIDATE_QUALIFICATIONS} must be a list")
            patch[KEY_CANDIDATE_QUALIFICATIONS] = normalize_qualifications(qualifications)

        updated = srv.patch_profile(patch)

        changed_rule_keys = srv.SettingsHandler._changed_matching_rule_keys(current, updated)
        # The workspace summary is cached HTML, so profile-backed locations need the same refresh.
        current_search_locations = (current.get("search_settings") or {}).get("locations", [])
        updated_search_locations = (updated.get("search_settings") or {}).get("locations", [])
        search_locations_changed = current_search_locations != updated_search_locations
        if changed_rule_keys or search_locations_changed:
            refresh_reasons = []
            if changed_rule_keys:
                refresh_reasons.append(
                    f"profile matching rules saved: {', '.join(sorted(changed_rule_keys))}"
                )
            if search_locations_changed:
                refresh_reasons.append("profile search locations saved")
            srv.rebuild_workspace_after_rule_change(
                "; ".join(refresh_reasons)
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


@router.post("/api/profile/resolve-role-family")
def api_profile_resolve_role_family(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    """Propose a neutral role family before a user saves role preference."""

    try:
        title = str(body.get("title") or "").strip()
        result = resolve_role_family(title)
        if not result.get("resolved") or not str(result.get("role_family") or "").strip():
            raise ValueError(
                "This role could not be resolved confidently. Please enter the role family you want to search."
            )
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
    return json_response({"ok": True, **result})


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
def api_admin_system_warnings_get(
    request: Request, include_diagnostics: bool = False
):  # type: ignore[no-untyped-def]
    if not is_admin(request):
        return auth_required_response("/api/admin/system-warnings", False)
    try:
        labels = srv.load_system_health_labels()
        unresolved_warnings = list_system_warnings()
        actionable_warnings = []
        diagnostics = []

        for warning in unresolved_warnings:
            enriched = dict(warning)
            classification = classify_system_warning(enriched)["kind"]
            enriched["classification"] = classification
            if classification == "diagnostic":
                diagnostics.append(enriched)
                continue

            operator_action = system_warning_operator_action(enriched)
            if operator_action is None:
                enriched["operator_action"] = None
                enriched["operator_guidance"] = labels[
                    "system_health_developer_investigation_help"
                ]
            else:
                enriched["operator_action"] = {
                    "type": operator_action["type"],
                    "label": labels[operator_action["label_key"]],
                }
                enriched["operator_guidance"] = labels[operator_action["guidance_key"]]
            actionable_warnings.append(enriched)

        diagnostic_groups = aggregate_system_warning_diagnostics(diagnostics)
        for group in diagnostic_groups:
            group["classification"] = "diagnostic"

        return json_response(
            {
                "warnings": actionable_warnings,
                "diagnostic_groups": diagnostic_groups if include_diagnostics else [],
                "labels": labels,
                "summary": {
                    "total_unresolved_records": len(unresolved_warnings),
                    "active_problem_records": len(actionable_warnings),
                    "active_problem_occurrences": sum(
                        int(warning["count"]) for warning in actionable_warnings
                    ),
                    "diagnostic_records": len(diagnostics),
                    "diagnostic_occurrences": sum(int(warning["count"]) for warning in diagnostics),
                    "diagnostic_groups": len(diagnostic_groups),
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
        action = str(body.get("action") or "").strip().lower()
        if action != "acknowledge":
            raise ValueError("Unsupported system warning action")

        warning = next(
            (item for item in list_system_warnings() if int(item["id"]) == int(warning_id)),
            None,
        )
        if warning is None:
            raise LookupError(f"System warning {warning_id} not found")
        if not is_actionable_system_warning(warning):
            raise ValueError("Technical diagnostics are read-only")

        updated = update_system_warning_status(warning_id, "reviewed")
        return json_response({"ok": True, "warning": updated})
    except LookupError as exc:
        return json_response({"error": str(exc)}, 404)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
