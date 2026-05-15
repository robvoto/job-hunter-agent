from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_managed_knowledge_payload(path: Path, *, entries_key: str) -> dict[str, Any]:
    if not path.exists():
        return {entries_key: []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise OSError(f"Failed to read {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} contains invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def save_managed_knowledge_payload(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
