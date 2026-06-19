"""Tests for job review pipeline."""

import json
import logging

from job_hunter_agent import job_review_pipeline, source_learning
from job_hunter_agent.database import init_db
from job_hunter_agent.fit_scoring import fit_score, fit_score_breakdown
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.paths import SCORING_RULES_PATH
from job_hunter_agent.occupation_taxonomy import (
    RESULT_FAR,
    RESULT_UNCERTAIN,
    OccupationClassification,
    classify_title,
)
from job_hunter_agent.record_schema import (
    RECORD_CARD_SALARY_KEY,
    RECORD_COMPANY_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_DECISION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_ELAPSED_MS_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LOCATION_KEY,
    RECORD_ONET_CLASSIFICATION_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_SALARY_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_TYPE_KEY,
)


def _review_profile():
    return {
        "candidate_capabilities": [],
        "dominant_signal_clusters": [],
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_sector": False,
            "engagement_type": [],
            "preferred_contract_months": 0,
            "short_contract_months": 0,
        },
        "must_not_require_skills": [],
        "preference_weights": {},
        "salary_preferences": {},
        "scoring_rules": json.loads(SCORING_RULES_PATH.read_text(encoding="utf-8")),
    }


def _review_context(source_name: str):
    return ReviewPipelineContext(
        profile=_review_profile(),
        job_history={},
        audit_rows=[],
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        seen_job_keys=set(),
        seen_urls=set(),
        run_iso="2026-05-26T00:00:00+10:00",
        date_range_days=30,
        source_name=source_name,
    )


def _base_record(source: str, description_source: str, work_mode_source: str) -> dict:
    return {
        RECORD_JOB_KEY: f"{source}-job-1",
        RECORD_TITLE_KEY: "Business Analyst",
        RECORD_COMPANY_KEY: "Acme",
        RECORD_URL_KEY: f"https://example.com/{source}/job/1",
        RECORD_LOCATION_KEY: "Sydney NSW",
        RECORD_WORK_MODE_KEY: "Hybrid",
        RECORD_WORK_TYPE_KEY: "Full Time",
        RECORD_CARD_SALARY_KEY: "N/A",
        RECORD_DETAILS_TEXT_KEY: "Business analyst role supporting delivery and stakeholders.",
        RECORD_DETAILS_STATUS_KEY: "ok",
        RECORD_DESCRIPTION_SOURCE_KEY: description_source,
        RECORD_POSTED_AGE_DAYS_KEY: 1,
        "source": source,
        "source_metadata": {
            "source": source,
            "raw_source_fields": {"source": source},
        },
        "work_mode_source": work_mode_source,
        "work_mode_evidence": "card text",
        "work_mode_needs_review": False,
        "teaser": "Business analyst role",
        "posted": "Today",
    }


def _patch_llm_review_path(monkeypatch, payload):
    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": True, "reason": "OK"},
    )
    monkeypatch.setattr(
        job_review_pipeline, "passes_quick_card_filters", lambda **kwargs: (True, "OK")
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_content_filters",
        lambda details_text, card_location, title_reason: (True, "OK"),
    )
    monkeypatch.setattr(job_review_pipeline, "find_hard_block_matches", lambda text, terms=None: [])
    monkeypatch.setattr(
        job_review_pipeline, "passes_preference_filters", lambda record, profile: (True, "OK")
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_fit_highlights", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "build_risk_and_missing_profile_support",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], []),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "deterministic_review_outcome",
        lambda record, profile, fit_highlights, missing_profile_support, soft_risk_reasons: None,
    )
    monkeypatch.setattr(
        job_review_pipeline, "resolve_llm_review_payload", lambda record, llm_cache: payload
    )
    monkeypatch.setattr(
        job_review_pipeline, "register_pending_learning_signals", lambda signals: None
    )
    monkeypatch.setattr(
        job_review_pipeline, "detect_competitive_signals", lambda details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "reviewed_signal_matches_for_text", lambda details_text: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "evaluate_competitive_signal_alignment", lambda signal, profile: signal
    )
    monkeypatch.setattr(
        job_review_pipeline, "extract_skill_observations", lambda record, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_ad_learning_signals", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_role_summary", lambda record, details_text, profile: "summary"
    )


def test_review_outcome_is_source_neutral_for_equivalent_normalized_jobs(monkeypatch):
    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": True, "reason": "OK"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_quick_card_filters",
        lambda **kwargs: (True, "OK"),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_content_filters",
        lambda details_text, card_location, title_reason: (True, "OK"),
    )
    monkeypatch.setattr(job_review_pipeline, "find_hard_block_matches", lambda text, terms=None: [])
    monkeypatch.setattr(
        job_review_pipeline, "passes_preference_filters", lambda record, profile: (True, "OK")
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_fit_highlights", lambda record, details_text, profile: ["fit"]
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "build_risk_and_missing_profile_support",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], []),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "deterministic_review_outcome",
        lambda record, profile, fit_highlights, missing_profile_support, soft_risk_reasons: {
            "decision": "KEEP",
            "grade": "SOLID",
        },
    )
    monkeypatch.setattr(job_review_pipeline, "llm_extract_job_requirements", lambda text: [])
    monkeypatch.setattr(
        job_review_pipeline, "register_pending_learning_signals", lambda signals: None
    )
    monkeypatch.setattr(
        job_review_pipeline, "detect_competitive_signals", lambda details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "reviewed_signal_matches_for_text", lambda details_text: []
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "evaluate_competitive_signal_alignment",
        lambda signal, profile: signal,
    )
    monkeypatch.setattr(
        job_review_pipeline, "extract_skill_observations", lambda record, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_ad_learning_signals", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "preferred_salary_display",
        lambda *values: next((value for value in values if value and value != "N/A"), "N/A"),
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_role_summary", lambda record, details_text, profile: "summary"
    )
    monkeypatch.setattr(source_learning, "register_signals", lambda items, category="": None)
    monkeypatch.setattr(
        source_learning,
        "find_hard_block_matches",
        lambda details_text, terms=None: [],
    )
    monkeypatch.setattr("job_hunter_agent.fit_scoring.load_profile", _review_profile)

    seek_record = _base_record("seek", "seek_detail", "card")
    linkedin_record = _base_record("linkedin", "linkedin_full_description", "description")

    seek_pre_outcome, seek_record, _, seek_should_fetch = review_pre_detail_normalized_job(
        seek_record, _review_context("SEEK")
    )
    linkedin_pre_outcome, linkedin_record, _, linkedin_should_fetch = (
        review_pre_detail_normalized_job(
            linkedin_record,
            _review_context("LinkedIn"),
        )
    )
    seek_outcome, seek_record, _ = review_post_detail_normalized_job(
        seek_record, _review_context("SEEK")
    )
    linkedin_outcome, linkedin_record, _ = review_post_detail_normalized_job(
        linkedin_record, _review_context("LinkedIn")
    )

    outcome_keys = [
        RECORD_DECISION_KEY,
        RECORD_REJECT_REASON_KEY,
        RECORD_TITLE_REASON_KEY,
        RECORD_CONTENT_REASON_KEY,
        RECORD_HARD_BLOCK_REASONS_KEY,
        RECORD_LLM_DECISION_KEY,
        RECORD_LLM_FIT_GRADE_KEY,
        "review_source",
    ]
    assert seek_pre_outcome["decision"] == "KEEP"
    assert linkedin_pre_outcome["decision"] == "KEEP"
    assert seek_should_fetch is True
    assert linkedin_should_fetch is True
    assert {key: seek_outcome[key] for key in outcome_keys} == {
        key: linkedin_outcome[key] for key in outcome_keys
    }
    assert fit_score(seek_record, _review_profile()) == fit_score(
        linkedin_record, _review_profile()
    )
    assert fit_score_breakdown(seek_record, _review_profile()) == fit_score_breakdown(
        linkedin_record, _review_profile()
    )


def test_hard_block_rejection_registers_learning_signal(monkeypatch):
    registrations = []
    profile = _review_profile()
    profile["must_not_require_skills"] = ["SAP"]

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": True, "reason": "OK"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_quick_card_filters",
        lambda **kwargs: (True, "OK"),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_content_filters",
        lambda details_text, card_location, title_reason: (False, "DESC_HARD_BLOCK_RULE:sap"),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "find_hard_block_matches",
        lambda details_text, terms=None: [
            {
                "value": "demonstrated experience in {term}",
                "matched_term": "SAP",
                "context": "must have SAP experience",
            }
        ],
    )
    monkeypatch.setattr(
        source_learning,
        "find_hard_block_matches",
        lambda details_text, terms=None: [
            {
                "value": "demonstrated experience in {term}",
                "matched_term": "SAP",
                "context": "must have SAP experience",
            }
        ],
    )
    monkeypatch.setattr(
        source_learning,
        "register_signals",
        lambda items, category="": registrations.append((items, category)),
    )

    record = _base_record("seek", "seek_detail", "card")
    outcome, updated_record, skill_observations = review_post_detail_normalized_job(
        record,
        ReviewPipelineContext(
            profile=profile,
            job_history={},
            audit_rows=[],
            llm_cache={},
            applied_job_keys=set(),
            hidden_job_keys=set(),
            seen_job_keys=set(),
            run_iso="2026-05-26T00:00:00+10:00",
            date_range_days=30,
            source_name="SEEK",
        ),
    )

    assert outcome[RECORD_DECISION_KEY] == "REJECT"
    assert outcome[RECORD_REJECT_REASON_KEY] == "DESC_HARD_BLOCK_RULE:sap"
    assert updated_record[RECORD_HARD_BLOCK_REASONS_KEY] == ["demonstrated experience in {term}"]
    assert skill_observations == []
    assert registrations == [
        (
            [
                {
                    "signal": "demonstrated experience in {term}",
                    "suggested_category": "hard_blocker_pattern",
                    "original_texts": ["must have SAP experience"],
                }
            ],
            "",
        )
    ]


def test_seek_card_review_skips_detail_fetch_when_onet_confirms_far_occupation(monkeypatch):
    record = _base_record("seek", "seek_detail", "card")
    context = _review_context("SEEK")

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": False, "reason": "TITLE_NOT_TARGET"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "_onet_classify_title",
        lambda title, profile: OccupationClassification(
            result=RESULT_FAR, matched_occupation_code="35-1011.00", confidence=0.9, reason="far"
        ),
    )

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert outcome["decision"] == "REJECT"
    assert updated_record[RECORD_REJECT_REASON_KEY] == "ONET_FAR_OCCUPATION"
    assert updated_record[RECORD_ONET_CLASSIFICATION_KEY]["matched_occupation_code"] == "35-1011.00"
    assert should_fetch is False, "detail fetch must not happen when O*NET confirms far occupation"


def test_title_not_target_continues_to_description_when_onet_uncertain(monkeypatch):
    record = _base_record("seek", "seek_detail", "card")
    context = _review_context("SEEK")

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": False, "reason": "TITLE_NOT_TARGET"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "_onet_classify_title",
        lambda title, profile: OccupationClassification(
            result=RESULT_UNCERTAIN, matched_occupation_code=None, confidence=0.0, reason="no_match"
        ),
    )

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is True, "uncertain O*NET result must not block description fetch"
    assert updated_record[RECORD_TITLE_REASON_KEY] == "TITLE_POTENTIAL_MATCH"
    assert updated_record[RECORD_ONET_CLASSIFICATION_KEY]["result"] == RESULT_UNCERTAIN


def test_title_not_target_stops_before_detail_fetch_when_onet_is_far(monkeypatch, tmp_path):
    record = _base_record("seek", "seek_detail", "card")
    context = _review_context("SEEK")
    db_path = tmp_path / "test.db"
    init_db(db_path)
    project_delivery_profile = {
        "target_occupation_queries": ["project manager", "project delivery manager"],
    }
    finance_index = {
        "project manager": [
            {
                "occupation_code": "13-1082.00",
                "occupation_title": "Project Management Specialists",
                "source": "occupation_title",
            }
        ],
        "project delivery manager": [
            {
                "occupation_code": "13-1082.00",
                "occupation_title": "Project Management Specialists",
                "matched_title": "Project Delivery Manager",
                "source": "alternate_title",
            }
        ],
        "senior accountant": [
            {
                "occupation_code": "13-2011.00",
                "occupation_title": "Accountants and Auditors",
                "matched_title": "Senior Accountant",
                "source": "alternate_title",
            }
        ],
    }

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": False, "reason": "TITLE_NOT_TARGET"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "_onet_classify_title",
        lambda title, profile: classify_title(
            title, project_delivery_profile, db_path=db_path, _index=finance_index
        ),
    )
    record[RECORD_TITLE_KEY] = "Senior Accountant"

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is False
    assert outcome[RECORD_DECISION_KEY] == "REJECT"
    assert updated_record[RECORD_REJECT_REASON_KEY] == "ONET_FAR_OCCUPATION"
    assert updated_record[RECORD_ONET_CLASSIFICATION_KEY]["result"] == RESULT_FAR


def test_pipeline_logs_job_centric_block_format(caplog, monkeypatch):
    """Pipeline emits a job-centric block: header at CARD_SEEN, status lines, close at FINAL_DECISION."""
    record = _base_record("seek", "seek_detail", "card")
    context = _review_context("SEEK")

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": False, "reason": "TITLE_NOT_TARGET"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "_onet_classify_title",
        lambda title, profile: OccupationClassification(
            result=RESULT_UNCERTAIN, matched_occupation_code=None, confidence=0.0, reason="no_match"
        ),
    )

    with caplog.at_level(logging.INFO, logger="job_hunter_agent.job_review_pipeline"):
        review_pre_detail_normalized_job(record, context)

    messages = [r.message for r in caplog.records]

    header = next((m for m in messages if "Business Analyst" in m and "Acme" in m), None)
    assert header is not None, "expected a job header line with title and company"

    title_note = next(
        (
            m
            for m in messages
            if "title not in your target roles" in m or "will read description" in m
        ),
        None,
    )
    assert title_note is not None, "expected a title status line"

    # ONET_DECISION with FETCH_DETAILS is the pipeline's structured signal that
    # description fetch will proceed (replaces the removed "→ fetching description..." line).
    onet_line = next((m for m in messages if "ONET_DECISION" in m and "FETCH_DETAILS" in m), None)
    assert onet_line is not None, "expected ONET_DECISION log with FETCH_DETAILS outcome"


def test_duplicate_job_key_is_skipped_before_detail_fetch(monkeypatch):
    record_one = _base_record("seek", "seek_detail", "card")
    record_two = _base_record("seek", "seek_detail", "card")
    record_two[RECORD_URL_KEY] = "https://example.com/seek/job/2"
    context = _review_context("SEEK")

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": True, "reason": "OK"},
    )

    first_outcome, _, first_obs, first_should_fetch = review_pre_detail_normalized_job(
        record_one, context
    )
    second_outcome, _, second_obs, second_should_fetch = review_pre_detail_normalized_job(
        record_two, context
    )

    assert first_should_fetch is True, "first record should proceed to detail fetch"
    assert second_outcome["decision"] == "SKIP"
    assert record_two[RECORD_REJECT_REASON_KEY] == "DUPLICATE_JOB_KEY"
    assert second_should_fetch is False
    assert first_obs == []
    assert second_obs == []


def test_linkedin_salary_is_preserved_by_post_detail_review(monkeypatch):
    record = _base_record("linkedin", "linkedin_full_description", "description")
    record[RECORD_SALARY_KEY] = "AUD 120k"
    record[RECORD_DETAILS_TEXT_KEY] = "Business analyst role supporting delivery and stakeholders."
    record[RECORD_TITLE_REASON_KEY] = "OK"

    monkeypatch.setattr(
        job_review_pipeline,
        "passes_content_filters",
        lambda details_text, card_location, title_reason: (True, "OK"),
    )
    monkeypatch.setattr(job_review_pipeline, "find_hard_block_matches", lambda text, terms=None: [])
    monkeypatch.setattr(
        job_review_pipeline, "passes_preference_filters", lambda record, profile: (True, "OK")
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_fit_highlights", lambda record, details_text, profile: ["fit"]
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "build_risk_and_missing_profile_support",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], []),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "deterministic_review_outcome",
        lambda record, profile, fit_highlights, missing_profile_support, soft_risk_reasons: {
            "decision": "KEEP",
            "grade": "SOLID",
        },
    )
    monkeypatch.setattr(job_review_pipeline, "llm_extract_job_requirements", lambda text: [])
    monkeypatch.setattr(
        job_review_pipeline, "register_pending_learning_signals", lambda signals: None
    )
    monkeypatch.setattr(
        job_review_pipeline, "detect_competitive_signals", lambda details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "reviewed_signal_matches_for_text", lambda details_text: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "evaluate_competitive_signal_alignment", lambda signal, profile: signal
    )
    monkeypatch.setattr(
        job_review_pipeline, "extract_skill_observations", lambda record, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_ad_learning_signals", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_role_summary", lambda record, details_text, profile: "summary"
    )

    outcome, updated_record, _ = review_post_detail_normalized_job(
        record,
        ReviewPipelineContext(
            profile=_review_profile(),
            job_history={},
            audit_rows=[],
            llm_cache={},
            applied_job_keys=set(),
            hidden_job_keys=set(),
            seen_job_keys=set(),
            seen_urls=set(),
            run_iso="2026-05-26T00:00:00+10:00",
            date_range_days=30,
            source_name="LinkedIn",
        ),
    )

    assert outcome["decision"] == "KEEP"
    assert updated_record[RECORD_SALARY_KEY] == "AUD 120k"


def test_llm_review_fields_persist_on_record(monkeypatch):
    payload = {
        "fit_review": {"decision": "KEEP", "grade": "STRONG"},
        "debug_reason": "Strong requirement coverage with capability support.",
        "job_requirements": ["Stakeholder engagement"],
        "requirement_coverage": [
            {
                "requirement": "Stakeholder engagement",
                "status": "supported",
                "capability_name": "Stakeholder Engagement",
                "matched_job_text": "work with stakeholders",
                "profile_support": ["stakeholder management"],
            },
        ],
        "llm_cost_usd": 0.0123,
    }
    _patch_llm_review_path(monkeypatch, payload)

    record = _base_record("seek", "seek_detail", "card")
    outcome, updated_record, _ = review_post_detail_normalized_job(record, _review_context("SEEK"))

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record[RECORD_LLM_ELAPSED_MS_KEY] is not None
    assert updated_record[RECORD_LLM_COST_USD_KEY] == 0.0123


# ── observability log events ──────────────────────────────────────────────────


def test_onet_decision_log_emitted_for_title_not_target(caplog, monkeypatch):
    """[PIPELINE][ONET_DECISION] must be logged for every TITLE_NOT_TARGET path."""
    record = _base_record("seek", "seek_detail", "card")
    context = _review_context("SEEK")

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": False, "reason": "TITLE_NOT_TARGET"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "_onet_classify_title",
        lambda title, profile: OccupationClassification(
            result=RESULT_FAR, matched_occupation_code="35-1011.00", confidence=0.9, reason="far"
        ),
    )

    with caplog.at_level(logging.INFO, logger="job_hunter_agent.job_review_pipeline"):
        review_pre_detail_normalized_job(record, context)

    messages = [r.message for r in caplog.records]
    onet_log = next((m for m in messages if "ONET_DECISION" in m), None)
    assert onet_log is not None, "expected [PIPELINE][ONET_DECISION] log"
    assert "TITLE_NOT_TARGET" in onet_log
    assert "onet_response" in onet_log
    assert "outside your target roles" in onet_log
    assert "35-1011.00" in onet_log
    assert "REJECT" in onet_log
    assert "elapsed_ms" in onet_log


def test_llm_call_error_log_emitted_with_structured_fields(caplog, monkeypatch):
    """[PIPELINE][LLM_CALL_ERROR] must include purpose, model, error_type, status_code, elapsed_ms."""
    from job_hunter_agent.llm_gate import LLMCallError

    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_TITLE_REASON_KEY] = "OK"

    monkeypatch.setattr(
        job_review_pipeline,
        "passes_content_filters",
        lambda details_text, card_location, title_reason: (True, "OK"),
    )
    monkeypatch.setattr(job_review_pipeline, "find_hard_block_matches", lambda text, terms=None: [])
    monkeypatch.setattr(
        job_review_pipeline, "passes_preference_filters", lambda record, profile: (True, "OK")
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_fit_highlights", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "build_risk_and_missing_profile_support",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], []),
    )
    monkeypatch.setattr(
        job_review_pipeline, "detect_competitive_signals", lambda details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "reviewed_signal_matches_for_text", lambda details_text: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "evaluate_competitive_signal_alignment", lambda signal, profile: signal
    )
    monkeypatch.setattr(
        job_review_pipeline, "extract_skill_observations", lambda record, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_ad_learning_signals", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_role_summary", lambda record, details_text, profile: "summary"
    )

    def _raise_llm_error(record, profile, llm_cache):
        raise LLMCallError(
            "HTTP 520 — unknown error",
            purpose="fit_review",
            model="gpt-4o-mini",
            status_code=520,
        )

    monkeypatch.setattr(job_review_pipeline, "_evaluate_job_fit", _raise_llm_error)

    with caplog.at_level(logging.ERROR, logger="job_hunter_agent.job_review_pipeline"):
        outcome, updated_record, _ = review_post_detail_normalized_job(
            record,
            ReviewPipelineContext(
                profile=_review_profile(),
                job_history={},
                audit_rows=[],
                llm_cache={},
                applied_job_keys=set(),
                hidden_job_keys=set(),
                run_iso="2026-05-26T00:00:00+10:00",
                date_range_days=30,
                source_name="SEEK",
            ),
        )

    assert outcome["decision"] == "REJECT"
    assert outcome["reject_reason"] == "LLM_ERROR"

    error_logs = [r.message for r in caplog.records if r.levelno >= logging.ERROR]
    error_log = next((m for m in error_logs if "LLM_CALL_ERROR" in m), None)
    assert error_log is not None, "expected [PIPELINE][LLM_CALL_ERROR] error log"
    assert "fit_review" in error_log
    assert "gpt-4o-mini" in error_log
    assert "520" in error_log
    assert "elapsed_ms" in error_log


def test_llm_missing_provider_key_is_reported_as_unavailable(caplog, monkeypatch):
    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_TITLE_REASON_KEY] = "OK"

    monkeypatch.setattr(
        job_review_pipeline,
        "passes_content_filters",
        lambda details_text, card_location, title_reason: (True, "OK"),
    )
    monkeypatch.setattr(job_review_pipeline, "find_hard_block_matches", lambda text, terms=None: [])
    monkeypatch.setattr(
        job_review_pipeline, "passes_preference_filters", lambda record, profile: (True, "OK")
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_fit_highlights", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "build_risk_and_missing_profile_support",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], []),
    )
    monkeypatch.setattr(
        job_review_pipeline, "deterministic_review_outcome", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "resolve_llm_review_payload",
        lambda record, llm_cache: (_ for _ in ()).throw(
            RuntimeError("LLM review requested but no provider key is configured")
        ),
    )
    monkeypatch.setattr(
        job_review_pipeline, "register_pending_learning_signals", lambda signals: None
    )
    monkeypatch.setattr(
        job_review_pipeline, "detect_competitive_signals", lambda details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "reviewed_signal_matches_for_text", lambda details_text: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "evaluate_competitive_signal_alignment", lambda signal, profile: signal
    )
    monkeypatch.setattr(
        job_review_pipeline, "extract_skill_observations", lambda record, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_ad_learning_signals", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_role_summary", lambda record, details_text, profile: "summary"
    )

    with caplog.at_level(logging.WARNING, logger="job_hunter_agent.job_review_pipeline"):
        outcome, updated_record, _ = review_post_detail_normalized_job(
            record,
            ReviewPipelineContext(
                profile=_review_profile(),
                job_history={},
                audit_rows=[],
                llm_cache={},
                applied_job_keys=set(),
                hidden_job_keys=set(),
                run_iso="2026-05-26T00:00:00+10:00",
                date_range_days=30,
                source_name="SEEK",
            ),
        )

    assert outcome["decision"] == "REJECT"
    assert outcome["reject_reason"] == "LLM_UNAVAILABLE"

    warning_logs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    warning_log = next((m for m in warning_logs if "LLM_CALL_ERROR" in m), None)
    assert warning_log is not None, "expected [PIPELINE][LLM_CALL_ERROR] warning log"
    assert "no provider key is configured" in warning_log
    assert "error_type" in warning_log


def _patch_review_post_detail_for_work_type_assertions(monkeypatch, expected_work_type):
    def _assert_inferred_work_type(record, profile):
        actual_work_type = record[RECORD_WORK_TYPE_KEY]
        assert actual_work_type == expected_work_type, (
            f"expected {expected_work_type}, got {actual_work_type}"
        )
        return True, "OK"

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": True, "reason": "OK"},
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_quick_card_filters",
        lambda **kwargs: (True, "OK"),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_content_filters",
        lambda details_text, card_location, title_reason: (True, "OK"),
    )
    monkeypatch.setattr(job_review_pipeline, "find_hard_block_matches", lambda text, terms=None: [])
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_preference_filters",
        _assert_inferred_work_type,
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_fit_highlights", lambda record, details_text, profile: ["fit"]
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "build_risk_and_missing_profile_support",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], []),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "deterministic_review_outcome",
        lambda record, profile, fit_highlights, missing_profile_support, soft_risk_reasons: {
            "decision": "KEEP",
            "grade": "SOLID",
        },
    )
    monkeypatch.setattr(job_review_pipeline, "llm_extract_job_requirements", lambda text: [])
    monkeypatch.setattr(
        job_review_pipeline, "register_pending_learning_signals", lambda signals: None
    )
    monkeypatch.setattr(
        job_review_pipeline, "detect_competitive_signals", lambda details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "reviewed_signal_matches_for_text", lambda details_text: []
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "evaluate_competitive_signal_alignment",
        lambda signal, profile: signal,
    )
    monkeypatch.setattr(
        job_review_pipeline, "extract_skill_observations", lambda record, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_ad_learning_signals", lambda record, details_text, profile: []
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "preferred_salary_display",
        lambda *values: next((value for value in values if value and value != "N/A"), "N/A"),
    )
    monkeypatch.setattr(
        job_review_pipeline, "build_role_summary", lambda record, details_text, profile: "summary"
    )
    monkeypatch.setattr(source_learning, "register_signals", lambda items, category="": None)
    monkeypatch.setattr(
        source_learning,
        "find_hard_block_matches",
        lambda details_text, terms=None: [],
    )
    monkeypatch.setattr("job_hunter_agent.fit_scoring.load_profile", _review_profile)


def test_full_time_without_contract_keywords_infers_permanent_before_preference_filters(
    monkeypatch,
):
    _patch_review_post_detail_for_work_type_assertions(monkeypatch, "Permanent")

    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_DETAILS_TEXT_KEY] = "This role is full time and supports business delivery."

    outcome, updated_record, _ = review_post_detail_normalized_job(record, _review_context("SEEK"))

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record[RECORD_WORK_TYPE_KEY] == "Permanent"


def test_full_time_12_month_contract_infers_ftc_before_preference_filters(monkeypatch):
    _patch_review_post_detail_for_work_type_assertions(monkeypatch, "Full Time Contract")

    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_DETAILS_TEXT_KEY] = "This is a full time 12 month contract role."

    outcome, updated_record, _ = review_post_detail_normalized_job(record, _review_context("SEEK"))

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record[RECORD_WORK_TYPE_KEY] == "Full Time Contract"
