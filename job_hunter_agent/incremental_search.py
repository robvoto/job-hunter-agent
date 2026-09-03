"""Conservative, persisted checkpoints for incremental source discovery.

This module owns only search-window optimisation.  The configured full
lookback and the existing learned role-query plan remain separate inputs.  A
checkpoint is trusted only after a source reports a healthy, complete run.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from job_hunter_agent.database import db_conn, ensure_user_row
from job_hunter_agent.global_settings import (
    get_incremental_search_catch_up_interval_days,
    get_incremental_search_late_discovery_threshold_days,
    get_incremental_search_overlap_days,
)
from job_hunter_agent.paths import get_active_user_id
from job_hunter_agent.record_schema import (
    RECORD_JOB_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_SEARCH_KEYWORDS_KEY,
    RECORD_SEARCH_LOCATION_KEY,
)


@dataclass(frozen=True)
class IncrementalSearchPlan:
    source: str
    signature: str
    mode: str
    reason: str
    configured_window_days: int
    effective_window_days: int
    effective_hours_old: int | None
    checkpoint_age_days: float | None
    known_job_keys: frozenset[str] = field(default_factory=frozenset)
    checkpoints: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    targets: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def is_incremental(self) -> bool:
        return self.mode == "incremental"

    def as_log_fields(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "reason": self.reason,
            "configured_lookback_days": self.configured_window_days,
            "effective_window_days": self.effective_window_days,
            "effective_hours_old": self.effective_hours_old,
            "checkpoint_age_days": (
                round(self.checkpoint_age_days, 3)
                if self.checkpoint_age_days is not None
                else None
            ),
            "known_job_keys": len(self.known_job_keys),
        }


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _target_key(source: str, target: dict[str, Any]) -> tuple[str, str]:
    term_key = "keywords" if str(source).lower() == "seek" else "search_term"
    return (
        str(target.get("location") or "").strip(),
        str(target.get(term_key) or "").strip(),
    )


def _load_state(
    *, source: str, signature: str, location: str, role_target: str, user_id: str | None = None
) -> dict[str, Any]:
    uid = str(user_id or get_active_user_id()).strip()
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT data
              FROM incremental_search_state
             WHERE user_id = ? AND source = ? AND signature = ?
               AND location = ? AND role_target = ?
            """,
            (uid, str(source).strip().lower(), signature, location, role_target),
        ).fetchone()
    if row is None:
        return {}
    try:
        payload = json.loads(row["data"])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Invalid incremental search checkpoint") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Incremental search checkpoint must contain an object")
    return payload


def load_incremental_checkpoints(
    *, source: str, signature: str, targets: Iterable[dict[str, Any]], user_id: str | None = None
) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        key: _load_state(
            source=source,
            signature=signature,
            location=key[0],
            role_target=key[1],
            user_id=user_id,
        )
        for key in {_target_key(source, target) for target in targets}
        if key[1]
    }


def plan_incremental_search(
    *,
    source: str,
    signature: str,
    targets: list[dict[str, Any]],
    configured_window_days: int,
    configured_hours_old: int | None = None,
    force_refresh: bool = False,
    now: datetime | None = None,
) -> IncrementalSearchPlan:
    """Choose a full or bounded window without changing semantic search inputs.

    Missing state, an explicit refresh, and the periodic catch-up boundary all
    select the configured full window.  Otherwise the overlap is widened to
    cover elapsed time since the oldest target checkpoint, preventing a gap
    when a run was delayed.
    """
    source_name = str(source).strip().lower()
    full_days = max(1, int(configured_window_days))
    current = _now(now)
    checkpoints = load_incremental_checkpoints(
        source=source_name, signature=signature, targets=targets
    )
    target_keys = {_target_key(source_name, target) for target in targets if _target_key(source_name, target)[1]}
    missing = [key for key in sorted(target_keys) if not checkpoints.get(key)]
    if force_refresh:
        reason = "force_refresh"
        mode = "full"
    elif missing:
        reason = "no_trustworthy_checkpoint"
        mode = "full"
    else:
        ages: list[float] = []
        catch_up_due = False
        for checkpoint in checkpoints.values():
            successful_at = str(checkpoint.get("last_successful_at") or "").strip()
            full_at = str(checkpoint.get("last_full_at") or successful_at).strip()
            try:
                successful_datetime = datetime.fromisoformat(successful_at.replace("Z", "+00:00"))
                full_datetime = datetime.fromisoformat(full_at.replace("Z", "+00:00"))
            except ValueError:
                catch_up_due = True
                continue
            if successful_datetime.tzinfo is None:
                successful_datetime = successful_datetime.replace(tzinfo=timezone.utc)
            if full_datetime.tzinfo is None:
                full_datetime = full_datetime.replace(tzinfo=timezone.utc)
            ages.append(max(0.0, (current - successful_datetime).total_seconds() / 86400))
            if (current - full_datetime).total_seconds() >= (
                get_incremental_search_catch_up_interval_days() * 86400
            ):
                catch_up_due = True
        if catch_up_due:
            reason = "periodic_catch_up"
            mode = "full"
        else:
            reason = "healthy_checkpoint"
            mode = "incremental"

    checkpoint_age = None
    if checkpoints:
        parsed_ages: list[float] = []
        for checkpoint in checkpoints.values():
            try:
                observed = datetime.fromisoformat(
                    str(checkpoint.get("last_successful_at") or "").replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            parsed_ages.append(max(0.0, (current - observed).total_seconds() / 86400))
        if parsed_ages:
            checkpoint_age = max(parsed_ages)

    if mode == "full":
        effective_days = full_days
    else:
        elapsed_days = max(1, math.ceil(checkpoint_age or 0))
        effective_days = min(
            full_days,
            max(get_incremental_search_overlap_days(), elapsed_days),
        )
    effective_hours = None
    if configured_hours_old is not None:
        full_hours = max(1, int(configured_hours_old))
        effective_hours = min(full_hours, max(1, effective_days * 24))

    known_keys: set[str] = set()
    if mode == "incremental":
        for checkpoint in checkpoints.values():
            values = checkpoint.get("known_job_keys")
            if isinstance(values, list):
                known_keys.update(str(value).strip() for value in values if str(value).strip())
    return IncrementalSearchPlan(
        source=source_name,
        signature=signature,
        mode=mode,
        reason=reason,
        configured_window_days=full_days,
        effective_window_days=effective_days,
        effective_hours_old=effective_hours,
        checkpoint_age_days=checkpoint_age,
        known_job_keys=frozenset(known_keys),
        checkpoints=checkpoints,
        targets=tuple(targets),
    )


def _records_by_target(source: str, records: Iterable[dict[str, Any]]) -> dict[tuple[str, str], set[str]]:
    result: dict[tuple[str, str], set[str]] = {}
    for record in records:
        key = str(record.get(RECORD_JOB_KEY) or "").strip()
        location = str(record.get(RECORD_SEARCH_LOCATION_KEY) or "").strip()
        term = str(record.get(RECORD_SEARCH_KEYWORDS_KEY) or "").strip()
        if key and term:
            result.setdefault((location, term), set()).add(key)
    return result


def save_incremental_checkpoints(
    plan: IncrementalSearchPlan,
    *,
    targets: list[dict[str, Any]],
    discovery_records: list[dict[str, Any]],
    completed: bool,
    run_at: datetime | None = None,
) -> dict[str, Any]:
    """Advance healthy checkpoints and return aggregate late-discovery stats."""
    if not completed:
        return {"advanced": False, "reason": "incomplete_run"}
    uid = get_active_user_id()
    ensure_user_row(uid)
    observed_at = _now(run_at).isoformat(timespec="seconds")
    records_by_target = _records_by_target(plan.source, discovery_records)
    late_threshold = get_incremental_search_late_discovery_threshold_days()
    late_age_distribution: dict[str, int] = {}
    late_count = 0
    discovery_count = 0
    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for target in targets:
        location, role_target = _target_key(plan.source, target)
        if not role_target:
            continue
        checkpoint = plan.checkpoints.get((location, role_target), {})
        previous_keys = {
            str(value).strip()
            for value in checkpoint.get("known_job_keys", [])
            if str(value).strip()
        }
        current_keys = records_by_target.get((location, role_target), set())
        known_keys = current_keys if plan.mode == "full" else previous_keys | current_keys
        target_discovery_count = 0
        target_late_count = 0
        target_late_distribution: dict[str, int] = {}
        target_records = [
            record
            for record in discovery_records
            if str(record.get(RECORD_SEARCH_LOCATION_KEY) or "").strip() == location
            and str(record.get(RECORD_SEARCH_KEYWORDS_KEY) or "").strip() == role_target
        ]
        for record in target_records:
            job_key = str(record.get(RECORD_JOB_KEY) or "").strip()
            if not job_key or job_key in previous_keys:
                continue
            discovery_count += 1
            target_discovery_count += 1
            age = record.get(RECORD_POSTED_AGE_DAYS_KEY)
            if isinstance(age, (int, float)) and age > late_threshold:
                late_count += 1
                target_late_count += 1
                bucket = str(int(math.floor(age)))
                late_age_distribution[bucket] = late_age_distribution.get(bucket, 0) + 1
                target_late_distribution[bucket] = target_late_distribution.get(bucket, 0) + 1
        prior_late = checkpoint.get("late_discovery") if isinstance(checkpoint.get("late_discovery"), dict) else {}
        prior_distribution = prior_late.get("age_distribution") if isinstance(prior_late, dict) else {}
        aggregate_distribution = {
            str(key): int(value)
            for key, value in (prior_distribution or {}).items()
            if str(key).isdigit()
        }
        for bucket, count in target_late_distribution.items():
            aggregate_distribution[bucket] = aggregate_distribution.get(bucket, 0) + count
        prior_discoveries = int(prior_late.get("discovery_count", 0) or 0) if isinstance(prior_late, dict) else 0
        prior_late_count = int(prior_late.get("late_count", 0) or 0) if isinstance(prior_late, dict) else 0
        state = {
            "source": plan.source,
            "signature": plan.signature,
            "location": location,
            "role_target": role_target,
            "last_successful_at": observed_at,
            "last_full_at": observed_at if plan.mode == "full" else checkpoint.get("last_full_at", observed_at),
            "last_mode": plan.mode,
            "known_job_keys": sorted(known_keys),
            "late_discovery": {
                "threshold_days": late_threshold,
                "discovery_count": prior_discoveries + target_discovery_count,
                "late_count": prior_late_count + target_late_count,
                "rate": round((prior_late_count + target_late_count) / max(1, prior_discoveries + target_discovery_count), 4),
                "age_distribution": aggregate_distribution,
            },
        }
        rows.append(
            (
                uid,
                plan.source,
                plan.signature,
                location,
                role_target,
                json.dumps(state, ensure_ascii=False, sort_keys=True),
                observed_at,
            )
        )
    with db_conn() as conn:
        conn.executemany(
            """
            INSERT INTO incremental_search_state
                (user_id, source, signature, location, role_target, data, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, source, signature, location, role_target) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            rows,
        )
    return {
        "advanced": True,
        "mode": plan.mode,
        "targets": len(rows),
        "new_discoveries": discovery_count,
        "late_discoveries": late_count,
        "late_discovery_rate": round(late_count / max(1, discovery_count), 4),
        "late_age_distribution": late_age_distribution,
    }
