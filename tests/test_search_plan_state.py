"""Tests for remembered search-plan selection and persistence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from job_hunter_agent.database import ensure_user_row, init_db
from job_hunter_agent.search_plan_state import (
    load_search_plan_state,
    save_search_plan_observation,
    select_query_cover,
)


def test_select_query_cover_uses_complete_probe_sets_not_input_order():
    first_order = {
        "Senior Systems Analyst": {"job-1", "job-2"},
        "Technical Business Analyst": {"job-1", "job-2", "job-3"},
        "Scrum Master": {"job-4"},
        "Business Analyst": {"job-1"},
    }
    reverse_order = dict(reversed(list(first_order.items())))

    assert select_query_cover(first_order) == ["Technical Business Analyst", "Scrum Master"]
    assert select_query_cover(reverse_order) == ["Technical Business Analyst", "Scrum Master"]


def test_search_plan_state_remembers_selection_counts_across_runs(tmp_path, monkeypatch):
    db = tmp_path / "job_hunter.db"
    monkeypatch.setenv("JOB_HUNTER_DB_PATH", str(db))
    init_db(db)
    ensure_user_row("user-1", db_path=db)

    first = save_search_plan_observation(
        source="seek",
        signature="signature-1",
        location="NSW",
        probe_terms=["Business Analyst", "Technical Business Analyst", "Scrum Master"],
        selected_terms=["Technical Business Analyst", "Scrum Master"],
        coverage_job_count=12,
        user_id="user-1",
    )
    second = save_search_plan_observation(
        source="seek",
        signature="signature-1",
        location="NSW",
        probe_terms=["Business Analyst", "Technical Business Analyst", "Scrum Master"],
        selected_terms=["Technical Business Analyst", "Scrum Master"],
        coverage_job_count=13,
        user_id="user-1",
    )

    assert first["sample_count"] == 1
    assert second["sample_count"] == 2
    assert second["selection_counts"] == {
        "Technical Business Analyst": 2,
        "Scrum Master": 2,
    }
    assert load_search_plan_state(
        source="seek",
        signature="signature-1",
        location="NSW",
        user_id="user-1",
    ) == second


def test_planned_search_terms_requires_fresh_corroborated_evidence():
    from job_hunter_agent.search_plan_state import planned_search_terms

    observed_at = datetime.now(timezone.utc)
    state = {
        "probe_terms": ["Role A", "Role B"],
        "selected_terms": ["Role A"],
        "selection_counts": {"Role A": 2},
        "observed_at": observed_at.isoformat(),
    }

    assert planned_search_terms(
        state,
        ["Role A", "Role B"],
        min_corroboration_samples=2,
        max_age_minutes=60,
        now=observed_at,
    ) == (["Role A"], "remembered")
    assert planned_search_terms(
        state,
        ["Role A", "Role B"],
        min_corroboration_samples=2,
        max_age_minutes=60,
        now=observed_at + timedelta(minutes=61),
    ) == (["Role A", "Role B"], "probe_required")
