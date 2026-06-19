"""Shared runtime helpers for CLI flags and runtime logs.

This module provides common utilities for the job hunter agent's
execution environment. It includes logic for detecting command-line
arguments and maintains persistent runtime logs for LLM costs and
investigation events.
"""

import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

CLI_FLAG_NO_LLM = "--no-llm"
CLI_FLAG_DEBUG = "--debug"
CLI_FLAG_REBUILD_WORKSPACE = "--rebuild-workspace"
CLI_FLAG_RESET_NEW_TO_YOU = "--reset-new-to-you"
DESKTOP_RUNTIME_ENV_VAR = "JOB_HUNTER_DESKTOP_MODE"


def has_cli_flag(argv: list[str], flag: str) -> bool:
    return flag in argv


def is_desktop_runtime() -> bool:
    """Return True when the desktop launcher has marked this runtime as desktop."""
    return str(os.environ.get(DESKTOP_RUNTIME_ENV_VAR, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
        logger.warning("[RUNTIME_HELPERS][WARN] Failed to write LLM cost log to %s: %s", path, exc)


def append_uncertainty_log(path: Path, entry: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning(
            "[RUNTIME_HELPERS][WARN] Failed to write uncertainty log to %s: %s", path, exc
        )


_SENSITIVE_SETTING_KEYWORDS = ("password", "secret", "token", "api_key", "apikey", "key")


def _is_sensitive_setting_path(path: tuple[str, ...]) -> bool:
    if not path:
        return False
    leaf = path[-1].lower()
    return any(keyword in leaf for keyword in _SENSITIVE_SETTING_KEYWORDS)


def _format_setting_value(value: Any, *, redact: bool) -> str:
    if redact:
        return "<redacted>"
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = repr(value)
    return text if len(text) <= 240 else f"{text[:237]}..."


def _iter_settings_diffs(
    before: Any,
    after: Any,
    path: tuple[str, ...] = (),
) -> Iterable[tuple[tuple[str, ...], Any, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before) | set(after))
        for key in keys:
            yield from _iter_settings_diffs(before.get(key), after.get(key), path + (str(key),))
        return
    if before != after:
        yield path, before, after


def log_settings_change(
    logger: logging.Logger,
    *,
    scope: str,
    before: Any,
    after: Any,
) -> None:
    """Log a small before/after summary for saved settings payloads."""
    diffs = list(_iter_settings_diffs(before or {}, after or {}))
    if not diffs:
        logger.info("[%s] settings saved; no effective changes", scope)
        return

    logger.info("[%s] settings changed (%d field%s):", scope, len(diffs), "" if len(diffs) == 1 else "s")
    for path, old_value, new_value in diffs:
        redact = _is_sensitive_setting_path(path)
        logger.info(
            "[%s] %s: %s -> %s",
            scope,
            ".".join(path) or "(root)",
            _format_setting_value(old_value, redact=redact),
            _format_setting_value(new_value, redact=redact),
        )
