"""Regression tests for persistent pre-detail LLM title-judgment caching."""

from job_hunter_agent import io_utils, job_review_pipeline, llm_gate
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.occupation_taxonomy import RESULT_UNCERTAIN, OccupationClassification
from job_hunter_agent.record_schema import (
    RECORD_COMPANY_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_TITLE_JUDGMENT_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_TITLE_KEY,
    RECORD_URL_KEY,
)


def _context() -> ReviewPipelineContext:
    return ReviewPipelineContext(
        profile={
            "target_roles": ["business analyst"],
            "also_consider_roles": ["technical business analyst"],
            "candidate_capabilities": [{"name": "Stakeholder Management"}],
            "explore_adjacent_roles": True,
        },
        job_history={},
        audit_rows=[],
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        seen_job_keys=set(),
        seen_urls=set(),
        run_iso="2026-08-14T17:00:00+10:00",
        date_range_days=30,
        source_name="SEEK",
    )


def _record(job_key: str) -> dict:
    return {
        RECORD_JOB_KEY: job_key,
        RECORD_TITLE_KEY: "Technology Delivery Specialist",
        RECORD_COMPANY_KEY: "Acme",
        RECORD_URL_KEY: f"https://example.com/jobs/{job_key}",
        "source": "seek",
    }


def _patch_title_review_path(monkeypatch) -> None:
    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": False, "reason": "TITLE_NOT_TARGET"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "_onet_classify_title",
        lambda title, profile: OccupationClassification(
            result=RESULT_UNCERTAIN,
            matched_occupation_code=None,
            confidence=0.0,
            reason="No exact O*NET title match.",
        ),
    )
    monkeypatch.setattr(job_review_pipeline, "_log_title_classification_uncertainty", lambda *args: None)


def test_title_judgment_is_reused_from_llm_cache(monkeypatch):
    monkeypatch.setattr(llm_gate, "_profile_fingerprint", lambda: "profile-fp")
    _patch_title_review_path(monkeypatch)
    context = _context()
    calls = []

    def fake_title_judge(*args, **kwargs):
        calls.append((args, kwargs))
        return {"verdict": "no_match", "reason": "Clearly a different role."}

    monkeypatch.setattr(job_review_pipeline, "llm_judge_title", fake_title_judge)

    _, first, _, first_should_fetch = review_pre_detail_normalized_job(_record("seek-1"), context)
    _, second, _, second_should_fetch = review_pre_detail_normalized_job(_record("seek-2"), context)

    assert len(calls) == 1
    assert first_should_fetch is False
    assert second_should_fetch is False
    assert first[RECORD_REJECT_REASON_KEY] == "LLM_TITLE_NOT_TARGET"
    assert second[RECORD_REJECT_REASON_KEY] == "LLM_TITLE_NOT_TARGET"
    assert second[RECORD_LLM_TITLE_JUDGMENT_KEY] == {
        "verdict": "no_match",
        "reason": "Clearly a different role.",
    }
    assert len(context.llm_cache) == 1


def test_title_judgment_cache_key_changes_when_relevant_inputs_change(monkeypatch):
    monkeypatch.setattr(llm_gate, "_profile_fingerprint", lambda: "profile-fp")

    base = llm_gate.build_title_judgment_cache_key(
        "Technology Delivery Specialist",
        ["Business Analyst"],
        ["Technical Business Analyst"],
        ["Stakeholder Management"],
        explore_adjacent_roles=True,
    )
    changed_capability = llm_gate.build_title_judgment_cache_key(
        "Technology Delivery Specialist",
        ["Business Analyst"],
        ["Technical Business Analyst"],
        ["Cloud Engineering"],
        explore_adjacent_roles=True,
    )
    strict_a = llm_gate.build_title_judgment_cache_key(
        "Technology Delivery Specialist",
        ["Business Analyst"],
        ["Technical Business Analyst"],
        ["Stakeholder Management"],
        explore_adjacent_roles=False,
    )
    strict_b = llm_gate.build_title_judgment_cache_key(
        " technology   delivery specialist ",
        ["business analyst"],
        ["technical business analyst"],
        ["Cloud Engineering"],
        explore_adjacent_roles=False,
    )

    assert changed_capability != base
    assert strict_a == strict_b


def test_title_judgment_cache_entry_survives_current_profile_pruning(monkeypatch):
    monkeypatch.setattr(llm_gate, "_profile_fingerprint", lambda: "active-fp")
    key = llm_gate.build_title_judgment_cache_key(
        "Technology Delivery Specialist",
        ["Business Analyst"],
        [],
    )
    value = {"verdict": "uncertain", "reason": "Description needed."}

    pruned, removed = io_utils.prune_llm_cache_for_current_profile({key: value})

    assert removed == 0
    assert pruned == {key: value}
