"""Bounded JH-308 personal-history reconciliation and retirement input.

The normal application path must not import or repair legacy application
history.  This command is the one explicit cutover owner: it reads the JH-307
evidence sources, migrates only exact identities through JH-305, preserves
unlinked evidence without a job identity, and quarantines excluded rows.

The command never reads email through Gmail or calls an LLM.  A source URL or
platform ID is only a candidate for the supported JMM exact lookup; the JMM
response must confirm the same source identity before an activity event is
written.  Employer, role, date, and email text are never used to resolve a
job.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from job_hunter_agent import activity_ledger as activity
from job_hunter_agent.jh307_audit import (
    CLASS_ALREADY_CANONICAL,
    CLASS_EXACT_IDENTITY_RECOVERABLE,
    CLASS_EXACT_MIGRATABLE,
    CLASS_HISTORICAL_UNLINKED,
    CLASS_JUNK_OR_DUPLICATE,
    build_audit_report,
    fetch_configured_sheet_rows,
)
from job_hunter_agent.job_identity import normalize_job_key
from job_hunter_agent.job_market_map_client import JobMarketMapClient, JobMarketMapError
from job_hunter_agent.paths import DATA_DIR, OUTPUT_DIR, REPO_ROOT

_MIGRATION_SOURCE_BY_LEGACY_SOURCE = {
    "rejection_sheet": activity.SOURCE_REJECTION_SHEET,
    "sheet_import": activity.SOURCE_REJECTION_SHEET,
    "gmail_apps_script": activity.SOURCE_GMAIL_ACK,
    "gmail_ack": activity.SOURCE_GMAIL_ACK,
    "seek_applied": activity.SOURCE_SEEK_APPLIED,
    "manual": activity.SOURCE_MANUAL,
}
_MIGRATION_AGENT_ID = activity.AGENT_MANUAL
_OUTCOME_TYPES = frozenset(activity.OUTCOME_ACTIVITY_TYPES)
_REPORT_VERSION = "JH-308.v1"
_COUNTED_TABLES = (
    "candidate_application_events",
    "candidate_application_history",
    "job_activity_events",
    "historical_application_evidence",
    "historical_application_quarantine",
)


class CutoverBlocked(RuntimeError):
    """The evidence or exact-lookup contract is not sufficient to apply."""


def _text(value: object) -> str:
    return str(value or "").strip()


def _date(value: object) -> str:
    raw = _text(value)
    return raw[:10] if len(raw) >= 10 else ""


def _evidence_id(record: Mapping[str, Any]) -> str:
    raw = f"{record.get('store', '')}|{record.get('record_ref', '')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _identity_fields(record: Mapping[str, Any]) -> dict[str, str]:
    fields = {
        "source_url": "",
        "source_job_id": "",
        "requisition_id": "",
        "source": "",
    }
    for item in record.get("identity_evidence") or ():
        if not isinstance(item, Mapping):
            continue
        kind = _text(item.get("kind")).lower()
        value = _text(item.get("value"))
        if not value:
            continue
        if kind in {"job_url", "source_job_url", "canonical_url"} and not fields["source_url"]:
            fields["source_url"] = value
        elif kind in {"platform_job_id", "seek_job_id", "linkedin_job_id", "apsjobs_job_id"}:
            if not fields["source_job_id"]:
                fields["source_job_id"] = value
            fields["source"] = fields["source"] or _text(item.get("source")).lower()
        elif kind in {"ats_requisition_id", "requisition_id"}:
            fields["requisition_id"] = fields["requisition_id"] or value
            fields["source"] = fields["source"] or _text(item.get("source")).lower()
    return fields


def _lookup_candidates(record: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Return exact source/id candidates from documented identity fields only."""
    fields = _identity_fields(record)
    candidates: list[tuple[str, str]] = []
    if fields["source_job_id"] and fields["source"]:
        candidates.append((fields["source"], fields["source_job_id"]))
    if fields["source_url"]:
        normalized = normalize_job_key(fields["source_url"])
        if ":" in normalized:
            source, source_job_id = normalized.split(":", 1)
            candidates.append((source, source_job_id))
    return list(dict.fromkeys(candidates))


def _confirmed_job_key(
    record: Mapping[str, Any], client: JobMarketMapClient
) -> tuple[str, dict[str, Any]] | None:
    resolved: list[tuple[str, dict[str, Any]]] = []
    for source, source_job_id in _lookup_candidates(record):
        payload = client.lookup_source_job(source=source, source_job_id=source_job_id)
        job = payload.get("job")
        if not isinstance(job, Mapping):
            raise CutoverBlocked("JMM exact lookup returned no job object")
        returned_source = _text(job.get("source")).lower()
        returned_id = _text(job.get("source_job_id"))
        if returned_source != source.lower() or returned_id != source_job_id:
            raise CutoverBlocked("JMM exact lookup response does not confirm requested identity")
        job_key = normalize_job_key(returned_id, source=returned_source)
        if not job_key:
            raise CutoverBlocked("JMM exact lookup returned no usable JH source identity")
        resolved.append((job_key, dict(job)))
    if not resolved:
        return None
    if len({item[0] for item in resolved}) != 1:
        raise CutoverBlocked("durable identity evidence resolves to conflicting JMM jobs")
    return resolved[0]


def _activity_source(record: Mapping[str, Any]) -> str:
    source = _text(record.get("source")).lower()
    try:
        return _MIGRATION_SOURCE_BY_LEGACY_SOURCE[source]
    except KeyError as exc:
        raise CutoverBlocked(f"unsupported legacy activity source: {source!r}") from exc


def _integrity_counts(db_path: Path, user_id: str) -> dict[str, Any]:
    with sqlite3.connect(db_path) as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        counts = {
            table: int(
                conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE user_id = ?', (user_id,)).fetchone()[0]
            )
            for table in _COUNTED_TABLES
        }
    return {"integrity_check": integrity, "user_id": user_id, "counts": counts}


def create_backup(db_path: Path, backup_path: Path) -> None:
    """Create a consistent SQLite rollback snapshot before any cutover write."""
    if db_path.resolve() == backup_path.resolve():
        raise ValueError("backup_path must be different from db_path")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(db_path)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()


def _insert_historical_evidence(
    conn: sqlite3.Connection, record: Mapping[str, Any]
) -> bool:
    fields = _identity_fields(record)
    values = (
        _text(record.get("user_id")),
        _evidence_id(record),
        _text(record.get("outcome")),
        _date(record.get("event_date")),
        _text(record.get("employer")),
        _text(record.get("role")),
        _text(record.get("source")),
        _text(record.get("evidence_ref")),
        _text(record.get("actor_id")),
        _text(record.get("thread_id")),
        _text(record.get("message_id")),
        fields["source_url"],
        fields["source_job_id"],
        fields["requisition_id"],
        _text(record.get("store")),
        _text(record.get("record_ref")),
    )
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO historical_application_evidence
            (user_id, evidence_id, outcome, event_date, employer_raw, role_title,
             source, evidence_ref, actor_id, thread_id, message_id, source_url,
             source_job_id, requisition_id, origin_store, origin_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return cursor.rowcount == 1


def _insert_quarantine(
    conn: sqlite3.Connection, record: Mapping[str, Any], reason: str
) -> bool:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO historical_application_quarantine
            (user_id, evidence_id, reason, outcome, event_date, employer_raw,
             role_title, source, evidence_ref, origin_store, origin_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _text(record.get("user_id")),
            _evidence_id(record),
            reason,
            _text(record.get("outcome")),
            _date(record.get("event_date")),
            _text(record.get("employer")),
            _text(record.get("role")),
            _text(record.get("source")),
            _text(record.get("evidence_ref")),
            _text(record.get("store")),
            _text(record.get("record_ref")),
        ),
    )
    return cursor.rowcount == 1


def _prune_bounded_store(conn: sqlite3.Connection, table: str, user_id: str, max_entries: int) -> int:
    rows = conn.execute(
        f"""
        SELECT evidence_id FROM {table}
         WHERE user_id = ?
         ORDER BY event_date DESC, evidence_id DESC
         LIMIT -1 OFFSET ?
        """,
        (user_id, max_entries),
    ).fetchall()
    if not rows:
        return 0
    conn.executemany(
        f"DELETE FROM {table} WHERE user_id = ? AND evidence_id = ?",
        [(user_id, row[0]) for row in rows],
    )
    return len(rows)


def _canonical_outcome_keys(user_id: str, db_path: Path) -> set[tuple[str, str]]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT job_key, activity_type FROM job_activity_events WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {(str(row[0]), str(row[1])) for row in rows}


def run_cutover(
    db_path: Path,
    *,
    target_user_id: str,
    local_history_path: Path | None = None,
    ownership: Mapping[str, str] | None = None,
    client: JobMarketMapClient | None = None,
    max_entries: int | None = None,
    apply: bool = False,
    backup_path: Path | None = None,
    request_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Plan or apply the one-time JH-308 reconciliation for one user."""
    if not _text(target_user_id):
        raise ValueError("target_user_id is required")
    if apply and client is None:
        client = JobMarketMapClient.from_environment()

    sheet_rows, sheet_status = fetch_configured_sheet_rows(
        db_path,
        override_path=DATA_DIR / "runtime" / "rob_candidate_application_history_import.local.json",
        request_get=request_get or requests.get,
    )
    audit = build_audit_report(
        db_path,
        target_user_id=target_user_id,
        sheet_rows=sheet_rows,
        sheet_status=sheet_status,
        sheet_user_id=target_user_id,
        local_history_path=local_history_path,
        local_history_user_id=target_user_id,
        explicit_user_scopes=ownership,
        repo_root=REPO_ROOT,
    )
    if audit["blockers"] and apply:
        raise CutoverBlocked("; ".join(audit["blockers"]))

    before = _integrity_counts(db_path, target_user_id)
    if apply:
        if backup_path is None:
            raise ValueError("backup_path is required when apply=True")
        create_backup(db_path, backup_path)

    counters: Counter[str] = Counter()
    canonical_keys = _canonical_outcome_keys(target_user_id, db_path)
    lookup_client = client
    pending_activity: list[tuple[Mapping[str, Any], str]] = []
    pending_history: list[Mapping[str, Any]] = []
    pending_quarantine: list[tuple[Mapping[str, Any], str]] = []
    for record in audit["records"]:
        if _text(record.get("owner")) != "rob":
            counters["unscoped"] += 1
            continue
        classification = _text(record.get("classification"))
        if classification == CLASS_ALREADY_CANONICAL:
            counters["already_canonical"] += 1
            continue
        if classification == CLASS_HISTORICAL_UNLINKED:
            pending_history.append(record)
            counters["historical_planned"] += 1
            continue
        if classification == CLASS_JUNK_OR_DUPLICATE:
            pending_quarantine.append(
                (record, _text(record.get("classification_reason")) or "excluded by JH-307")
            )
            counters["quarantine_planned"] += 1
            continue

        job_key = _text(record.get("job_key")).lower()
        if classification == CLASS_EXACT_IDENTITY_RECOVERABLE:
            if lookup_client is None:
                counters["unresolved_exact_evidence"] += 1
                pending_history.append(record)
                continue
            try:
                resolved = _confirmed_job_key(record, lookup_client)
            except (JobMarketMapError, CutoverBlocked, ValueError):
                resolved = None
            if resolved is None:
                pending_history.append(record)
                counters["unresolved_archive_planned"] += 1
                continue
            job_key = resolved[0]
            counters["exact_lookup_resolved"] += 1

        if classification not in {CLASS_EXACT_MIGRATABLE, CLASS_EXACT_IDENTITY_RECOVERABLE}:
            counters["unhandled"] += 1
            continue
        outcome = _text(record.get("outcome")).lower()
        if not job_key or outcome not in _OUTCOME_TYPES or not _date(record.get("event_date")):
            pending_quarantine.append((record, "exact record is missing a valid job identity, outcome, or date"))
            counters["unresolved_invalid_exact_record"] += 1
            continue
        try:
            _activity_source(record)
        except CutoverBlocked as exc:
            pending_quarantine.append((record, str(exc)))
            counters["unsupported_exact_source"] += 1
            continue
        pair = (job_key, outcome)
        if pair in canonical_keys:
            counters["duplicate_canonical"] += 1
            continue
        pending_activity.append((record, job_key))
        canonical_keys.add(pair)
        counters["activity_planned"] += 1

    if apply:
        for record, job_key in pending_activity:
            activity.record_activity_event(
                user_id=target_user_id,
                job_key=job_key,
                activity_type=_text(record.get("outcome")).lower(),
                agent_id=_MIGRATION_AGENT_ID,
                occurred_at=f"{_date(record.get('event_date'))}T00:00:00+00:00",
                source=_activity_source(record),
                evidence_ref=_text(record.get("evidence_ref")),
                idempotency_key=f"jh308:{_evidence_id(record)}",
                metadata={"migration_source": _text(record.get("store"))},
                employer_raw=_text(record.get("employer")),
                role_title=_text(record.get("role")),
                db_path=db_path,
            )
            counters["activity_migrated"] += 1
        with sqlite3.connect(db_path) as conn:
            for record in pending_history:
                inserted = _insert_historical_evidence(conn, record)
                counters["historical_inserted"] += int(inserted)
            for record, reason in pending_quarantine:
                inserted = _insert_quarantine(conn, record, reason)
                counters["quarantine_inserted"] += int(inserted)
            from job_hunter_agent.global_settings import (
                get_historical_application_evidence_max_entries,
            )

            bound = int(
                max_entries
                if max_entries is not None
                else get_historical_application_evidence_max_entries()
            )
            if bound < 1:
                raise ValueError("historical evidence bound must be positive")
            counters["historical_pruned"] = _prune_bounded_store(
                conn, "historical_application_evidence", target_user_id, bound
            )
            counters["quarantine_pruned"] = _prune_bounded_store(
                conn, "historical_application_quarantine", target_user_id, bound
            )
    else:
        counters["historical_planned"] = len(pending_history)
        counters["quarantine_planned"] = len(pending_quarantine)

    after = _integrity_counts(db_path, target_user_id) if apply else before
    return {
        "report_version": _REPORT_VERSION,
        "target_user_id": target_user_id,
        "apply": apply,
        "backup_path": str(backup_path) if backup_path else "",
        "before": before,
        "after": after,
        "counters": dict(sorted(counters.items())),
        "audit_summary": audit["legacy_record_summary"],
        "audit_blockers": audit["blockers"],
        "policy": {
            "no_gmail_search": True,
            "no_llm": True,
            "exact_jmm_lookup_only": True,
            "unlinked_rows_have_no_job_key": True,
            "raw_email_bodies_stored": False,
        },
    }


def write_report(report: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or apply the bounded JH-308 cutover.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--target-user-id", required=True)
    parser.add_argument("--local-history", type=Path, default=DATA_DIR / "runtime" / "candidate_application_history.json")
    parser.add_argument("--ownership", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write the verified cutover; omitted means plan only.")
    parser.add_argument("--backup", type=Path, help="SQLite rollback snapshot path; required with --apply.")
    parser.add_argument("--report", type=Path, default=OUTPUT_DIR / "jh308_cutover.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    ownership = {}
    if args.ownership:
        payload = json.loads(args.ownership.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("ownership manifest must be a JSON object")
        ownership = {str(key): str(value) for key, value in payload.items()}
    report = run_cutover(
        args.db,
        target_user_id=args.target_user_id,
        local_history_path=args.local_history,
        ownership=ownership,
        apply=args.apply,
        backup_path=args.backup,
    )
    write_report(report, args.report)
    print(json.dumps({"apply": report["apply"], "counters": report["counters"], "report": str(args.report)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
