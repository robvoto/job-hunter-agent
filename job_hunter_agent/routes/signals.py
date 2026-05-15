from fastapi import APIRouter, Body

from job_hunter_agent import server_helpers as srv

from job_hunter_agent.routes.responses import json_response

router = APIRouter()


@router.get("/api/signal-registry")
def api_signal_registry():  # type: ignore[no-untyped-def]
    from job_hunter_agent.signal_registry import CATEGORY_LABELS, CATEGORY_METADATA, VALID_SIGNAL_CATEGORIES, load_registry

    registry = load_registry()
    signals = sorted(registry.values(), key=lambda r: str(r.get("signal", "")).lower())
    return json_response(
        {
            "signals": signals,
            "total": len(signals),
            "categories": [
                {
                    "key": category,
                    "label": CATEGORY_LABELS.get(category, category.replace("_", " ").title()),
                    "description": CATEGORY_METADATA.get(category, {}).get("description", ""),
                    "examples": CATEGORY_METADATA.get(category, {}).get("examples", []),
                    "warning": CATEGORY_METADATA.get(category, {}).get("warning"),
                }
                for category in sorted(VALID_SIGNAL_CATEGORIES)
            ],
        },
    )


@router.patch("/api/signal-registry")
def api_signal_registry_patch(body: dict = Body(...)):  # type: ignore[no-untyped-def]
    try:
        from job_hunter_agent.signal_registry import approve_signal, ignore_signal, set_signal_category

        key = str(body.get("key") or "").strip()
        category = str(body.get("category") or "").strip()

        if not key:
            return json_response({"error": "key is required"}, 400)

        action = str(body.get("action") or "category").strip().lower()
        if action == "approve":
            updated = approve_signal(key, category=category)
            if updated is None:
                return json_response({"error": f"Signal '{key}' not found in registry"}, 404)
            return json_response({"ok": True, "signal": updated})

        if action == "ignore":
            updated = ignore_signal(key)
            if updated is None:
                return json_response({"error": f"Signal '{key}' not found in registry"}, 404)
            return json_response({"ok": True, "signal": updated})

        updated = set_signal_category(key, category)
        if updated is None:
            return json_response({"error": f"Signal '{key}' not found in registry"}, 404)
        return json_response({"ok": True, "signal": updated})

    except ValueError as exc:
        return json_response({"error": str(exc)}, 400)
    except Exception as exc:
        return json_response({"error": str(exc)}, 400)
