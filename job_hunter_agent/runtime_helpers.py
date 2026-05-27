"""Shared runtime helpers for CLI flags and runtime logs.

This module provides common utilities for the job hunter agent's 
execution environment. It includes logic for detecting command-line 
arguments and maintains persistent runtime logs for LLM costs and
investigation events.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLI_FLAG_NO_LLM = "--no-llm"
CLI_FLAG_DEBUG = "--debug"
CLI_FLAG_REBUILD_WORKSPACE = "--rebuild-workspace"
CLI_FLAG_RESET_NEW_TO_YOU = "--reset-new-to-you"


def has_cli_flag(argv: list[str], flag: str) -> bool:
    return flag in argv


def build_uncertainty_entry(
    *,
    reason_code: str,
    stage: str,
    field: str,
    raw_value: str,
    detail: str,
    source: str = "",
    job_key: str = "",
    normalized_value: str = "",
    severity: str = "warning",
) -> dict[str, Any]:
    return {
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason_code": reason_code,
        "stage": stage,
        "field": field,
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "detail": detail,
        "source": source,
        "job_key": job_key,
        "severity": severity,
    }


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


def _format_llm_cost_log(prefix: str, entry: dict[str, Any]) -> str:
    lines = [
        f"{prefix}",
        f"  purpose: {entry['purpose']}",
        f"  model: {entry['model']}",
        f"  input tokens: {entry['tok_in']}",
        f"  output tokens: {entry['tok_out']}",
        f"  cost: ${entry['cost_usd']:.6f}",
        f"  session: ${entry['session_usd']:.6f}",
    ]
    return "\n".join(lines)


def append_llm_cost_log(path: Path, entry: dict[str, Any], *, prefix: str = "[LLM]") -> None:
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        print(f"[RUNTIME_HELPERS][WARN] Failed to write LLM cost log to {path}: {exc}")
        pass
    print(_format_llm_cost_log(prefix, entry))


def append_uncertainty_log(path: Path, entry: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        print(f"[RUNTIME_HELPERS][WARN] Failed to write uncertainty log to {path}: {exc}")
