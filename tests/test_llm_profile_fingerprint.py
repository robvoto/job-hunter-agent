"""Regression tests for profile-aware LLM cache fingerprints."""

from job_hunter_agent import llm_gate, profile_store


def test_profile_fingerprint_tracks_semantic_prompt_context_not_save_timestamp(monkeypatch):
    state = {"context": "candidate-context-v1"}
    monkeypatch.setattr(llm_gate, "build_profile_prompt_context", lambda: state["context"])

    llm_gate.invalidate_profile_fingerprint_cache()
    first = llm_gate._profile_fingerprint()

    # Review-only/profile-row saves invalidate the process memo, but unchanged
    # fit context must resolve to the same persistent cache namespace.
    llm_gate.invalidate_profile_fingerprint_cache()
    assert llm_gate._profile_fingerprint() == first

    state["context"] = "candidate-context-v2"
    llm_gate.invalidate_profile_fingerprint_cache()
    assert llm_gate._profile_fingerprint() != first


def test_save_profile_invalidates_process_local_profile_fingerprint(isolated_db, monkeypatch):
    monkeypatch.setattr(llm_gate, "_profile_fingerprint_cache", "stale-process-fingerprint")

    profile_store.save_profile({**profile_store.DEFAULT_PROFILE})

    assert llm_gate._profile_fingerprint_cache is None
