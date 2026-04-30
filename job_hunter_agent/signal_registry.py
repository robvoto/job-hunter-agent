"""Signal Registry - governs extracted CV/profile signals.

Each extracted signal gets a record with decision, scope, source, needs_review,
notes, history, normalized_key, and original_texts. New signals default to
decision='review' until the user decides. Existing signals keep their current
decision unchanged.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REGISTRY_PATH = Path(__file__).parent.parent / "data" / "signal_registry.json"


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


_VALID_DECISIONS = {"use", "ignore", "evidence_only", "review"}
_VALID_SCOPES = {"global", "role_specific", "domain_specific"}


def update_signal(
    key: str,
    decision: str,
    scope: str = "global",
    notes: str = "",
    source: str = "user",
) -> dict[str, Any] | None:
    """Update decision, scope, and notes for a registered signal.

    Returns the updated record, or None if the key is not found.
    Raises ValueError for invalid decision or scope values.
    Appends a history entry on every update.
    """
    key = str(key or "").strip().lower()
    decision = str(decision or "").strip()
    scope = str(scope or "global").strip()
    notes = str(notes or "").strip()
    if not key:
        return None
    if decision not in _VALID_DECISIONS:
        raise ValueError(f"Invalid decision '{decision}'. Must be one of: {sorted(_VALID_DECISIONS)}")
    if scope not in _VALID_SCOPES:
        raise ValueError(f"Invalid scope '{scope}'. Must be one of: {sorted(_VALID_SCOPES)}")
    registry = load_registry()
    record = registry.get(key)
    if record is None:
        return None
    record["decision"] = decision
    record["scope"] = scope
    record["notes"] = notes
    record["needs_review"] = decision == "review"
    record.setdefault("history", []).append({
        "decision": decision,
        "source": source,
        "timestamp": _now_iso(),
        "notes": notes,
    })
    save_registry(registry)
    return record


def get_decision(signal_name: str) -> str:
    """Return the registry decision for a signal, defaulting to 'review'."""
    key = str(signal_name or "").strip().lower()
    if not key:
        return "review"
    record = load_registry().get(key)
    return str(record.get("decision", "review")) if record else "review"
