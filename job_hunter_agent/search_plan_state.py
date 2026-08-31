"""Persisted search-plan evidence derived from complete first-page probes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Iterable

from job_hunter_agent.database import db_conn, ensure_user_row
from job_hunter_agent.paths import get_active_user_id


def select_query_cover(term_job_keys: dict[str, set[str]]) -> list[str]:
    """Return a compact deterministic query set covering all observed direct matches.

    This is a greedy set-cover pass over the complete probe result, not an
    incremental first-query-wins decision. Ties are resolved by normalized term
    text so the result does not depend on configured query order.
    """
    uncovered: set[str] = set()
    for job_keys in term_job_keys.values():
        uncovered.update(job_keys)

    selected: list[str] = []
    remaining_terms = set(term_job_keys)
    while uncovered and remaining_terms:
        ranked = sorted(
            remaining_terms,
            key=lambda term: (
                -len(term_job_keys.get(term, set()) & uncovered),
                term.casefold(),
                term,
            ),
        )
        best_term = ranked[0]
        gained = term_job_keys.get(best_term, set()) & uncovered
        if not gained:
            break
        selected.append(best_term)
        uncovered.difference_update(gained)
        remaining_terms.remove(best_term)
    return selected


def _resolve_user_id(user_id: str | None) -> str:
    return str(user_id or get_active_user_id()).strip()


def is_search_plan_trusted(
    state: dict,
    probe_terms: Iterable[str],
    *,
    min_corroboration_samples: int,
    max_age_minutes: int,
    now: datetime | None = None,
) -> bool:
    """Return whether persisted complete-probe evidence may prune this target set.

    Search terms must match exactly. This function only trusts observed job-key
    coverage; it does not infer that two role labels are semantically related.
    """
    normalized_probe_terms = [str(term).strip() for term in probe_terms if str(term).strip()]
    remembered_probe_terms = [
        str(term).strip() for term in state.get("probe_terms", []) if str(term).strip()
    ]
    selected_terms = [
        str(term).strip() for term in state.get("selected_terms", []) if str(term).strip()
    ]
    if not normalized_probe_terms or remembered_probe_terms != normalized_probe_terms:
        return False
    if not selected_terms or not set(selected_terms).issubset(normalized_probe_terms):
        return False
    selection_counts = state.get("selection_counts")
    if not isinstance(selection_counts, dict):
        return False
    if any(
        int(selection_counts.get(term, 0)) < int(min_corroboration_samples)
        for term in selected_terms
    ):
        return False

    observed_at = str(state.get("observed_at") or "").strip()
    if not observed_at:
        return False
    try:
        observed_datetime = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if observed_datetime.tzinfo is None:
        observed_datetime = observed_datetime.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current - observed_datetime <= timedelta(minutes=max(0, int(max_age_minutes)))


def planned_search_terms(
    state: dict,
    probe_terms: Iterable[str],
    *,
    min_corroboration_samples: int,
    max_age_minutes: int,
    now: datetime | None = None,
) -> tuple[list[str], str]:
    """Choose live terms and explain whether this run is a complete probe."""
    normalized_probe_terms = [str(term).strip() for term in probe_terms if str(term).strip()]
    if is_search_plan_trusted(
        state,
        normalized_probe_terms,
        min_corroboration_samples=min_corroboration_samples,
        max_age_minutes=max_age_minutes,
        now=now,
    ):
        return [
            str(term).strip() for term in state["selected_terms"] if str(term).strip()
        ], "remembered"
    if state:
        return normalized_probe_terms, "probe_required"
    return normalized_probe_terms, "bootstrap"


def load_search_plan_state(
    *,
    source: str,
    signature: str,
    location: str,
    user_id: str | None = None,
) -> dict:
    """Load remembered plan state for one source signature and location."""
    uid = _resolve_user_id(user_id)
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT data
              FROM search_plan_state
             WHERE user_id = ? AND source = ? AND signature = ? AND location = ?
            """,
            (uid, source, signature, location),
        ).fetchone()
    if row is None:
        return {}
    payload = json.loads(row["data"])
    return payload if isinstance(payload, dict) else {}


def save_search_plan_observation(
    *,
    source: str,
    signature: str,
    location: str,
    probe_terms: Iterable[str],
    selected_terms: Iterable[str],
    coverage_job_count: int,
    term_job_counts: dict[str, int] | None = None,
    selected_coverage_job_count: int | None = None,
    observed_at: datetime | None = None,
    user_id: str | None = None,
) -> dict:
    """Persist one complete-probe observation and cumulative selection counts."""
    uid = _resolve_user_id(user_id)
    normalized_probe_terms = [str(term).strip() for term in probe_terms if str(term).strip()]
    normalized_selected_terms = [
        str(term).strip() for term in selected_terms if str(term).strip()
    ]
    previous = load_search_plan_state(
        source=source,
        signature=signature,
        location=location,
        user_id=uid,
    )
    selection_counts = {
        str(term): int(count)
        for term, count in (previous.get("selection_counts") or {}).items()
        if str(term).strip()
    }
    for term in normalized_selected_terms:
        selection_counts[term] = selection_counts.get(term, 0) + 1

    payload = {
        "sample_count": int(previous.get("sample_count") or 0) + 1,
        "probe_terms": normalized_probe_terms,
        "selected_terms": normalized_selected_terms,
        "selection_counts": selection_counts,
        "coverage_job_count": int(coverage_job_count),
        "term_job_counts": {
            str(term).strip(): int(count)
            for term, count in (term_job_counts or {}).items()
            if str(term).strip()
        },
        "selected_coverage_job_count": (
            int(selected_coverage_job_count)
            if selected_coverage_job_count is not None
            else int(coverage_job_count)
        ),
        "observed_at": (observed_at or datetime.now(timezone.utc)).isoformat(),
    }
    ensure_user_row(uid)
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO search_plan_state (user_id, source, signature, location, data, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, source, signature, location) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (uid, source, signature, location, json.dumps(payload, ensure_ascii=False)),
        )
    return payload
