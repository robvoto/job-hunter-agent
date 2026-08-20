"""Tests for job review pipeline."""

import json
import logging

from job_hunter_agent import (
    job_review_pipeline,
    llm_gate,
    occupation_taxonomy,
    source_learning,
    workspace_renderer,
)
from job_hunter_agent.database import init_db
from job_hunter_agent.filters import build_title_block_rule
from job_hunter_agent.fit_scoring import fit_score, fit_score_breakdown
from job_hunter_agent.history import update_job_history
from job_hunter_agent.job_review_pipeline import (
    ReviewPipelineContext,
    review_post_detail_normalized_job,
    review_pre_detail_normalized_job,
)
from job_hunter_agent.occupation_taxonomy import (
    RESULT_FAR,
    RESULT_UNCERTAIN,
    OccupationClassification,
    classify_title,
)
from job_hunter_agent.paths import SCORING_RULES_PATH
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EXTERNAL_APPLY,
    RECORD_APPLY_METHOD_KEY,
    RECORD_CARD_SALARY_KEY,
    RECORD_COMPANY_KEY,
    RECORD_CONTENT_REASON_KEY,
    RECORD_DECISION_EXPLANATION_KEY,
    RECORD_DECISION_KEY,
    RECORD_DESCRIPTION_SOURCE_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_DETAILS_TEXT_KEY,
    RECORD_HARD_BLOCK_REASONS_KEY,
    RECORD_IS_REPOSTED_KEY,
    RECORD_JOB_KEY,
    RECORD_LLM_COST_USD_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_ELAPSED_MS_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    RECORD_LLM_TITLE_JUDGMENT_KEY,
    RECORD_LOCATION_KEY,
    RECORD_ONET_CLASSIFICATION_KEY,
    RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY,
    RECORD_ORIGINAL_POSTED_DATE_KEY,
    RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY,
    RECORD_POSTED_AGE_DAYS_KEY,
    RECORD_POSTING_CHANNEL_EVIDENCE_KEY,
    POSTING_CHANNEL_CLASSIFIER_VERSION,
    POSTING_CHANNEL_VERSION_KEY,
    RECORD_REJECT_REASON_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
    RECORD_SALARY_KEY,
    RECORD_TITLE_KEY,
    RECORD_TITLE_REASON_KEY,
    RECORD_URL_KEY,
    RECORD_WORK_MODE_KEY,
    RECORD_WORK_TYPE_KEY,
    SOURCE_METADATA_SCHEMA_VERSION,
    SOURCE_METADATA_VERSION_KEY,
)
from job_hunter_agent.signal_schema import (
    CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW,
    LEARNING_ORIGINAL_TEXTS_KEY,
    LEARNING_SIGNAL_KEY,
    LEARNING_SUGGESTED_CATEGORY_KEY,
    LEARNING_SUGGESTED_REQUIREMENT_SUBTYPE_KEY,
    LEARNING_SUGGESTED_REQUIREMENT_TYPE_KEY,
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


def _keep_review_payload(
    requirement: str = "Stakeholder engagement",
    capability_name: str = "Stakeholder Engagement",
    matched_job_text: str = "work with stakeholders",
    profile_support: list[str] | None = None,
    grade: str = "SOLID",
    debug_reason: str = "Requirement coverage confirmed by LLM.",
) -> dict:
    return {
        "fit_review": {"decision": "KEEP", "grade": grade},
        "debug_reason": debug_reason,
        "requirement_coverage": [
            {
                "requirement": requirement,
                "importance": "required",
                "status": "supported",
                "capability_name": capability_name,
                "matched_job_text": matched_job_text,
                "profile_support": profile_support or ["stakeholder management"],
            },
        ],
        "llm_cost_usd": 0.0123,
        "llm_input_tokens": 1234,
        "llm_output_tokens": 234,
    }


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
            SOURCE_METADATA_VERSION_KEY: SOURCE_METADATA_SCHEMA_VERSION,
            "source": source,
            "raw_source_fields": {"source": source},
        },
        "work_mode_source": work_mode_source,
        "work_mode_evidence": "card text",
        "work_mode_needs_review": False,
        "teaser": "Business analyst role",
        "posted": "Today",
    }


def _render_ready_record(source: str = "seek") -> dict:
    record = _base_record(source, "jobAdDetails", "card")
    record.update(
        {
            RECORD_TITLE_REASON_KEY: "OK",
            RECORD_CONTENT_REASON_KEY: "OK",
            RECORD_LLM_FIT_GRADE_KEY: "SOLID",
            "full_description": "Business analyst role supporting delivery and stakeholders. " * 20,
            "fit_highlights": [],
        }
    )
    return record


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
        lambda details_text, card_location, title_reason, profile=None: (True, "OK"),
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
        "build_pre_review_risk_signals",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], [], []),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "deterministic_review_outcome",
        lambda record, profile, fit_highlights, missing_profile_support, soft_risk_reasons, missing_clearance_support=None: None,
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "resolve_llm_review_payload",
        lambda record, llm_cache, profile=None: payload,
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


def test_apply_source_metadata_to_record_uses_llm_for_direct_employer_when_urls_are_not_proof():
    record = _base_record("linkedin", "jobAdDetails", "card")
    record["source_metadata"] = {
        "platform": "linkedin",
        "apply_url": "https://jobs.lever.co/acme/123",
        "apply_domain": "jobs.lever.co",
        "company_profile_url": "https://acme.com.au",
        "company_profile_name": "Acme",
        "poster_company": "Acme",
        "hiring_company": "",
        "ats_source": "jobs.lever.co",
        "raw_source_fields": {
            "job_url_direct": "https://jobs.lever.co/acme/123",
            "company_url_direct": "https://acme.com.au",
        },
    }

    job_review_pipeline._apply_source_metadata_to_record(
        record,
        {
            "kind": "direct_employer",
            "confident": True,
            "evidence": "The ad describes Acme's own team and employee benefits.",
        },
    )

    channel = record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY]
    assert channel[POSTING_CHANNEL_VERSION_KEY] == POSTING_CHANNEL_CLASSIFIER_VERSION
    assert channel["kind"] == "direct_employer"
    assert channel["source"] == "llm_classifier"
    assert channel["needs_review"] is False
    assert "job_url_direct" in channel["trusted_metadata"]
    assert "company_url_direct" in channel["trusted_metadata"]
    assert "apply domain = jobs.lever.co" in channel["trusted_metadata"]
    assert "company profile link = https://acme.com.au" in channel["trusted_metadata"]
    assert channel["text_evidence"] == ["The ad describes Acme's own team and employee benefits."]

def test_apply_source_metadata_to_record_preserves_agency_recruiter_kind():
    record = _base_record("seek", "jobAdDetails", "card")
    record["source_metadata"] = {
        "platform": "seek",
        "apply_url": "",
        "apply_domain": "",
        "company_profile_url": "",
        "company_profile_name": "Recruiter Co",
        "poster_company": "Recruiter Co",
        "hiring_company": "",
        "ats_source": "",
        "raw_source_fields": {
            "recruiter_badge": "Recruiter",
        },
    }

    job_review_pipeline._apply_source_metadata_to_record(record, None)

    channel = record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY]
    assert channel["kind"] == "agency_or_recruiter"
    assert channel["source"] == "metadata_first"
    assert channel["needs_review"] is False
    assert channel[POSTING_CHANNEL_VERSION_KEY] == POSTING_CHANNEL_CLASSIFIER_VERSION
    assert "recruiter_badge" in channel["trusted_metadata"]


def test_apply_source_metadata_to_record_stores_review_signal_shape(monkeypatch):
    record = _base_record("seek", "jobAdDetails", "card")
    monkeypatch.setattr(
        job_review_pipeline,
        "infer_posting_channel",
        lambda record, llm_posting_channel: {
            POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
            "kind": "unknown",
            "source": "",
            "trusted_metadata": [],
            "text_evidence": ["our client"],
            "needs_review": True,
        },
    )

    job_review_pipeline._apply_source_metadata_to_record(
        record, {"kind": "unknown", "confident": False, "evidence": "our client"}
    )

    assert record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] == {
        POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
        "kind": "unknown",
        "source": "",
        "trusted_metadata": [],
        "text_evidence": ["our client"],
        "needs_review": True,
    }


def test_apply_source_metadata_to_record_stores_unknown_without_review_when_no_evidence(monkeypatch):
    record = _base_record("seek", "jobAdDetails", "card")
    monkeypatch.setattr(
        job_review_pipeline,
        "infer_posting_channel",
        lambda record, llm_posting_channel: {
            POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
            "kind": "unknown",
            "source": "",
            "trusted_metadata": [],
            "text_evidence": [],
            "needs_review": False,
        },
    )

    job_review_pipeline._apply_source_metadata_to_record(record, None)

    assert record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] == {
        POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
        "kind": "unknown",
        "source": "",
        "trusted_metadata": [],
        "text_evidence": [],
        "needs_review": False,
    }


def test_apply_source_metadata_to_record_does_not_treat_linkedin_publisher_as_employer():
    record = _render_ready_record("linkedin")
    record["company"] = "Aspen Medical"
    record["source_metadata"] = {
        "platform": "linkedin",
        "apply_url": "https://www.linkedin.com/jobs/view/4439784341",
        "apply_domain": "www.linkedin.com",
        "company_profile_url": "https://au.linkedin.com/company/aspen-medical-pty-ltd",
        "company_profile_name": "Aspen Medical",
        "poster_company": "Aspen Medical",
        "hiring_company": "Aspen Medical",
        "ats_source": "www.linkedin.com",
        "raw_source_fields": {
            "job_url_direct": None,
            "company_url_direct": None,
        },
    }

    job_review_pipeline._apply_source_metadata_to_record(record, None)
    html = workspace_renderer.render_job_card(record, _review_profile())

    assert "Source unclear" in html
    assert "Direct employer" not in html


def test_apply_source_metadata_to_record_then_render_job_card_shows_recruiter_badge():
    record = _render_ready_record("seek")
    record["company"] = "Recruiter Co"
    record["source_metadata"] = {
        "platform": "seek",
        "apply_url": "",
        "apply_domain": "",
        "company_profile_url": "",
        "company_profile_name": "Recruiter Co",
        "poster_company": "Recruiter Co",
        "hiring_company": "",
        "ats_source": "",
        "raw_source_fields": {
            "recruiter_badge": "Recruiter",
        },
    }

    job_review_pipeline._apply_source_metadata_to_record(record, None)
    html = workspace_renderer.render_job_card(record, _review_profile())

    assert "Agency recruiter" in html
    assert "Source unclear" not in html


def test_apply_source_metadata_to_record_then_render_job_card_shows_likely_recruiter_for_llm_signal():
    record = _render_ready_record("seek")
    llm_posting_channel = {
        "kind": "agency_or_recruiter",
        "confident": False,
        "evidence": "our client is seeking a business analyst",
    }

    job_review_pipeline._apply_source_metadata_to_record(record, llm_posting_channel)
    html = workspace_renderer.render_job_card(record, _review_profile())

    assert "Likely recruiter" in html
    assert "Source unclear" not in html


def test_apply_work_type_inference_reads_contract_signal_from_title_not_just_description():
    # Reproduces a live case: SEEK tagged the ad "Permanent" in its structured field, and
    # the only "Fixed Term" evidence is in the title — the description body never repeats it.
    record = _base_record("seek", "jobAdDetails", "card")
    record[RECORD_TITLE_KEY] = "Senior Business Analyst -Fixed Term to June 2027"
    record[RECORD_WORK_TYPE_KEY] = "Permanent"
    details_text = "Great analyst opportunity working with stakeholders across the business."

    job_review_pipeline._apply_work_type_inference(record, details_text)

    assert record[RECORD_WORK_TYPE_KEY] == "Full Time Contract"
    assert record["work_type_inference_evidence"] == "fixed term"


def test_apply_work_type_inference_permanent_with_no_signal_stays_permanent():
    record = _base_record("seek", "jobAdDetails", "card")
    record[RECORD_WORK_TYPE_KEY] = "Permanent"
    details_text = "Great analyst opportunity working with stakeholders across the business."

    job_review_pipeline._apply_work_type_inference(record, details_text)

    assert record[RECORD_WORK_TYPE_KEY] == "Permanent"


def test_review_outcome_is_source_neutral_for_equivalent_normalized_jobs(monkeypatch):
    payload = _keep_review_payload(
        requirement="Delivery governance",
        capability_name="Delivery Governance",
        matched_job_text="governance and delivery oversight",
        grade="SOLID",
        debug_reason="LLM confirmed equivalent fit for both normalized sources.",
    )
    _patch_llm_review_path(monkeypatch, payload)
    monkeypatch.setattr(
        job_review_pipeline,
        "preferred_salary_display",
        lambda *values: next((value for value in values if value and value != "N/A"), "N/A"),
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
    assert seek_outcome["review_source"] == "llm"
    assert fit_score(seek_record, _review_profile()) == fit_score(
        linkedin_record, _review_profile()
    )
    assert fit_score_breakdown(seek_record, _review_profile()) == fit_score_breakdown(
        linkedin_record, _review_profile()
    )


def test_review_pre_detail_rejects_closed_jobs_before_title_review(monkeypatch):
    record = _base_record("linkedin", "linkedin_full_description", "description")
    record[RECORD_DETAILS_TEXT_KEY] = (
        "This role is no longer accepting applications. "
        "Please do not submit a new application."
    )

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: (_ for _ in ()).throw(
            AssertionError("title analysis should not run for closed jobs")
        ),
    )

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(
        record, _review_context("LinkedIn")
    )

    assert outcome[RECORD_DECISION_KEY] == "REJECT"
    assert outcome[RECORD_REJECT_REASON_KEY] == "JOB_CLOSED"
    assert should_fetch is False
    assert updated_record[RECORD_REJECT_REASON_KEY] == "JOB_CLOSED"


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
        lambda details_text, card_location, title_reason, profile=None: (
            False,
            "DESC_HARD_BLOCK_RULE:sap",
        ),
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

    _, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is True, "uncertain O*NET result must not block description fetch"
    assert updated_record[RECORD_TITLE_REASON_KEY] == "TITLE_POTENTIAL_MATCH"
    assert updated_record[RECORD_ONET_CLASSIFICATION_KEY]["result"] == RESULT_UNCERTAIN


def test_title_not_target_logs_uncertainty_when_onet_is_uncertain(monkeypatch, tmp_path):
    record = _base_record("seek", "seek_detail", "card")
    context = _review_context("SEEK")
    context.profile["target_occupation_queries"] = ["Business Analyst"]
    uncertainty_log = tmp_path / "uncertainty.jsonl"

    monkeypatch.setattr(job_review_pipeline, "UNCERTAINTY_LOG_PATH", uncertainty_log)
    monkeypatch.setattr(
        occupation_taxonomy,
        "_load_index",
        lambda: {
            "business analyst": [
                {
                    "occupation_code": "13-1111.00",
                    "occupation_title": "Management Analysts",
                    "source": "occupation_title",
                }
            ]
        },
    )
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
    monkeypatch.setattr(job_review_pipeline, "llm_judge_title", lambda *args, **kwargs: None)

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is True
    assert updated_record[RECORD_TITLE_REASON_KEY] == "TITLE_POTENTIAL_MATCH"
    rows = [json.loads(line) for line in uncertainty_log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["reason_code"] == "TITLE_UNCLEAR"
    assert rows[0]["stage"] == "title_classification"
    assert rows[0]["job_key"] == "seek-job-1"
    assert rows[0]["raw_value"] == "Business Analyst"
    assert rows[0]["target_occupation_queries"] == ["Business Analyst"]
    assert rows[0]["target_occupation_codes"] == ["13-1111.00"]
    assert rows[0]["onet_result"] == RESULT_UNCERTAIN


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


def test_llm_title_judgment_hard_rejects_confident_no_match(monkeypatch):
    """JH-226: a confident LLM no_match verdict on a near/uncertain O*NET title is a hard reject.

    Regression case for the original false-KEEP: a title like "Business Enablement
    Coordinator" that O*NET treats as near/uncertain but is clearly not one of the
    candidate's target roles must be rejected before the expensive detail fetch.
    """
    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_TITLE_KEY] = "Business Enablement Coordinator"
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
    monkeypatch.setattr(
        job_review_pipeline,
        "llm_judge_title",
        lambda title, target_roles, secondary_roles, candidate_capabilities=None, **kwargs: {
            "verdict": "no_match",
            "reason": "Enablement/coordination role, not a target analyst or delivery role.",
        },
    )

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is False, "confident LLM no_match must skip the detail fetch"
    assert outcome[RECORD_DECISION_KEY] == "REJECT"
    assert updated_record[RECORD_REJECT_REASON_KEY] == "LLM_TITLE_NOT_TARGET"
    assert updated_record[RECORD_LLM_TITLE_JUDGMENT_KEY]["verdict"] == "no_match"

    assert (
        updated_record[RECORD_DECISION_EXPLANATION_KEY]
        == "Enablement/coordination role, not a target analyst or delivery role."
    )


def test_llm_title_judgment_uncertain_falls_through_to_detail_fetch(monkeypatch):
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
    monkeypatch.setattr(
        job_review_pipeline,
        "llm_judge_title",
        lambda title, target_roles, secondary_roles, candidate_capabilities=None, **kwargs: {
            "verdict": "uncertain",
            "reason": "Title alone does not rule the role in or out.",
        },
    )

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is True, "uncertain LLM verdict must not block description fetch"
    assert updated_record[RECORD_TITLE_REASON_KEY] == "TITLE_POTENTIAL_MATCH"
    assert updated_record[RECORD_LLM_TITLE_JUDGMENT_KEY]["verdict"] == "uncertain"


def test_unlisted_adjacent_title_uses_candidate_capabilities_and_reaches_description(monkeypatch):
    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_TITLE_KEY] = "Technology Delivery Specialist"
    context = _review_context("SEEK")
    context.profile["target_roles"] = ["business analyst"]
    context.profile["also_consider_roles"] = []
    context.profile["explore_adjacent_roles"] = True
    context.profile["candidate_capabilities"] = [
        {"name": "Business Analysis", "level": "strong"},
        {"name": "Agile Delivery Management", "level": "strong"},
        {"name": "Stakeholder Management", "level": "strong"},
    ]
    seen = {}

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

    def fake_title_judge(title, target_roles, secondary_roles, candidate_capabilities=None, **kwargs):
        seen["capabilities"] = candidate_capabilities
        return {"verdict": "uncertain", "reason": "Delivery capability makes the title plausible."}

    monkeypatch.setattr(job_review_pipeline, "llm_judge_title", fake_title_judge)

    _, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is True
    assert "Agile Delivery Management" in seen["capabilities"]
    assert updated_record[RECORD_TITLE_REASON_KEY] == "TITLE_POTENTIAL_MATCH"


def test_llm_title_judgment_match_falls_through_to_detail_fetch(monkeypatch):
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
    monkeypatch.setattr(
        job_review_pipeline,
        "llm_judge_title",
        lambda title, target_roles, secondary_roles, candidate_capabilities=None, **kwargs: {"verdict": "match", "reason": "Close variant."},
    )

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is True
    assert updated_record[RECORD_TITLE_REASON_KEY] == "TITLE_POTENTIAL_MATCH"


def test_llm_title_judgment_unavailable_falls_through_safely(monkeypatch):
    """LLM unavailable/failed (returns None) must never hard-reject — same safety net as O*NET uncertain."""
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
    monkeypatch.setattr(
        job_review_pipeline,
        "llm_judge_title",
        lambda title, target_roles, secondary_roles, candidate_capabilities=None, **kwargs: None,
    )

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is True
    assert updated_record[RECORD_TITLE_REASON_KEY] == "TITLE_POTENTIAL_MATCH"
    assert RECORD_LLM_TITLE_JUDGMENT_KEY not in updated_record


def test_pipeline_leaves_info_clear_and_stashes_curated_summary_for_the_report(
    tmp_path, monkeypatch
):
    """The pipeline logger no longer writes a curated per-job block at INFO — that
    block now only lives in output/last_run_report.log, built once at run end by
    scrape_finalize from the audit rows. INFO stays clear and the raw pipeline
    trace (title gate, ONET/LLM judgment markers) only shows up at DEBUG — this is
    what `--debug` controls in production. The record is stashed with the elapsed/
    cost fields the end-of-run report needs, and render_human_job_result produces
    the same curated block scrape_finalize will write for this job."""
    record = _base_record("apsjobs", "apsjobs_detail_page", "card")
    record[RECORD_JOB_KEY] = "apsjobs:a05oy00000pwiq1yap"
    record[RECORD_TITLE_KEY] = "ServiceNow Team Member"
    record[RECORD_COMPANY_KEY] = "Australian Federal Police"
    record[RECORD_URL_KEY] = (
        "https://www.apsjobs.gov.au/s/job-details?title=servicenow-team-member&Id=a05OY00000PWIQ1YAP"
    )
    context = _review_context("APSJOBS")
    info_log_path = tmp_path / "info.log"
    debug_log_path = tmp_path / "debug.log"

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
            reason="service platform team role, not a business analysis title",
        ),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "llm_judge_title",
        lambda title, target_roles, secondary_roles, candidate_capabilities=None, **kwargs: {
            "verdict": "no_match",
            "reason": (
                "The title suggests a general ServiceNow platform role rather than a "
                "Business Analyst, Scrum Master or consulting role."
            ),
        },
    )
    monkeypatch.setattr(job_review_pipeline, "get_source_display_label", lambda source: "APSJobs")

    pipeline_logger = logging.getLogger("job_hunter_agent.job_review_pipeline")
    old_level = pipeline_logger.level
    pipeline_logger.setLevel(logging.DEBUG)

    info_handler = logging.FileHandler(info_log_path, encoding="utf-8")
    info_handler.setLevel(logging.INFO)
    info_handler.setFormatter(logging.Formatter("%(message)s"))

    debug_handler = logging.FileHandler(debug_log_path, encoding="utf-8")
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(logging.Formatter("%(message)s"))

    pipeline_logger.addHandler(info_handler)
    pipeline_logger.addHandler(debug_handler)
    try:
        review_pre_detail_normalized_job(record, context)
    finally:
        pipeline_logger.removeHandler(info_handler)
        pipeline_logger.removeHandler(debug_handler)
        info_handler.close()
        debug_handler.close()
        pipeline_logger.setLevel(old_level)

    info_output = info_log_path.read_text(encoding="utf-8")
    debug_output = debug_log_path.read_text(encoding="utf-8")

    assert info_output == ""

    assert "PIPELINE][TITLE_GATE" in debug_output
    assert "LLM_TITLE_NOT_TARGET" in debug_output
    assert "apsjobs:a05oy00000pwiq1yap" in debug_output
    assert "PIPELINE][LLM_TITLE_JUDGMENT" in debug_output

    # The end-of-run report (output/last_run_report.log) is built from audit_rows
    # after the run, not logged live — the record must carry what it needs.
    assert record["_obs_elapsed"] != ""
    assert record[RECORD_REJECT_REASON_KEY] == "LLM_TITLE_NOT_TARGET"

    report_block = job_review_pipeline.render_human_job_result(
        record,
        decision=str(record.get(RECORD_DECISION_KEY) or ""),
        reason=str(record.get(RECORD_REJECT_REASON_KEY) or ""),
        explanation=str(record.get(RECORD_DECISION_EXPLANATION_KEY) or ""),
        elapsed=record["_obs_elapsed"],
        llm_cost=record["_obs_llm_cost"],
    )
    assert report_block.count("=" * 72) == 2
    assert "ServiceNow Team Member" in report_block
    assert "Australian Federal Police" in report_block
    assert (
        "https://www.apsjobs.gov.au/s/job-details?title=servicenow-team-member&Id=a05OY00000PWIQ1YAP"
        in report_block
    )
    assert "REJECTED" in report_block
    normalized_report_block = " ".join(report_block.split())
    assert (
        "The title suggests a general ServiceNow platform role rather than a Business Analyst, Scrum Master or consulting role."
        in normalized_report_block
    )


def test_explicit_title_reject_rule_logs_immediate_title_reject(monkeypatch, caplog):
    record = _base_record("seek", "seek_detail", "card")
    context = _review_context("SEEK")

    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": False, "reason": "TITLE_BAD_KEYWORD:sap"},
    )

    with caplog.at_level(logging.DEBUG, logger="job_hunter_agent.job_review_pipeline"):
        outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is False
    assert outcome[RECORD_DECISION_KEY] == "REJECT"
    assert updated_record[RECORD_REJECT_REASON_KEY] == "TITLE_BAD_KEYWORD:sap"
    assert "will read description" not in caplog.text
    assert "PIPELINE][TITLE_GATE" in caplog.text


def test_configured_sap_title_blocker_stops_pipeline_before_llm_or_fit_work(
    monkeypatch,
):
    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_TITLE_KEY] = "Senior SAP Business Analyst"
    context = _review_context("SEEK")
    context.profile.update(
        {
            "target_roles": ["business analyst"],
            "also_consider_roles": ["project coordinator"],
            "reject_title_rules": [build_title_block_rule("sap")],
        }
    )

    monkeypatch.setattr(
        job_review_pipeline,
        "passes_quick_card_filters",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("configured title blocker must run before card/fit work")
        ),
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "resolve_llm_review_payload",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("configured title blocker must stop before LLM review")
        ),
    )

    outcome, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is False
    assert outcome[RECORD_DECISION_KEY] == "REJECT"
    assert updated_record[RECORD_REJECT_REASON_KEY] == "TITLE_BAD_KEYWORD:sap"


def test_sap_in_description_only_does_not_trigger_clean_title_blocker(monkeypatch):
    record = _base_record("seek", "seek_detail", "card")
    record[RECORD_TITLE_KEY] = "Business Analyst"
    record[RECORD_DETAILS_TEXT_KEY] = "This role works with SAP stakeholders and delivery teams."
    context = _review_context("SEEK")
    context.profile.update(
        {
            "target_roles": ["business analyst"],
            "also_consider_roles": ["project coordinator"],
            "reject_title_rules": [build_title_block_rule("sap")],
        }
    )
    monkeypatch.setattr(
        job_review_pipeline, "passes_quick_card_filters", lambda **kwargs: (True, "OK")
    )

    _, updated_record, _, should_fetch = review_pre_detail_normalized_job(record, context)

    assert should_fetch is True
    assert updated_record[RECORD_TITLE_REASON_KEY] == "OK"


def test_external_apply_verified_repost_is_kept_and_flagged(monkeypatch):
    record = _base_record("linkedin", "jobAdDetails", "card")
    record[RECORD_TITLE_REASON_KEY] = "OK"
    record[RECORD_APPLY_METHOD_KEY] = APPLY_METHOD_EXTERNAL_APPLY
    record[RECORD_POSTED_AGE_DAYS_KEY] = 2.0
    record["source_metadata"] = {
        "apply_url": "https://jobs.example.com/apply/123",
        "raw_source_fields": {},
    }
    context = _review_context("LINKEDIN")

    _patch_llm_review_path(monkeypatch, _keep_review_payload())
    monkeypatch.setattr(
        job_review_pipeline,
        "fetch_external_html",
        lambda _url: (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","datePosted":"2026-04-24"}'
            "</script>"
        ),
    )

    outcome, updated_record, _ = review_post_detail_normalized_job(record, context)

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record.get(RECORD_REJECT_REASON_KEY) is None
    assert updated_record[RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY] == "verified"
    assert updated_record[RECORD_ORIGINAL_POSTED_DATE_KEY] == "2026-04-24"
    assert updated_record[RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY] == 32.0
    assert updated_record[RECORD_IS_REPOSTED_KEY] is True


def test_external_apply_unverified_original_date_does_not_reject(monkeypatch):
    record = _base_record("linkedin", "jobAdDetails", "card")
    record[RECORD_TITLE_REASON_KEY] = "OK"
    record[RECORD_APPLY_METHOD_KEY] = APPLY_METHOD_EXTERNAL_APPLY
    record["source_metadata"] = {
        "apply_url": "https://jobs.example.com/apply/123",
        "raw_source_fields": {},
    }
    context = _review_context("LINKEDIN")

    _patch_llm_review_path(monkeypatch, _keep_review_payload())
    monkeypatch.setattr(
        job_review_pipeline,
        "fetch_external_html",
        lambda _url: "<html><body>Apply now with your resume.</body></html>",
    )

    outcome, updated_record, _ = review_post_detail_normalized_job(record, context)

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record.get(RECORD_REJECT_REASON_KEY) is None
    assert updated_record[RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY] == "unverified"
    assert updated_record[RECORD_ORIGINAL_POSTED_DATE_KEY] == ""
    assert updated_record[RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY] is None
    assert updated_record[RECORD_IS_REPOSTED_KEY] is None


def test_external_apply_verified_same_listing_date_is_not_reposted(monkeypatch):
    record = _base_record("linkedin", "jobAdDetails", "card")
    record[RECORD_TITLE_REASON_KEY] = "OK"
    record[RECORD_APPLY_METHOD_KEY] = APPLY_METHOD_EXTERNAL_APPLY
    record[RECORD_POSTED_AGE_DAYS_KEY] = 1.0
    record["source_metadata"] = {
        "apply_url": "https://jobs.example.com/apply/123",
        "raw_source_fields": {},
    }
    context = _review_context("LINKEDIN")

    _patch_llm_review_path(monkeypatch, _keep_review_payload())
    monkeypatch.setattr(
        job_review_pipeline,
        "fetch_external_html",
        lambda _url: (
            '<script type="application/ld+json">'
            '{"@type":"JobPosting","datePosted":"2026-05-25"}'
            "</script>"
        ),
    )

    outcome, updated_record, _ = review_post_detail_normalized_job(record, context)

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record[RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY] == "verified"
    assert updated_record[RECORD_ORIGINAL_POSTED_AGE_DAYS_KEY] == 1.0
    assert updated_record[RECORD_IS_REPOSTED_KEY] is False


def _seed_reusable_kept_history(context, source: str) -> None:
    kept_record = _base_record(source, "jobAdDetails", "card")
    kept_record[RECORD_DECISION_KEY] = "KEEP"
    kept_record["llm_decision"] = "KEEP"
    kept_record["llm_fit_grade"] = "STRONG"
    kept_record[RECORD_REQUIREMENT_COVERAGE_KEY] = [
        {"requirement": "Stakeholder engagement", "importance": "required", "status": "supported"}
    ]
    kept_record[RECORD_POSTING_CHANNEL_EVIDENCE_KEY] = {
        POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
        "kind": "direct_employer",
        "source": "llm_classifier",
        "text_evidence": ["The ad describes the employer's own team."],
    }
    update_job_history(context.job_history, kept_record, context.run_iso)


def test_seek_kept_job_with_reusable_snapshot_skips_detail_fetch(monkeypatch):
    """Regression: SEEK used to be unconditionally deferred to post-detail reuse,
    forcing a browser detail fetch even for a job with a fresh, reusable KEEP
    snapshot. SEEK no longer performs the external posting-date check that
    justified deferring (see _should_check_external_posting_date), so the
    pre-detail reuse short-circuit should now apply."""
    context = _review_context("SEEK")
    _seed_reusable_kept_history(context, "seek")
    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": True, "reason": "OK"},
    )

    new_card = _base_record("seek", "jobAdDetails", "card")
    outcome, _, _, should_fetch = review_pre_detail_normalized_job(new_card, context)

    assert should_fetch is False
    assert outcome[RECORD_DECISION_KEY] == "KEEP"


def test_linkedin_external_apply_still_defers_reuse_to_post_detail(monkeypatch):
    """LinkedIn external-apply records must still defer reuse until after the
    post-detail stale-repost check runs, so a stale repost can still be caught
    even for a job that was previously kept."""
    context = _review_context("LINKEDIN")
    _seed_reusable_kept_history(context, "linkedin")
    monkeypatch.setattr(
        job_review_pipeline,
        "analyze_title_filters",
        lambda title, profile: {"ok": True, "reason": "OK"},
    )

    new_card = _base_record("linkedin", "jobAdDetails", "card")
    new_card[RECORD_APPLY_METHOD_KEY] = APPLY_METHOD_EXTERNAL_APPLY
    _, _, _, should_fetch = review_pre_detail_normalized_job(new_card, context)

    assert should_fetch is True


def test_required_eligibility_rejects_llm_keep_when_profile_fact_is_false(monkeypatch):
    record = _base_record("seek", "jobAdDetails", "card")
    record[RECORD_TITLE_REASON_KEY] = "OK"
    context = _review_context("SEEK")
    context.profile["candidate_eligibility"] = [{"name": "NV2", "value": False}]
    payload = _keep_review_payload(requirement="NV2 Security Clearance Required")
    payload["requirement_coverage"] = [
        {
            "requirement": "NV2 Security Clearance Required",
            "canonical_requirement": "NV2",
            "importance": "required",
            "requirement_type": "eligibility",
            "status": "not_shown",
            "matched_candidate_fact": "",
            "matched_job_text": "NV2 Security Clearance Required",
            "profile_support": [],
        }
    ]
    _patch_llm_review_path(monkeypatch, payload)

    outcome, updated_record, _ = review_post_detail_normalized_job(record, context)

    assert outcome[RECORD_DECISION_KEY] == "REJECT"
    assert updated_record[RECORD_REJECT_REASON_KEY] == "REQUIRED_ELIGIBILITY_FAILED"
    assert updated_record[RECORD_DECISION_EXPLANATION_KEY] == "NV2 Security Clearance Required"


def test_llm_supported_specific_capability_without_valid_candidate_fact_gets_no_pipeline_credit(
    monkeypatch,
):
    context = _review_context("SEEK")
    context.profile["candidate_capabilities"] = [
        {"name": "Business Analysis", "level": "strong"},
        {"name": "CRM", "level": "strong"},
        {"name": "Stakeholder Management", "level": "strong"},
    ]
    raw_payload = {
        "fit_review": {"decision": "KEEP", "grade": "EXCELLENT"},
        "requirement_coverage": [
            {
                "requirement": "5+ years of Salesforce configuration experience required",
                "importance": "required",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Salesforce",
                "matched_job_text": "5+ years of Salesforce configuration experience required",
                "profile_support": ["Business analysis and CRM experience."],
            }
        ],
    }
    valid_capability_names = {
        "business analysis": "Business Analysis",
        "crm": "CRM",
        "stakeholder management": "Stakeholder Management",
    }
    normalized_payload = llm_gate.normalize_llm_review_payload(
        raw_payload,
        valid_capability_names=valid_capability_names,
    )
    _patch_llm_review_path(monkeypatch, normalized_payload)

    outcome, updated_record, _ = review_post_detail_normalized_job(
        _base_record("seek", "seek_detail", "card"), context
    )

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record[RECORD_REQUIREMENT_COVERAGE_KEY][0]["status"] == "not_shown"
    assert updated_record[RECORD_REQUIREMENT_COVERAGE_KEY][0]["matched_candidate_fact"] == ""
    assert updated_record["fit_score"] == 0
    assert updated_record[RECORD_LLM_FIT_GRADE_KEY] != "EXCELLENT"


def test_preferred_eligibility_does_not_reject_llm_keep(monkeypatch):
    record = _base_record("seek", "jobAdDetails", "card")
    record[RECORD_TITLE_REASON_KEY] = "OK"
    context = _review_context("SEEK")
    context.profile["candidate_eligibility_facts"] = [{"name": "CBAP", "value": False}]
    payload = _keep_review_payload(requirement="CBAP certification is desirable")
    payload["requirement_coverage"] = [
        {
            "requirement": "CBAP certification is desirable",
            "canonical_requirement": "CBAP",
            "importance": "preferred",
            "requirement_type": "eligibility",
            "status": "mismatch",
            "matched_candidate_fact": "",
            "matched_job_text": "CBAP certification is desirable",
            "profile_support": [],
        }
    ]
    _patch_llm_review_path(monkeypatch, payload)

    outcome, updated_record, _ = review_post_detail_normalized_job(record, context)

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record.get(RECORD_REJECT_REASON_KEY) is None


def test_job_cost_preserves_micro_cost_precision(monkeypatch):
    job_key = "seek-job-micro-cost"
    job_review_pipeline._job_start_costs[job_key] = 1.0
    monkeypatch.setattr(job_review_pipeline, "get_session_cost_usd", lambda: 1.000049)

    try:
        assert job_review_pipeline._job_cost(job_key) == "$0.000049"
    finally:
        job_review_pipeline._job_start_costs.pop(job_key, None)


def test_job_time_summary_omits_llm_when_no_llm_call(monkeypatch):
    job_key = "seek-job-no-llm"
    job_review_pipeline._job_start_times[job_key] = 0.0
    job_review_pipeline._job_start_costs[job_key] = 1.0
    monkeypatch.setattr(job_review_pipeline, "_elapsed", lambda key: "0.0s")
    monkeypatch.setattr(job_review_pipeline, "get_session_cost_usd", lambda: 1.0)

    try:
        assert job_review_pipeline._job_time_summary(job_key) == "time: 0.0s"
    finally:
        job_review_pipeline._job_start_times.pop(job_key, None)
        job_review_pipeline._job_start_costs.pop(job_key, None)


def test_job_time_summary_shows_llm_when_cost_incurred(monkeypatch):
    job_key = "seek-job-with-llm"
    job_review_pipeline._job_start_times[job_key] = 0.0
    job_review_pipeline._job_start_costs[job_key] = 1.0
    monkeypatch.setattr(job_review_pipeline, "_elapsed", lambda key: "3.0s")
    monkeypatch.setattr(job_review_pipeline, "get_session_cost_usd", lambda: 1.000122)

    try:
        assert job_review_pipeline._job_time_summary(job_key) == "time: 3.0s  |  LLM: $0.000122"
    finally:
        job_review_pipeline._job_start_times.pop(job_key, None)
        job_review_pipeline._job_start_costs.pop(job_key, None)


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
    payload = _keep_review_payload()
    _patch_llm_review_path(monkeypatch, payload)
    record = _base_record("linkedin", "linkedin_full_description", "description")
    record[RECORD_SALARY_KEY] = "AUD 120k"
    record[RECORD_DETAILS_TEXT_KEY] = "Business analyst role supporting delivery and stakeholders."
    record[RECORD_TITLE_REASON_KEY] = "OK"

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
        "requirement_coverage": [
            {
                "requirement": "Stakeholder engagement",
                "importance": "required",
                "status": "supported",
                "capability_name": "Stakeholder Engagement",
                "matched_job_text": "work with stakeholders",
                "profile_support": ["stakeholder management"],
            },
        ],
        "llm_cost_usd": 0.0123,
        "llm_input_tokens": 1234,
        "llm_output_tokens": 234,
    }
    _patch_llm_review_path(monkeypatch, payload)

    record = _base_record("seek", "seek_detail", "card")
    outcome, updated_record, _ = review_post_detail_normalized_job(record, _review_context("SEEK"))

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record[RECORD_LLM_ELAPSED_MS_KEY] is not None
    assert updated_record[RECORD_LLM_COST_USD_KEY] == 0.0123
    assert updated_record[RECORD_LLM_INPUT_TOKENS_KEY] == 1234
    assert updated_record[RECORD_LLM_OUTPUT_TOKENS_KEY] == 234
    assert updated_record[RECORD_REQUIREMENT_COVERAGE_KEY]


def test_deterministic_keep_candidate_requires_full_llm_review(monkeypatch, caplog):
    payload = _keep_review_payload(
        requirement="Governance collaboration",
        capability_name="Governance Collaboration",
        matched_job_text="collaborate on governance",
        grade="STRONG",
        debug_reason="Deterministic keep candidate confirmed by full LLM review.",
    )
    _patch_llm_review_path(monkeypatch, payload)
    monkeypatch.setattr(
        job_review_pipeline,
        "deterministic_review_outcome",
        lambda record, profile, fit_highlights, missing_profile_support, soft_risk_reasons, missing_clearance_support=None: {
            "decision": "KEEP",
            "grade": "STRONG",
            "det_rule": "strong",
        },
    )

    record = _base_record("seek", "seek_detail", "card")

    with caplog.at_level(logging.DEBUG):
        outcome, updated_record, _ = review_post_detail_normalized_job(
            record, _review_context("SEEK")
        )

    assert outcome["decision"] == "KEEP"
    assert updated_record["review_source"] == "llm"
    assert updated_record[RECORD_LLM_DECISION_KEY] == "KEEP"
    assert updated_record[RECORD_REQUIREMENT_COVERAGE_KEY]
    assert any("DET_KEEP_CANDIDATE" in record.message for record in caplog.records)


def test_invalid_keep_review_without_requirement_coverage_is_rejected(monkeypatch, caplog):
    payload = {
        "fit_review": {"decision": "KEEP", "grade": "STRONG"},
        "debug_reason": "Model returned a grade without requirement coverage.",
        "requirement_coverage": [],
        "llm_cost_usd": 0.0123,
    }
    _patch_llm_review_path(monkeypatch, payload)

    record = _base_record("seek", "seek_detail", "card")

    with caplog.at_level(logging.ERROR):
        outcome, updated_record, _ = review_post_detail_normalized_job(
            record, _review_context("SEEK")
        )

    assert outcome["decision"] == "REJECT"
    assert outcome["reject_reason"] == "LLM_INVALID_REVIEW"
    assert updated_record["decision"] == "REJECT"
    assert updated_record["reject_reason"] == "LLM_INVALID_REVIEW"
    assert any("LLM_INVALID_REVIEW" in entry.message for entry in caplog.records)


def test_maybe_review_with_complete_coverage_is_not_rejected(monkeypatch, caplog):
    payload = _keep_review_payload(
        requirement="Financial markets compliance",
        capability_name="Regulatory Compliance",
        matched_job_text="not shown",
        grade="SOLID",
        debug_reason="Strong business analysis fit but required compliance experience missing.",
    )
    payload["fit_review"]["decision"] = "MAYBE"
    _patch_llm_review_path(monkeypatch, payload)

    record = _base_record("seek", "seek_detail", "card")

    with caplog.at_level(logging.ERROR):
        outcome, updated_record, _ = review_post_detail_normalized_job(
            record, _review_context("SEEK")
        )

    assert outcome["decision"] == "KEEP"
    assert updated_record[RECORD_LLM_DECISION_KEY] == "MAYBE"
    assert updated_record[RECORD_REQUIREMENT_COVERAGE_KEY]
    assert not any("LLM_INVALID_REVIEW" in entry.message for entry in caplog.records)


def test_frozen_requirement_fit_score_breakdown_is_stored_once(caplog, monkeypatch):
    """Frozen Requirement Fit % score and breakdown are stored together."""
    payload = {
        "fit_review": {"decision": "KEEP", "grade": "STRONG"},
        "debug_reason": "Strong requirement coverage with capability support.",
        "requirement_coverage": [
            {
                "requirement": "Stakeholder engagement",
                "importance": "required",
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
    with caplog.at_level(logging.INFO):
        outcome, updated_record, _ = review_post_detail_normalized_job(
            record, _review_context("SEEK")
        )

    assert outcome[RECORD_DECISION_KEY] == "KEEP"
    assert updated_record["fit_score"] == sum(
        e["value"] for e in updated_record["fit_score_breakdown"]
    )
    assert updated_record["fit_score_breakdown"][0]["section"] == "requirement_fit"


def test_fit_review_logs_shared_requirement_score_diagnostics(monkeypatch, caplog):
    payload = {
        "fit_review": {"decision": "KEEP", "grade": "STRONG"},
        "debug_reason": "Requirement coverage returned for scoring diagnostics.",
        "requirement_coverage": [
            {
                "requirement": "Stakeholder engagement",
                "importance": "required",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "Stakeholder Engagement",
                "capability_name": "Stakeholder Engagement",
                "matched_job_text": "work with stakeholders",
                "profile_support": ["Led stakeholder workshops."],
            },
            {
                "requirement": "Australian citizenship",
                "importance": "preferred",
                "requirement_type": "eligibility",
                "status": "mismatch",
                "matched_candidate_fact": "",
                "matched_job_text": "Australian citizenship required",
                "profile_support": [],
            },
        ],
        "llm_cost_usd": 0.0123,
    }
    _patch_llm_review_path(monkeypatch, payload)

    record = _base_record("seek", "seek_detail", "card")
    with caplog.at_level(logging.DEBUG, logger="job_hunter_agent.job_review_pipeline"):
        review_post_detail_normalized_job(record, _review_context("SEEK"))

    messages = [entry.message for entry in caplog.records]
    block = next(message for message in messages if "Requirement scoring" in message)
    assert "Outcome: KEEP | Grade: STRONG" in block
    assert "Eligibility gate: Not applicable | No required eligibility requirements were returned." in block
    assert "Why: Requirement coverage returned for scoring diagnostics." in block
    assert (
        "Stakeholder engagement | Required | Capability | In profile | Stakeholder Engagement"
        in block
    )
    assert "Evidence: Led stakeholder workshops." in block
    assert "Australian citizenship | Preferred | Eligibility | Not in profile" in block
    assert "Final calculation:" in block


def test_fit_review_logs_role_duration_requirement_diagnostics(monkeypatch, caplog):
    payload = {
        "fit_review": {"decision": "KEEP", "grade": "SOLID"},
        "debug_reason": "Years-on-role requirement checked against onboarding role history.",
        "requirement_coverage": [
            {
                "requirement": "Minimum 5 years experience as Business Analyst",
                "importance": "required",
                "requirement_type": "capability",
                "status": "partially_supported",
                "matched_candidate_fact": "Business Analysis",
                "capability_name": "Business Analysis",
                "matched_job_text": "Minimum 5 years experience as Business Analyst",
                "profile_support": ["Ran BA activities across delivery teams."],
                "required_experience_months": 60,
                "matched_role_experience_title": "business analyst",
                "matched_role_experience_months": 36,
                "matched_role_experience_end_year": 2024,
            }
        ],
        "llm_cost_usd": 0.0123,
    }
    _patch_llm_review_path(monkeypatch, payload)

    record = _base_record("seek", "seek_detail", "card")
    with caplog.at_level(logging.DEBUG, logger="job_hunter_agent.job_review_pipeline"):
        review_post_detail_normalized_job(record, _review_context("SEEK"))

    messages = [entry.message for entry in caplog.records]
    block = next(message for message in messages if "Requirement scoring" in message)
    assert "Role history: business analyst 36 months matched against required 60 months" in block
    assert "most recent end year 2024" in block


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

    with caplog.at_level(logging.DEBUG, logger="job_hunter_agent.job_review_pipeline"):
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
        lambda details_text, card_location, title_reason, profile=None: (True, "OK"),
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
        "build_pre_review_risk_signals",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], [], []),
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
        lambda details_text, card_location, title_reason, profile=None: (True, "OK"),
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
        "build_pre_review_risk_signals",
        lambda details_text, title_reason, profile, competitive_signals=None: ([], [], []),
    )
    monkeypatch.setattr(
        job_review_pipeline, "deterministic_review_outcome", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "resolve_llm_review_payload",
        lambda record, llm_cache, profile=None: (_ for _ in ()).throw(
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

    _patch_llm_review_path(monkeypatch, _keep_review_payload())
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_quick_card_filters",
        lambda **kwargs: (True, "OK"),
    )
    monkeypatch.setattr(job_review_pipeline, "find_hard_block_matches", lambda text, terms=None: [])
    monkeypatch.setattr(
        job_review_pipeline,
        "passes_preference_filters",
        _assert_inferred_work_type,
    )
    monkeypatch.setattr(
        job_review_pipeline,
        "preferred_salary_display",
        lambda *values: next((value for value in values if value and value != "N/A"), "N/A"),
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


def test_build_requirement_classification_review_signals_surfaces_uncertain_items_only():
    record = {
        RECORD_REQUIREMENT_COVERAGE_KEY: [
            {
                "requirement": "5+ years working in a security clearance environment",
                "importance": "required",
                "requirement_type": "uncertain",
                "classification_reviewable": True,
                "status": "invalid",
                "llm_proposed_requirement_type": "capability",
            },
            {
                "requirement": "Strong stakeholder engagement skills",
                "importance": "preferred",
                "requirement_type": "capability",
                "status": "supported",
                "matched_candidate_fact": "stakeholder engagement",
            },
        ]
    }

    signals = job_review_pipeline._build_requirement_classification_review_signals(record)

    assert signals == [
        {
            LEARNING_SIGNAL_KEY: "5+ years working in a security clearance environment",
            LEARNING_SUGGESTED_CATEGORY_KEY: CATEGORY_REQUIREMENT_CLASSIFICATION_REVIEW,
            LEARNING_ORIGINAL_TEXTS_KEY: ["5+ years working in a security clearance environment"],
            LEARNING_SUGGESTED_REQUIREMENT_TYPE_KEY: "capability",
        }
    ]


def test_build_requirement_classification_review_signals_suppresses_mixed_compound_requirement():
    record = {
        RECORD_REQUIREMENT_COVERAGE_KEY: [
            {
                "requirement": "A degree plus several years of relevant experience",
                "requirement_type": "uncertain",
                "classification_reviewable": False,
                "llm_proposed_requirement_type": "qualification",
            }
        ]
    }

    assert job_review_pipeline._build_requirement_classification_review_signals(record) == []


def test_build_requirement_classification_review_signals_dedupes_by_requirement_text():
    record = {
        RECORD_REQUIREMENT_COVERAGE_KEY: [
            {
                "requirement": "5+ years working in a security clearance environment",
                "requirement_type": "uncertain",
                "classification_reviewable": True,
                "llm_proposed_requirement_type": "eligibility",
                "llm_proposed_requirement_subtype": "clearance",
            },
            {
                "requirement": "5+ years working in a security clearance environment",
                "requirement_type": "uncertain",
                "classification_reviewable": True,
                "llm_proposed_requirement_type": "eligibility",
            },
        ]
    }

    signals = job_review_pipeline._build_requirement_classification_review_signals(record)

    assert len(signals) == 1
    assert signals[0][LEARNING_SUGGESTED_REQUIREMENT_TYPE_KEY] == "eligibility"
    assert signals[0][LEARNING_SUGGESTED_REQUIREMENT_SUBTYPE_KEY] == "clearance"


def test_build_requirement_classification_review_signals_keeps_missing_proposal_unset():
    record = {
        RECORD_REQUIREMENT_COVERAGE_KEY: [
            {
                "requirement": "A single unresolved professional requirement",
                "requirement_type": "uncertain",
                "classification_reviewable": True,
            }
        ]
    }

    signals = job_review_pipeline._build_requirement_classification_review_signals(record)

    assert LEARNING_SUGGESTED_REQUIREMENT_TYPE_KEY not in signals[0]
    assert LEARNING_SUGGESTED_REQUIREMENT_SUBTYPE_KEY not in signals[0]
