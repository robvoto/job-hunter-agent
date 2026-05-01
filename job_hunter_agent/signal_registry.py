"""Signal Registry - governs extracted CV/profile signals.

Each extracted signal gets a record with decision, scope, source, needs_review,
notes, history, normalized_key, and original_texts. New signals default to
decision='review' until the user decides. Existing signals keep their current
decision unchanged.
"""

import json
from datetime import datetime, timezone
from typing import Any
from job_hunter_agent.paths import SIGNAL_REGISTRY_PATH as _REGISTRY_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry() -> dict[str, dict[str, Any]]:
    if not _REGISTRY_PATH.exists():
        return {}
    try:
        with open(_REGISTRY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_registry(registry: dict[str, dict[str, Any]]) -> None:
    _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def _make_record(signal: str, source: str) -> dict[str, Any]:
    key = signal.lower()
    now = _now_iso()
    return {
        "signal": signal,
        "normalized_key": key,
        "original_texts": [signal],
        "decision": "review",
        "scope": "global",
        "source": source,
        "needs_review": True,
        "notes": "",
        "history": [
            {
                "decision": "review",
                "source": source,
                "timestamp": now,
                "notes": "",
            }
        ],
    }


def register_signals(signal_names: list[str], source: str = "system") -> None:
    """Register signals extracted from CV/profile.

    New signals are added with decision='review'. Existing signals keep their
    current decision unchanged so user decisions are never overwritten.
    Original texts are accumulated; history is backfilled on older records.
    """
    if not signal_names:
        return
    registry = load_registry()
    changed = False
    for name in signal_names:
        name = str(name or "").strip()
        if not name:
            continue
        key = name.lower()
        if key not in registry:
            registry[key] = _make_record(name, source)
            changed = True
        else:
            record = registry[key]
            if "normalized_key" not in record:
                record["normalized_key"] = key
                changed = True
            original_texts: list[str] = record.setdefault("original_texts", [])
            if name not in original_texts:
                original_texts.append(name)
                changed = True
            if "history" not in record:
                record["history"] = [
                    {
                        "decision": record.get("decision", "review"),
                        "source": record.get("source", source),
                        "timestamp": _now_iso(),
                        "notes": record.get("notes", ""),
                    }
                ]
                changed = True
    if changed:
        save_registry(registry)

VALID_LEARNING_STATUSES = {"review", "approved", "ignored"}

VALID_SIGNAL_CATEGORIES = {
    "government_context",
    "capability_concept",
    "role_title_token",
    "generic_noise",
}

CATEGORY_TARGET_FILES = {
    "government_context": "government_context_knowledge.json",
    "capability_concept": "capability_knowledge.json",
    "role_title_token": "role_title_knowledge.json",
    "generic_noise": "",
} 
_VALID_SCOPES = {"global", "role_specific", "domain_specific"}


def update_signal(
    key: str,
    learning_status: str,
    suggested_category: str = "",
    scope: str = "",
    target_file: str = "",
    notes: str = "", 
) -> dict[str, Any] | None:
    """Update learning review metadata for a registered signal."""
    key = str(key or "").strip().lower()
    learning_status = str(learning_status or "").strip()
    suggested_category = str(suggested_category or "").strip()
    target_file = str(target_file or "").strip()
    notes = str(notes or "").strip()

    if not key:
        return None

    if learning_status not in VALID_LEARNING_STATUSES:
      raise ValueError(f"Invalid learning_status '{learning_status}'.")

    if suggested_category and suggested_category not in VALID_SIGNAL_CATEGORIES:
      raise ValueError(f"Invalid suggested_category '{suggested_category}'.")

    expected_target = CATEGORY_TARGET_FILES.get(suggested_category, "")
    if target_file != expected_target:
      raise ValueError(
        f"Invalid target_file '{target_file}' for category '{suggested_category}'."
    )

    registry = load_registry()
    record = registry.get(key)
    if record is None:
        return None

    record["learning_status"] = learning_status 
    record["suggested_category"] = suggested_category
    record["target_file"] = target_file
    record["notes"] = notes
    record["needs_review"] = learning_status == "review"

    record.setdefault("history", []).append({
        "learning_status": learning_status,
        "suggested_category": suggested_category,
        "target_file": target_file,
        "scope": scope, 
        "timestamp": _now_iso(),
        "notes": notes,
    })

    save_registry(registry)
    return record

def get_learning_status(signal_name: str) -> str:
    """Return the registry learning status for a signal, defaulting to 'review'."""
    key = str(signal_name or "").strip().lower()
    if not key:
        return "review"
    record = load_registry().get(key)
    return str(record.get("learning_status", "review")) if record else "review"
