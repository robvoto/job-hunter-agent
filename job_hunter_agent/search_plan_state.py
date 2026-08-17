"""Persisted search-plan evidence derived from complete first-page probes."""

from __future__ import annotations

import json
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
