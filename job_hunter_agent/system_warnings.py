"""Central runtime warning store helpers."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from job_hunter_agent.database import db_conn, ensure_system_warnings_schema

logger = logging.getLogger(__name__)

_SYSTEM_WARNING_STATUSES = {"unresolved", "reviewed", "dismissed"}
_SYSTEM_WARNING_DIAGNOSTIC_WARNING_CATEGORIES = frozenset(
    {
        "job_identity_uncertainty",
        "llm_requirement_coverage",
        "preference_uncertainty",
        "requirement_coverage_uncertainty",
    }
)
_SCRAPER_VALIDATION_CATEGORIES = frozenset(
    {
        "scraper_configuration_validation",
        "source_failure",
        "source_timeout",
    }
)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _warning_context_json(context: Any | None) -> str:
    if context is None:
        return "{}"
    return json.dumps(context, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _warning_row(row) -> dict[str, Any]:
    payload = dict(row)
    context_json = str(payload.get("context_json") or "{}")
    try:
        payload["context"] = json.loads(context_json)
    except Exception as exc:  # pragma: no cover - schema corruption should not be silent
        raise ValueError(f"Invalid warning context_json: {context_json!r}") from exc
    return payload


def classify_system_warning(warning: dict[str, Any]) -> dict[str, str]:
    """Classify one stored warning for the admin System health surface.

    This module is the single owner of actionable-versus-diagnostic policy. UI
    consumers receive the classification result and must not recreate category
    lists or severity rules.
    """

    severity = str(warning["severity"]).strip().lower()
    category = str(warning["category"]).strip().lower()

    if severity == "info":
        return {"kind": "diagnostic"}
    if severity == "warning" and category in _SYSTEM_WARNING_DIAGNOSTIC_WARNING_CATEGORIES:
        return {"kind": "diagnostic"}
    return {"kind": "operational"}


def is_actionable_system_warning(warning: dict[str, Any]) -> bool:
    """Return whether a warning belongs in the default System health incident feed."""

    return classify_system_warning(warning)["kind"] == "operational"


def system_warning_operator_action(warning: dict[str, Any]) -> dict[str, str] | None:
    """Return the operator action contract owned by this warning classification."""

    if not is_actionable_system_warning(warning):
        return None
    category = str(warning["category"]).strip().lower()
    if category in _SCRAPER_VALIDATION_CATEGORIES:
        return {
            "type": "run_scraper_validation",
            "label_key": "system_health_scraper_validation_action_label",
            "guidance_key": "system_health_scraper_investigation_help",
        }
    return None


def aggregate_system_warning_diagnostics(
    warnings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aggregate diagnostic rows by category and source with the latest sample."""

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for warning in warnings:
        if classify_system_warning(warning)["kind"] != "diagnostic":
            continue

        category = str(warning["category"]).strip()
        source = str(warning["source"]).strip()
        key = (category, source)
        count = int(warning["count"])
        last_seen_at = str(warning["last_seen_at"]).strip()

        group = groups.get(key)
        if group is None:
            groups[key] = {
                "category": category,
                "source": source,
                "record_count": 1,
                "occurrence_count": count,
                "last_seen_at": last_seen_at,
                "sample": dict(warning),
            }
            continue

        group["record_count"] += 1
        group["occurrence_count"] += count
        if last_seen_at > str(group["last_seen_at"]):
            group["last_seen_at"] = last_seen_at
            group["sample"] = dict(warning)

    return sorted(
        groups.values(),
        key=lambda item: (str(item["last_seen_at"]), str(item["category"]), str(item["source"])),
        reverse=True,
    )


def make_system_warning_fingerprint(*parts: Any) -> str:
    payload = json.dumps(
        [str(part or "").strip() for part in parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_system_warning(
    *,
    severity: str,
    category: str,
    source: str,
    message: str,
    fingerprint: str,
    job_key: str | None = None,
    run_id: str | None = None,
    context: Any | None = None,
    status: str = "unresolved",
    db_path: Path | None = None,
) -> dict[str, Any]:
    """Insert or update a deduplicated system warning row."""

    severity_text = str(severity or "").strip()
    category_text = str(category or "").strip()
    source_text = str(source or "").strip()
    message_text = str(message or "").strip()
    fingerprint_text = str(fingerprint or "").strip()
    job_key_text = str(job_key or "").strip()
    run_id_text = str(run_id or "").strip()
    status_text = str(status or "").strip().lower()

    if not severity_text:
        raise ValueError("severity is required for system warnings")
    if not category_text:
        raise ValueError("category is required for system warnings")
    if not source_text:
        raise ValueError("source is required for system warnings")
    if not message_text:
        raise ValueError("message is required for system warnings")
    if not fingerprint_text:
        raise ValueError("fingerprint is required for system warnings")
    if status_text not in _SYSTEM_WARNING_STATUSES:
        raise ValueError(f"Unsupported system warning status: {status_text!r}")

    context_json = _warning_context_json(context)
    now_iso = _now_iso()

    with db_conn(db_path) as conn:
        ensure_system_warnings_schema(conn)
        conn.execute(
            """
            INSERT INTO system_warnings (
                severity, category, source, message, fingerprint, status,
                job_key, run_id, context_json, first_seen_at, last_seen_at, count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(fingerprint) DO UPDATE SET
                severity = excluded.severity,
                category = excluded.category,
                source = excluded.source,
                message = excluded.message,
                job_key = CASE
                    WHEN excluded.job_key IS NULL OR excluded.job_key = ''
                    THEN system_warnings.job_key
                    ELSE excluded.job_key
                END,
                run_id = CASE
                    WHEN excluded.run_id IS NULL OR excluded.run_id = ''
                    THEN system_warnings.run_id
                    ELSE excluded.run_id
                END,
                context_json = excluded.context_json,
                last_seen_at = excluded.last_seen_at,
                count = system_warnings.count + 1,
                -- Every recurrence is a fresh incident, regardless of the prior
                -- reviewed/dismissed status or any caller-supplied insert status.
                status = 'unresolved'
            """,
            (
                severity_text,
                category_text,
                source_text,
                message_text,
                fingerprint_text,
                status_text,
                job_key_text or None,
                run_id_text or None,
                context_json,
                now_iso,
                now_iso,
            ),
        )
        row = conn.execute(
            """
            SELECT
                id, severity, category, source, message, fingerprint, status,
                job_key, run_id, context_json, first_seen_at, last_seen_at, count
            FROM system_warnings
            WHERE fingerprint = ?
            """,
            (fingerprint_text,),
        ).fetchone()

    if row is None:  # pragma: no cover - insert/select should always round-trip
        raise RuntimeError("Failed to persist system warning")
    return _warning_row(row)


def list_system_warnings(
    *, status: str = "unresolved", limit: int | None = None, db_path: Path | None = None
) -> list[dict[str, Any]]:
    status_text = str(status or "").strip().lower()
    if status_text not in _SYSTEM_WARNING_STATUSES:
        raise ValueError(f"Unsupported system warning status: {status_text!r}")
    params: list[Any] = [status_text]
    limit_clause = ""
    if limit is not None:
        limit_value = int(limit)
        if limit_value < 0:
            raise ValueError("limit must be >= 0")
        limit_clause = " LIMIT ?"
        params.append(limit_value)
    with db_conn(db_path) as conn:
        ensure_system_warnings_schema(conn)
        rows = conn.execute(
            """
            SELECT
                id, severity, category, source, message, fingerprint, status,
                job_key, run_id, context_json, first_seen_at, last_seen_at, count
            FROM system_warnings
            WHERE status = ?
            ORDER BY
                CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'error' THEN 1
                    WHEN 'warning' THEN 2
                    WHEN 'info' THEN 3
                    ELSE 4
                END,
                last_seen_at DESC,
                id DESC
            """
            + limit_clause,
            params,
        ).fetchall()
    return [_warning_row(row) for row in rows]


def update_system_warning_status(
    warning_id: int, status: str, db_path: Path | None = None
) -> dict[str, Any]:
    status_text = str(status or "").strip().lower()
    if status_text not in _SYSTEM_WARNING_STATUSES:
        raise ValueError(f"Unsupported system warning status: {status_text!r}")
    with db_conn(db_path) as conn:
        ensure_system_warnings_schema(conn)
        conn.execute(
            "UPDATE system_warnings SET status = ? WHERE id = ?",
            (status_text, int(warning_id)),
        )
        row = conn.execute(
            """
            SELECT
                id, severity, category, source, message, fingerprint, status,
                job_key, run_id, context_json, first_seen_at, last_seen_at, count
            FROM system_warnings
            WHERE id = ?
            """,
            (int(warning_id),),
        ).fetchone()
    if row is None:
        raise LookupError(f"System warning {warning_id} not found")
    return _warning_row(row)
