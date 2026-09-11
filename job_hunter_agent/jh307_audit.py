"""Read-only JH-307 cutover audit.

This module inventories legacy personal evidence and Job Hunter's remaining
market/history dependencies before JH-308.  It deliberately does not import
or call migration, Gmail, LLM, workspace rebuild, or normal runtime loaders.
SQLite is opened with ``mode=ro`` so even a diagnostic run cannot create or
modify runtime state.

The audit classifies only explicit structured identity evidence.  A canonical
``source:id`` value is directly migratable; a documented job URL, platform ID,
or ATS/requisition ID is reported as durable evidence for later exact lookup,
but this ticket never resolves it to a new identity.  Missing or ambiguous
identity remains unresolved rather than being inferred from employer, role,
date, or email prose.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlsplit

import requests

from job_hunter_agent.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT

AUDIT_VERSION = "JH-307.v1"

CLASS_ALREADY_CANONICAL = "already_canonical"
CLASS_EXACT_MIGRATABLE = "exact_migratable"
CLASS_EXACT_IDENTITY_RECOVERABLE = "exact_identity_recoverable"
CLASS_HISTORICAL_UNLINKED = "historical_unlinked"
CLASS_JUNK_OR_DUPLICATE = "junk_or_duplicate"
CLASS_UNSCOPED = "unscoped_non_target"

OWNER_ROB = "rob"
OWNER_AGENT = "agent"
OWNER_AUTOMATION = "automation"
OWNER_SYSTEM = "system"
OWNER_TEST = "test"
OWNER_OTHER = "other"
OWNER_UNCLASSIFIED = "unclassified_non_target"

_CANONICAL_JOB_KEY = re.compile(r"^[a-z]+:[a-z0-9][a-z0-9_-]*$")
_SUPPORTED_OUTCOMES = frozenset(
    {
        "applied",
        "withdrawn",
        "rejected",
        "unrejected",
        "interview",
        "progressed",
        "no_response",
        "un_no_response",
    }
)
_LEGACY_OUTCOME_MAP = {"rejection": "rejected"}
_EXPLICIT_IDENTITY_FIELDS = (
    "job_key",
    "canonical_job_key",
    "job_url",
    "source_job_url",
    "canonical_url",
    "platform_job_id",
    "seek_job_id",
    "linkedin_job_id",
    "apsjobs_job_id",
    "ats_requisition_id",
    "requisition_id",
)
_EXPLICIT_SOURCE_FIELDS = ("job_source", "source_platform", "platform", "job_board")
_KNOWN_SOURCE_NAMES = frozenset({"seek", "linkedin", "apsjobs"})
_SHEET_SETTING_KEY = "candidate_application_history"
_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={tab_name}"
)
_REQUIRED_SHEET_HEADERS = (
    "Run Date",
    "Company",
    "From",
    "Subject",
    "Content",
    "Thread ID",
    "Message ID",
    "Status",
)


@dataclass(frozen=True)
class AuditRecord:
    """Structured, body-free representation of one personal evidence row."""

    store: str
    record_ref: str
    user_id: str
    outcome: str
    event_date: str
    employer: str
    role: str
    source: str
    evidence_ref: str
    actor_id: str
    thread_id: str
    message_id: str
    job_key: str
    identity_evidence: tuple[dict[str, str], ...]
    explicit_non_job: bool = False
    malformed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "record_ref": self.record_ref,
            "user_id": self.user_id,
            "outcome": self.outcome,
            "event_date": self.event_date,
            "employer": self.employer,
            "role": self.role,
            "source": self.source,
            "evidence_ref": self.evidence_ref,
            "actor_id": self.actor_id,
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "job_key": self.job_key,
            "identity_evidence": [dict(item) for item in self.identity_evidence],
            "explicit_non_job": self.explicit_non_job,
            "malformed": self.malformed,
        }


@dataclass(frozen=True)
class DependencySpec:
    """An exact source token and its human-approved cutover owner."""

    dependency_id: str
    tokens: tuple[str, ...]
    replacement: str
    disposition: str


DEPENDENCY_SPECS = (
    DependencySpec(
        "legacy_job_history",
        ("job_history", "load_job_history", "save_job_history"),
        "JH-305 for activity; JH-owned analysis where still meaningful",
        "replace_or_retire",
    ),
    DependencySpec(
        "legacy_workspace_pool",
        ("workspace_pool", "load_saved_workspace_pool", "_save_workspace_pool"),
        "JMM market data plus JH analysis and JH-305 activity",
        "replace_or_retire",
    ),
    DependencySpec(
        "legacy_history_snapshots",
        ("last_kept_snapshot", "detail_evidence"),
        "JMM current JD evidence; recalculate stale analysis",
        "retire",
    ),
    DependencySpec(
        "legacy_full_description_reuse",
        ("get_trusted_full_description", "full_description"),
        "JMM current full_description",
        "replace",
    ),
    DependencySpec(
        "legacy_candidate_events",
        ("candidate_application_events",),
        "JH-305 exact events or bounded unlinked evidence",
        "preserve_then_retire",
    ),
    DependencySpec(
        "legacy_candidate_history",
        ("candidate_application_history", "Job_Rejections"),
        "JH-305 exact events or bounded unlinked evidence; Sheet remains provenance",
        "preserve_then_retire",
    ),
    DependencySpec(
        "canonical_activity_ledger",
        ("job_activity_events", "activity_ledger"),
        "Retain as JH-305 personal activity authority",
        "retain",
    ),
    DependencySpec(
        "profile_settings_job_keys",
        ("review_controls", "applied_job_keys", "rejected_job_keys", "hidden_job_keys"),
        "JH-305 activity; retain only candidate-owned controls",
        "replace_or_retire",
    ),
    DependencySpec(
        "jh_source_collection",
        (
            "source_runner",
            "source_connector",
            "scrapers.seek",
            "scrapers.linkedin",
            "scrapers.apsjobs",
        ),
        "JMM supported market feed",
        "replace",
    ),
    DependencySpec(
        "jh_jd_fetch",
        ("fetch_job_details", "fetch_job_detail", "_fetch_linkedin_detail_evidence"),
        "JMM JD hydration",
        "replace",
    ),
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _canonical_key(value: Any) -> str:
    candidate = _text(value).lower()
    return candidate if _CANONICAL_JOB_KEY.fullmatch(candidate) else ""


def _normalise_outcome(value: Any) -> str:
    """Convert the one explicit local-store status spelling to JH-305's type."""

    outcome = _text(value).lower()
    return _LEGACY_OUTCOME_MAP.get(outcome, outcome)


def _mapping_value(mapping: Mapping[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = mapping.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _identity_evidence(payload: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    """Extract only explicitly named identity fields; never inspect free text."""

    evidence: list[dict[str, str]] = []
    direct_key = _canonical_key(
        next(
            (payload.get(name) for name in ("job_key", "canonical_job_key") if payload.get(name)),
            "",
        )
    )
    if direct_key:
        evidence.append({"kind": "canonical_job_key", "value": direct_key})

    for name in ("job_url", "source_job_url", "canonical_url"):
        value = _text(payload.get(name))
        parsed = urlsplit(value) if value else None
        if parsed and parsed.scheme in {"http", "https"} and parsed.netloc:
            evidence.append({"kind": name, "value": value})

    source = _text(_mapping_value(payload, _EXPLICIT_SOURCE_FIELDS)).lower()
    for name in ("platform_job_id", "seek_job_id", "linkedin_job_id", "apsjobs_job_id"):
        value = _text(payload.get(name))
        if value:
            item = {"kind": name, "value": value}
            if source in _KNOWN_SOURCE_NAMES:
                item["source"] = source
            evidence.append(item)

    for name in ("ats_requisition_id", "requisition_id"):
        value = _text(payload.get(name))
        if value:
            item = {"kind": name, "value": value}
            if source:
                item["source"] = source
            evidence.append(item)
    return tuple(evidence)


def _record_from_db_row(row: sqlite3.Row) -> AuditRecord:
    payload: dict[str, Any] = {}
    payload_valid = True
    try:
        decoded = json.loads(row["data"] or "{}")
        if isinstance(decoded, dict):
            payload = decoded
    except (TypeError, ValueError):
        payload_valid = False
    key = _canonical_key(payload.get("job_key"))
    event_type = _normalise_outcome(row["event_type"])
    return AuditRecord(
        store="candidate_application_events",
        record_ref=f"candidate_application_events:{_text(row['user_id'])}:{_text(row['event_id'])}",
        user_id=_text(row["user_id"]),
        outcome=event_type,
        event_date=_text(row["event_date"]),
        employer=_text(row["employer_raw"]),
        role=_text(row["role_title"]),
        source=_text(row["source"]),
        evidence_ref=_text(row["evidence_ref"]),
        actor_id=_text(payload.get("agent_id")) or _text(row["source"]),
        thread_id=_text(payload.get("thread_id")),
        message_id=(
            _text(payload.get("message_id"))
            or (
                _text(row["evidence_ref"])
                if _text(row["source"]) in {"rejection_sheet", "gmail_ack"}
                else ""
            )
        ),
        job_key=key,
        identity_evidence=_identity_evidence(payload),
        malformed=(
            not payload_valid
            or event_type not in _SUPPORTED_OUTCOMES
            or not _text(row["event_date"])
            or not _text(row["employer_raw"])
        ),
    )


def _record_from_local_row(row: Mapping[str, Any], index: int) -> AuditRecord:
    payload = dict(row)
    record_id = _text(payload.get("id"))
    message_id = _text(payload.get("message_id"))
    thread_id = _text(payload.get("thread_id")) or _text(payload.get("id"))
    outcome = _normalise_outcome(payload.get("status") or payload.get("event_type"))
    return AuditRecord(
        store="candidate_application_history",
        record_ref=f"candidate_application_history:{message_id or record_id or index}",
        user_id=_text(payload.get("user_id")),
        outcome=outcome,
        event_date=_text(payload.get("date") or payload.get("run_date")),
        employer=_text(payload.get("company") or payload.get("raw_company")),
        role=_text(payload.get("role") or payload.get("raw_role")),
        source=_text(payload.get("source")),
        evidence_ref=message_id or record_id,
        actor_id=_text(payload.get("agent_id")) or _text(payload.get("source")),
        thread_id=thread_id,
        message_id=message_id,
        job_key=_canonical_key(payload.get("job_key")),
        identity_evidence=_identity_evidence(payload),
        malformed=(
            outcome not in _SUPPORTED_OUTCOMES
            or not _text(payload.get("date") or payload.get("run_date"))
            or not _text(payload.get("company"))
        ),
    )


def _record_from_db_history_row(row: sqlite3.Row) -> AuditRecord:
    payload: dict[str, Any] = {}
    payload_valid = True
    try:
        decoded = json.loads(row["data"] or "{}")
        if isinstance(decoded, dict):
            payload = decoded
    except (TypeError, ValueError):
        payload_valid = False
    # The table row's job_key is an explicit schema field, so it is stronger
    # than any same-shaped value inside its opaque JSON payload.
    payload["job_key"] = _text(row["job_key"])
    outcome = _normalise_outcome(payload.get("event_type") or payload.get("status"))
    return AuditRecord(
        store="candidate_application_history_db",
        record_ref=f"candidate_application_history_db:{_text(row['user_id'])}:{_text(row['job_key'])}",
        user_id=_text(row["user_id"]),
        outcome=outcome,
        event_date=_text(payload.get("event_date") or payload.get("date") or row["created_at"]),
        employer=_text(payload.get("employer") or payload.get("company")),
        role=_text(payload.get("role_title") or payload.get("role") or payload.get("title")),
        source=_text(payload.get("source")),
        evidence_ref=_text(payload.get("evidence_ref") or payload.get("message_id")),
        actor_id=_text(payload.get("agent_id")) or _text(payload.get("source")),
        thread_id=_text(payload.get("thread_id")),
        message_id=_text(payload.get("message_id")),
        job_key=_canonical_key(row["job_key"]),
        identity_evidence=_identity_evidence(payload),
        malformed=(
            not payload_valid
            or outcome not in _SUPPORTED_OUTCOMES
            or not _text(row["created_at"])
            or not _text(payload.get("employer") or payload.get("company"))
        ),
    )


def _record_from_sheet_row(row: Mapping[str, Any], index: int) -> AuditRecord:
    payload = {str(key).strip().lower().replace(" ", "_"): value for key, value in row.items()}
    message_id = _text(payload.get("message_id"))
    thread_id = _text(payload.get("thread_id"))
    status = _text(payload.get("status")).lower()
    identity_payload = {
        key: value
        for key, value in payload.items()
        if key in {name.lower() for name in _EXPLICIT_IDENTITY_FIELDS + _EXPLICIT_SOURCE_FIELDS}
    }
    return AuditRecord(
        store="Job_Rejections",
        record_ref=f"Job_Rejections:{message_id or thread_id or index}:{index}",
        user_id=_text(payload.get("user_id")),
        outcome="rejected",
        event_date=_text(payload.get("run_date")),
        employer=_text(payload.get("company")),
        role=_text(payload.get("role")),
        source="rejection_sheet",
        evidence_ref=message_id or thread_id,
        actor_id="rejection_sheet",
        thread_id=thread_id,
        message_id=message_id,
        job_key=_canonical_key(payload.get("job_key")),
        identity_evidence=_identity_evidence(identity_payload),
        explicit_non_job=status == "not job-related",
        malformed=not _text(payload.get("run_date"))
        or not _text(payload.get("company"))
        or not status,
    )


def _record_sort_key(record: AuditRecord) -> tuple[str, str, str]:
    return (record.store, record.record_ref, record.user_id)


def _evidence_duplicate_key(record: AuditRecord) -> str:
    stable = record.message_id or record.thread_id
    return f"message:{stable}" if stable else ""


def _classify_user(
    user_id: str, target_user_id: str | None, explicit_scopes: Mapping[str, str]
) -> str:
    if target_user_id and user_id == target_user_id:
        return OWNER_ROB
    return explicit_scopes.get(user_id, OWNER_UNCLASSIFIED)


def _classify_record(
    record: AuditRecord,
    *,
    canonical_keys: set[tuple[str, str, str]],
    duplicate_of: str | None,
) -> tuple[str, str]:
    if duplicate_of:
        return CLASS_JUNK_OR_DUPLICATE, f"duplicate durable evidence of {duplicate_of}"
    if record.explicit_non_job:
        return CLASS_JUNK_OR_DUPLICATE, "source explicitly marked the row not job-related"
    if record.malformed:
        return CLASS_JUNK_OR_DUPLICATE, "required structured outcome fields are missing or invalid"
    if record.job_key:
        if (record.user_id, record.job_key, record.outcome) in canonical_keys:
            return (
                CLASS_ALREADY_CANONICAL,
                "same user, exact job key, and outcome already exist in JH-305",
            )
        return CLASS_EXACT_MIGRATABLE, "explicit canonical JH source:id identity is present"
    if record.identity_evidence:
        return (
            CLASS_EXACT_IDENTITY_RECOVERABLE,
            "durable explicit identity evidence exists; JH-307 does not resolve it",
        )
    return CLASS_HISTORICAL_UNLINKED, "no exact structured job identity evidence is present"


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Database not found: {resolved}")
    # ``mode=ro`` includes committed WAL state while preventing SQL writes.
    # Callers should run the audit against a quiescent DB snapshot; the audit
    # itself never checkpoints, vacuums, seeds, or otherwise mutates it.
    connection = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _table_count(conn: sqlite3.Connection, table: str, user_id: str | None = None) -> int:
    if user_id is None:
        return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    return int(
        conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE user_id = ?', (user_id,)).fetchone()[0]
    )


def _job_key_collection_inventory(conn: sqlite3.Connection) -> dict[str, Any]:
    """Report explicit profile/settings key collections without interpreting them."""

    result: dict[str, Any] = {"user_profile": {}, "user_settings": {}}
    for table in ("user_profile", "user_settings"):
        rows = conn.execute(f"SELECT user_id, data FROM {table} ORDER BY user_id").fetchall()
        for row in rows:
            try:
                payload = json.loads(row["data"] or "{}")
            except (TypeError, ValueError):
                result[table][_text(row["user_id"])] = {"status": "invalid_json", "collections": {}}
                continue
            controls = payload.get("review_controls") if isinstance(payload, dict) else None
            collections: dict[str, int] = {}
            if isinstance(controls, dict):
                for field in (
                    "liked_job_keys",
                    "hidden_job_keys",
                    "applied_job_keys",
                    "rejected_job_keys",
                    "no_response_job_keys",
                ):
                    values = controls.get(field)
                    if isinstance(values, list):
                        collections[field] = sum(bool(_canonical_key(value)) for value in values)
            result[table][_text(row["user_id"])] = {
                "status": "read",
                "collections": collections,
            }
    return result


def _legacy_job_inventory(conn: sqlite3.Connection) -> dict[str, Any]:
    result: dict[str, Any] = {"job_history": {}, "workspace_pool": {}}
    for row in conn.execute("SELECT user_id, job_key FROM job_history ORDER BY user_id, job_key"):
        result["job_history"].setdefault(_text(row["user_id"]), []).append(_text(row["job_key"]))
    for row in conn.execute("SELECT user_id, data FROM workspace_pool ORDER BY user_id"):
        try:
            payload = json.loads(row["data"] or "[]")
        except (TypeError, ValueError):
            result["workspace_pool"][_text(row["user_id"])] = {
                "status": "invalid_json",
                "job_keys": [],
            }
            continue
        records = payload if isinstance(payload, list) else []
        result["workspace_pool"][_text(row["user_id"])] = {
            "status": "read",
            "job_keys": sorted(
                key
                for key in (
                    _canonical_key(item.get("job_key"))
                    for item in records
                    if isinstance(item, dict)
                )
                if key
            ),
        }
    return result


def _load_local_history(path: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if path is None:
        return [], {"path": None, "status": "not_supplied", "rows": 0}
    if not path.is_file():
        return [], {"path": str(path), "status": "not_found", "rows": 0}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], {"path": str(path), "status": "unreadable", "rows": 0, "error": str(exc)}
    if not isinstance(payload, list):
        return [], {"path": str(path), "status": "invalid_shape", "rows": 0}
    rows = [dict(item) for item in payload if isinstance(item, dict)]
    return rows, {
        "path": str(path),
        "status": "read",
        "rows": len(rows),
        "ignored_non_object_rows": len(payload) - len(rows),
    }


def _load_configured_sheet_settings(
    conn: sqlite3.Connection, override_path: Path | None
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT value FROM global_settings WHERE key = ?", ("global_settings",)
    ).fetchone()
    settings: dict[str, Any] = {}
    if row:
        try:
            decoded = json.loads(row["value"] or "{}")
            if isinstance(decoded, dict):
                settings = dict(decoded.get(_SHEET_SETTING_KEY) or {})
        except (TypeError, ValueError):
            settings = {}
    if override_path and override_path.is_file():
        try:
            decoded = json.loads(override_path.read_text(encoding="utf-8"))
            if isinstance(decoded, dict):
                overlay = decoded.get(_SHEET_SETTING_KEY, decoded)
                if isinstance(overlay, dict):
                    settings.update(overlay)
        except (OSError, ValueError) as exc:
            settings["_override_error"] = str(exc)
    return settings


def fetch_configured_sheet_rows(
    db_path: Path,
    *,
    override_path: Path | None = None,
    request_get: Callable[..., Any] = requests.get,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch the configured rejection Sheet without importing or writing anything."""

    conn = _read_only_connection(db_path)
    try:
        settings = _load_configured_sheet_settings(conn, override_path)
    finally:
        conn.close()
    if settings.get("_override_error"):
        return [], {
            "status": "unreadable_override",
            "error": settings["_override_error"],
            "rows": 0,
        }
    if not bool(settings.get("enabled")):
        return [], {"status": "disabled_or_not_configured", "rows": 0}
    sheet_id = _text(settings.get("spreadsheet_id"))
    tab_name = _text(settings.get("tab_name"))
    headers = tuple(settings.get("required_headers") or _REQUIRED_SHEET_HEADERS)
    if not sheet_id or not tab_name:
        return [], {"status": "not_configured", "rows": 0}
    try:
        response = request_get(
            _SHEET_CSV_URL.format(sheet_id=sheet_id, tab_name=tab_name), timeout=30
        )
    except requests.RequestException as exc:
        return [], {"status": "fetch_failed", "rows": 0, "error": str(exc)}
    if not response.ok:
        return [], {"status": "fetch_failed", "rows": 0, "http_status": response.status_code}
    reader = csv.DictReader(io.StringIO(response.text))
    available_headers = set(reader.fieldnames or ())
    missing = sorted(set(headers) - available_headers)
    if missing:
        return [], {"status": "missing_headers", "rows": 0, "missing_headers": missing}
    rows = list(reader)
    return rows, {"status": "read", "rows": len(rows), "tab_name": tab_name}


def _scan_dependencies(repo_root: Path) -> list[dict[str, Any]]:
    files = sorted(repo_root.joinpath("job_hunter_agent").rglob("*.py"))
    results: list[dict[str, Any]] = []
    for spec in DEPENDENCY_SPECS:
        references: list[dict[str, Any]] = []
        for path in files:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            for line_number, line in enumerate(lines, 1):
                for token in spec.tokens:
                    if token in line:
                        references.append(
                            {
                                "file": str(path.relative_to(repo_root)),
                                "line": line_number,
                                "token": token,
                            }
                        )
        results.append(
            {
                "dependency_id": spec.dependency_id,
                "replacement": spec.replacement,
                "disposition": spec.disposition,
                "reference_count": len(references),
                "references": references,
            }
        )
    return results


def build_audit_report(
    db_path: Path,
    *,
    target_user_id: str | None,
    sheet_rows: Iterable[Mapping[str, Any]] = (),
    sheet_status: Mapping[str, Any] | None = None,
    sheet_user_id: str | None = None,
    local_history_path: Path | None = None,
    local_history_user_id: str | None = None,
    explicit_user_scopes: Mapping[str, str] | None = None,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Build a deterministic body-free report from DB, local store, and rows."""

    explicit_user_scopes = dict(explicit_user_scopes or {})
    local_rows, local_status = _load_local_history(local_history_path)
    conn = _read_only_connection(db_path)
    try:
        users = [
            dict(row)
            for row in conn.execute(
                "SELECT user_id, email, display_name, access_status FROM users ORDER BY user_id"
            )
        ]
        canonical_rows = conn.execute(
            "SELECT user_id, job_key, activity_type FROM job_activity_events ORDER BY user_id, occurred_at, event_id"
        ).fetchall()
        canonical_keys = {
            (
                _text(row["user_id"]),
                _text(row["job_key"]).lower(),
                _text(row["activity_type"]).lower(),
            )
            for row in canonical_rows
        }
        db_rows = conn.execute(
            "SELECT * FROM candidate_application_events ORDER BY user_id, event_date, event_id"
        ).fetchall()
        db_history_rows = conn.execute(
            "SELECT user_id, job_key, data, created_at FROM candidate_application_history ORDER BY user_id, job_key"
        ).fetchall()
        key_collections = _job_key_collection_inventory(conn)
        legacy_job_inventory = _legacy_job_inventory(conn)
        state_counts = {
            table: {
                "all_users": _table_count(conn, table),
                "target_user": _table_count(conn, table, target_user_id)
                if target_user_id
                else None,
            }
            for table in (
                "job_history",
                "workspace_pool",
                "candidate_application_history",
                "candidate_application_events",
                "job_activity_events",
                "user_profile",
                "user_settings",
            )
        }
    finally:
        conn.close()

    records = [_record_from_db_row(row) for row in db_rows]
    records.extend(_record_from_db_history_row(row) for row in db_history_rows)
    records.extend(
        AuditRecord(
            **{
                **record.__dict__,
                "user_id": local_history_user_id or record.user_id,
            }
        )
        for index, row in enumerate(local_rows)
        for record in (_record_from_local_row(row, index),)
    )
    records.extend(
        AuditRecord(
            **{
                **record.__dict__,
                "user_id": sheet_user_id or record.user_id,
            }
        )
        for index, row in enumerate(sheet_rows)
        for record in (_record_from_sheet_row(row, index),)
    )
    records.sort(key=_record_sort_key)

    seen_evidence: dict[str, str] = {}
    classifications: list[dict[str, Any]] = []
    summary_by_scope: Counter[str] = Counter()
    summary_by_class: Counter[str] = Counter()
    for record in records:
        owner = _classify_user(record.user_id, target_user_id, explicit_user_scopes)
        duplicate_key = _evidence_duplicate_key(record)
        duplicate_of = seen_evidence.get(duplicate_key) if duplicate_key else None
        if duplicate_key and duplicate_of is None:
            seen_evidence[duplicate_key] = record.record_ref
        if owner != OWNER_ROB:
            classification, reason = (
                CLASS_UNSCOPED,
                "record is outside the explicitly selected Rob user scope",
            )
        else:
            classification, reason = _classify_record(
                record, canonical_keys=canonical_keys, duplicate_of=duplicate_of
            )
        item = record.as_dict()
        item.update(
            {"owner": owner, "classification": classification, "classification_reason": reason}
        )
        if duplicate_of:
            item["duplicate_of"] = duplicate_of
        classifications.append(item)
        summary_by_scope[owner] += 1
        summary_by_class[classification] += 1

    blockers: list[str] = []
    if not target_user_id:
        blockers.append(
            "target_user_id is required before personal-history counts can be treated as Rob's"
        )
    if target_user_id and not any(_text(user.get("user_id")) == target_user_id for user in users):
        blockers.append("target_user_id is not present in the users table")
    if sheet_status and sheet_status.get("status") not in {"read", "disabled_or_not_configured"}:
        blockers.append(f"Job_Rejections sheet was not read: {sheet_status.get('status')}")
    if sheet_status and sheet_status.get("status") == "disabled_or_not_configured":
        blockers.append("configured Job_Rejections sheet is disabled or not configured")
    if sheet_rows and not sheet_user_id:
        blockers.append(
            "sheet_user_id is required before rejection-sheet rows can be treated as Rob's"
        )
    if local_rows and not local_history_user_id:
        blockers.append(
            "local_history_user_id is required before local history rows can be treated as Rob's"
        )
    if target_user_id and sheet_user_id and sheet_user_id != target_user_id:
        blockers.append("sheet_user_id does not match target_user_id")
    if target_user_id and local_history_user_id and local_history_user_id != target_user_id:
        blockers.append("local_history_user_id does not match target_user_id")
    if local_status.get("status") in {"unreadable", "invalid_shape"}:
        blockers.append(f"local candidate history store is {local_status['status']}")

    user_inventory = []
    for user in users:
        user_id = _text(user.get("user_id"))
        user_inventory.append(
            {
                "user_id": user_id,
                "email": _text(user.get("email")),
                "display_name": _text(user.get("display_name")),
                "access_status": _text(user.get("access_status")),
                "scope": _classify_user(user_id, target_user_id, explicit_user_scopes),
            }
        )

    return {
        "audit_version": AUDIT_VERSION,
        "read_only": True,
        "db_path": str(db_path.expanduser().resolve()),
        "target_user_id": target_user_id,
        "users": user_inventory,
        "store_counts": state_counts,
        "job_key_collections": key_collections,
        "legacy_job_inventory": legacy_job_inventory,
        "local_history": local_status,
        "sheet": dict(sheet_status or {"status": "not_requested", "rows": 0}),
        "legacy_record_summary": {
            "total_records": len(records),
            "by_owner": dict(sorted(summary_by_scope.items())),
            "by_classification": dict(sorted(summary_by_class.items())),
        },
        "records": classifications,
        "dependencies": _scan_dependencies(repo_root),
        "blockers": blockers,
        "policy": {
            "no_gmail_search": True,
            "no_llm": True,
            "no_identity_resolution": True,
            "no_jmm_mapping": True,
            "raw_email_bodies_committed": False,
        },
    }


def write_private_report(report: Mapping[str, Any], path: Path) -> None:
    """Write the body-free-but-personal report to ignored runtime/output state."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the JH-307 read-only personal-history and JMM cutover dependency audit."
    )
    parser.add_argument(
        "--db", type=Path, required=True, help="Path to the existing Job Hunter SQLite database."
    )
    parser.add_argument(
        "--target-user-id", help="Exact registered user_id whose history belongs to Rob."
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=OUTPUT_DIR / "jh307_cutover_audit.json",
        help="Ignored private report path.",
    )
    parser.add_argument(
        "--local-history",
        type=Path,
        default=DATA_DIR / "runtime" / "candidate_application_history.json",
        help="Existing candidate_application_history.json path to inspect.",
    )
    parser.add_argument(
        "--local-history-user-id",
        help="Exact user_id that owns the local owner-only history store.",
    )
    parser.add_argument(
        "--sheet-user-id",
        help="Exact user_id that owns the configured Job_Rejections evidence source.",
    )
    parser.add_argument(
        "--ownership",
        type=Path,
        help="JSON object mapping non-target user_id values to agent/automation/system/test/other.",
    )
    return parser


def _load_ownership(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
    ):
        raise ValueError("ownership manifest must be a JSON object of user_id to scope")
    allowed = {OWNER_AGENT, OWNER_AUTOMATION, OWNER_SYSTEM, OWNER_TEST, OWNER_OTHER}
    if any(value not in allowed for value in payload.values()):
        raise ValueError(f"ownership manifest values must be one of {sorted(allowed)}")
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        ownership = _load_ownership(args.ownership)
        sheet_rows, sheet_status = fetch_configured_sheet_rows(
            args.db,
            override_path=DATA_DIR
            / "runtime"
            / "rob_candidate_application_history_import.local.json",
        )
        report = build_audit_report(
            args.db,
            target_user_id=args.target_user_id,
            sheet_rows=sheet_rows,
            sheet_status=sheet_status,
            sheet_user_id=args.sheet_user_id,
            local_history_path=args.local_history,
            local_history_user_id=args.local_history_user_id,
            explicit_user_scopes=ownership,
        )
        write_private_report(report, args.report)
        print(f"[JH-307] report: {args.report}")
        print(f"[JH-307] read_only: {report['read_only']}")
        print(f"[JH-307] legacy_records: {report['legacy_record_summary']['total_records']}")
        print(
            f"[JH-307] by_classification: {json.dumps(report['legacy_record_summary']['by_classification'], sort_keys=True)}"
        )
        print(f"[JH-307] blockers: {json.dumps(report['blockers'], ensure_ascii=True)}")
    except Exception as exc:
        print(f"[JH-307] unavailable: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
