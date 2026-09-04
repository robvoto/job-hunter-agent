"""Tests for source connector fit explanations."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from job_hunter_agent import (
    capability_matching,
    description_trust,
    fit_scoring,
    llm_gate,
    role_analysis,
    signal_detection,
    source_connector,
    source_learning,
    workspace_renderer,
    workspace_service,
)
from job_hunter_agent.filters import build_title_block_rule
from job_hunter_agent.paths import SCORING_RULES_PATH
from job_hunter_agent.profile_store import (
    KEY_EVIDENCE_TIERS,
    KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
)
from job_hunter_agent.record_schema import (
    APPLY_METHOD_EXTERNAL_APPLY,
    APPLY_METHOD_EASY_APPLY,
    APPLY_METHOD_QUICK_APPLY,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    DETAILS_STATUS_OK,
    RECORD_APPLY_METHOD_KEY,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_FIT_CONFIDENCE_KEY,
    RECORD_FIT_LABEL_KEY,
    RECORD_FIT_SCORE_BREAKDOWN_KEY,
    RECORD_FIT_SCORE_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FIT_TONE_CLASS_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
    RECORD_IS_REPOSTED_KEY,
    RECORD_LLM_DECISION_KEY,
    RECORD_LLM_FIT_GRADE_KEY,
    RECORD_LLM_INPUT_TOKENS_KEY,
    RECORD_LLM_OUTPUT_TOKENS_KEY,
    RECORD_ORIGINAL_POSTED_DATE_KEY,
    ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED,
    ORIGINAL_POSTED_DATE_STATUS_VERIFIED,
    POSTING_CHANNEL_CLASSIFIER_VERSION,
    POSTING_CHANNEL_VERSION_KEY,
    RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)
from job_hunter_agent.scrapers.seek import build_seek_search_targets
from job_hunter_agent.signal_schema import (
    SIGNAL_ADJUSTMENT_KEY,
    SIGNAL_ALIGNMENT_KEY,
    SIGNAL_LABEL_KEY,
    SIGNAL_RISK_LABEL_KEY,
)
from job_hunter_agent.work_mode_extraction import extract_from_text


def _test_profile():
    return {
        "candidate_capabilities": [],
        "dominant_signal_clusters": [],
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_sector": True,
            "engagement_type": ["permanent", "contract"],
            "preferred_contract_months": 12,
            "short_contract_months": 6,
        },
        "preference_weights": {},
        "salary_preferences": {},
        "scoring_rules": json.loads(SCORING_RULES_PATH.read_text(encoding="utf-8")),
    }


def _capability_profile():
    return {
        **_test_profile(),
        "candidate_capabilities": [
            {
                "name": "Agile methodologies",
                "level": "strong",
                "fit": "core",
                "aliases": ["agile", "scrum", "kanban"],
            },
            {
                "name": "Acceptance testing",
                "level": "strong",
                "fit": "core",
                "aliases": ["uat", "user acceptance testing", "acceptance criteria"],
            },
            {
                "name": "Primary stakeholder engagement",
                "level": "strong",
                "fit": "supporting",
                "aliases": [
                    "stakeholder engagement",
                    "stakeholder management",
                    "facilitate workshops",
                ],
            },
        ],
    }


def _breakdown_value(breakdown, label):
    for item in breakdown:
        if item["label"] == label:
            return item["value"]
    return None


def _workspace_record(**overrides):
    record = {
        "job_key": "job-1",
        "title": "Business Analyst",
        "company": "Example Co",
        "url": "https://example.test/job-1",
        "source": "seek",
        "title_reason": "OK",
        "content_reason": "OK",
        "details_text": "Work with stakeholders and process mapping.",
        "description_source": "details",
        "details_status": "ok",
        "fit_confidence": "HIGH",
        RECORD_FIT_SCORE_KEY: 54,
        RECORD_FIT_LABEL_KEY: "Weak fit",
        RECORD_FIT_TONE_CLASS_KEY: "tone-low",
        RECORD_FIT_SCORE_BREAKDOWN_KEY: [],
        "applied": False,
        "archived": False,
        "hidden": False,
    }
    record.update(overrides)
    return record


def _render_job_card(record, profile=None, **kwargs):
    scored_record = _workspace_record(**record)
    return _ORIGINAL_RENDER_JOB_CARD(scored_record, profile, **kwargs)


_ORIGINAL_RENDER_JOB_CARD = workspace_renderer.render_job_card
workspace_renderer.render_job_card = _render_job_card


def test_infer_posting_channel_does_not_treat_recruiter_owned_direct_urls_as_employer_proof():
    channel = role_analysis.infer_posting_channel(
        {
            "company": "Peoplebank",
            "source_metadata": {
                "platform": "linkedin",
                "apply_url": "https://peoplebank.com.au/job/271673",
                "apply_domain": "peoplebank.com.au",
                "company_profile_url": "https://linkedin.com/company/peoplebank",
                "company_profile_name": "Peoplebank",
                "poster_company": "Peoplebank",
                "poster_company_industry": "Staffing and Recruiting",
                "hiring_company": "",
                "ats_source": "peoplebank.com.au",
                "raw_source_fields": {
                    "job_url_direct": "https://peoplebank.com.au/job/271673",
                    "company_url_direct": "https://peoplebank.com.au",
                },
            },
        },
        {
            "kind": "agency_or_recruiter",
            "confident": True,
            "evidence": "We are expert recruiters; our Federal Government Client is seeking...",
        },
    )

    assert channel["kind"] == "agency_or_recruiter"
    assert channel["source"] == "llm_classifier"
    assert channel["needs_review"] is False
    assert "job_url_direct" in channel["trusted_metadata"]
    assert "company_url_direct" in channel["trusted_metadata"]
    assert "poster industry = Staffing and Recruiting" in channel["trusted_metadata"]

def test_infer_posting_channel_does_not_treat_linkedin_publisher_profile_as_employer_proof():
    channel = role_analysis.infer_posting_channel(
        {
            "company": "Aspen Medical",
            "source_metadata": {
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
            },
        },
        None,
    )

    assert channel["kind"] == "unknown"
    assert channel["source"] == "insufficient_evidence"
    assert channel["needs_review"] is False
    assert "company profile link = https://au.linkedin.com/company/aspen-medical-pty-ltd" in channel["trusted_metadata"]


def test_infer_posting_channel_uses_llm_signal_when_no_trusted_metadata():
    channel = role_analysis.infer_posting_channel(
        {
            "company": "Hays",
            "source_metadata": {
                "platform": "linkedin",
                "apply_url": "https://www.linkedin.com/jobs/view/4445491073",
                "apply_domain": "www.linkedin.com",
                "company_profile_url": "https://uk.linkedin.com/company/hays",
                "company_profile_name": "Hays",
                "poster_company": "Hays",
                "hiring_company": "Hays",
                "raw_source_fields": {},
            },
        },
        {
            "kind": "agency_or_recruiter",
            "confident": True,
            "evidence": "this federal government agency is seeking",
        },
    )

    assert channel["kind"] == "agency_or_recruiter"
    assert channel["source"] == "llm_classifier"
    assert channel["needs_review"] is False
    assert "this federal government agency is seeking" in channel["text_evidence"]


def test_infer_posting_channel_marks_needs_review_when_llm_not_confident():
    channel = role_analysis.infer_posting_channel(
        {"source_metadata": {"platform": "seek", "raw_source_fields": {}}},
        {
            "kind": "agency_or_recruiter",
            "confident": False,
            "evidence": "our client is seeking a business analyst",
        },
    )

    assert channel["kind"] == "agency_or_recruiter"
    assert channel["source"] == "llm_classifier"
    assert channel["needs_review"] is True
    assert "our client is seeking a business analyst" in channel["text_evidence"]


def test_infer_posting_channel_falls_back_to_unknown_without_trusted_metadata_or_llm_signal():
    channel = role_analysis.infer_posting_channel(
        {"source_metadata": {"platform": "seek", "raw_source_fields": {}}},
        None,
    )

    assert channel["kind"] == "unknown"
    assert channel["source"] == "insufficient_evidence"
    assert channel["needs_review"] is False


def test_infer_posting_channel_ignores_company_name_alone_without_llm_signal():
    channel = role_analysis.infer_posting_channel(
        {
            "company": "Acme Recruitment",
            "source_metadata": {"platform": "seek", "raw_source_fields": {}},
        },
        None,
    )

    assert channel["kind"] == "unknown"
    assert channel["source"] == "insufficient_evidence"


def test_score_to_match_label_uses_central_match_band_mapping():
    from job_hunter_agent.match_labels import score_to_match_label

    assert score_to_match_label(92) == "Strong match"
    assert score_to_match_label(74) == "Good match"
    assert score_to_match_label(61) == "Possible fit"
    assert score_to_match_label(40) == "Stretch"


def test_llm_grade_does_not_create_requirement_fit_score():
    profile = {**_test_profile(), "scoring_rules": {"fit_breakdown": {"hard_block_penalty": -100}}}
    record = {
        "title": "Accounts Payable Officer",
        "title_reason": "TITLE_NOT_TARGET",
        "content_reason": "NO_MATCH",
        "llm_fit_grade": "STRONG",
        "requirement_coverage": [],
    }

    assert fit_scoring.fit_score(record, profile) == 0

def test_score_labels_and_tones_can_use_profile_match_levels():
    profile = {
        **_test_profile(),
        "match_levels": [
            {"minimum_score": 90, "label": "Top tier", "description": "highest confidence"},
            {"minimum_score": 65, "label": "Review next", "description": "good candidates"},
            {"minimum_score": 40, "label": "Maybe", "description": "review if needed"},
            {"minimum_score": 0, "label": "Low fit", "description": "least aligned"},
        ],
    }

    assert workspace_renderer.score_filter_option_label(90, profile) == "Top tier only"
    assert workspace_renderer.score_filter_option_label(65, profile) == "Review next or better"
    from job_hunter_agent.match_labels import score_to_match_label

    assert score_to_match_label(67, profile["match_levels"]) == "Review next"
    from job_hunter_agent.score_labels import score_to_tone_class

    assert score_to_tone_class(67, profile) == "tone-good"


def test_render_job_card_does_not_create_needs_confirmation_from_raw_job_requirements_only():
    html = workspace_renderer.render_job_card(
        {
            "requirement_coverage": [],
        },
        _test_profile(),
    )

    assert "Needs confirmation" not in html
    assert "job-action-rec" not in html


def test_render_job_card_keeps_unknown_required_requirement_visible_once():
    requirement = "Must hold an unfamiliar professional registration"
    html = workspace_renderer.render_job_card(
        {
            "requirement_coverage": [
                {
                    "requirement": requirement,
                    "importance": "mandatory",
                    "requirement_type": "invalid",
                    "status": "invalid",
                }
            ],
        },
        _test_profile(),
    )

    assert html.count(requirement) == 1
    assert "Needs attention" in html
    assert "No proof in profile" not in html
    assert "Needs classification/review" not in html
    assert "prefill_eligibility=" not in html


def test_render_job_card_shows_single_badge_for_uncertain_classification_and_no_add_action():
    requirement = "5+ years working in a security clearance environment"
    html = workspace_renderer.render_job_card(
        {
            "requirement_coverage": [
                {
                    "requirement": requirement,
                    "importance": "mandatory",
                    "requirement_type": "uncertain",
                    "status": "invalid",
                    "llm_proposed_requirement_type": "capability",
                }
            ],
        },
        _test_profile(),
    )

    assert html.count(requirement) == 1
    assert "Needs attention" in html
    assert "Needs classification/review" not in html
    assert "No proof in profile" not in html
    assert "prefill_eligibility=" not in html
    assert "prefill_capability=" not in html


def test_render_job_card_gap_button_carries_the_capability_name_not_requirement_text():
    html = workspace_renderer.render_job_card(
        {
            "requirement_coverage": [
                {
                    "requirement": "Cloud computing (AWS) experience",
                    "requirement_type": "capability",
                    "status": "not_shown",
                    "capability_name": "Cloud computing (AWS)",
                    "matched_job_text": "AWS platform experience",
                    "canonical_requirement": "Cloud computing (AWS)",
                    "profile_action_allowed": True,
                    "matched_candidate_fact": "Cloud computing (AWS)",
                }
            ],
        },
        _test_profile(),
    )

    assert 'data-capability-name="Cloud computing (AWS)"' in html
    assert "data-requirement=" not in html


def test_capability_coverage_uses_capabilities_panel_heading():
    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "job_requirements": [],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "status": "supported",
                    "matched_candidate_fact": "stakeholder engagement",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "Strong stakeholder engagement",
                    "profile_support": ["stakeholder engagement"],
                }
            ],
            "source": "seek",
        },
        _capability_profile(),
    )

    assert "job-requirements-panel" in html
    assert ">Capabilities<" in html
    assert ">Job Requirements<" not in html


def test_render_job_card_omits_gap_actions_for_vague_or_alternative_requirement():
    # A disjunctive clause (e.g. "CBAP or equivalent") decomposes to an OR row
    # and never gets profile_action_allowed=True. It must stay visible as an
    # unresolved requirement but show no confirmation buttons.
    requirement = "CBAP, Agile BA, or equivalent certifications"
    html = workspace_renderer.render_job_card(
        {
            "requirement_coverage": [
                {
                    "requirement": requirement,
                    "requirement_type": "qualification",
                    "status": "not_shown",
                    "qualification_name": "CBAP",
                    "matched_job_text": requirement,
                    "canonical_requirement": "",
                    "profile_action_allowed": False,
                    "matched_candidate_fact": "CBAP",
                }
            ],
        },
        _test_profile(),
    )

    assert html.count(requirement) >= 1
    assert "job-qualification-panel" in html
    assert ">Qualifications<" in html
    assert "job-requirements-panel" not in html
    assert "Needs confirmation" not in html
    assert "gap-btn" not in html


def test_render_job_card_partial_match_is_actionable_for_exact_requirement():
    # The LLM matched the requirement to an adjacent capability the candidate
    # holds ("Agile methodologies"), so the row stays a Partial match. Because
    # the exact requested concept is not itself in the profile, the row must
    # still offer an Add action for that exact concept — not the adjacent one.
    html = workspace_renderer.render_job_card(
        {
            "requirement_coverage": [
                {
                    "requirement": "IT systems and infrastructure project management",
                    "requirement_type": "capability",
                    "status": "partially_supported",
                    "capability_name": "Agile methodologies",
                    "matched_candidate_fact": "Agile methodologies",
                    "matched_job_text": "Lead IT infrastructure projects",
                    "canonical_requirement": "IT systems and infrastructure project management",
                    "profile_action_allowed": True,
                    "profile_support": ["agile delivery"],
                    "covered_requirement_elements": ["project management"],
                }
            ],
        },
        _capability_profile(),
    )

    assert "Partial matches" in html
    assert 'data-action="confirm_have"' in html
    assert (
        'data-capability-name="IT systems and infrastructure project management"'
        in html
    )
    # The adjacent capability must never be offered as the exact requested one.
    assert 'data-capability-name="Agile methodologies"' not in html


def test_render_job_card_partial_match_no_action_when_exact_capability_confirmed():
    # canonical_requirement resolves to a capability the candidate already holds
    # (via alias "stakeholder engagement"): nothing to add, so no gap buttons.
    html = workspace_renderer.render_job_card(
        {
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement across delivery teams",
                    "requirement_type": "capability",
                    "status": "partially_supported",
                    "capability_name": "Agile methodologies",
                    "matched_candidate_fact": "Agile methodologies",
                    "matched_job_text": "Engage stakeholders across teams",
                    "canonical_requirement": "stakeholder engagement",
                    "profile_action_allowed": True,
                    "profile_support": ["agile delivery"],
                    "covered_requirement_elements": ["stakeholders"],
                }
            ],
        },
        _capability_profile(),
    )

    assert "Partial matches" in html
    assert "gap-btn" not in html
    assert 'data-action="confirm_have"' not in html


def test_render_job_card_requirement_groups_ordered_attention_partial_matched():
    html = workspace_renderer.render_job_card(
        {
            "requirement_coverage": [
                {
                    "requirement": "Kubernetes administration",
                    "requirement_type": "capability",
                    "status": "not_shown",
                    "canonical_requirement": "Kubernetes administration",
                    "profile_action_allowed": True,
                    "matched_job_text": "Operate Kubernetes clusters",
                },
                {
                    "requirement": "IT systems and infrastructure project management",
                    "requirement_type": "capability",
                    "status": "partially_supported",
                    "capability_name": "Agile methodologies",
                    "matched_candidate_fact": "Agile methodologies",
                    "canonical_requirement": "IT systems and infrastructure project management",
                    "profile_action_allowed": True,
                    "profile_support": ["agile delivery"],
                    "covered_requirement_elements": ["project management"],
                },
                {
                    "requirement": "Agile delivery",
                    "requirement_type": "capability",
                    "status": "supported",
                    "capability_name": "Agile methodologies",
                    "matched_candidate_fact": "Agile methodologies",
                    "matched_job_text": "Deliver in agile teams",
                    "profile_support": ["agile"],
                },
            ],
        },
        _capability_profile(),
    )

    attention_at = html.index(">Needs attention</strong>")
    partial_at = html.index(">Partial matches</strong>")
    matched_at = html.index(">Matched</strong>")
    assert attention_at < partial_at < matched_at


def test_build_ad_learning_signals_registers_pending_capability_signals(monkeypatch):
    monkeypatch.setattr(
        source_learning,
        "signal_in_approved_knowledge",
        lambda category, signal, aliases=None: (False, ""),
    )

    signals = source_learning.build_ad_learning_signals(
        {
            "title": "Senior Delivery Ninja",
            "company": "Acme",
            "title_reason": "TITLE_POTENTIAL_MATCH",
            "skill_observations": [
                {"skill": "process mapping"},
            ],
        },
        "Process mapping across delivery teams.",
        profile={},
    )

    assert signals == [
        {
            "signal": "process mapping",
            "suggested_category": "capability_concept",
            "original_texts": ["process mapping"],
        },
    ]


def test_build_ad_learning_signals_registers_capability_from_structured_observation(monkeypatch):
    monkeypatch.setattr(
        source_learning,
        "signal_in_approved_knowledge",
        lambda category, signal, aliases=None: (False, ""),
    )

    signals = source_learning.build_ad_learning_signals(
        {
            "title": "Business Analyst",
            "company": "Acme",
            "skill_observations": [
                {"skill": "process mapping"},
            ],
        },
        "Process mapping across delivery teams.",
        profile={},
    )

    assert signals == [
        {
            "signal": "process mapping",
            "suggested_category": "capability_concept",
            "original_texts": ["process mapping"],
        }
    ]


def test_seek_search_targets_use_seek_location_code():
    profile = {
        "search_settings": {
            "keywords": "Business Analyst",
            "locations": ["New South Wales"],
            "classification_ids": [],
        }
    }

    targets = build_seek_search_targets(profile, configured_date_range=3, sort_newest_first=True)

    assert len(targets) == 1
    assert targets[0]["location"] == "NSW"
    assert parse_qs(urlparse(targets[0]["url"]).query)["where"] == ["NSW"]


def test_seek_search_targets_use_all_distinct_profile_role_terms_not_legacy_keyword():
    profile = {
        "target_roles": ["Systems Analyst", "Business Analyst"],
        "also_consider_roles": ["AI Business Analyst"],
        "search_settings": {
            "keywords": "legacy business analyst keyword",
            "locations": ["New South Wales"],
            "classification_ids": [],
        },
    }

    targets = build_seek_search_targets(profile, configured_date_range=7, sort_newest_first=True)

    assert [target["keywords"] for target in targets] == [
        "Systems Analyst",
        "Business Analyst",
        "AI Business Analyst",
    ]
    assert [parse_qs(urlparse(target["url"]).query)["keywords"][0] for target in targets] == [
        "Systems Analyst",
        "Business Analyst",
        "AI Business Analyst",
    ]


def test_build_ad_learning_signals_does_not_infer_hard_blockers_from_raw_text(monkeypatch):
    monkeypatch.setattr(
        source_learning,
        "signal_in_approved_knowledge",
        lambda category, signal, aliases=None: (False, ""),
    )

    signals = source_learning.build_ad_learning_signals(
        {
            "title": "Business Analyst",
            "company": "Acme",
            "hard_block_reasons": [],
        },
        "Must have SAP experience for this role.",
        profile={},
    )

    assert all(item["suggested_category"] != "hard_blocker_pattern" for item in signals)


def test_fit_confidence_does_not_override_trusted_description_calculation():
    record = {
        RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
        RECORD_FULL_DESCRIPTION_KEY: "Business analyst duties. " * 40,
        RECORD_FIT_CONFIDENCE_KEY: CONFIDENCE_LOW,
    }

    assert description_trust.full_description_confidence(record) == CONFIDENCE_HIGH
    assert description_trust.get_trusted_full_description(record).startswith(
        "Business analyst duties."
    )
    assert description_trust.is_description_trusted(record)


def test_fit_confidence_low_when_no_trusted_description_exists():
    record = {
        RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
        RECORD_FIT_SOURCE_TEXT_KEY: "Too short to trust.",
        RECORD_FIT_CONFIDENCE_KEY: CONFIDENCE_HIGH,
    }

    assert description_trust.full_description_confidence(record) == CONFIDENCE_LOW
    assert not description_trust.is_description_trusted(record)


def test_fit_confidence_low_for_browser_interstitial_text():
    record = {
        RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
        RECORD_FULL_DESCRIPTION_KEY: (
            "Loading×Sorry to interruptCSS ErrorRefresh (function() { "
            "if (!navigator.cookieEnabled) { var cookieMessage = document.createElement('div'); } })"
        ),
        RECORD_FIT_CONFIDENCE_KEY: CONFIDENCE_HIGH,
    }

    assert description_trust.full_description_confidence(record) == CONFIDENCE_LOW
    assert description_trust.get_trusted_full_description(record) == ""
    assert not description_trust.is_description_trusted(record)


def test_extract_work_mode_prioritises_strict_office_requirement_over_delivery_method():
    result = extract_from_text(
        "Familiarity with Agile, Waterfall, or hybrid delivery environments. This role is 5 days in office."
    )
    assert result["work_mode"] == "onsite"
    assert result["work_mode_source"] == "fallback_text"
    assert result["work_mode_needs_review"] is True


def test_build_role_summary_prefers_description_snippet_over_generic_sector_stub():
    summary = workspace_renderer.build_role_summary(
        {
            "title": "Project Coordinator",
            "company": "Standards Australia Ltd",
            "location": "Sydney NSW",
            "work_type": "Full time",
            "teaser": "Private sector role for a Project Coordinator.",
        },
        "About the role: Coordinate delivery planning, stakeholder updates, and standards publication schedules across multiple teams.",
    )

    assert "Coordinate delivery planning" in summary
    assert "Private sector role" not in summary


def test_render_job_card_does_not_claim_private_sector_by_default():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-sector-unknown",
            "title": "Project Coordinator",
            "company": "Standards Australia Ltd",
            "url": "https://example.com/job",
            "title_reason": "TITLE_POTENTIAL_MATCH",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Coordinate delivery planning, stakeholder updates, and standards publication schedules across multiple teams. "
            * 20,
            "fit_source_text": "Coordinate delivery planning, stakeholder updates, and standards publication schedules across multiple teams. "
            * 20,
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "Private sector role" not in html
    assert ">Government<" not in html

def test_fit_summary_uses_requirement_coverage_only_and_limits_to_three_bullets():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-fit-summary-coverage-only",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analyst role supporting agile delivery, stakeholder engagement, and data analysis. "
            * 20,
            "fit_highlights": ["Location matches primary preference ✓", "The ad asks for X"],
            "requirement_coverage": [
                {"requirement": "Business analysis", "status": "supported"},
                {"requirement": "Stakeholder engagement", "status": "supported"},
                {"requirement": "Agile delivery", "status": "supported"},
                {"requirement": "Data analysis", "status": "supported"},
            ],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "Why this is a good fit" not in html
    assert "Location matches primary preference" not in html
    assert "The ad asks for" not in html


def test_render_job_card_includes_expandable_full_description_when_trusted_text_is_available():
    full_description = (
        "Senior business analysis role leading discovery workshops, process mapping, "
        "UAT coordination, and stakeholder communication across a complex delivery program. "
        * 10
    )
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-full-description-panel",
            "title": "Senior Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "teaser": "Lead discovery workshops and coordinate delivery outcomes.",
            "full_description": full_description,
            "fit_source_text": full_description,
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "source": "seek",
        },
        _test_profile(),
    )

    assert 'class="job-summary-expand"' in html
    assert 'class="job-summary-toggle"' in html
    assert "Show more" in html  # screen-reader label remains
    assert "Show less" in html  # screen-reader label remains
    assert 'class="job-full-description-body"' in html
    assert 'class="job-full-description-reading"' in html
    assert html.count('class="job-full-description"') >= 2
    assert "process mapping, UAT coordination" in html


def test_render_job_card_full_description_cleans_markdown_escape_artifacts():
    full_description = (
        "How to Apply: Visit https://example.com/login?org_code\\=WXWPMT and share your role summary. "
        * 8
    )
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-full-description-cleanup",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": full_description,
            "fit_source_text": full_description,
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "source": "seek",
        },
        _test_profile(),
    )

    assert "org_code\\=WXWPMT" not in html
    assert "org_code=WXWPMT" in html


def test_render_job_card_full_description_preserves_source_paragraphs():
    full_description = (
        "About the Role\n"
        "\n"
        "First paragraph with stakeholder engagement and delivery planning.\n"
        "\n"
        "Second paragraph covering workshops and operating rhythm."
    )
    html = workspace_renderer._render_full_description_html(full_description)

    assert 'class="job-full-description-reading"' in html
    assert "<h4 class=\"job-full-description-heading\">About the Role</h4>" in html
    assert (
        '<p class="job-full-description">First paragraph with stakeholder engagement and delivery planning.</p>'
        in html
    )
    assert (
        '<p class="job-full-description">Second paragraph covering workshops and operating rhythm.</p>'
        in html
    )


def test_render_job_card_full_description_renders_headings_and_lists_semantically():
    full_description = (
        "Key Responsibilities\n"
        "- Lead workshops\n"
        "- Write requirements\n"
        "\n"
        "Why Fujitsu?\n"
        "Inclusive culture and growth pathways.\n"
        "\n"
        "For Security Cleared Roles - PLEASE NOTE citizenship is required."
    )
    html = workspace_renderer._render_full_description_html(full_description)

    assert "<h4 class=\"job-full-description-heading\">Key Responsibilities</h4>" in html
    assert "<h4 class=\"job-full-description-heading\">Why Fujitsu?</h4>" in html
    assert "<h4 class=\"job-full-description-heading\">For Security Cleared Roles</h4>" in html
    assert '<ul class="job-full-description-list">' in html
    assert '<li class="job-full-description-list-item">Lead workshops</li>' in html
    assert '<li class="job-full-description-list-item">Write requirements</li>' in html
    assert "Inclusive culture and growth pathways." in html
    assert "PLEASE NOTE citizenship is required." in html


def test_render_job_card_full_description_escapes_html_without_losing_text():
    full_description = (
        "Skills and Experience\n"
        "- Own <script>alert('x')</script> safely\n"
        "- Use analytics & reporting\n"
        "\n"
        "Plain text follows."
    )
    html = workspace_renderer._render_full_description_html(full_description)

    assert "<script>" not in html
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in html
    assert "analytics &amp; reporting" in html
    assert "Plain text follows." in html


def test_render_job_card_full_description_plain_text_falls_back_to_chunked_paragraphs():
    full_description = (
        "Senior business analysis role leading discovery workshops, process mapping, "
        "UAT coordination, stakeholder communication, and reporting across a complex "
        "delivery program. "
        * 8
    )
    html = workspace_renderer._render_full_description_html(full_description)

    assert html.count('class="job-full-description"') >= 2
    assert 'class="job-full-description-list"' not in html
    assert 'class="job-full-description-heading"' not in html


def test_render_job_card_full_description_preserves_all_meaningful_content():
    full_description = (
        "About the Role\n"
        "Lead discovery.\n"
        "\n"
        "Key Responsibilities\n"
        "- Facilitate workshops\n"
        "- Document requirements\n"
        "\n"
        "For Security Cleared Roles\n"
        "Australian citizenship required."
    )
    html = workspace_renderer._render_full_description_html(full_description)

    for expected in [
        "About the Role",
        "Lead discovery.",
        "Key Responsibilities",
        "Facilitate workshops",
        "Document requirements",
        "For Security Cleared Roles",
        "Australian citizenship required.",
    ]:
        assert expected in html


def test_render_job_card_omits_expandable_full_description_when_no_trusted_text_exists():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-full-description-panel-absent",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            RECORD_FIT_SOURCE_TEXT_KEY: "Short teaser only.",
            "teaser": "Short teaser only.",
            "description_source": "details",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "source": "seek",
        },
        _test_profile(),
    )

    assert 'class="job-summary-expand"' not in html


def test_build_fit_highlights_recomputes_instead_of_reusing_stale_highlights(monkeypatch):
    monkeypatch.setattr(
        fit_scoring,
        "load_profile",
        lambda: {
            "candidate_capabilities": [],
            "match_preferences": {
                "home_location": "",
                "prefer_sector": True,
                "engagement_type": ["permanent", "contract"],
                "preferred_contract_months": 12,
                "short_contract_months": 6,
            },
            "dominant_signal_clusters": [],
            "preference_weights": {},
            "salary_preferences": {},
        },
    )

    highlights = fit_scoring.build_fit_highlights(
        {
            "title": "Lead Business Analyst",
            "company": "Preacta Recruitment",
            "teaser": "Enterprise data assessment role.",
            "fit_highlights": ["Government context"],
            "work_type": "Contract/Temp",
            "location": "Sydney NSW",
        },
        "Join a global consultancy. Analyse current-state data capability and maturity.",
    )

    assert highlights == []


def test_reviewed_signal_matches_respect_registry_decisions(monkeypatch):
    _registry = lambda: {
        "stakeholder management": {
            "signal": "stakeholder management",
            "decision": "use",
            "original_texts": ["stakeholder management"],
        },
        "jira": {"signal": "jira", "decision": "use", "original_texts": ["jira"]},
        "banking": {"signal": "banking", "decision": "review", "original_texts": ["banking"]},
        "project": {"signal": "project", "decision": "ignore", "original_texts": ["project"]},
        "delivery": {
            "signal": "delivery",
            "decision": "evidence_only",
            "original_texts": ["delivery"],
        },
    }
    monkeypatch.setattr(capability_matching, "load_registry", _registry)
    monkeypatch.setattr(capability_matching, "load_registry", _registry)
    monkeypatch.setattr(capability_matching, "load_approved_signal_catalog", lambda: [])

    matches = capability_matching.reviewed_signal_matches_for_text(
        "Stakeholder management, Jira, banking, project, and delivery are all mentioned in the role."
    )

    assert matches == {
        "matched": ["Stakeholder management", "Jira"],
        "evidence_only": ["Delivery"],
        "ignored": ["Project"],
        "unresolved": ["Banking"],
    }


def test_fit_score_breakdown_does_not_score_reviewed_signal_matches(monkeypatch):
    monkeypatch.setattr(
        capability_matching,
        "load_registry",
        lambda: {
            "jira": {"signal": "jira", "decision": "use", "original_texts": ["jira"]},
            "banking": {"signal": "banking", "decision": "review", "original_texts": ["banking"]},
            "project": {"signal": "project", "decision": "ignore", "original_texts": ["project"]},
        },
    )

    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Lead Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "fit_highlights": [],
            "location": "Sydney NSW",
            "work_type": "Contract/Temp",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "competitive_signals": [],
            "full_description": "Jira and banking domain experience are helpful in this project role.",
            "fit_source_text": "Jira and banking domain experience are helpful in this project role.",
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
        },
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "Reviewed signal matches") is None


def test_fit_score_evidence_ignores_display_only_fit_highlights():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Lead Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "fit_highlights": [
                "Strong capability match: Agile methodologies",
                "Government context",
                "12+ month contract",
                "Location matches primary preference: Sydney NSW",
                "Public sector transformation \u2713",
            ],
            "location": "Sydney NSW",
            "work_type": "Contract/Temp",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "competitive_signals": [],
        },
        _capability_profile(),
    )

    # No contextual_capability_matches \u2192 no capability evidence entries
    assert not any("[llm_confirmed]" in item["label"] for item in breakdown)


def test_fit_score_requirement_coverage_directly_drives_requirement_fit_score():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Lead Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "competitive_signals": [],
            "requirement_coverage": [
                {
                    "requirement": "Agile delivery",
                    "importance": "mandatory",
                    "status": "supported",
                    "capability_name": "agile methodologies",
                    "matched_job_text": "agile delivery ceremonies",
                    "profile_support": ["Agile methodologies"],
                    "matched_candidate_fact": "agile methodologies",
                },
                {
                    "requirement": "Acceptance testing",
                    "importance": "preferred",
                    "status": "supported",
                    "capability_name": "acceptance testing",
                    "matched_job_text": "acceptance criteria",
                    "profile_support": ["Acceptance Testing"],
                    "matched_candidate_fact": "acceptance testing",
                },
            ],
        },
        _capability_profile(),
    )

    assert breakdown[0]["section"] == "requirement_fit"
    assert breakdown[0]["value"] == 100
    assert breakdown[0]["label"].startswith("Requirement Fit: 100%")

def test_strong_high_confidence_fit_keeps_requirement_coverage_transparency_only():
    profile = _capability_profile()
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary"},
        "content_reason": "OK",
        "llm_fit_grade": "STRONG",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "posted_age_days": 1,
        "competitive_signals": [],
        "missing_profile_support": [],
        "soft_risk_reasons": [],
        RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
        "description_source": "jobAdDetails",
        "full_description": "Business analyst role driving agile delivery and stakeholder engagement. "
        * 20,
        "requirement_coverage": [
            {
                "requirement": "Agile delivery",
                "status": "supported",
                "capability_name": "agile methodologies",
                "matched_job_text": "agile delivery",
                "profile_support": [],
                "matched_candidate_fact": "agile methodologies",
            },
            {
                "requirement": "Acceptance testing",
                "status": "supported",
                "capability_name": "acceptance testing",
                "matched_job_text": "acceptance criteria",
                "profile_support": [],
                "matched_candidate_fact": "acceptance testing",
            },
            {
                "requirement": "Stakeholder engagement",
                "status": "supported",
                "capability_name": "primary stakeholder engagement",
                "matched_job_text": "stakeholder workshops",
                "profile_support": [],
                "matched_candidate_fact": "primary stakeholder engagement",
            },
        ],
    }

    breakdown = fit_scoring.fit_score_breakdown(record, profile)

    assert _breakdown_value(breakdown, "Multiple strong signals align") is None
    assert fit_scoring.fit_score(record, profile) >= 68


def test_required_blocker_watchouts_do_not_mark_desirable_mentions_as_missing():
    watchouts = capability_matching.description_watchout_reasons(
        "ERP experience is desirable for this business analyst role.",
        {
            "must_not_require_skills": ["ERP"],
            "reject_description_phrase_rules": [],
            "reject_title_rules": [],
        },
    )
    risks, missing, missing_clearance = capability_matching.build_pre_review_risk_signals(
        "ERP experience is desirable for this business analyst role.",
        "OK",
        {
            "must_not_require_skills": ["ERP"],
            "reject_description_phrase_rules": [],
            "reject_title_rules": [],
            "candidate_capabilities": [],
        },
    )

    assert watchouts == ["erp appears desirable"]
    assert risks == ["erp appears desirable"]
    assert missing == []
    assert missing_clearance == []


def test_missing_required_requirement_uses_deterministic_scan_without_llm_coverage():
    profile = {
        "must_not_require_skills": [],
        "reject_description_phrase_rules": [],
        "reject_title_rules": [],
        "candidate_capabilities": [],
        "candidate_eligibility": [{"name": "NV1", "value": False, "evidence": []}],
    }

    _, missing, missing_clearance = capability_matching.build_pre_review_risk_signals(
        "Security Clearance: NV1 / Baseline / As per role",
        "OK",
        profile,
    )

    # No LLM judgment available yet: falls back to the deterministic keyword scan,
    # which cannot see that NV1 is one option in an alternation. Clearance misses are
    # reported in their own list, never merged into the generic "missing" list.
    assert missing == []
    assert missing_clearance == ["Missing mandatory requirement: Nv1"]


def test_eligibility_coverage_renders_in_clearance_panel_when_supported():
    # Once the fit-review LLM has judged an eligibility requirement, its verdict is
    # the single source of truth and lives in the dedicated Clearances panel — the
    # pre-review deterministic scan is never consulted again for display.
    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "requirement_coverage": [
                {
                    "requirement": "Security Clearance: NV1 / Baseline / As per role",
                    "importance": "mandatory",
                    "requirement_type": "eligibility",
                    "requirement_subtype": "clearance",
                    "status": "supported",
                    "eligibility_name": "Baseline clearance",
                    "matched_job_text": "Security Clearance: NV1 / Baseline / As per role",
                    "profile_support": [],
                    "matched_candidate_fact": "Baseline clearance",
                }
            ],
            "source": "seek",
        },
        _capability_profile(),
    )

    assert "job-clearance-panel" not in html
    assert "job-eligibility-panel" in html
    assert "Clearance" in html
    assert "job-requirement-item--supported" in html
    assert "Security Clearance: NV1 / Baseline / As per role" in html
    assert "Missing mandatory requirement" not in html


def test_eligibility_mismatch_renders_in_clearance_panel_not_checks_before_applying():
    # An eligibility mismatch from the LLM must appear exactly once — in the
    # Clearances panel — and never be duplicated into "Checks before applying".
    requirement_coverage = [
        {
            "requirement": "Security Clearance: NV1 only, no alternatives accepted",
            "importance": "mandatory",
            "requirement_type": "eligibility",
            "requirement_subtype": "clearance",
            "status": "mismatch",
            "eligibility_name": "NV1",
            "matched_job_text": "Security Clearance: NV1 only, no alternatives accepted",
            "profile_support": [],
            "matched_candidate_fact": "NV1",
        }
    ]

    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "requirement_coverage": requirement_coverage,
            "source": "seek",
        },
        _capability_profile(),
    )

    assert "job-clearance-panel" not in html
    assert "job-eligibility-panel" in html
    assert "Clearance" in html
    assert "NV1" in html

    checks = workspace_renderer._build_checks_before_applying_items(
        history_warning_signals=[],
        description_issue=False,
        is_possible_repost=False,
        similar_applied_record=None,
        candidate_history=None,
        hard_block_reasons_list=[],
        salary_fit_state="unknown",
        soft_risk_reasons=[],
    )
    assert checks == []


def test_fit_score_breakdown_ignores_profile_title_scoring_rule_overrides():
    profile = {
        **_capability_profile(),
        "scoring_rules": {"fit_breakdown": {"title_direct": 20, "hard_block_penalty": -100}},
    }

    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "title_match_metadata": {"match_family": "primary"},
            "requirement_coverage": [
                {"requirement": "Agile delivery", "importance": "mandatory", "status": "supported", "capability_name": "agile methodologies", "matched_candidate_fact": "agile methodologies"}
            ],
        },
        profile,
    )

    assert _breakdown_value(breakdown, "The job title matches one of your target roles") is None
    assert breakdown[0]["value"] == 100

def test_fit_score_breakdown_keeps_easy_apply_as_badge_only():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "title_match_metadata": {
                "match_family": "primary",
            },
            "fit_highlights": [],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analyst duties. " * 40,
            "competitive_signals": [],
            RECORD_APPLY_METHOD_KEY: APPLY_METHOD_EASY_APPLY,
        },
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "Easy/Quick Apply available") is None


def test_fit_score_breakdown_keeps_secondary_role_family_out_of_score():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Lead Project Coordinator",
            "title_reason": "TITLE_POTENTIAL_MATCH",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "title_match_metadata": {"match_family": "secondary"},
            "requirement_coverage": [
                {"requirement": "Agile delivery", "importance": "mandatory", "status": "supported", "capability_name": "agile methodologies", "matched_candidate_fact": "agile methodologies"}
            ],
        },
        _capability_profile(),
    )

    assert _breakdown_value(breakdown, "The job title matches one of your alternative roles") is None
    assert _breakdown_value(breakdown, "Preferred seniority adjustment") is None
    assert breakdown[0]["value"] == 100

def test_job_card_shows_negative_score_factors_without_debug_mode():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-visible-negative",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "On-site",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "<strong>What lowers it</strong>" not in html
    assert "Score penalties" not in html


def test_job_card_shows_unknown_posted_date_when_missing():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-missing-posted",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "On-site",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "<strong>Posted</strong>" not in html


def test_job_card_shows_reviewed_signal_transparency_groups(monkeypatch):
    _registry = lambda: {
        "stakeholder management": {
            "signal": "stakeholder management",
            "decision": "use",
            "original_texts": ["stakeholder management"],
        },
        "jira": {"signal": "jira", "decision": "use", "original_texts": ["jira"]},
        "banking": {"signal": "banking", "decision": "review", "original_texts": ["banking"]},
        "project": {"signal": "project", "decision": "ignore", "original_texts": ["project"]},
    }
    monkeypatch.setattr(capability_matching, "load_registry", _registry)
    monkeypatch.setattr(capability_matching, "load_registry", _registry)

    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-reviewed-signals",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Strong stakeholder management, Jira, banking exposure, and project coordination needed.",
            "fit_source_text": "Strong stakeholder management, Jira, banking exposure, and project coordination needed.",
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "Approved experience matches" not in html
    assert "The ad mentions Stakeholder management, and your profile shows related experience." not in html
    assert "The ad mentions Jira, and your profile shows related experience." not in html
    assert "Found, not scored" not in html
    assert "Filtered out" not in html
    assert "The ad mentions Project, and your profile shows related experience." not in html
    # Unresolved signals (Banking) only render in debug mode


def test_job_card_uses_score_tone_as_card_accent_class():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-card-tone",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert 'class="job-card tone-low"' in html
    assert 'class="match-tile tone-low"' in html
    assert ">New To You<" in html


def test_job_card_shows_easy_apply_badge():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-easy-apply-badge",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "linkedin",
            RECORD_APPLY_METHOD_KEY: APPLY_METHOD_EASY_APPLY,
        },
        _test_profile(),
    )

    assert (
        'class="badge jh-badge badge-source-linkedin" title="Sourced from LinkedIn. Apply directly on the job board with one click." '
        'aria-label="Sourced from LinkedIn. Apply directly on the job board with one click.">LinkedIn · Easy Apply<'
        in html
    )
    assert 'data-apply-method="easy_apply"' in html


def test_job_card_shows_quick_apply_badge():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-quick-apply-badge",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            RECORD_APPLY_METHOD_KEY: APPLY_METHOD_QUICK_APPLY,
        },
        _test_profile(),
    )

    assert 'class="badge jh-badge badge-source-seek"' in html
    assert "SEEK · Quick Apply" in html
    assert html.count('class="badge jh-badge badge-source-seek"') == 1


def test_job_card_omits_apply_method_badge_when_unknown():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-unknown-apply-badge",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "badge-apply-method" not in html
    assert 'data-apply-method="unknown"' in html


def test_job_card_shows_reposted_and_original_posted_dates_separately():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-repost-dates",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://linkedin.com/jobs/view/1",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "linkedin",
            "posted": "15 hours ago",
            "posted_age_days": 15 / 24,
            RECORD_APPLY_METHOD_KEY: APPLY_METHOD_EXTERNAL_APPLY,
            RECORD_ORIGINAL_POSTED_DATE_KEY: "2026-06-24",
            RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY: ORIGINAL_POSTED_DATE_STATUS_VERIFIED,
            RECORD_IS_REPOSTED_KEY: True,
        },
        _test_profile(),
    )

    assert ">Reposted</span>" in html
    assert "LinkedIn reposted" in html
    assert "15 hours ago" in html
    assert "Originally posted" in html
    assert "24 Jun 2026" in html
    assert "<strong>Posted</strong>" not in html


def test_applied_repost_does_not_show_repost_badge_or_repost_metadata():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-applied-repost",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://linkedin.com/jobs/view/3",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "linkedin",
            "posted": "15 hours ago",
            "posted_age_days": 15 / 24,
            "applied": True,
            RECORD_APPLY_METHOD_KEY: APPLY_METHOD_EXTERNAL_APPLY,
            RECORD_ORIGINAL_POSTED_DATE_KEY: "2026-06-24",
            RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY: ORIGINAL_POSTED_DATE_STATUS_VERIFIED,
            RECORD_IS_REPOSTED_KEY: True,
        },
        _test_profile(),
    )

    assert ">Reposted</span>" not in html
    assert "LinkedIn reposted" not in html
    assert "Originally posted" not in html
    assert "15 hours ago" in html


def test_verified_original_date_without_repost_uses_normal_posted_metadata():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-not-reposted",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://linkedin.com/jobs/view/4",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "linkedin",
            "posted": "1 day ago",
            "posted_age_days": 1,
            RECORD_APPLY_METHOD_KEY: APPLY_METHOD_EXTERNAL_APPLY,
            RECORD_ORIGINAL_POSTED_DATE_KEY: "2026-08-16",
            RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY: ORIGINAL_POSTED_DATE_STATUS_VERIFIED,
            RECORD_IS_REPOSTED_KEY: False,
        },
        _test_profile(),
    )

    assert ">Reposted</span>" not in html
    assert "LinkedIn reposted" not in html
    assert "Originally posted" not in html
    assert "1 day ago" in html


def test_job_card_flags_unverified_linkedin_external_apply_freshness():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-linkedin-unverified-freshness",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://linkedin.com/jobs/view/2",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "linkedin",
            "posted": "15 hours ago",
            "posted_age_days": 15 / 24,
            RECORD_APPLY_METHOD_KEY: APPLY_METHOD_EXTERNAL_APPLY,
            RECORD_ORIGINAL_POSTED_DATE_STATUS_KEY: ORIGINAL_POSTED_DATE_STATUS_UNVERIFIED,
        },
        _test_profile(),
    )

    assert "Freshness may be unreliable" in html
    assert "LinkedIn listed" in html
    assert "15 hours ago" in html
    assert "<strong>Posted</strong>" not in html
    assert "Originally posted" not in html


def test_job_card_summary_unescapes_literal_pipe():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-summary-pipe",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Canberra ACT",
            "work_type": "Contract",
            "work_mode": "On-site",
            "salary": "N/A",
            "full_description": (
                "Business Analyst \\| Child Support Reform Program: We are seeking an experienced "
                "business analyst to work with stakeholders across delivery teams. "
                * 3
            ),
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "Business Analyst \\| Child Support Reform Program" not in html
    assert "Business Analyst | Child Support Reform Program" in html


def test_job_card_summary_normalizes_escaped_list_markers():
    teaser = (
        "\\* Role: Business Analyst "
        "\\* Location of work: Canberra, Brisbane, Melbourne and Sydney "
        "\\* Length of contract: 12 Months (update if different) "
        "\\* Contract Extensions: Extension Available (update if applicable) "
        "\\* Security Clearance: NV1 / Baseline / As per role (update if applicable)"
    )
    full_description = (
        "\\* Role: Business Analyst\n"
        "\\* Location of work: Canberra, Brisbane, Melbourne and Sydney\n"
        "\\* Length of contract: 12 Months (update if different)\n"
        "\\* Contract Extensions: Extension Available (update if applicable)\n"
        "\\* Security Clearance: NV1 / Baseline / As per role (update if applicable)\n"
        "Candidates must have\n"
        "- Strategic planning, business analysis, and solution design.\n"
    )
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-summary-escaped-bullets",
            "title": "Senior Business Analysts - Canberra, Brisbane, Melbourne and Sydney",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Canberra ACT",
            "work_type": "Contract",
            "work_mode": "On-site",
            "salary": "N/A",
            "teaser": teaser,
            "full_description": full_description,
            "fit_source_text": full_description,
            "description_source": "linkedin_structured",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "source": "linkedin",
        },
        _test_profile(),
    )

    assert "Business Analyst \\ Location of work" not in html
    assert "Business Analyst | Location of work: Canberra, Brisbane, Melbourne and Sydney" in html
    assert 'data-job-teaser="\\* Role: Business Analyst' not in html
    assert 'data-job-teaser="Role: Business Analyst | Location of work: Canberra, Brisbane, Melbourne and Sydney' in html


def test_render_job_card_hides_browser_interstitial_summary_text():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-browser-interstitial-summary",
            "title": "Analyst (Multiple Positions)",
            "company": "Australian Energy Regulator",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "DETAILS_CHALLENGE_PAGE",
            "llm_fit_grade": "",
            "location": "Canberra ACT",
            "work_type": "",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "teaser": (
                "Loading×Sorry to interruptCSS ErrorRefresh (function() { "
                "if (!navigator.cookieEnabled) { var cookieMessage = document.createElement('div'); } })"
            ),
            "role_snapshot": (
                "Loading×Sorry to interruptCSS ErrorRefresh (function() { "
                "if (!navigator.cookieEnabled) { var cookieMessage = document.createElement('div'); } })"
            ),
            RECORD_DETAILS_STATUS_KEY: "challenge_page",
            "source": "apsjobs",
        },
        _test_profile(),
    )

    assert "Sorry to interrupt" not in html
    assert "navigator.cookieEnabled" not in html
    assert "Analyst (Multiple Positions)" in html
    assert 'data-job-teaser=""' in html


def test_posting_channel_badge_uses_llm_classifier_review_class():
    channel = role_analysis.infer_posting_channel(
        {"company": "Acme", "source_metadata": {"platform": "seek", "raw_source_fields": {}}},
        {
            "kind": "agency_or_recruiter",
            "confident": False,
            "evidence": "our client is seeking a business analyst",
        },
    )
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-posting-channel-badge",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Our client is seeking a business analyst. Contact our recruitment team for details. "
            * 20,
            "fit_highlights": [],
            "requirement_coverage": [
                {
                    "requirement": "Strong stakeholder engagement and communication skills",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "status": "supported",
                    "matched_candidate_fact": "stakeholder engagement",
                },
                {
                    "requirement": "Experience across end-to-end BA activities",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "status": "mismatch",
                },
            ],
            "source": "seek",
            "posting_channel_evidence": channel,
        },
        {
            **_test_profile(),
            "candidate_capabilities": [
                {"name": "stakeholder engagement", "level": "strong", "fit": "core", "aliases": []},
            ],
            "must_not_require_skills": ["end-to-end BA activities"],
        },
    )

    assert 'badge-warning" title="Recruiter language detected' in html
    assert "Likely recruiter" in html
    assert "Source unclear" not in html
    assert ">Recruiter<" not in html
    assert ">Capabilities<" in html
    assert ">Job Requirements<" not in html
    assert "Strong stakeholder engagement and communication skills" in html
    assert "In profile" not in html
    assert "Needs attention" in html
    assert "Not in profile" not in html
    assert "job-requirement-item--supported" in html
    assert "job-requirement-item--mismatch" in html
    assert "badge-sector-government" not in html


def test_posting_channel_badge_uses_confident_llm_classification():
    channel = role_analysis.infer_posting_channel(
        {
            "company": "Acme Recruitment",
            "source_metadata": {"platform": "seek", "raw_source_fields": {}},
        },
        {
            "kind": "agency_or_recruiter",
            "confident": True,
            "evidence": "on behalf of a leading government agency",
        },
    )
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-posting-channel-company-indicator",
            "title": "Business Analyst",
            "company": "Acme Recruitment",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analysis support across delivery teams.",
            "fit_highlights": [],
            "source": "seek",
            "posting_channel_evidence": channel,
        },
        _test_profile(),
    )

    assert "Agency recruiter" in html
    assert "Likely recruiter" not in html
    assert "Source unclear" not in html


def test_render_job_card_shows_source_unclear_badge_for_unknown_posting_channel():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-posting-channel-unknown",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analysis support across delivery teams.",
            "fit_highlights": [],
            "source": "seek",
            "posting_channel_evidence": {
                POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION,
                "kind": "unknown",
                "source": "insufficient_evidence",
                "trusted_metadata": [],
                "text_evidence": [],
                "needs_review": False,
            },
        },
        _test_profile(),
    )

    assert "Source unclear" in html


def test_render_job_card_suppresses_stale_posting_channel_badge():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-posting-channel-stale",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analysis support across delivery teams.",
            "fit_highlights": [],
            "source": "seek",
            "posting_channel_evidence": {
                POSTING_CHANNEL_VERSION_KEY: POSTING_CHANNEL_CLASSIFIER_VERSION - 1,
                "kind": "direct_employer",
                "source": "metadata_first",
            },
        },
        _test_profile(),
    )

    assert "Direct employer" not in html
    assert "Source unclear" not in html


def test_infer_posting_channel_keeps_unknown_without_trusted_linkedin_employer_metadata():
    channel = role_analysis.infer_posting_channel(
        {
            "company": "Hammondcare",
            "source_metadata": {
                "platform": "linkedin",
                "apply_url": "https://www.linkedin.com/jobs/view/4439784341",
                "apply_domain": "www.linkedin.com",
                "company_profile_url": "",
                "company_profile_name": "Hammondcare",
                "poster_company": "Hammondcare",
                "hiring_company": "Hammondcare",
                "ats_source": "www.linkedin.com",
                "raw_source_fields": {},
            },
        },
        None,
    )

    assert channel["kind"] == "unknown"
    assert channel["source"] == "insufficient_evidence"
    assert channel["needs_review"] is False


def test_render_job_card_shows_posted_age_in_metadata(monkeypatch):
    monkeypatch.setattr(
        workspace_renderer,
        "current_posted_age_days",
        lambda record, now=None: float(record["posted_age_days"]),
    )
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-posted-age-badge",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "posted": "26 Jul 2026",
            "posted_age_days": 7,
            "full_description": "Business analysis support across delivery teams.",
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert 'class="job-posted-age"> · 7 days old</span>' in html
    assert "badge-stale" not in html


def test_render_job_card_omits_posted_meta_when_posted_is_missing():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-posted-missing",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "posted": "",
            "posted_age_days": None,
            "full_description": "Business analysis support across delivery teams.",
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "<strong>Posted</strong>" not in html


def test_render_job_card_requirement_coverage_omits_duplicate_matched_text():
    requirement = "Minimum 5 years experience as Business Analyst in digital environment"
    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "requirement_coverage": [
                {
                    "requirement": requirement,
                    "importance": "mandatory",
                    "status": "supported",
                    "capability_name": "acceptance testing",
                    "matched_job_text": requirement,
                    "profile_support": [],
                    "matched_candidate_fact": "acceptance testing",
                }
            ],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=True,
    )

    assert "job-requirements-panel" in html
    assert "job-coverage-panel" not in html
    assert "Job Requirements" in html
    assert "req-coverage-detail" in html
    assert "acceptance testing (Strong)" in html
    assert f'"{requirement}"' not in html


def test_render_job_card_requirement_coverage_shows_evidence_subtitles_in_normal_mode():
    requirement = "Minimum 5 years experience as Business Analyst in digital environment"
    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "requirement_coverage": [
                {
                    "requirement": requirement,
                    "importance": "mandatory",
                    "status": "supported",
                    "capability_name": "acceptance testing",
                    "matched_job_text": requirement,
                    "profile_support": [],
                    "matched_candidate_fact": "acceptance testing",
                }
            ],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=False,
    )

    assert "job-requirements-hint" not in html
    assert "req-coverage-detail" not in html
    assert "acceptance testing" not in html
    assert "acceptance testing (Strong)" not in html
    assert f'"{requirement}"' not in html


def test_render_job_card_requirement_coverage_hides_capability_badge_in_normal_mode():
    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "requirement_coverage": [
                {
                    "requirement": "Lead delivery across multiple initiatives",
                    "importance": "mandatory",
                    "status": "supported",
                    "capability_name": "agile delivery",
                    "matched_job_text": "Lead end-to-end delivery within Agile squads, working across multiple initiatives across data, technology, and change",
                    "profile_support": [],
                    "matched_candidate_fact": "agile delivery",
                }
            ],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=False,
    )

    assert '<span class="req-coverage-tag jh-badge">agile delivery</span>' not in html
    assert ">Capability<" not in html
    assert '<span class="req-coverage-detail-text">agile delivery</span>' not in html
    assert "job-requirement-status" not in html
    assert "Ad wording" not in html
    assert "Lead end-to-end delivery within Agile squads" not in html


def test_requirement_importance_badges_keep_shared_geometry_and_status_badges_are_removed():
    css = (
        Path(__file__).resolve().parents[1]
        / "templates"
        / "static"
        / "results"
        / "results-page.css"
    ).read_text(encoding="utf-8")

    assert ".job-requirement-status" not in css
    shared_selector = ".job-req-importance {"
    assert shared_selector in css

    badges_block = css.split(".job-requirement-badges {", 1)[1].split("}", 1)[0]
    assert "align-items: center;" in badges_block
    assert "gap: var(--control-space-xs);" in badges_block

    shared_block = css.split(shared_selector, 1)[1].split("}", 1)[0]
    for declaration in (
        "font-family: inherit;",
        "font-size: var(--font-size-2xs);",
        "font-weight: var(--text-role-status-font-weight);",
        "line-height: var(--chip-line-height);",
        "justify-content: center;",
    ):
        assert declaration in shared_block

def test_render_job_card_requirement_coverage_shows_ad_wording_in_debug_mode():
    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "requirement_coverage": [
                {
                    "requirement": "Lead delivery across multiple initiatives",
                    "importance": "mandatory",
                    "status": "supported",
                    "capability_name": "agile delivery",
                    "matched_job_text": "Lead end-to-end delivery within Agile squads, working across multiple initiatives across data, technology, and change",
                    "profile_support": [],
                    "matched_candidate_fact": "agile delivery",
                }
            ],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=True,
    )

    assert '<span class="req-coverage-tag jh-badge">agile delivery</span>' in html
    assert ">Capability<" not in html
    assert "Ad wording" in html
    assert "Lead end-to-end delivery within Agile squads" in html
    assert (
        '<span class="req-coverage-detail">'
        '<span class="req-coverage-tag jh-badge">agile delivery</span>'
        '<span class="req-coverage-tag jh-badge req-coverage-tag--muted">Ad wording</span>'
        in html
    )
    assert "req-coverage-detail--capability" not in html
    assert "req-coverage-detail--evidence" not in html


def test_render_job_card_requirement_coverage_shows_role_duration_note_in_normal_mode():
    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "requirement_coverage": [
                {
                    "requirement": "Minimum 5 years experience as Business Analyst",
                    "importance": "mandatory",
                    "status": "partially_supported",
                    "capability_name": "acceptance testing",
                    "matched_job_text": "Minimum 5 years experience as Business Analyst",
                    "profile_support": [],
                    "required_experience_months": 60,
                    "matched_role_family": "business analyst",
                    "matched_role_family_months": 36,
                    "matched_role_family_end_year": 2024,
                    "experience_requirement_met": False,
                    "experience_duration_gap": True,
                    "matched_candidate_fact": "acceptance testing",
                }
            ],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=False,
    )

    assert "Role history shows 36 months in business analyst, short of the 60 required months" in html
    assert "most recent end year 2024" in html
    assert "req-coverage-detail" not in html
    assert "Partial matches" in html
    assert "Needs attention" not in html


def test_render_job_card_requirement_coverage_shows_eligibility_details_in_debug_mode():
    html = workspace_renderer.render_job_card(
        {
            **_test_profile(),
            "requirement_coverage": [
                {
                    "requirement": "Hold PV security clearance",
                    "importance": "mandatory",
                    "requirement_type": "eligibility",
                    "requirement_subtype": "clearance",
                    "status": "supported",
                    "matched_candidate_fact": "PV clearance",
                    "eligibility_name": "PV clearance",
                    "capability_name": "",
                    "matched_job_text": "Must hold a PV clearance",
                    "profile_support": [],
                }
            ],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=True,
    )

    assert "job-clearance-panel" not in html
    assert "job-eligibility-panel" in html
    assert "Clearance" in html
    assert "req-coverage-detail" in html
    assert "PV clearance" in html


def test_render_job_card_shows_empty_requirements_state_when_none_are_extracted():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "linkedin:li-empty-reqs",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "SOLID",
            RECORD_FIT_SCORE_KEY: 65,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 65, "section": "llm_fit"}
            ],
            "requirement_coverage": [],
            "location": "Sydney NSW",
            "work_type": "Permanent",
            "work_mode": "On-site",
            "salary": "N/A",
            "full_description": "Role details and responsibilities. " * 20,
            "fit_source_text": "Role details and responsibilities. " * 20,
            "description_source": "linkedin_full_description",
            "details_status": "ok",
            "source": "linkedin",
        },
        _test_profile(),
    )

    assert "job-requirements-panel" in html
    assert "No requirements were extracted for this job." in html


def test_score_to_tone_class_uses_same_bands_as_match_labels():
    from job_hunter_agent.score_labels import score_to_tone_class

    assert score_to_tone_class(84) == "tone-good"
    assert score_to_tone_class(69) == "tone-borderline"
    assert score_to_tone_class(54) == "tone-low"


def test_applied_and_hidden_cards_render_undo_actions():
    base_record = {
        "job_key": "test-undo",
        "title": "Business Analyst",
        "company": "Acme",
        "url": "https://example.com/job",
        "title_reason": "OK",
        "content_reason": "OK",
        "llm_fit_grade": "SOLID",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "full_description": "Requirements elicitation across delivery teams. " * 40,
        "fit_highlights": [],
        "source": "seek",
    }

    applied_html = workspace_renderer.render_job_card(
        {**base_record, "applied": True}, _test_profile()
    )
    hidden_html = workspace_renderer.render_job_card(
        {**base_record, "hidden": True}, _test_profile()
    )

    assert 'data-review-action="unapply"' in applied_html
    assert "Undo Applied" in applied_html
    assert 'data-review-action="unhide"' in hidden_html
    assert ">Unhide<" in hidden_html


def test_workspace_review_buttons_and_title_block_keep_semantic_hooks():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-hooks",
            "title": "Senior Business Analyst (Contract Management)",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert (
        'class="review-button review-applied jh-button jh-button--primary jh-button--compact" '
        'type="button" data-review-action="applied"'
    ) in html
    assert (
        'class="review-button review-not-for-me jh-button jh-button--danger jh-button--compact" '
        'type="button" data-review-action="not_for_me"'
    ) in html
    assert (
        'class="review-button review-hide jh-button jh-button--secondary jh-button--compact" '
        'type="button" data-review-action="hidden"'
    ) in html
    assert (
        'class="title-block-btn workspace-text-action workspace-text-action--muted" '
        'type="button" data-review-action="block_similar"'
    ) in html
    assert ">Hide similar titles<" in html
    assert 'Phrase to block' in html
    assert 'data-job-key="test-hooks"' in html
    assert 'data-job-title="Senior Business Analyst (Contract Management)"' in html
    assert 'data-job-url="https://example.com/job"' in html


def test_possible_repost_card_carries_duplicate_apply_warning_details():
    # find_confirmed_duplicate only matches confirmed duplicates (same job_key or URL).
    # Use the same job_key in the applied pool to trigger the repost warning path.
    html = workspace_renderer.render_job_card(
        {
            "job_key": "seek:repost",
            "title": "Senior Business Analyst",
            "company": "Acme",
            "url": "https://example.com/new-role",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "linkedin",
        },
        _test_profile(),
        applied_pool=[
            {
                "job_key": "seek:repost",
                "title": "Business Analyst Senior",
                "company": "Acme",
                "source": "seek",
            }
        ],
    )

    assert "Possible Repost" not in html
    assert 'data-similar-applied-warning="1"' in html
    assert 'data-similar-applied-job-key="seek:repost"' in html
    assert 'data-similar-applied-title="Business Analyst Senior"' in html
    assert "Checks before applying" in html
    assert "Possible repost of applied job: Business Analyst Senior — Acme — SEEK" in html
    assert "job-note" not in html
    assert "job-action-rec" not in html


def test_attention_strip_prefers_red_flag_over_everything_else():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }

    with patch(
        "job_hunter_agent.workspace_renderer.assess_history_warning_signals",
        return_value=["Potential red flag: Suspicious reposting pattern"],
    ):
        html = workspace_renderer.render_job_card(
            {
                "job_key": "test-alert-red-flag",
                "title": "Business Analyst",
                "company": "Acme",
                "url": "https://example.com/job",
                "title_reason": "OK",
                "content_reason": "OK",
                "llm_fit_grade": "SOLID",
                "location": "Sydney NSW",
                "work_type": "Full Time",
                "work_mode": "Hybrid",
                "salary": "$100k p.a.",
                "full_description": "",
                "fit_highlights": [],
                "source": "seek",
                "candidate_application_history": {
                    "llm_application_status": "rejection",
                    "llm_confidence": "high",
                    "llm_needs_review": False,
                    "llm_company": "Acme",
                    "llm_role": "Business Analyst",
                    "run_date": "2025-01-15",
                    "llm_evidence": "Thanks for applying",
                },
            },
            profile,
            applied_pool=[
                {
                    "job_key": "test-alert-red-flag",
                    "title": "Business Analyst",
                    "company": "Acme",
                    "source": "seek",
                }
            ],
    )

    assert "Checks before applying" in html
    assert "Suspicious reposting pattern." in html
    assert "Description issue: full job description was not captured clearly." in html
    assert "Possible repost of applied job: Business Analyst — Acme — SEEK" in html
    assert "Rejected before: Acme — Business Analyst" in html
    assert "Salary below target." in html


def test_attention_strip_prefers_description_issue_over_lower_priority_alerts():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-alert-description",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "$100k p.a.",
            "teaser": "Business analyst role.",
            "fit_highlights": [],
            "source": "seek",
            "candidate_application_history": {
                "llm_application_status": "rejection",
                "llm_confidence": "high",
                "llm_needs_review": False,
                "llm_company": "Acme",
                "llm_role": "Business Analyst",
                "run_date": "2025-01-15",
                "llm_evidence": "Thanks for applying",
            },
        },
        profile,
        applied_pool=[
            {
                "job_key": "test-alert-description",
                "title": "Business Analyst",
                "company": "Acme",
                "source": "seek",
            }
        ],
    )

    assert "Checks before applying" in html
    assert "Description issue: full job description was not captured clearly." in html
    assert "Possible repost of applied job: Business Analyst — Acme — SEEK" in html
    assert "Rejected before: Acme — Business Analyst" in html
    assert "Salary below target." in html


def test_checks_before_applying_returns_all_items_without_truncation():
    items = workspace_renderer._build_checks_before_applying_items(
        history_warning_signals=[
            "Potential red flag: Suspicious reposting pattern",
            "Potential red flag: Repeated role refreshes",
        ],
        description_issue=True,
        is_possible_repost=True,
        similar_applied_record={
            "title": "Business Analyst",
            "company": "Acme",
            "source": "seek",
        },
        candidate_history={
            "llm_application_status": "rejection",
            "llm_confidence": "high",
            "llm_company": "Acme",
            "llm_role": "Business Analyst",
        },
        hard_block_reasons_list=[
            "Missing mandatory requirement: SAP certification",
        ],
        salary_fit_state="below",
        soft_risk_reasons=[
            "Freshness may be unreliable — LinkedIn can show a reposted date for external-apply listings, and the original posting date could not be verified."
        ],
        job_quality_signals=[
            {
                "label": "Broad Ad",
                "evidence": 'Ad lists both permanent and contract work types ("full time contract") — may be a wide talent-pool search rather than a specific vacancy.',
            }
        ],
    )

    assert items == [
        "Suspicious reposting pattern.",
        "Repeated role refreshes.",
        "Description issue: full job description was not captured clearly.",
        "Possible repost of applied job: Business Analyst — Acme — SEEK",
        "Rejected before: Acme — Business Analyst",
        "Salary below target.",
        "Missing mandatory requirement: SAP Certification",
        "Freshness may be unreliable — LinkedIn can show a reposted date for external-apply listings, and the original posting date could not be verified.",
        'Ad lists both permanent and contract work types ("full time contract") — may be a wide talent-pool search rather than a specific vacancy.',
    ]


def test_candidate_application_history_warnings_stay_in_checks_panel_without_changing_score():
    base_record = {
        "job_key": "test-candidate-history",
        "title": "Business Analyst",
        "company": "Acme",
        "url": "https://example.com/job",
        "title_reason": "OK",
        "content_reason": "OK",
        "llm_fit_grade": "SOLID",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "full_description": "Requirements elicitation across delivery teams. " * 40,
        "fit_highlights": [],
        "source": "seek",
    }
    with_history = {
        **base_record,
        "candidate_application_history": {
            "llm_application_status": "rejection",
            "llm_confidence": "high",
            "llm_needs_review": True,
            "llm_company": "Acme",
            "llm_role": "Business Analyst",
            "run_date": "2025-01-15",
            "llm_evidence": "We regret to inform you",
            "llm_review_reason": "Company mismatch needs a manual check.",
        },
    }

    plain_html = workspace_renderer.render_job_card(base_record, _test_profile())
    history_html = workspace_renderer.render_job_card(
        with_history, _test_profile(), debug_mode=False
    )

    assert 'data-fit-score="' in plain_html
    assert 'data-fit-score="' in history_html
    assert (
        plain_html.split('data-fit-score="', 1)[1].split('"', 1)[0]
        == history_html.split('data-fit-score="', 1)[1].split('"', 1)[0]
    )
    assert "Checks before applying" in history_html
    assert "Rejected before: Acme — Business Analyst" in history_html
    assert "Possible previous application" not in history_html
    assert "Needs review" not in history_html
    assert "Acme" in history_html
    assert "Role: Business Analyst" in history_html
    assert "Confidence: high" not in history_html
    assert "Evidence: We regret to inform you" in history_html
    assert "Review reason: Company mismatch needs a manual check." not in history_html


def test_attention_strip_shows_salary_below_target_when_it_is_the_last_remaining_issue():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-alert-salary",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "$100k p.a.",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        profile,
    )

    assert "Checks before applying" in html
    assert "Salary below target." in html
    assert "Description issue:" not in html
    assert "Possible repost of applied job:" not in html
    assert "Rejected before:" not in html


def test_candidate_application_history_possible_rejection_uses_possible_previous_application_label():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-candidate-history-possible",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            "candidate_application_history": {
                "llm_application_status": "possible_rejection",
                "llm_confidence": "medium",
                "llm_needs_review": False,
                "llm_company": "Acme",
                "llm_role": "Business Analyst",
                "run_date": "2025-01-15",
                "llm_evidence": "Application mentioned",
            },
        },
        _test_profile(),
    )

    assert "Possible previous application" in html
    assert "Needs review" not in html


def test_candidate_application_history_low_confidence_uses_possible_previous_application_label():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-candidate-history-low-confidence",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            "candidate_application_history": {
                "llm_application_status": "unknown",
                "llm_confidence": "low",
                "llm_needs_review": False,
                "llm_company": "Acme",
                "llm_role": "Business Analyst",
                "run_date": "2025-01-15",
                "llm_evidence": "Application mentioned",
            },
        },
        _test_profile(),
    )

    assert "Possible previous application" in html
    assert "Needs review" not in html


def test_candidate_application_history_renders_expanded_details_section():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-candidate-history-details",
            "title": "Technical Analyst",
            "company": "MUFG Pension & Market Services",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            "candidate_application_history": {
                "llm_application_status": "rejection",
                "llm_confidence": "high",
                "llm_needs_review": True,
                "llm_company": "MUFG Pension & Market Services",
                "llm_role": "Technical Analyst",
                "run_date": "5/7/2026 18:37:57",
                "_match_confidence": "medium",
                "_company_match_reason": "Company token-overlap match",
                "llm_evidence": "Thank you for your recent application for the Technical Analyst role within MUFG Pension & Market Services. "
                "We appreciate your interest in the position and have completed our review. "
                "This is a longer note so the workspace should show it in full without truncating.",
                "llm_review_reason": "Company mismatch needs a manual check.",
            },
        },
        _test_profile(),
        debug_mode=True,
    )

    assert "Candidate application history" in html
    assert "MUFG Pension &amp; Market Services — 7 May 2026" in html
    assert "5/7/2026 18:37:57" not in html
    assert "Role: Technical Analyst" in html
    # Classification / company-match confidence values are no longer rendered.
    assert "Confidence: high" not in html
    assert "Company match confidence" not in html
    assert "Company match reason" not in html
    # Evidence shows in full, no truncation.
    assert "Evidence: Thank you for your recent application" in html
    assert "show it in full without truncating." in html
    assert "..." not in html.split("Evidence:")[1].split("</li>")[0]
    assert "Review reason: Company mismatch needs a manual check." in html

    risk_start = html.index('<details class="job-insights job-risk-panel">')
    risk_end = html.index("</details>", risk_start)
    risk_panel_html = html[risk_start:risk_end]
    assert "Candidate application history" in risk_panel_html
    assert '<details class="job-candidate-history">' not in html


def test_candidate_application_history_review_reason_is_debug_only():
    record = {
        "job_key": "test-candidate-history-diagnostics",
        "title": "Technical Analyst",
        "company": "Acme",
        "url": "https://example.com/job",
        "title_reason": "OK",
        "content_reason": "OK",
        "llm_fit_grade": "SOLID",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "full_description": "Requirements elicitation across delivery teams. " * 40,
        "fit_highlights": [],
        "source": "seek",
        "candidate_application_history": {
            "llm_application_status": "rejection",
            "llm_confidence": "high",
            "llm_company": "Acme",
            "llm_role": "Technical Analyst",
            "run_date": "2026-05-07",
            "_match_confidence": "medium",
            "_company_match_reason": "Company token-overlap match",
            "llm_evidence": "We regret to inform you",
            "llm_review_reason": "Needs manual review",
        },
    }

    normal_html = workspace_renderer.render_job_card(
        record, _test_profile(), debug_mode=False
    )
    debug_html = workspace_renderer.render_job_card(record, _test_profile(), debug_mode=True)

    assert "Role: Technical Analyst" in normal_html
    assert "Evidence: We regret to inform you" in normal_html

    # Classification / company-match confidence values are never rendered.
    for dropped in (
        "Confidence: high",
        "Company match confidence: medium",
        "Company match reason: Company token-overlap match",
    ):
        assert dropped not in normal_html
        assert dropped not in debug_html

    # The review reason stays debug-only.
    assert "Review reason: Needs manual review" not in normal_html
    assert "Review reason: Needs manual review" in debug_html


def test_candidate_application_history_renders_escaped_values_safely():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-candidate-history-escape",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            "candidate_application_history": {
                "llm_application_status": "rejection",
                "llm_confidence": "high",
                "llm_needs_review": True,
                "llm_company": "<Acme & Co>",
                "llm_role": "Business Analyst <script>",
                "run_date": "2026-05-07",
                "llm_evidence": "Evidence with <tag> & more",
                "llm_review_reason": "Needs <manual> review & approval",
            },
        },
        _test_profile(),
        debug_mode=True,
    )

    assert "&lt;Acme &amp; Co&gt;" in html
    assert "Business Analyst &lt;script&gt;" in html
    assert "Evidence with &lt;tag&gt; &amp; more" in html
    assert "Needs &lt;manual&gt; review &amp; approval" in html
    assert "<Acme & Co>" not in html
    assert "<script>" not in html


def test_job_card_formats_opened_by_you_as_date_only():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-opened-by-you-date",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            "times_viewed": 1,
            "last_viewed_at": "2026-08-17T13:05:00+10:00",
        },
        _test_profile(),
        debug_mode=False,
    )

    assert "Opened by you 17 Aug 2026" in html
    assert "Opened by you 17 Aug 2026 01:05 PM" not in html


def test_potential_duplicate_card_shows_compact_related_cards_section():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "seek:new-role",
            "title": "Senior Business Analyst",
            "company": "Acme Pty Ltd",
            "url": "https://example.com/new-role",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            "potential_duplicate_links": [
                {
                    "kind": "potential_duplicate",
                    "matched_on": ["base_role", "company_name"],
                    "related_job_key": "linkedin:2",
                    "related_title": "Senior Business Analyst",
                    "related_company": "Acme Pty Ltd",
                    "related_source": "linkedin",
                    "related_url": "https://example.com/related-role",
                }
            ],
        },
        _test_profile(),
    )

    assert 'Related cards (1)' in html
    assert 'job-related-cards-panel' in html
    assert html.index('class="job-meta"') < html.index('job-related-cards-panel')
    assert html.count('class="job-related-card-row"') == 1
    assert 'class="job-related-card-title">Senior Business Analyst</strong>' in html
    assert 'class="job-related-card-company">acme' in html
    assert "Open matching card" in html
    assert "&#8594;" in html
    assert 'href="#job-card-linkedin-2"' in html
    assert 'data-related-card-target="job-card-linkedin-2"' in html


def test_potential_duplicate_card_renders_all_related_cards_in_one_disclosure():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "seek:new-role",
            "title": "Senior Business Analyst",
            "company": "Acme Pty Ltd",
            "url": "https://example.com/new-role",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            "potential_duplicate_links": [
                {
                    "related_job_key": "linkedin:2",
                    "related_title": "Senior Business Analyst",
                    "related_company": "Acme Pty Ltd",
                },
                {
                    "related_job_key": "apsjobs:3",
                    "related_title": "Senior Business Analyst",
                    "related_company": "Acme Pty Ltd",
                },
            ],
        },
        _test_profile(),
    )

    assert 'Related cards (2)' in html
    assert html.count('class="job-related-card-row"') == 2
    assert 'href="#job-card-linkedin-2"' in html
    assert 'href="#job-card-apsjobs-3"' in html
    assert html.count('Open matching card') == 2


def test_positive_note_does_not_repeat_first_why_it_fits_bullet():
    profile = {
        **_test_profile(),
        "candidate_capabilities": [
            {
                "name": "multi-client delivery",
                "level": "strong",
                "fit": "core",
                "aliases": ["multiple client transition projects"],
            }
        ],
    }
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-repetition",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across multiple client transition projects. "
            * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        profile,
    )

    assert "Why this is a good fit" not in html
    assert "The ad asks for Multi-client delivery, and your profile shows this experience." not in html
    assert "Multi-client delivery — shown in profile" not in html


def test_low_confidence_card_shows_single_description_issue_section():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-low-description",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "teaser": "Business analyst role.",
            "fit_highlights": [],
            "source": "linkedin",
        },
        _test_profile(),
    )

    assert "Checks before applying" in html
    assert html.count("Description issue: full job description was not captured clearly.") == 1
    assert "<strong>Missing evidence</strong>" not in html
    assert "Risks &amp; missing evidence" not in html

    risk_start = html.index('<details class="job-insights job-risk-panel">')
    risk_end = html.index("</details>", risk_start)
    risk_panel_html = html[risk_start:risk_end]
    assert "Checks before applying" in risk_panel_html
    assert "Description issue: full job description was not captured clearly." in risk_panel_html
    assert "Why this is a good fit" not in html


def test_deterministic_review_counts_only_capability_highlights():
    from job_hunter_agent.source_learning import deterministic_review_outcome

    assert deterministic_review_outcome(
        {"title_reason": "OK"},
        {},
        [
            "Government context",
            "12+ month contract",
            "Location matches primary preference: Sydney NSW",
        ],
        [],
        [],
    ) is None

    assert deterministic_review_outcome(
        {"title_reason": "OK"},
        {},
        [
            "Strong capability match: Delivery teams",
            "Strong capability match: Process improvement",
            "Strong capability match: Stakeholder management",
        ],
        [],
        [],
    ) == {"decision": "KEEP", "grade": "SOLID", "det_rule": "solid"}


def test_fit_score_breakdown_raises_without_llm_review():
    with pytest.raises(RuntimeError, match="Cannot score job without LLM review"):
        fit_scoring.fit_score_breakdown(_workspace_record(), _test_profile())


def test_fit_score_breakdown_raises_with_partial_llm_review():
    # decision present but grade missing — still raises, not silently degraded
    with pytest.raises(RuntimeError, match="Cannot score job without LLM review"):
        fit_scoring.fit_score_breakdown(_workspace_record(llm_decision="KEEP"), _test_profile())


def test_salary_fit_label_marks_scores_above_target_as_meets():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }

    from job_hunter_agent.score_labels import salary_fit_label

    assert salary_fit_label({"salary": "$130k-$145k p.a."}, profile) == "meets"
    assert salary_fit_label({"salary": "$750 per day"}, profile) == "meets"
    assert salary_fit_label({"salary": "$100k p.a."}, profile) == "below"
    assert salary_fit_label({"salary": "$650 per day"}, profile) == "below"


def test_salary_fit_ignores_non_comparable_hourly_and_monthly_rates():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }

    from job_hunter_agent.preferences import salary_fit_adjustment

    assert salary_fit_adjustment({"salary": "$90/hr"}, profile) == 0
    assert salary_fit_adjustment({"salary": "$8,000 per month"}, profile) == 0
    assert salary_fit_adjustment({"salary": "$650 p/d"}, profile) < 0


def test_salary_fit_ignores_yearly_package_and_including_super_amounts():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }

    from job_hunter_agent.preferences import salary_fit_adjustment

    assert salary_fit_adjustment({"salary": "$130k package"}, profile) == 0
    assert salary_fit_adjustment({"salary": "$130k incl super"}, profile) == 0
    from job_hunter_agent.score_labels import salary_fit_label

    assert salary_fit_label({"salary": "$130k + super"}, profile) == "listed"


def test_render_job_card_keeps_bare_contract_salary_without_invented_period():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-salary-period-hint",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract",
            "work_mode": "Hybrid",
            "salary": "$125",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "Salary</strong> $125" in html
    assert "Salary</strong> $125/hr" not in html
    assert "Salary</strong> $125 p.a." not in html


def test_salary_fit_adjustment_can_use_profile_scoring_rule_overrides():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
        "scoring_rules": {
            "salary": {
                "meeting_target": 11,
                "below_target_near_min_ratio": 0.9,
                "below_target_near_adjustment": -2,
            }
        },
    }

    from job_hunter_agent.preferences import salary_fit_adjustment

    assert salary_fit_adjustment({"salary": "$130k-$145k p.a."}, profile) == 11
    assert salary_fit_adjustment({"salary": "$110k p.a."}, profile) == -2


def test_profile_recency_multiplier_uses_tiered_evidence_dates():
    current_year = datetime.now().year
    profile = {
        **_test_profile(),
        "cv_text": f"delivery leadership old from {current_year - 6}",
        KEY_EVIDENCE_TIERS: {
            KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT: f"{current_year - 1} - present: delivery leadership",
            KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT: "",
            KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT: "",
        },
    }

    from job_hunter_agent.scoring_utils import (
        find_profile_experience_year_in_text,
        profile_recency_multiplier,
    )

    assert (
        find_profile_experience_year_in_text(
            profile[KEY_EVIDENCE_TIERS][KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT],
            ["delivery leadership"],
        )
        == current_year
    )
    assert profile_recency_multiplier(profile, ["delivery leadership"]) == 1.0


def test_workspace_record_sets_rank_current_records_by_score_before_age(monkeypatch):
    monkeypatch.setattr(
        workspace_service, "fit_score_displayed", lambda record, profile=None: int(record["score"])
    )
    monkeypatch.setattr(
        workspace_service,
        "is_workspace_eligible",
        lambda record, profile=None, workspace_min_score=None: True,
    )

    records = [
        {"job_key": "fresh-low", "score": 55, "posted_age_days": 0.1, "times_viewed": 0},
        {"job_key": "older-high", "score": 90, "posted_age_days": 5, "times_viewed": 0},
        {"job_key": "fresh-mid", "score": 70, "posted_age_days": 0.2, "times_viewed": 0},
    ]

    workspace_records = workspace_service.build_workspace_record_sets(
        records,
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        reference_time=datetime(2026, 4, 21),
        scoring_profile={"match_levels": []},
    )

    assert [record["job_key"] for record in workspace_records["current_records"]] == [
        "older-high",
        "fresh-mid",
        "fresh-low",
    ]


def test_workspace_record_sets_never_include_rejected_rows(monkeypatch):
    monkeypatch.setattr(
        workspace_service, "fit_score_displayed", lambda record, profile=None: int(record["score"])
    )
    monkeypatch.setattr(
        workspace_service,
        "is_workspace_eligible",
        lambda record, profile=None, workspace_min_score=None: int(record["score"]) >= 55,
    )

    records = [
        {
            "job_key": "fresh-high",
            "score": 90,
            "posted_age_days": 0.1,
            "times_viewed": 0,
            "decision": "KEEP",
        },
        {
            "job_key": "fresh-low",
            "score": 40,
            "posted_age_days": 0.2,
            "times_viewed": 0,
            "decision": "KEEP",
        },
    ]

    workspace_records = workspace_service.build_workspace_record_sets(
        records,
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        reference_time=datetime(2026, 4, 21),
        scoring_profile={"match_levels": []},
        workspace_min_score=55,
    )

    assert [record["job_key"] for record in workspace_records["current_records"]] == ["fresh-high"]


def test_is_workspace_eligible_uses_saved_workspace_minimum_score(monkeypatch):
    monkeypatch.setattr(workspace_service, "passes_title_filters", lambda title: (True, "OK"))
    monkeypatch.setattr(
        workspace_service, "fit_score_displayed", lambda record, profile=None: int(record["score"])
    )
    monkeypatch.setattr(workspace_service, "get_workspace_minimum_score", lambda: 60)

    from job_hunter_agent.workspace_service import is_workspace_eligible

    valid_record = {
        "title": "Business Analyst",
        "score": 60,
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        "requirement_coverage": [
            {"requirement": "Business analysis", "importance": "mandatory", "status": "supported"}
        ],
    }

    assert is_workspace_eligible(valid_record) is True
    assert is_workspace_eligible({**valid_record, "score": 59}) is False


def test_is_workspace_eligible_preserves_kept_jobs_when_title_filters_change(monkeypatch):
    monkeypatch.setattr(workspace_service, "passes_title_filters", lambda title: (False, "TITLE_NOT_TARGET"))
    monkeypatch.setattr(
        workspace_service, "fit_score_displayed", lambda record, profile=None: int(record["score"])
    )
    monkeypatch.setattr(workspace_service, "get_workspace_minimum_score", lambda: 30)

    from job_hunter_agent.workspace_service import is_workspace_eligible

    kept_record = {
        "title": "Senior Business Analysts - Canberra, Brisbane, Melbourne and Sydney",
        "score": 94,
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        "requirement_coverage": [
            {"requirement": "Business analysis", "importance": "mandatory", "status": "supported"}
        ],
    }

    assert is_workspace_eligible(kept_record) is True


def test_is_workspace_eligible_excludes_stored_jobs_matching_explicit_title_block(
    monkeypatch,
):
    monkeypatch.setattr(
        workspace_service,
        "fit_score_displayed",
        lambda record, profile=None: int(record["score"]),
    )
    monkeypatch.setattr(workspace_service, "get_workspace_minimum_score", lambda: 30)

    from job_hunter_agent.workspace_service import is_workspace_eligible

    base_record = {
        "title": "ServiceNow Business Analyst",
        "score": 94,
        "llm_decision": "KEEP",
        "llm_fit_grade": "STRONG",
        "requirement_coverage": [
            {"requirement": "Business analysis", "importance": "mandatory", "status": "supported"}
        ],
    }
    profile = {"reject_title_rules": [build_title_block_rule("servicenow")]}

    assert is_workspace_eligible(base_record, profile) is False
    assert is_workspace_eligible({**base_record, "title": "Business Analyst"}, profile) is True


def test_score_filter_thresholds_hide_lowest_band_when_no_borderline_roles():
    thresholds = workspace_renderer.score_filter_thresholds(
        scoring_profile={},
        workspace_min_score=55,
    )

    assert thresholds == [85, 70, 55]


def test_score_filter_thresholds_show_lowest_band_when_floor_allows_it():
    thresholds = workspace_renderer.score_filter_thresholds(
        scoring_profile={},
        workspace_min_score=0,
    )

    assert thresholds == [85, 70, 55, 0]


def test_score_filter_thresholds_include_all_bands_in_debug_mode():
    thresholds = workspace_renderer.score_filter_thresholds(
        scoring_profile={},
        workspace_min_score=55,
        debug_mode=True,
    )

    assert thresholds == [85, 70, 55, 0]


def test_score_filter_options_use_match_labels_not_raw_thresholds():
    options_html = workspace_renderer.render_score_filter_options(
        scoring_profile={},
        workspace_min_score=55,
    )

    assert "All match levels" in options_html
    assert "Strong match only" in options_html
    assert "Good match or better" in options_html
    assert "Possible fit or better" in options_html
    assert "Stretch or better" not in options_html
    assert "50+ only" not in options_html


def test_score_filter_options_include_lowest_match_band_when_floor_allows_it():
    options_html = workspace_renderer.render_score_filter_options(
        scoring_profile={},
        workspace_min_score=0,
    )

    assert "Stretch or better" in options_html


def test_score_filter_options_default_to_all_in_debug_mode():
    options_html = workspace_renderer.render_score_filter_options(
        scoring_profile={},
        workspace_min_score=55,
        debug_mode=True,
    )

    assert '<option value="all" selected>All match levels</option>' in options_html
    assert 'value="0"' in options_html


def test_render_job_card_debug_mode_shows_filter_status_for_rejected_rows(monkeypatch):
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-debug-filter",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "TITLE_NOT_TARGET",
            "content_reason": "DESC_HARD_BLOCK_RULE:java",
            "reject_reason": "DESC_HARD_BLOCK_RULE:java",
            "decision": "REJECT",
            "hard_block_reasons": ["Java"],
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
        debug_mode=True,
    )

    assert "Hard blocked" in html
    assert "Filter status" not in html
    assert "Title filter" not in html


def test_render_job_card_debug_mode_shows_debug_only_label_for_non_blocker_rejections(monkeypatch):
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-debug-only",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "TITLE_NOT_TARGET",
            "content_reason": "OK",
            "reject_reason": "TITLE_NOT_TARGET",
            "decision": "REJECT",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
        debug_mode=True,
    )

    assert "Debug only" in html
    assert "Filter status" not in html
    assert "Title outside target role family" not in html


def test_render_job_card_shows_llm_review_section_in_debug_mode():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-llm-rationale",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            "llm_debug_reason": "Strong requirement coverage — 3 supported requirements with direct capability links.",
            RECORD_FIT_SCORE_KEY: 72,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 72, "section": "llm_fit"},
                {
                    "label": "Possible capability match — mentioned in the job, but not strong enough to affect the score.",
                    "value": 0,
                    "section": "capability",
                },
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=True,
    )

    assert "Debug: LLM fit review" in html
    assert "Final decision: KEPT" in html
    assert "Final score" in html
    assert "LLM fit grade" in html
    assert "Eligibility gate:" in html
    assert "Score breakdown" in html
    assert "Debug reason" not in html
    assert "Base fit: +72" in html


def test_render_job_card_debug_audit_shows_evidence_credit_and_decision_conversion():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-scoring-audit",
            "title": "Solutions Lead",
            "company": "Acme Health",
            "url": "https://example.com/job",
            "title_reason": "TITLE_POTENTIAL_MATCH",
            "content_reason": "OK",
            "review_source": "llm",
            "decision": "KEEP",
            "llm_decision": "MAYBE",
            "llm_fit_grade": "WEAK",
            RECORD_FIT_SCORE_KEY: 82,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Requirement Fit: 82%", "value": 82, "section": "requirement_fit"},
            ],
            "requirement_coverage": [
                {
                    "requirement": "5–7 years in digital health",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "status": "supported",
                    "matched_candidate_fact": "stakeholder engagement",
                    "capability_name": "stakeholder engagement",
                    "match_source": "related_skill",
                    "matched_profile_term": "health program delivery",
                    "matched_job_text": "5–7 years' experience in digital health",
                    "profile_support": ["Facilitated health-program stakeholders."],
                },
                {
                    "requirement": "Australian citizenship",
                    "importance": "preferred",
                    "requirement_type": "eligibility",
                    "status": "mismatch",
                    "matched_candidate_fact": "",
                    "profile_support": [],
                },
                {
                    "requirement": "Domain architecture",
                    "importance": "mandatory",
                    "requirement_type": "capability",
                    "status": "supported",
                    "matched_candidate_fact": "",
                    "profile_support": [],
                },
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Digital health solution leadership. " * 40,
            "fit_highlights": [],
            "source": "linkedin",
        },
        _capability_profile(),
        debug_mode=True,
    )

    assert "Scoring audit" in html
    assert "5–7 years in digital health" in html
    assert "Facilitated health-program stakeholders." in html
    assert "stakeholder engagement (Strong)" in html
    assert "Requirement type" in html
    assert "Matched via" in html
    assert "Matched term" in html
    assert "Related Skill" in html
    assert "health program delivery" in html
    assert "Calculation" in html
    assert "3 × 1 × 1 = 3 / 3" in html
    assert "Australian citizenship" in html
    assert "Domain architecture" in html
    assert "Unresolved mapping" in html
    assert "No profile evidence returned" in html
    assert "Earned weighted credit:" in html
    assert "Total requirement weight:" in html
    assert "Final Requirement Fit:" in html
    assert "Decision trace" in html
    assert "Full LLM review: Run" in html
    assert "Final conversion: MAYBE → KEEP" in html
    assert "Eligibility gate: Not applicable" in html


def test_render_job_card_hides_debug_fit_sections_in_normal_mode():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-normal-fit-sections",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            "llm_debug_reason": "Strong requirement coverage — 3 supported requirements with direct capability links.",
            RECORD_FIT_SCORE_KEY: 72,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 72, "section": "llm_fit"},
                {"label": "Possible capability match — mentioned in the job, but not strong enough to affect the score.", "value": 0, "section": "capability"},
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=False,
    )

    assert "Debug: LLM fit review" not in html
    assert "Debug: score details" not in html
    assert "Debug: scoring notes" not in html
    assert "Scoring audit" not in html
    assert "Base fit" not in html
    assert "Strong requirement coverage" not in html


def test_render_job_card_folds_debug_fit_internals_into_llm_review_panel_without_llm_data():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-debug-fit-internals-no-llm",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "TITLE_NOT_TARGET",
            "content_reason": "OK",
            "reject_reason": "TITLE_NOT_TARGET",
            "decision": "REJECT",
            RECORD_FIT_SCORE_KEY: 40,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 40, "section": "llm_fit"},
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=True,
    )

    assert "Debug: LLM fit review" in html
    debug_start = html.index('<details class="job-insights job-llm-review">')
    debug_end = html.index("</details>", debug_start)
    debug_panel_html = html[debug_start:debug_end]
    assert "Score breakdown" in debug_panel_html
    assert "Final decision" not in debug_panel_html


def test_render_job_card_fit_breakdown_starts_with_plain_english_summary_from_requirement_coverage_explicit_record_key():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-fit-summary-coverage",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            RECORD_FIT_SCORE_KEY: 72,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 72, "section": "llm_fit"},
            ],
            "requirement_coverage": [
                {
                    "requirement": "Agile delivery",
                    "importance": "mandatory",
                    "status": "supported",
                    "capability_name": "Agile methodologies",
                    "matched_job_text": "agile delivery",
                    "profile_support": ["agile"],
                    "matched_candidate_fact": "Agile methodologies",
                },
                {
                    "requirement": "Stakeholder engagement",
                    "importance": "strongly_preferred",
                    "status": "partially_supported",
                    "capability_name": "Primary stakeholder engagement",
                    "matched_job_text": "stakeholder engagement",
                    "profile_support": ["stakeholder engagement"],
                    "matched_candidate_fact": "Primary stakeholder engagement",
                },
                {
                    "requirement": "User acceptance testing",
                    "importance": "preferred",
                    "status": "supported",
                    "capability_name": "Acceptance testing",
                    "matched_job_text": "user acceptance testing",
                    "profile_support": ["uat"],
                    "matched_candidate_fact": "Acceptance testing",
                },
                {
                    "requirement": "SAP certification",
                    "importance": "mandatory",
                    "status": "mismatch",
                    "capability_name": "",
                    "matched_job_text": "SAP certification",
                    "profile_support": [],
                    "matched_candidate_fact": "",
                },
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": (
                "The role needs agile delivery, stakeholder engagement, and user acceptance testing experience. "
                * 20
            ),
            "fit_source_text": (
                "The role needs agile delivery, stakeholder engagement, and user acceptance testing experience. "
                * 20
            ),
            "description_source": "linkedin_full_description",
            "details_status": "ok",
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=False,
    )

    expected_summary = (
        "This role looks like a good fit because the ad asks for Agile delivery, "
        "Stakeholder engagement, and User acceptance testing, and the candidate profile shows support for those areas."
    )

    assert "Why this is a good fit" not in html
    assert expected_summary not in html
    assert '<span class="job-requirement-title-line">Agile delivery' in html
    assert '<span class="job-requirement-title-line">Stakeholder engagement' in html
    assert '<span class="job-requirement-title-line">User acceptance testing' in html
    assert "Agile methodologies" not in html
    assert "SAP certification" not in expected_summary


def test_render_job_card_fit_breakdown_does_not_invent_summary_when_requirement_coverage_missing():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-fit-summary-fallback",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            RECORD_FIT_SCORE_KEY: 68,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 68, "section": "llm_fit"},
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": (
                "This role focuses on agile delivery and user acceptance testing across delivery teams. "
                * 20
            ),
            "fit_source_text": (
                "This role focuses on agile delivery and user acceptance testing across delivery teams. "
                * 20
            ),
            "description_source": "linkedin_full_description",
            "details_status": "ok",
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=False,
    )

    assert "job-fit-summary" not in html
    assert "Base fit" not in html
    assert "Why this is a good fit" not in html


def test_workspace_record_sets_exclude_kept_jobs_without_complete_llm_data(monkeypatch):
    monkeypatch.setattr(workspace_service, "passes_title_filters", lambda title: (True, "OK"))
    monkeypatch.setattr(
        workspace_service, "fit_score_displayed", lambda record, profile=None: int(record["score"])
    )

    records = [
        {
            "job_key": "complete-keep",
            "score": 90,
            "posted_age_days": 0.1,
            "times_viewed": 0,
            "title": "Business Analyst",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "importance": "mandatory",
                    "status": "supported",
                }
            ],
        },
        {
            "job_key": "incomplete-keep",
            "score": 99,
            "posted_age_days": 0.2,
            "times_viewed": 0,
            "title": "Business Analyst",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            "requirement_coverage": [],
        },
    ]

    workspace_records = workspace_service.build_workspace_record_sets(
        records,
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        reference_time=datetime(2026, 4, 21),
        scoring_profile={"match_levels": []},
    )

    assert [record["job_key"] for record in workspace_records["current_records"]] == [
        "complete-keep"
    ]


def test_posted_filter_options_show_explicit_day_windows():
    options_html = workspace_renderer.render_posted_filter_options(
        [
            {"posted_age_days": 0.25},
            {"posted_age_days": 2},
            {"posted_age_days": 4},
            {"posted_age_days": None},
        ]
    )

    assert "Any posted date (4)" in options_html
    assert "Posted today (1)" in options_html
    assert "Last 3 days (2)" in options_html
    assert "Last 7 days (3)" in options_html
    # Last 14/30 days would repeat the same count as Last 7 days (no jobs
    # older than 4 days in this fixture), so they're omitted as redundant.
    assert "Last 14 days" not in options_html
    assert "Last 30 days" not in options_html


def test_posted_filter_options_omit_windows_that_repeat_the_same_count():
    options_html = workspace_renderer.render_posted_filter_options(
        [
            {"posted_age_days": 0.25},
            {"posted_age_days": 0.5},
        ]
    )

    assert "Any posted date (2)" in options_html
    assert "Posted today (2)" in options_html
    # Every job is already captured by "Posted today", so every wider
    # window would show the same count (2) and is left out entirely.
    assert "Last 3 days" not in options_html
    assert "Last 7 days" not in options_html
    assert "Last 14 days" not in options_html
    assert "Last 30 days" not in options_html
    # assert "Last 30 days (3)" in options_html


def test_workspace_renders_requirement_coverage_with_status_classes():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "seek:req-cov-test",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "SOLID",
            RECORD_FIT_SCORE_KEY: 65,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 65, "section": "llm_fit"}
            ],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "importance": "mandatory",
                    "status": "supported",
                    "capability_name": "stakeholder engagement",
                    "matched_job_text": "work with stakeholders",
                    "profile_support": ["stakeholder management"],
                    "matched_candidate_fact": "stakeholder engagement",
                },
                {
                    "requirement": "Agile delivery",
                    "importance": "strongly_preferred",
                    "status": "partially_supported",
                    "capability_name": "agile methodologies",
                    "matched_job_text": "agile ceremonies",
                    "profile_support": [],
                    "matched_candidate_fact": "agile methodologies",
                },
                {
                    "requirement": "Reporting",
                    "importance": "preferred",
                    "status": "supported",
                    "capability_name": "reporting",
                    "matched_job_text": "regular reporting",
                    "profile_support": [],
                    "matched_candidate_fact": "reporting",
                },
                {
                    "requirement": "SAP certification",
                    "importance": "mandatory",
                    "status": "mismatch",
                    "capability_name": "",
                    "matched_job_text": "SAP required",
                    "profile_support": [],
                    "matched_candidate_fact": "",
                },
                {
                    "requirement": "Financial reporting",
                    "importance": "bonus",
                    "status": "not_shown",
                    "capability_name": "",
                    "matched_job_text": "",
                    "profile_support": [],
                    "matched_candidate_fact": "",
                },
                {
                    "requirement": "PV clearance",
                    "importance": "mandatory",
                    "status": "invalid",
                    "requirement_type": "credential",
                    "capability_name": "",
                    "matched_job_text": "Must hold PV clearance",
                    "profile_support": [],
                    "matched_candidate_fact": "",
                },
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _capability_profile(),
    )

    assert "job-requirements-panel" in html
    assert "job-requirement-item--supported" in html
    assert "job-requirement-item--partially-supported" in html
    assert "job-requirement-item--mismatch" in html
    assert "job-requirement-item--not-shown" in html  # bonus not_shown → grey
    assert "job-requirement-item--invalid" in html
    assert "Stakeholder engagement" in html
    assert "SAP certification" in html
    assert "Needs attention" in html
    assert "Needs review" not in html
    assert "job-requirements-panel" in html
    assert "job-coverage-panel" not in html
    assert "Job Requirements" in html
    assert "job-req-importance" in html
    assert "job-requirement-badges" not in html
    assert "job-req-importance--mandatory" in html
    assert "job-req-importance--strongly-preferred" in html
    assert "job-req-importance--preferred" in html
    assert "job-req-importance--bonus" in html
    assert "Mandatory" in html  # mandatory label
    assert "Strongly Preferred" in html  # strongly preferred label
    assert "Preferred" in html  # preferred label
    assert "Bonus" in html  # bonus label


def test_workspace_hides_occupation_alignment_reason_outside_debug_mode():
    reason = (
        "The job is a Business Improvement Analyst role focused on waste management, "
        "which is adjacent to the candidate's target roles."
    )
    record = {
        "job_key": "seek:occupation-alignment-ui",
        "title": "Business Improvement Analyst",
        "company": "Acme",
        "url": "https://example.com/job",
        "title_reason": "OK",
        "content_reason": "OK",
        "decision": "KEEP",
        "llm_decision": "KEEP",
        "llm_fit_grade": "SOLID",
        "occupation_alignment": "adjacent",
        "occupation_alignment_reason": reason,
        "requirement_coverage": [],
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "full_description": "Business improvement role. " * 40,
        "fit_highlights": [],
        "source": "seek",
    }

    html = workspace_renderer.render_job_card(record, _test_profile())

    assert reason not in html
    assert "Job title match" not in html


def test_workspace_requirement_list_groups_attention_items_before_matched_items():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "seek:req-order-test",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "SOLID",
            RECORD_FIT_SCORE_KEY: 65,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 65, "section": "llm_fit"}
            ],
            "requirement_coverage": [
                {
                    "requirement": "Stakeholder engagement",
                    "importance": "mandatory",
                    "status": "supported",
                },
                {
                    "requirement": "Reporting",
                    "importance": "preferred",
                    "status": "supported",
                },
                {
                    "requirement": "Agile delivery",
                    "importance": "strongly_preferred",
                    "status": "supported",
                },
                {
                    "requirement": "Financial reporting",
                    "importance": "bonus",
                    "status": "not_shown",
                },
                {
                    "requirement": "SAP certification",
                    "importance": "mandatory",
                    "status": "mismatch",
                },
                {
                    "requirement": "PV clearance",
                    "importance": "mandatory",
                    "status": "invalid",
                },
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _capability_profile(),
    )

    # Not-yet-matched requirements (mismatch/invalid/not_shown) are grouped first,
    # each group internally sorted required -> expected -> preferred ->
    # bonus, then alphabetically within a tier.
    assert html.index("PV clearance") < html.index("SAP certification")
    assert html.index("SAP certification") < html.index("Financial reporting")
    assert html.index("Financial reporting") < html.index("Stakeholder engagement")
    assert html.index("Stakeholder engagement") < html.index("Agile delivery")
    assert html.index("Agile delivery") < html.index("Reporting")


def test_repeated_listing_history_adds_candidate_warning():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "seek:repeat-1",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
            "times_seen": 5,
            "first_seen_at": "2026-03-01T09:00:00+10:00",
            "last_seen_at": "2026-04-01T09:00:00+10:00",
        },
        _test_profile(),
    )

    assert "Potential Red Flag" not in html
    assert "this same listing has been seen 5 times over 31 days" in html


def test_posted_display_anchors_relative_text_to_retrieval_date():
    from job_hunter_agent.posting_utils import posted_display_label

    label = posted_display_label(
        {
            "posted": "2d ago",
            "posted_age_days": 2,
            "run_started_at": "2026-04-21T09:00:00+10:00",
        },
        now=datetime.fromisoformat("2026-04-22T12:00:00+10:00"),
    )

    assert label == "19 Apr 2026"


def test_posted_display_converts_today_to_retrieved_date():
    from job_hunter_agent.posting_utils import posted_display_label

    label = posted_display_label(
        {
            "posted": "today",
            "posted_age_days": 0,
            "run_started_at": "2026-04-21T09:00:00+10:00",
        },
        now=datetime.fromisoformat("2026-04-22T12:00:00+10:00"),
    )

    assert label == "21 Apr 2026"


def test_posted_display_shows_today_against_current_render_date():
    from job_hunter_agent.posting_utils import posted_display_label

    label = posted_display_label(
        {
            "posted": "3h ago",
            "posted_age_days": 0.125,
            "run_started_at": "2026-04-22T09:00:00+10:00",
        },
        now=datetime.fromisoformat("2026-04-22T12:00:00+10:00"),
    )

    assert label == "22 Apr 2026"


def test_hard_blocked_job_still_shows_requirement_fit_evidence():
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary"},
        "content_reason": "OK",
        "llm_fit_grade": "SOLID",
        "competitive_signals": [],
        "hard_block_reasons": ["requires SAP experience"],
        "requirement_coverage": [
            {"requirement": "Agile delivery", "importance": "mandatory", "status": "supported", "capability_name": "agile methodologies", "matched_candidate_fact": "agile methodologies"}
        ],
    }

    breakdown = fit_scoring.fit_score_breakdown(record, _capability_profile())
    labels = [item["label"] for item in breakdown]

    assert any("Hard blocker" in label for label in labels)
    assert labels[0].startswith("Requirement Fit: 100%")

def test_score_equivalent_where_no_hard_blockers():
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "content_reason": "OK",
        "llm_fit_grade": "SOLID",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "competitive_signals": [],
    }
    profile = _test_profile()

    breakdown = fit_scoring.fit_score_breakdown(record, profile)
    score = fit_scoring.fit_score(record, profile)

    assert score == max(min(sum(item["value"] for item in breakdown), 100), 0)
    assert not any("Hard blocker" in item["label"] for item in breakdown)


def test_build_pre_review_risk_signals_uses_shared_partial_support_label(monkeypatch):
    monkeypatch.setattr(
        capability_matching,
        "find_profile_capability_matches",
        lambda details_text, profile: {"must_not": [], "limited_depth": []},
    )

    risks, missing, missing_clearance = capability_matching.build_pre_review_risk_signals(
        "",
        None,
        _test_profile(),
        competitive_signals=[
            {
                SIGNAL_LABEL_KEY: "specialist context",
                SIGNAL_RISK_LABEL_KEY: "Role leans toward specialist depth",
                SIGNAL_ALIGNMENT_KEY: "strong",
                SIGNAL_ADJUSTMENT_KEY: -1,
            }
        ],
    )

    assert missing == []
    assert missing_clearance == []
    assert risks == [
        "Role leans toward specialist depth is only partially supported by your profile"
    ]


# ---------------------------------------------------------------------------
# Acceptance criteria: fit explanation language (human-friendly, no raw labels)
# ---------------------------------------------------------------------------


def _permanent_only_profile():
    return {
        **_test_profile(),
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_sector": True,
            "engagement_type": ["permanent"],
            "preferred_contract_months": 12,
            "short_contract_months": 6,
        },
    }


def _all_work_types_profile():
    return {
        **_test_profile(),
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_sector": True,
            "engagement_type": ["permanent", "contract", "temp", "casual"],
            "preferred_contract_months": 12,
            "short_contract_months": 6,
        },
    }


def _contract_only_profile():
    return {
        **_test_profile(),
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_sector": True,
            "engagement_type": ["contract"],
            "preferred_contract_months": 12,
            "short_contract_months": 6,
        },
    }


def test_fit_card_never_shows_internal_scoring_labels():
    """No raw internal labels should appear in the rendered job card HTML."""
    profile = {
        **_capability_profile(),
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_sector": True,
            "engagement_type": ["permanent"],
            "preferred_contract_months": 12,
            "short_contract_months": 6,
        },
    }
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-no-raw-labels",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "title_match_metadata": {"match_family": "primary"},
            "content_reason": "OK",
            "llm_fit_grade": "STRONG",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": (
                "Business analyst role driving agile delivery and stakeholder engagement. " * 20
            ),
            "fit_source_text": (
                "Business analyst role driving agile delivery and stakeholder engagement. " * 20
            ),
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "source": "seek",
        },
        profile,
    )

    forbidden = [
        "role-family",
        "description fit is",
        "Matched profile support",
        "nv1 appears",
        "Preferred role-family",
        "Primary role-family",
        "Alternative role-family",
        "Description fit is excellent",
        "Description fit is strong",
        "Description fit is solid",
        "Description fit is weak",
    ]
    for phrase in forbidden:
        assert phrase.lower() not in html.lower(), (
            f"Internal label found in rendered card: {phrase!r}"
        )


def test_fit_card_debug_score_breakdown_uses_frozen_labels_verbatim():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-frozen-score-breakdown-copy",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            RECORD_FIT_SCORE_KEY: 72,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Requirement Fit: 72%", "value": 72, "section": "requirement_fit"},
                {
                    "label": "Hard blocker requirement mismatch: NV1 clearance",
                    "value": -100,
                    "section": "risk",
                },
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analyst role driving agile delivery. " * 20,
            "fit_highlights": [],
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=True,
    )

    assert "Requirement Fit: 72%: +72" in html
    assert "Hard blocker requirement mismatch: NV1 clearance: -100" in html
    assert "BA / technical BA experience" not in html


def test_humanize_reject_reason_uses_owned_secondary_title_copy(monkeypatch):
    labels = json.loads(json.dumps(workspace_renderer.load_ui_labels()))
    labels["title_match_labels"]["secondary_match"] = "Configured alternative title copy"
    monkeypatch.setattr(workspace_renderer, "_workspace_ui_labels", lambda: labels)

    assert (
        workspace_renderer.humanize_reject_reason("TITLE_POTENTIAL_MATCH")
        == "Configured alternative title copy"
    )


def test_fit_card_capability_match_uses_sentence_format():
    """Capability matches render as 'The ad asks for X, and your profile includes this.'."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-capability-sentence",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": (
                "Agile delivery ceremonies and acceptance testing required. " * 20
            ),
            "fit_source_text": (
                "Agile delivery ceremonies and acceptance testing required. " * 20
            ),
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "source": "seek",
        },
        _capability_profile(),
    )

    assert "and your profile shows this experience" not in html
    assert "Strong capability match:" not in html
    assert "Why this is a good fit" not in html


def test_work_type_not_a_fit_reason_when_all_types_accepted():
    """Work type should NOT appear as a fit reason when user has no work type preference."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-work-type-suppressed",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract/Temp",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _all_work_types_profile(),
    )

    assert "Why this is a good fit" not in html
    assert "<strong>Work type</strong> Contract" in html


def test_work_type_is_fit_reason_when_user_prefers_permanent():
    """Work type appears as a fit reason when user explicitly selected permanent-only."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-work-type-shown",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _permanent_only_profile(),
    )

    assert "This matches your permanent preference." not in html
    assert "<strong>Work type</strong> Permanent" in html


def test_work_type_is_fit_reason_when_user_prefers_contract():
    """Contract should appear as a fit reason only when contract preference is explicit."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-work-type-contract",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract/Temp",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Requirements elicitation across delivery teams. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        _contract_only_profile(),
    )

    assert "This matches your contract preference." not in html
    assert "<strong>Work type</strong> Contract" in html


def test_contract_duration_meta_renders_for_contract_jobs():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-contract-duration-card",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract/Temp",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Initial 12 month contract supporting delivery teams.",
            "fit_highlights": [],
            "source": "seek",
        },
        _contract_only_profile(),
    )

    assert "<strong>Work type</strong> Contract" in html
    assert "<strong>Contract term</strong> 12 months" in html


def test_contract_duration_requirement_is_suppressed_when_already_shown_in_meta():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-contract-duration-requirement-card",
            "title": "Scrum Master",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Contract/Temp",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Initial 6 month contract supporting delivery teams.",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": [
                {
                    "requirement": "Contract (6 Months)",
                    "importance": "mandatory",
                    "status": "not_shown",
                    "matched_job_text": "Contract (6 Months)",
                }
            ],
        },
        _contract_only_profile(),
    )

    assert "<strong>Work type</strong> Contract" in html
    assert "<strong>Contract term</strong> 6 months" in html
    assert ">Contract (6 Months)<" not in html


def test_add_to_profile_button_carries_capability_data_attributes():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-prefill-link",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Stakeholder management across delivery teams.",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": [
                {
                    "requirement": "Strong stakeholder management is required",
                    "canonical_requirement": "Stakeholder management",
                    "profile_action_allowed": True,
                    "importance": "mandatory",
                    "status": "not_shown",
                    "matched_job_text": "Strong stakeholder management is required",
                }
            ],
        },
        _capability_profile(),
    )

    assert 'data-action="confirm_have" data-capability-name="Stakeholder management"' in html
    assert 'data-action="confirm_do_not_have" data-capability-name="Stakeholder management"' in html
    assert "Profile evidence:" not in html
    assert "Not confirmed" not in html
    assert "Add evidence" in html
    assert html.count("jh-button--micro job-requirement-action gap-btn") == 2
    assert "Needs confirmation" not in html


def test_canonical_fact_resolved_true_flows_through_to_add_to_profile_button():
    coverage = llm_gate.normalize_llm_requirement_coverage(
        [
            {
                "requirement": "Working knowledge of responsible AI principles",
                "importance": "mandatory",
                "requirement_type": "capability",
                "canonical_requirement": "Responsible AI",
                "decomposition": {
                    "operator": "single",
                    "elements": [
                        {
                            "text": "responsible AI principles",
                            "capability_judgement": "capability",
                            "canonical_concept": "Responsible AI",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        }
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "Working knowledge of responsible AI principles",
                "profile_support": [],
            }
        ],
        valid_capability_names={},
    )

    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-profile-fact-resolved",
            "title": "AI Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Working knowledge of responsible AI principles",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": coverage,
        },
        _test_profile(),
    )

    assert 'data-action="confirm_have" data-capability-name="Responsible AI"' in html


def test_compound_and_row_suppresses_add_to_profile_button():
    coverage = llm_gate.normalize_llm_requirement_coverage(
        [
            {
                "requirement": "Write testable user stories and acceptance criteria",
                "importance": "mandatory",
                "requirement_type": "capability",
                "canonical_requirement": "User stories and acceptance criteria",
                "decomposition": {
                    "operator": "and",
                    "elements": [
                        {
                            "text": "user stories",
                            "capability_judgement": "capability",
                            "canonical_concept": "User stories",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        },
                        {
                            "text": "acceptance criteria",
                            "capability_judgement": "capability",
                            "canonical_concept": "Acceptance criteria",
                            "canonical_fact_resolved": True,
                            "status": "not_shown",
                        },
                    ],
                },
                "status": "not_shown",
                "matched_job_text": "Write testable user stories and acceptance criteria",
                "profile_support": [],
            }
        ],
        valid_capability_names={
            "acceptance testing": "Acceptance testing",
            "acceptance criteria": "Acceptance testing",
        },
    )

    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-profile-fact-not-resolved",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Write testable user stories and acceptance criteria",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": coverage,
        },
        _capability_profile(),
    )

    assert "req-add-to-profile" not in html


def test_no_add_to_profile_link_for_unresolved_bonus_alternatives_list():
    """A vague group of named alternatives/examples must stay one visible row
    with no profile-learning action — it is not a clear canonical fact, so it
    must not be exploded into per-alternative gaps or actions (JH decomposition
    bug: 'Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA,
    CSPO, PSM) are a bonus.')."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-vague-bonus-alternatives",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA, CSPO, PSM) are a bonus.",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": [
                {
                    "requirement": "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA, CSPO, PSM) are a bonus.",
                    "requirement_type": "qualification",
                    "canonical_requirement": "",
                    "profile_action_allowed": False,
                    "importance": "bonus",
                    "status": "not_shown",
                    "matched_job_text": "Tertiary qualifications or BA/Agile certifications (IIBA, CBAP, CCBA, CSPO, PSM) are a bonus.",
                }
            ],
        },
        _test_profile(),
    )

    assert "Tertiary qualifications or BA/Agile certifications" in html
    assert "req-add-to-profile" not in html
    assert "prefill_qualification=" not in html
    assert "prefill_eligibility=" not in html
    assert "prefill_capability=" not in html
    assert "prefill_qualification=IIBA" not in html


def test_no_add_to_profile_link_for_unresolved_required_alternatives_list():
    """Vague mandatory ('required') wording that cannot resolve to one clear
    fact must stay visible (not hidden, not silently dropped) but must not be
    converted into a specific profile-learning action either."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-vague-required-alternatives",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "One of CBAP, CCBA, or an equivalent BA certification is required.",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": [
                {
                    "requirement": "One of CBAP, CCBA, or an equivalent BA certification is required.",
                    "requirement_type": "qualification",
                    "canonical_requirement": "",
                    "profile_action_allowed": False,
                    "importance": "mandatory",
                    "status": "not_shown",
                    "matched_job_text": "One of CBAP, CCBA, or an equivalent BA certification is required.",
                }
            ],
        },
        _test_profile(),
    )

    assert "One of CBAP, CCBA, or an equivalent BA certification is required." in html
    assert "job-requirement-item--mandatory-not-shown" in html
    assert "req-add-to-profile" not in html
    assert "prefill_qualification=" not in html


def test_add_to_profile_link_shown_for_clear_single_qualification():
    """A single, cleanly resolved qualification requirement must keep getting
    its Add-to-profile action — the vague-alternatives fix must not suppress
    the existing, valid behaviour."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-clear-single-qualification",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "CBAP certification is required.",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": [
                {
                    "requirement": "CBAP certification is required.",
                    "requirement_type": "qualification",
                    "canonical_requirement": "CBAP",
                    "profile_action_allowed": True,
                    "importance": "mandatory",
                    "status": "not_shown",
                    "matched_job_text": "CBAP certification is required.",
                }
            ],
        },
        _test_profile(),
    )

    assert 'data-action="confirm_have" data-capability-name="CBAP"' in html


def test_independent_and_joined_requirements_each_get_own_add_to_profile_link():
    """Genuinely independent requirements joined with AND must keep gating
    independently — the fix for OR-joined alternatives lists must not collapse
    real multi-requirement decomposition."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-independent-and-requirements",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Canberra ACT",
            "work_type": "Full Time",
            "work_mode": "On-site",
            "salary": "N/A",
            "full_description": "Australian Citizenship and NV2 Security Clearance are required.",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": [
                {
                    "requirement": "Australian Citizenship is required",
                    "requirement_type": "eligibility",
                    "canonical_requirement": "Australian Citizenship",
                    "profile_action_allowed": True,
                    "importance": "mandatory",
                    "status": "not_shown",
                    "matched_job_text": "Australian Citizenship is required",
                },
                {
                    "requirement": "NV2 Security Clearance is required",
                    "requirement_type": "eligibility",
                    "canonical_requirement": "NV2",
                    "profile_action_allowed": True,
                    "importance": "mandatory",
                    "status": "not_shown",
                    "matched_job_text": "NV2 Security Clearance is required",
                },
            ],
        },
        _test_profile(),
    )

    assert 'data-action="confirm_have" data-capability-name="Australian Citizenship"' in html
    assert 'data-action="confirm_have" data-capability-name="NV2"' in html


def test_no_add_to_profile_link_for_partial_match_alternatives():
    """Partial Match rows must never get the profile-learning action, even
    when a canonical fact happens to be present — tuning belongs in Settings,
    not a profile-learning shortcut on an uncertain match."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-partial-match-alternatives",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "CBAP, CCBA, or an equivalent certification is desirable.",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": [
                {
                    "requirement": "CBAP, CCBA, or an equivalent certification is desirable.",
                    "requirement_type": "qualification",
                    "canonical_requirement": "CBAP",
                    "profile_action_allowed": True,
                    "importance": "preferred",
                    "status": "partially_supported",
                    "matched_job_text": "CBAP, CCBA, or an equivalent certification is desirable.",
                }
            ],
        },
        _test_profile(),
    )

    assert "job-requirement-item--partially-supported" in html
    assert "req-add-to-profile" not in html
    assert "prefill_qualification=" not in html


def test_no_add_to_profile_link_for_matched_requirement():
    """Matched rows must never get the profile-learning action either — the
    fact is already represented in the profile, so offering to add it again
    is confusing and, if clicked, would create a duplicate."""
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-matched-requirement",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "CBAP certification is required.",
            "fit_highlights": [],
            "source": "seek",
            "requirement_coverage": [
                {
                    "requirement": "CBAP certification is required.",
                    "requirement_type": "qualification",
                    "canonical_requirement": "CBAP",
                    "profile_action_allowed": True,
                    "importance": "mandatory",
                    "status": "supported",
                    "matched_candidate_fact": "CBAP",
                    "matched_job_text": "CBAP certification is required.",
                }
            ],
        },
        _test_profile(),
    )

    assert "job-requirement-item--supported" in html
    assert "req-add-to-profile" not in html


def test_contract_duration_meta_stays_hidden_for_non_contract_jobs():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-non-contract-duration-card",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Permanent role on a 12 month transformation program.",
            "fit_highlights": [],
            "source": "seek",
        },
        _permanent_only_profile(),
    )

    assert "<strong>Work type</strong> Permanent" in html
    assert "<strong>Contract term</strong>" not in html


def test_nv1_check_item_renders_as_human_readable():
    """NV1 clearance check item must not expose the raw 'nv1 appears required' text."""
    reasons = workspace_renderer._humanize_check_item("nv1 appears required")
    assert "nv1 appears required" not in reasons.lower()
    assert "Missing mandatory requirement: NV1" in reasons


def test_check_item_unescapes_html_entities_before_rendering():
    reason = workspace_renderer._humanize_check_item(
        "The title specifies a &#x27;Contract Management&#x27; domain."
    )

    assert "&#x27;" not in reason
    assert "'Contract Management'" in reason


def test_must_not_require_skills_keyword_scan_no_longer_drives_checks_before_applying():
    """The pre-review must_not_require_skills keyword scan is used only to decide
    whether the LLM review can be skipped (see build_pre_review_risk_signals) — it
    must never leak a "Missing mandatory requirement" sentence into the rendered
    card, since that panel is now LLM-sourced only (competitive_signals /
    requirement_coverage), not a keyword scan of the description.
    """
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-nv1-card",
            "title": "Business Analyst",
            "company": "DHS",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Canberra ACT",
            "work_type": "Full Time",
            "work_mode": "On-site",
            "salary": "N/A",
            "full_description": (
                "Requirements elicitation for government agency. NV1 clearance required. " * 20
            ),
            "fit_source_text": (
                "Requirements elicitation for government agency. NV1 clearance required. " * 20
            ),
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "source": "seek",
        },
        {
            **_test_profile(),
            "must_not_require_skills": ["nv1"],
        },
    )

    assert "Missing mandatory requirement" not in html


def test_partial_requirement_coverage_shows_badge_in_job_requirements_only():
    # A partially-supported requirement is shown once, as a badged row in Job
    # Requirements — it must not also be duplicated as a sentence in "Checks
    # before applying".
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-partial-requirement-card",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "On-site",
            "salary": "N/A",
            "full_description": "Data integration and data services layer experience is helpful. " * 20,
            "fit_source_text": "Data integration and data services layer experience is helpful. " * 20,
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "requirement_coverage": [
                {
                    "requirement": "Data integration",
                    "importance": "strongly_preferred",
                    "status": "partially_supported",
                    "capability_name": "data integration",
                    "matched_job_text": "data integration and data services layers",
                    "profile_support": [],
                    "matched_candidate_fact": "data integration",
                }
            ],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "job-requirements-panel" in html
    assert "job-requirement-item--partially-supported" in html
    assert "Data integration" in html
    assert "Partly matches your profile: Data integration" not in html
    assert "Partial requirement coverage" not in html


def test_reviewed_signal_matches_render_as_plain_english_sentences(monkeypatch):
    """Approved review signals should render as plain-English evidence sentences."""
    profile = {
        **_capability_profile(),
        "match_preferences": _all_work_types_profile()["match_preferences"],
    }
    monkeypatch.setattr(
        capability_matching,
        "load_registry",
        lambda: {
            "stakeholder": {
                "signal": "stakeholder management",
                "decision": "use",
                "original_texts": ["stakeholder management"],
            },
            "contract": {
                "signal": "contract",
                "decision": "use",
                "original_texts": ["contract"],
            },
        },
    )

    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-reviewed-signal-sentence",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": (
                "Strong stakeholder management, Jira, banking exposure, and project coordination needed."
            ),
            "fit_source_text": (
                "Strong stakeholder management, Jira, banking exposure, and project coordination needed."
            ),
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "reviewed_signal_matches": {
                "matched": ["stakeholder management", "contract"],
                "evidence_only": [],
                "ignored": [],
                "unresolved": [],
            },
            "source": "seek",
        },
        profile,
        debug_mode=True,
    )

    assert "The ad mentions Stakeholder management, and your profile shows" not in html
    assert "Reviewed signal evidence" not in html
    assert "This matches your contract preference." not in html
    assert "<strong>Work type</strong> Permanent" in html


def test_debug_llm_review_shows_cost_and_token_metrics_without_signal_evidence():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-debug-llm-metrics",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            RECORD_LLM_DECISION_KEY: "KEEP",
            RECORD_LLM_FIT_GRADE_KEY: "STRONG",
            RECORD_FIT_SCORE_KEY: 68,
            RECORD_FIT_LABEL_KEY: "Possible fit",
            RECORD_FIT_TONE_CLASS_KEY: "tone-borderline",
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 68, "section": "llm_fit"},
            ],
            RECORD_LLM_INPUT_TOKENS_KEY: 2422,
            RECORD_LLM_OUTPUT_TOKENS_KEY: 557,
            "llm_cost_usd": 0.00186,
            "llm_elapsed_ms": 1234,
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analyst role supporting delivery and stakeholders. " * 20,
            "fit_source_text": "Business analyst role supporting delivery and stakeholders. " * 20,
            "details_status": "ok",
            "reviewed_signal_matches": {
                "matched": [
                    "The ad mentions Quality assurance, and your profile shows related experience."
                ],
                "unresolved": [],
                "evidence_only": [],
                "ignored": [],
            },
            "source": "seek",
        },
        _test_profile(),
        debug_mode=True,
    )

    assert "Debug: LLM fit review" in html
    assert "LLM cost: $0.001860" in html
    assert "Input tokens: 2422" in html
    assert "Output tokens: 557" in html
    assert "Reviewed signal evidence" not in html


def test_match_tile_number_is_debug_only():
    record = {
        "job_key": "test-debug-score-tile",
        "title": "Business Analyst",
        "company": "Acme",
        "url": "https://example.com/job",
        "title_reason": "OK",
        "content_reason": "OK",
        RECORD_FIT_SCORE_KEY: 68,
        RECORD_FIT_LABEL_KEY: "Possible fit",
        RECORD_FIT_TONE_CLASS_KEY: "tone-borderline",
        RECORD_FIT_SCORE_BREAKDOWN_KEY: [],
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "full_description": "Business analyst role supporting delivery and stakeholders.",
        "fit_source_text": "Business analyst role supporting delivery and stakeholders.",
        "details_status": "ok",
        "source": "seek",
    }

    debug_html = workspace_renderer.render_job_card(record, _test_profile(), debug_mode=True)
    normal_html = workspace_renderer.render_job_card(record, _test_profile(), debug_mode=False)

    assert '<span class="match-tile-number">68</span>' in debug_html
    assert "match-tile-number" not in normal_html


def test_fit_section_heading_uses_human_friendly_language():
    """Section headings use the new human-friendly copy, not the old internal labels.

    The LLM's own competitive_signals (not a keyword scan) is what surfaces a soft
    risk so the 'Checks before applying' section renders.
    """
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-headings",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": (
                "Agile delivery and stakeholder engagement required. SAP experience required. " * 20
            ),
            "fit_source_text": (
                "Agile delivery and stakeholder engagement required. SAP experience required. " * 20
            ),
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            RECORD_REQUIREMENT_COVERAGE_KEY: [
                {"requirement": "Agile delivery", "importance": "mandatory", "status": "supported"},
                {"requirement": "SAP experience", "importance": "mandatory", "status": "mismatch"},
            ],
            "competitive_signals": [
                {
                    SIGNAL_LABEL_KEY: "specialist context",
                    SIGNAL_RISK_LABEL_KEY: "Role leans toward specialist depth",
                    SIGNAL_ALIGNMENT_KEY: "strong",
                    SIGNAL_ADJUSTMENT_KEY: -1,
                }
            ],
            "fit_highlights": [],
            "source": "seek",
        },
        _capability_profile(),
    )

    assert "Why this is a good fit" not in html
    assert "Checks before applying" in html
    assert "Why it fits" not in html
    assert "What lowers it" not in html


def test_score_gap_notes_use_friendly_copy():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-gap-notes",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "A detailed description that is safely captured. " * 20,
            "fit_source_text": "A detailed description that is safely captured. " * 20,
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
        debug_mode=True,
    )

    assert "Debug: LLM fit review" in html
    assert "Why this score is lower" not in html
    assert "What we couldn't score" not in html


def test_render_job_card_fit_breakdown_starts_with_plain_english_summary_from_requirement_coverage():
    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-fit-summary-coverage",
            "title": "Business Analyst",
            "company": "Acme",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "decision": "KEEP",
            "llm_decision": "KEEP",
            "llm_fit_grade": "STRONG",
            RECORD_FIT_SCORE_KEY: 72,
            RECORD_FIT_SCORE_BREAKDOWN_KEY: [
                {"label": "Base fit", "value": 72, "section": "llm_fit"},
            ],
            RECORD_REQUIREMENT_COVERAGE_KEY: [
                {"requirement": "Agile delivery", "importance": "mandatory", "status": "supported"},
                {"requirement": "Stakeholder engagement", "importance": "strongly_preferred", "status": "partially_supported"},
                {"requirement": "User acceptance testing", "importance": "preferred", "status": "supported"},
                {"requirement": "SAP certification", "importance": "mandatory", "status": "mismatch"},
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Agile delivery, stakeholder engagement, and user acceptance testing. " * 20,
            "fit_source_text": "Agile delivery, stakeholder engagement, and user acceptance testing. " * 20,
            "description_source": "linkedin_full_description",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "source": "seek",
        },
        _capability_profile(),
        debug_mode=False,
    )

    assert "Why this is a good fit" not in html
    assert "Agile delivery — shown in profile" not in html
    assert "Stakeholder engagement — partly shown in profile" not in html
    assert "User acceptance testing — shown in profile" not in html
    assert "This role looks like a good fit because" not in html
    assert '<span class="job-requirement-title-line">Agile delivery' in html
    assert '<span class="job-requirement-title-line">Stakeholder engagement' in html
    assert '<span class="job-requirement-title-line">User acceptance testing' in html
    assert "Agile methodologies" not in html
    assert "Base fit" not in html


def test_requirement_group_headings_have_semantic_tone_hooks():
    source = Path(workspace_renderer.__file__).read_text(encoding="utf-8")
    assert 'job-requirement-group--{safe_html(tone)}' in source
    assert '"partial"' in source
    assert '"attention"' in source
    assert '"matched"' in source
