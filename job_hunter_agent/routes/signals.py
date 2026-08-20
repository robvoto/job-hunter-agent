"""Route handlers for signals."""

from fastapi import APIRouter, Body

from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.signal_schema import (
    CATEGORY_CAPABILITY_CONCEPT,
    CATEGORY_CV_FARMING_PATTERN,
    CATEGORY_HARD_BLOCKER_PATTERN,
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE,
    CATEGORY_PROFILE_SECTION_LABEL,
    CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW,
)

router = APIRouter()

_SIGNAL_CATEGORY_LABEL_FIELDS = {
    CATEGORY_CAPABILITY_CONCEPT: (
        "category_capability_label",
        "category_capability_description",
        "category_capability_examples",
        "category_capability_warning",
    ),
    CATEGORY_CV_FARMING_PATTERN: (
        "category_cv_farming_label",
        "category_cv_farming_description",
        "category_cv_farming_examples",
        "category_cv_farming_warning",
    ),
    CATEGORY_HARD_BLOCKER_PATTERN: (
        "category_hard_blocker_label",
        "category_hard_blocker_description",
        "category_hard_blocker_examples",
        "category_hard_blocker_warning",
    ),
    CATEGORY_JOB_TYPE_NORMALIZATION_CANDIDATE: (
        "category_job_type_label",
        "category_job_type_description",
        "category_job_type_examples",
        "category_job_type_warning",
    ),
    CATEGORY_PROFILE_SECTION_LABEL: (
        "category_profile_section_label",
        "category_profile_section_description",
        "category_profile_section_examples",
        "category_profile_section_warning",
    ),
    CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW: (
        "category_requirement_review_label",
        "category_requirement_review_description",
        "category_requirement_review_examples",
        "category_requirement_review_warning",
    ),
}

_REQUIREMENT_TYPE_LABEL_FIELDS = (
    ("capability", "type_capability_label"),
    ("eligibility", "type_eligibility_label"),
    ("qualification", "type_qualification_label"),
)


@router.get("/api/signal-registry")
def api_signal_registry():  # type: ignore[no-untyped-def]

    from job_hunter_agent.requirement_classification import load_eligibility_subtypes
    from job_hunter_agent.server_helpers import (
        load_requirement_taxonomy_labels,
        load_signal_registry_labels,
    )
    from job_hunter_agent.signal_registry import (
        VALID_SIGNAL_CATEGORIES,
        load_registry,
    )
    from job_hunter_agent.signal_schema import PATTERN_SIGNAL_CATEGORIES

    registry = load_registry()

    signals = sorted(registry.values(), key=lambda r: str(r.get("signal", "")).lower())
    labels = load_signal_registry_labels()
    taxonomy_labels = load_requirement_taxonomy_labels()
    eligibility_subtypes = load_eligibility_subtypes()
    subtype_labels = taxonomy_labels["eligibility_subtype_labels"]
    missing_subtype_labels = [
        subtype for subtype in eligibility_subtypes if subtype not in subtype_labels
    ]
    if missing_subtype_labels:
        raise ValueError(
            "ui_labels.json is missing requirement taxonomy subtype labels: "
            + ", ".join(missing_subtype_labels)
        )

    def category_payload(category: str) -> dict:
        label_key, description_key, examples_key, warning_key = _SIGNAL_CATEGORY_LABEL_FIELDS[category]
        # The route combines canonical category/type values with managed display metadata; it does not own UI wording.
        payload = {
            "key": category,
            "label": labels[label_key],
            "description": labels[description_key],
            "examples": labels[examples_key],
            "warning": labels[warning_key],
        }
        if category == CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW:
            payload["requirement_type_label"] = taxonomy_labels["type_field_label"]
            payload["requirement_type_options"] = [
                {"value": value, "label": taxonomy_labels[label_key]}
                for value, label_key in _REQUIREMENT_TYPE_LABEL_FIELDS
            ]
            payload["requirement_subtype_parent_type"] = "eligibility"
            payload["requirement_subtype_label"] = taxonomy_labels["eligibility_subtype_field_label"]
            payload["requirement_subtype_options"] = [
                {"value": subtype, "label": subtype_labels[subtype]}
                for subtype in eligibility_subtypes
            ]
        return payload

    return json_response(
        {
            "signals": signals,
            "total": len(signals),
            "pattern_categories": sorted(PATTERN_SIGNAL_CATEGORIES),
            "categories": [category_payload(category) for category in sorted(VALID_SIGNAL_CATEGORIES)],
            "field_labels": {
                "signal": labels["signal_field_label"],
                "requirement": labels["requirement_field_label"],
                "category": labels["category_field_label"],
                "category_help": labels["category_help_aria_label"],
                "requirement_type_help": labels["requirement_type_help_aria_label"],
            },
        },
    )


@router.patch("/api/signal-registry")
def api_signal_registry_patch(body: dict = Body(...)):  # type: ignore[no-untyped-def]

    try:
        from job_hunter_agent.signal_registry import (
            approve_signal,
            ignore_signal,
            set_signal_category,
        )

        key = str(body.get("key") or "").strip()

        category = str(body.get("category") or "").strip()

        value = str(body.get("value") or "").strip()

        classification = str(body.get("classification") or "").strip()

        subtype = str(body.get("subtype") or "").strip()

        if not key:
            return json_response({"error": "key is required"}, 400)

        action = str(body.get("action") or "category").strip().lower()

        if action == "approve":
            updated = approve_signal(
                key,
                category=category,
                value=value,
                classification=classification,
                subtype=subtype,
            )

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
