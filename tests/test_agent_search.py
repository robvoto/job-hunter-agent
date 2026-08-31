"""Tests for job_hunter_agent.agent_search (JH-292)."""

from __future__ import annotations

import json

import pytest

from job_hunter_agent import user_context
from job_hunter_agent.agent_search import (
    build_ad_hoc_profile,
    ephemeral_user_id,
    get_ad_hoc_results,
)
from job_hunter_agent.database import db_conn
from job_hunter_agent.profile_store import load_profile, normalize_full_profile, save_profile


BASE_USER_ID = "test-real-user-1"


def _seed_base_profile():
    user_context.set_user_id(BASE_USER_ID)
    profile = normalize_full_profile(
        {
            "target_roles": ["business analyst"],
            "also_consider_roles": ["scrum master"],
            "search_settings": {
                "keywords": "business analyst",
                "locations": ["NSW"],
                "date_range_days": 7,
            },
            "salary_preferences": {"minimum_salary_yearly": 100000},
            "onboarding_complete": True,
        }
    )
    save_profile(profile)
    return profile


def test_ephemeral_user_id_is_deterministic_and_distinct():
    a = ephemeral_user_id(BASE_USER_ID)
    b = ephemeral_user_id(BASE_USER_ID)
    assert a == b
    assert a != BASE_USER_ID
    assert a.startswith(BASE_USER_ID)


def test_ephemeral_user_id_rejects_empty_base():
    with pytest.raises(ValueError):
        ephemeral_user_id("")


def test_build_ad_hoc_profile_overrides_keywords_and_salary_without_mutating_input():
    base = _seed_base_profile()
    original_json = json.dumps(base, sort_keys=True)

    override = build_ad_hoc_profile(
        base,
        keywords=["business support officer", "change analyst"],
        locations=["Sydney"],
        min_salary=0,
        sources=["seek"],
        date_range_days=3,
    )

    # base_profile must never be mutated in place.
    assert json.dumps(base, sort_keys=True) == original_json

    assert override["target_roles"] == ["business support officer", "change analyst"]
    assert override["also_consider_roles"] == []
    assert override["search_settings"]["keywords"] == "business support officer"
    assert override["search_settings"]["locations"] == ["Sydney"]
    assert override["search_settings"]["date_range_days"] == 3
    assert override["enabled_sources"] == ["seek"]
    assert override["search_settings"]["seek_enabled"] is True
    assert override["search_settings"]["linkedin_enabled"] is False
    assert override["salary_preferences"]["minimum_salary_yearly"] == 0


def test_build_ad_hoc_profile_zero_salary_means_no_minimum():
    base = _seed_base_profile()
    override = build_ad_hoc_profile(base, keywords=["any role"], min_salary=None)
    assert override["salary_preferences"]["minimum_salary_yearly"] == 0


def test_build_ad_hoc_profile_requires_keywords():
    base = _seed_base_profile()
    with pytest.raises(ValueError):
        build_ad_hoc_profile(base, keywords=[])


def test_ad_hoc_profile_persistence_does_not_touch_base_user_profile_row():
    """Core safety guarantee: writing an ad-hoc override under the ephemeral
    user_id must never change the base user's own persisted profile row."""
    _seed_base_profile()

    with db_conn() as conn:
        before = conn.execute(
            "SELECT data FROM user_profile WHERE user_id = ?", (BASE_USER_ID,)
        ).fetchone()["data"]

    override = build_ad_hoc_profile(
        load_profile(),
        keywords=["completely different role"],
        min_salary=0,
    )

    target_id = ephemeral_user_id(BASE_USER_ID)
    user_context.set_user_id(target_id)
    try:
        save_profile(override)
    finally:
        user_context.set_user_id(BASE_USER_ID)

    with db_conn() as conn:
        after = conn.execute(
            "SELECT data FROM user_profile WHERE user_id = ?", (BASE_USER_ID,)
        ).fetchone()["data"]
        ephemeral_row = conn.execute(
            "SELECT data FROM user_profile WHERE user_id = ?", (target_id,)
        ).fetchone()

    assert before == after, "base user's persisted profile row must be unchanged"
    assert ephemeral_row is not None
    ephemeral_data = json.loads(ephemeral_row["data"])
    assert ephemeral_data["target_roles"] == ["completely different role"]


def test_get_ad_hoc_results_returns_empty_list_when_no_run_has_happened():
    assert get_ad_hoc_results("user-with-no-adhoc-runs-yet") == []


def test_get_ad_hoc_results_reads_ephemeral_workspace_pool_only():
    target_id = ephemeral_user_id(BASE_USER_ID)
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO workspace_pool (user_id, data, updated_at) VALUES (?, ?, datetime('now')) "
            "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
            (target_id, json.dumps([{"title": "Test Job"}])),
        )
        conn.commit()

    results = get_ad_hoc_results(BASE_USER_ID)
    assert results == [{"title": "Test Job"}]
