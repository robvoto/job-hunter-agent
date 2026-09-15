"""Tests for job_hunter_agent.agent_search (JH-292)."""

from __future__ import annotations

import importlib
import json
import os

import pytest

from job_hunter_agent import agent_search, runtime_helpers, user_context
from job_hunter_agent.agent_search import (
    build_ad_hoc_profile,
    ephemeral_user_id,
    get_ad_hoc_results,
)
from job_hunter_agent.database import db_conn, init_db
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


def test_agent_search_loads_repo_environment_before_database_access(monkeypatch, tmp_path):
    db_path = tmp_path / "agent-search-startup.db"
    load_calls: list[None] = []

    def load_test_environment() -> bool:
        os.environ["JOB_HUNTER_DB_PATH"] = str(db_path)
        init_db(db_path)
        load_calls.append(None)
        return True

    try:
        with monkeypatch.context() as test_env:
            test_env.delenv("JOB_HUNTER_DB_PATH", raising=False)
            test_env.setattr(runtime_helpers, "load_repo_dotenv", load_test_environment)
            reloaded_agent_search = importlib.reload(agent_search)
            assert load_calls == [None]
            assert reloaded_agent_search.get_ad_hoc_results("fresh-user") == []
    finally:
        importlib.reload(agent_search)


def test_agent_ad_hoc_search_preserves_copied_prevalidated_capabilities(monkeypatch):
    from job_hunter_agent import llm_gate, profile_store, source_connector

    legacy_name = "Business analysis and stakeholder management"
    base_profile = _seed_base_profile()
    base_profile["candidate_capabilities"] = [{"name": legacy_name, "level": "working"}]
    profile_store.save_profile(
        base_profile,
        prevalidated_capability_names={legacy_name},
    )
    base_snapshot = json.dumps(profile_store.load_profile(), sort_keys=True)

    atomicity_calls = []
    monkeypatch.setattr(
        llm_gate,
        "llm_validate_profile_capability_atomicity",
        lambda capabilities: atomicity_calls.append(capabilities)
        or pytest.fail("copied capability must not be revalidated"),
    )
    save_calls = []
    original_save_profile = profile_store.save_profile

    def capture_ephemeral_save(profile, **kwargs):
        save_calls.append(kwargs)
        return original_save_profile(profile, **kwargs)

    monkeypatch.setattr(profile_store, "save_profile", capture_ephemeral_save)
    monkeypatch.setattr(
        source_connector,
        "scrape_jobs_direct",
        lambda **_kwargs: "mocked ad-hoc result",
    )

    result = agent_search.run_agent_ad_hoc_search(
        keywords=["business analyst"],
        base_user_id=BASE_USER_ID,
        sources=["seek"],
    )

    copied_name = profile_store.load_profile()["candidate_capabilities"][0]["name"]
    assert atomicity_calls == []
    assert save_calls == [{"prevalidated_capability_names": {copied_name}}]
    assert result["result_message"] == "mocked ad-hoc result"
    assert json.dumps(profile_store.load_profile(), sort_keys=True) == base_snapshot
