"""Tests for job review pipeline."""

from job_hunter_agent import job_review_pipeline
import logging

from job_hunter_agent.fit_scoring import fit_score, fit_score_breakdown
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.occupation_taxonomy import OccupationClassification, RESULT_FAR, RESULT_UNCERTAIN
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
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LOCATION_KEY,
    RECORD_ONET_CLASSIFICATION_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_SALARY_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_TYPE_KEY,
)
from job_hunter_agent import source_learning
from job_hunter_agent.scrapers import seek_runner


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
        "scoring_rules": {},
    }


def _review_context(source_name: str):
    return ReviewPipelineContext(
        profile=_review_profile(),
        job_history={},
        audit_rows=[],
        llm_cache={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
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
    monkeypatch.setattr(job_review_pipeline, "passes_preference_filters", lambda record, profile: (True, "OK"))
    monkeypatch.setattr(job_review_pipeline, "build_fit_highlights", lambda record, details_text, profile: ["fit"])
    monkeypatch.setattr(
        job_review_pipeline,
        "build_risk_and_missing_evidence",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], []),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "deterministic_review_outcome",
        lambda record, profile, fit_highlights, missing_evidence, soft_risk_reasons: {"decision": "KEEP", "grade": "SOLID"},
    )
    monkeypatch.setattr(job_review_pipeline, "llm_extract_job_requirements", lambda text: [])
    monkeypatch.setattr(job_review_pipeline, "register_pending_learning_signals", lambda signals: None)
    monkeypatch.setattr(job_review_pipeline, "detect_competitive_signals", lambda details_text, profile: [])
    monkeypatch.setattr(job_review_pipeline, "reviewed_signal_matches_for_text", lambda details_text: [])
    monkeypatch.setattr(
        job_review_pipeline,
        "evaluate_competitive_signal_alignment",
        lambda signal, profile: signal,
    )
    monkeypatch.setattr(job_review_pipeline, "extract_skill_observations", lambda record, profile: [])
    monkeypatch.setattr(job_review_pipeline, "build_ad_learning_signals", lambda record, details_text, profile: [])
    monkeypatch.setattr(job_review_pipeline, "preferred_salary_display", lambda *values: next((value for value in values if value and value != "N/A"), "N/A"))
    monkeypatch.setattr(job_review_pipeline, "build_role_summary", lambda record, details_text, profile: "summary")
    monkeypatch.setattr(source_learning, "register_signals", lambda items, category="": None)
    monkeypatch.setattr(
        source_learning,
        "find_hard_block_matches",
        lambda details_text, terms=None: [],
    )
    monkeypatch.setattr("job_hunter_agent.fit_scoring.load_profile", _review_profile)

    seek_record = _base_record("seek", "seek_detail", "card")
    linkedin_record = _base_record("linkedin", "linkedin_full_description", "description")

    seek_pre_outcome, seek_record, _, seek_should_fetch = review_pre_detail_normalized_job(seek_record, _review_context("SEEK"))
    linkedin_pre_outcome, linkedin_record, _, linkedin_should_fetch = review_pre_detail_normalized_job(
        linkedin_record,
        _review_context("LinkedIn"),
    )
    seek_outcome, seek_record, _ = review_post_detail_normalized_job(seek_record, _review_context("SEEK"))
    linkedin_outcome, linkedin_record, _ = review_post_detail_normalized_job(linkedin_record, _review_context("LinkedIn"))

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
    assert {key: seek_outcome[key] for key in outcome_keys} == {key: linkedin_outcome[key] for key in outcome_keys}
    assert fit_score(seek_record, _review_profile()) == fit_score(linkedin_record, _review_profile())
    assert fit_score_breakdown(seek_record, _review_profile()) == fit_score_breakdown(linkedin_record, _review_profile())


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
    monkeypatch.setattr(source_learning, "register_signals", lambda items, category="": registrations.append((items, category)))

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
    fetch_called = []

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
    monkeypatch.setattr(
        seek_runner,
        "fetch_job_details_payload",
        lambda *args, **kwargs: fetch_called.append(True) or {},
    )

    outcome, updated_record, skill_observations = seek_runner.review_seek_card_record(
        record,
        detail_page=None,
        review_context=context,
    )

    assert outcome["decision"] == "REJECT"
    assert updated_record[RECORD_REJECT_REASON_KEY] == "ONET_FAR_OCCUPATION"
    assert updated_record[RECORD_ONET_CLASSIFICATION_KEY]["matched_occupation_code"] == "35-1011.00"
    assert fetch_called == [], "detail fetch must not be called when O*NET confirms far occupation"
    assert skill_observations == []


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


def test_pipeline_logs_render_as_column_blocks(caplog, monkeypatch):
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

    title_gate_log = next(
        record.message for record in caplog.records if "[PIPELINE][TITLE_GATE]" in record.message
    )
    assert "\n  source" in title_gate_log
    assert "\n  job_key" in title_gate_log
    assert "\n  title" in title_gate_log
    assert "\n  company" in title_gate_log


def test_seek_card_review_sets_broad_engagement_signal_before_pre_detail(monkeypatch):
    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_WORK_TYPE_KEY] = "Full Time / Contract"
    context = _review_context("SEEK")
    captured = {}

    def _pre_detail(current_record, current_context):
        captured["signals"] = list(current_record.get("job_quality_signals") or [])
        return {"decision": "REJECT", "reject_reason": "TITLE"}, current_record, [], False

    monkeypatch.setattr(seek_runner, "review_pre_detail_normalized_job", _pre_detail)
    monkeypatch.setattr(
        seek_runner,
        "_process_seek_job_details",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("detail fetch should not be called")),
    )

    seek_runner.review_seek_card_record(record, detail_page=None, review_context=context)

    assert captured["signals"]
    assert captured["signals"][0]["kind"] == "broad_engagement"


def test_duplicate_url_is_skipped_before_detail_fetch(monkeypatch):
    record = _base_record("seek", "seek_detail", "card")
    context = _review_context("SEEK")
    fetch_calls = {"count": 0}

    monkeypatch.setattr(job_review_pipeline, "analyze_title_filters", lambda title, profile: {"ok": True, "reason": "OK"})

    def _process(current_record, detail_page, review_context):
        fetch_calls["count"] += 1
        return (
            {"decision": "KEEP", "reject_reason": None},
            {**current_record, RECORD_DECISION_KEY: "KEEP"},
            [],
        )

    monkeypatch.setattr(seek_runner, "_process_seek_job_details", _process)

    first_outcome, _, first_skills = seek_runner.review_seek_card_record(record, detail_page=None, review_context=context)
    second_outcome, _, second_skills = seek_runner.review_seek_card_record(record, detail_page=None, review_context=context)

    assert first_outcome["decision"] == "KEEP"
    assert second_outcome["decision"] == "SKIP"
    assert fetch_calls["count"] == 1
    assert first_skills == []
    assert second_skills == []


def test_linkedin_salary_is_preserved_by_post_detail_review(monkeypatch):
    record = _base_record("linkedin", "linkedin_full_description", "description")
    record[RECORD_SALARY_KEY] = "AUD 120k"
    record[RECORD_DETAILS_TEXT_KEY] = "Business analyst role supporting delivery and stakeholders."
    record[RECORD_TITLE_REASON_KEY] = "OK"

    monkeypatch.setattr(job_review_pipeline, "passes_content_filters", lambda details_text, card_location, title_reason: (True, "OK"))
    monkeypatch.setattr(job_review_pipeline, "find_hard_block_matches", lambda text, terms=None: [])
    monkeypatch.setattr(job_review_pipeline, "passes_preference_filters", lambda record, profile: (True, "OK"))
    monkeypatch.setattr(job_review_pipeline, "build_fit_highlights", lambda record, details_text, profile: ["fit"])
    monkeypatch.setattr(job_review_pipeline, "build_risk_and_missing_evidence", lambda details_text, title_reason, profile, competitive_signals=None: ([], []))
    monkeypatch.setattr(job_review_pipeline, "deterministic_review_outcome", lambda record, profile, fit_highlights, missing_evidence, soft_risk_reasons: {"decision": "KEEP", "grade": "SOLID"})
    monkeypatch.setattr(job_review_pipeline, "llm_extract_job_requirements", lambda text: [])
    monkeypatch.setattr(job_review_pipeline, "register_pending_learning_signals", lambda signals: None)
    monkeypatch.setattr(job_review_pipeline, "detect_competitive_signals", lambda details_text, profile: [])
    monkeypatch.setattr(job_review_pipeline, "reviewed_signal_matches_for_text", lambda details_text: [])
    monkeypatch.setattr(job_review_pipeline, "evaluate_competitive_signal_alignment", lambda signal, profile: signal)
    monkeypatch.setattr(job_review_pipeline, "extract_skill_observations", lambda record, profile: [])
    monkeypatch.setattr(job_review_pipeline, "build_ad_learning_signals", lambda record, details_text, profile: [])
    monkeypatch.setattr(job_review_pipeline, "build_role_summary", lambda record, details_text, profile: "summary")

    outcome, updated_record, _ = review_post_detail_normalized_job(
        record,
        ReviewPipelineContext(
            profile=_review_profile(),
            job_history={},
            audit_rows=[],
            llm_cache={},
            applied_job_keys=set(),
            hidden_job_keys=set(),
            seen_urls=set(),
            run_iso="2026-05-26T00:00:00+10:00",
            date_range_days=30,
            source_name="LinkedIn",
        ),
    )

    assert outcome["decision"] == "KEEP"
    assert updated_record[RECORD_SALARY_KEY] == "AUD 120k"
