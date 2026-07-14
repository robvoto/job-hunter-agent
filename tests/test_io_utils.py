"""Tests for I/O helpers."""

from job_hunter_agent import io_utils


def test_prune_llm_cache_for_current_profile_keeps_only_active_fingerprint(monkeypatch):
    monkeypatch.setattr("job_hunter_agent.llm_gate._profile_fingerprint", lambda: "active-fp")

    cache = {
        "active-fp:one": {"value": 1},
        "stale-fp:two": {"value": 2},
        "active-fp:three": {"value": 3},
    }

    pruned, removed = io_utils.prune_llm_cache_for_current_profile(cache)

    assert removed == 1
    assert pruned == {
        "active-fp:one": {"value": 1},
        "active-fp:three": {"value": 3},
    }
