"""Shared runtime helpers for CLI flags and LLM cost logging."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLI_FLAG_CHEAP_LLM = "--cheap-llm"
CLI_FLAG_NO_LLM = "--no-llm"
CLI_FLAG_DEBUG_MODE = "--debug-mode"
CLI_FLAG_REBUILD_DASHBOARD = "--rebuild-dashboard"


def has_cli_flag(argv: list[str], flag: str) -> bool:
    return flag in argv


def build_llm_cost_entry(
    *,
    purpose: str,
    model: str,
    tok_in: int,
    tok_out: int,
    cost_usd: float,
    session_usd: float,
) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "purpose": purpose,
        "model": model,
        "tok_in": tok_in,
        "tok_out": tok_out,
        "cost_usd": round(cost_usd, 6),
        "session_usd": round(session_usd, 6),
    }


def append_llm_cost_log(path: Path, entry: dict[str, Any], *, prefix: str = "[LLM]") -> None:
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    print(
        f"{prefix} {entry['purpose']} | {entry['model']} | "
        f"in={entry['tok_in']} out={entry['tok_out']} | "
        f"${entry['cost_usd']:.6f} | session=${entry['session_usd']:.6f}"
    )
