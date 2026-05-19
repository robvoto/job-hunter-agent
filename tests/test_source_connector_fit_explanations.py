from datetime import datetime
import json
import pytest
from urllib.parse import parse_qs, urlparse

from job_hunter_agent import fit_scoring, workspace_service
from job_hunter_agent import capability_matching, workspace_renderer, signal_detection, source_connector
from job_hunter_agent import role_analysis, source_learning, description_trust
from job_hunter_agent.scrapers.seek import build_seek_search_targets
from job_hunter_agent.record_schema import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    DETAILS_STATUS_OK,
    RECORD_DETAILS_STATUS_KEY,
    RECORD_FIT_CONFIDENCE_KEY,
    RECORD_FIT_SOURCE_TEXT_KEY,
    RECORD_FULL_DESCRIPTION_KEY,
)
from job_hunter_agent.profile_store import (
    KEY_EVIDENCE_TIERS,
    KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT,
    KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT,
)
from job_hunter_agent.paths import SCORING_RULES_PATH
from job_hunter_agent.work_mode_extraction import extract_from_text


def _test_profile():
    return {
        "capability_profile_rules": [],
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
    }


def _capability_profile():
    return {
        **_test_profile(),
        "capability_profile_rules": [
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
                "aliases": ["stakeholder engagement", "stakeholder management", "facilitate workshops"],
            },
        ],
    }


def _breakdown_value(breakdown, label):
    for item in breakdown:
        if item["label"] == label:
            return item["value"]
    return None


def test_infer_posting_channel_uses_trusted_metadata_before_text():
    channel = role_analysis.infer_posting_channel(
        {
            "source_metadata": {
                "platform": "linkedin",
                "apply_url": "https://jobs.lever.co/acme/123",
                "apply_domain": "jobs.lever.co",
                "company_profile_url": "https://acme.com.au",
                "company_profile_name": "Acme",
                "poster_company": "Acme",
                "hiring_company": "Acme",
                "ats_source": "jobs.lever.co",
                "raw_source_fields": {
                    "job_url_direct": "https://jobs.lever.co/acme/123",
                    "company_url_direct": "https://acme.com.au",
                },
            }
        },
        "",
    )

    assert channel["kind"] == "direct_employer"
    assert channel["source"] == "metadata_first"
    assert channel["needs_review"] is False
    assert "job_url_direct" in channel["trusted_metadata"]


def test_infer_posting_channel_returns_fallback_text_evidence():
    channel = role_analysis.infer_posting_channel(
        {"source_metadata": {"platform": "seek", "raw_source_fields": {}}},
        "Our client is seeking a consultant. Contact our recruitment team for details.",
    )

    assert channel["kind"] == "unknown"
    assert channel["source"] == "fallback_text_evidence"
    assert channel["needs_review"] is True
    assert "our client" in channel["weak_text_matches"]
    assert "client is seeking" in channel["weak_text_matches"]


def test_infer_role_sector_only_claims_government_when_explicit():
    assert role_analysis.infer_role_sector(
        {"company": "Standards Australia Ltd"},
        "Project coordination role supporting internal standards delivery.",
    ) == {
        "kind": "unknown",
        "label": "",
        "confidence": "unknown",
    }


def test_score_to_match_label_uses_central_match_band_mapping():
    from job_hunter_agent.match_labels import score_to_match_label
    assert score_to_match_label(92) == "Strong match"
    assert score_to_match_label(74) == "Good match"
    assert score_to_match_label(61) == "Possible fit"
    assert score_to_match_label(40) == "Stretch"


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


def test_has_public_sector_context_detects_real_public_sector_language():
    assert role_analysis.has_public_sector_context(
        "Federal government department delivering a public sector program."
    )


def test_has_public_sector_context_ignores_privacy_notice_government_id_phrase():
    assert not role_analysis.has_public_sector_context(


def test_government_context_rules_file_contains_pattern_lists():
    from job_hunter_agent.paths import GOVERNMENT_CONTEXT_RULES_PATH
    payload = json.loads(SECTOR_RULES_PATH.read_text(encoding="utf-8"))

    assert payload["kind"] == "rules"
        "\\baps\\d+\\b",
        "\\bel\\s*[12]\\b",
        "\\bbaseline clearance\\b",
    ]
    assert payload["false_positive_patterns"] == [
    assert payload["false_positive_patterns"] == [ # This is still government-specific detection
        "\\bgovernment-issued\\s+id(?:entification)?\\b",
        "\\bgovernment\\s+id(?:entification)?\\s+(?:number|numbers|document|documents)?\\b",
    ]

def test_government_context_knowledge_file_contains_approved_terms():
    from job_hunter_agent.paths import GOVERNMENT_CONTEXT_KNOWLEDGE_PATH
    payload = json.loads(GOVERNMENT_CONTEXT_KNOWLEDGE_PATH.read_text(encoding="utf-8"))
def test_sector_knowledge_file_contains_approved_terms():
    from job_hunter_agent.paths import SECTOR_KNOWLEDGE_PATH
    payload = json.loads(SECTOR_KNOWLEDGE_PATH.read_text(encoding="utf-8"))

    assert payload["kind"] == "managed_knowledge"
    assert values == [
        "government",
        "public sector",
        "government agency",
        "state agency",
    ]


def test_has_government_context_matches_approved_knowledge(tmp_path, monkeypatch):
    rules_path = tmp_path / "government_context_rules.json"
    knowledge_path = tmp_path / "government_context_knowledge.json"
def test_has_public_sector_context_matches_approved_knowledge(tmp_path, monkeypatch):
    rules_path = tmp_path / "sector_rules.json"
    knowledge_path = tmp_path / "sector_knowledge.json"
    rules_path.write_text(
        json.dumps(
                "name": "sector_rules",
                "positive_patterns": ["\\bgovernment\\b"],
                "false_positive_patterns": [
                    "\\bgovernment\\s+id(?:entification)?\\s+(?:number|numbers|document|documents)?\\b",
                ],
        ),
        encoding="utf-8",
    )
    knowledge_path.write_text(
        json.dumps(
            {
                "kind": "managed_knowledge",
                "name": "government_context_knowledge",
                "name": "sector_knowledge",
                "entries": [
                    {"value": "NSW Health", "aliases": ["state health department"]},
                ],
            }
        encoding="utf-8",
    )
    monkeypatch.setattr(role_analysis, "GOVERNMENT_CONTEXT_RULES_PATH", rules_path)
    monkeypatch.setattr(role_analysis, "GOVERNMENT_CONTEXT_KNOWLEDGE_PATH", knowledge_path)
    monkeypatch.setattr(role_analysis, "SECTOR_KNOWLEDGE_PATH", knowledge_path)

    assert role_analysis.has_government_context("Role in NSW Health digital delivery program")
    assert role_analysis.has_public_sector_context("Role in NSW Health digital delivery program")

def test_build_ad_learning_signals_registers_pending_capability_and_title_tokens(monkeypatch):
    monkeypatch.setattr(
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
        {
            "signal": "ninja",
            "suggested_category": "role_title_token",
            "original_texts": ["Senior Delivery Ninja"],
        },
    ]


def test_build_ad_learning_signals_registers_capability_from_structured_observation(monkeypatch):
    monkeypatch.setattr(
        signal_detection,
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


def test_build_ad_learning_signals_registers_government_context_from_job_description(monkeypatch):
def test_build_ad_learning_signals_registers_public_sector_context_from_job_description(monkeypatch):
    monkeypatch.setattr(
        signal_detection,
        "signal_in_approved_knowledge",
        lambda category, signal, aliases=None: (False, ""),

    signals = source_learning.build_ad_learning_signals(
        {
            "title": "APS6 Policy Officer",
            "company": "Australian Government Department of Health",
            "full_description": "Baseline clearance required for this APS6 role.",
        },
        "Baseline clearance required for this APS6 role.",
        profile={},
    )

    assert [item["signal"] for item in signals] == [
        "government",
        "aps6",
        "baseline",
        "department of health",
    ]
    assert all(item["suggested_category"] == "government_context" for item in signals)
    ] # These are still government-specific terms
    assert all(item["suggested_category"] == "sector" for item in signals)


def test_build_ad_learning_signals_registers_title_normalization_candidates(monkeypatch):
    monkeypatch.setattr(
        lambda category, signal, aliases=None: (False, ""),
    )

    signals = source_learning.build_ad_learning_signals(
        {
            "title": "PM",
            "company": "Acme",
        },
        "Contract role for PM with delivery oversight.",
        profile={},
    )

    assert signals == [
        {
            "signal": "pm",
            "suggested_category": "title_normalization_candidate",
            "original_texts": ["PM"],
        }
    ]


def test_build_ad_learning_signals_does_not_infer_hard_blockers_from_raw_text(monkeypatch):
    monkeypatch.setattr(
        signal_detection,
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
    assert description_trust.get_trusted_full_description(record).startswith("Business analyst duties.")
    assert description_trust.is_description_trusted(record)


def test_fit_confidence_low_when_no_trusted_description_exists():
    record = {
        RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
        RECORD_FIT_SOURCE_TEXT_KEY: "Too short to trust.",
        RECORD_FIT_CONFIDENCE_KEY: CONFIDENCE_HIGH,
    }

    assert description_trust.full_description_confidence(record) == CONFIDENCE_LOW
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
            "full_description": "Coordinate delivery planning, stakeholder updates, and standards publication schedules across multiple teams. " * 20,
            "fit_source_text": "Coordinate delivery planning, stakeholder updates, and standards publication schedules across multiple teams. " * 20,
            "description_source": "jobAdDetails",
            RECORD_DETAILS_STATUS_KEY: DETAILS_STATUS_OK,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "Private sector role" not in html
    assert ">Government<" not in html


# This test needs to be updated to reflect the new "Sector" concept.
def test_visible_fit_reasons_backfills_from_positive_score_drivers():
    reasons = workspace_renderer.visible_fit_reasons(
        ["Strong capability match: Delivery teams"],
        [
            {"label": "Description fit is strong", "value": 16},
            # Per-capability entries are excluded from visible reasons (surfaced via fit_highlights)
            {"label": "stakeholder management [canonical]", "value": 4},
            {"label": "Posted within the last day", "value": 9},
            {"label": "Posted within the last day", "value": 9}, # This is fine, not related to sector
            {"label": "Hybrid work available", "value": 1},
        ],
    )

    assert reasons == [
        "Primary role-family match",
        "Description fit is strong",
        "Posted within the last day",
    ]


def test_build_fit_highlights_recomputes_instead_of_reusing_stale_highlights(monkeypatch):
    monkeypatch.setattr(
        source_connector,
        "load_profile",
        lambda: {
            "capability_profile_rules": [],
            "match_preferences": {},
            "dominant_signal_clusters": [],
        },
    )
    monkeypatch.setattr(
        fit_scoring,
        "reviewed_signal_matches_for_text",
        lambda text: {
            "matched": [],
            "evidence_only": [],
            "ignored": [],
            "unresolved": [],
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
        "stakeholder management": {"signal": "stakeholder management", "decision": "use", "original_texts": ["stakeholder management"]},
        "jira": {"signal": "jira", "decision": "use", "original_texts": ["jira"]},
        "banking": {"signal": "banking", "decision": "review", "original_texts": ["banking"]},
        "project": {"signal": "project", "decision": "ignore", "original_texts": ["project"]},
        "delivery": {"signal": "delivery", "decision": "evidence_only", "original_texts": ["delivery"]},
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

    # No description text \u2192 no capability evidence entries
    assert not any("[canonical]" in item["label"] or "[alias:" in item["label"] for item in breakdown)


def test_fit_score_evidence_credits_alias_matches():
    # Aliases (agile, uat, facilitate workshops) now earn the same credit as canonical names.
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Lead Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": (
                "Lead agile delivery ceremonies, write acceptance criteria, coordinate UAT, "
                "and facilitate workshops with business stakeholders."
            ),
            "competitive_signals": [],
        },
        _capability_profile(),
    )

    # All three capabilities matched via aliases — entries show [alias:...] tags
    capability_labels = [item["label"] for item in breakdown if "[alias:" in item["label"]]
    assert len(capability_labels) >= 1


def test_fit_score_evidence_credits_canonical_mentions():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Lead Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": (
                "Lead agile methodologies, acceptance testing, "
                "and primary stakeholder engagement across delivery teams."
            ),
            "competitive_signals": [],
        },
        _capability_profile(),
    )

    capability_labels = [item["label"] for item in breakdown if "[canonical]" in item["label"]]
    assert len(capability_labels) == 3
    total_capability_points = sum(item["value"] for item in breakdown if "[canonical]" in item["label"])
    assert total_capability_points == 12


def test_strong_high_confidence_fit_gets_convergence_bonus():
    profile = _capability_profile()
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary", "seniority_adjustment": 0},
        "content_reason": "OK",
        "llm_fit_grade": "STRONG",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "posted_age_days": 1,
        "full_description": (
            "Business analyst role driving agile delivery, backlog refinement, acceptance criteria, "
            "user acceptance testing, and stakeholder management workshops across teams. "
        ) * 20,
        "competitive_signals": [],
        "missing_evidence": [],
        "soft_risk_reasons": [],
    }

    breakdown = fit_scoring.fit_score_breakdown(record, profile)

    assert _breakdown_value(breakdown, "Multiple strong signals align") == 5
    assert fit_scoring.fit_score(record, profile) >= 70


def test_convergence_bonus_entry_can_use_profile_scoring_rule_overrides(monkeypatch):
    monkeypatch.setattr(fit_scoring, "full_description_confidence", lambda record: "HIGH")

    profile = {
        **_test_profile(),
        "scoring_rules": {
            "convergence": {
                "eligible_grades": ["SOLID"],
                "min_positive_matches": 1,
                "required_title_reason": "TITLE_POTENTIAL_MATCH",
                "required_content_reason": "DESC_OK",
                "required_fit_confidence": "HIGH",
                "bonus_no_soft_risks": 11,
                "bonus_with_soft_risks": 7,
                "label": "Aligned",
            }
        },
    }
    record = {
        "title_reason": "TITLE_POTENTIAL_MATCH",
        "content_reason": "DESC_OK",
        "llm_fit_grade": "SOLID",
        "missing_evidence": [],
        "soft_risk_reasons": [],
    }

    entry = fit_scoring.convergence_bonus_entry(
        record,
        {"strong": ["platform engineering"], "working": [], "basic": []},
        profile,
    )

    assert entry == {"label": "Aligned", "value": 11}


def test_required_blocker_watchouts_do_not_mark_desirable_mentions_as_missing():
    watchouts = capability_matching.description_watchout_reasons(
        "ERP experience is desirable for this business analyst role.",
        {
            "must_not_require_skills": ["ERP"],
            "reject_description_phrase_rules": [],
            "reject_title_rules": [],
        },
    )
    risks, missing = capability_matching.build_risk_and_missing_evidence(
        "ERP experience is desirable for this business analyst role.",
        "OK",
        {
            "must_not_require_skills": ["ERP"],
            "reject_description_phrase_rules": [],
            "reject_title_rules": [],
            "capability_profile_rules": [],
        },
    )

    assert watchouts == ["erp appears desirable"]
    assert risks == ["erp appears desirable"]
    assert missing == []


def test_job_parsing_rejection_registers_hard_blocker_pattern(monkeypatch):
    registrations = []
    from job_hunter_agent.scrapers import seek_runner

    monkeypatch.setattr(
        seek_runner,
        "fetch_job_details_payload",
        lambda detail_page, url: {"text": "Hands-on coding required for this role.", "status": "ok", "source": "jobAdDetails"},
    )
    monkeypatch.setattr(
        seek_runner,
        "passes_content_filters",
        lambda details_text, card_location="", title_reason="": (False, "DESC_HARD_BLOCK_RULE:sap"),
    )
    monkeypatch.setattr(
        seek_runner,
        "find_hard_block_matches",
        lambda details_text, terms=None: [
            {
                "value": "demonstrated experience in {term}",
                "matched_term": "SAP",
                "context": "must have SAP experience",
            }
        ],
    )
    from job_hunter_agent import source_learning
    monkeypatch.setattr(source_learning, "find_hard_block_matches", lambda details_text, terms=None: [
        {
            "value": "demonstrated experience in {term}",
            "matched_term": "SAP",
            "context": "must have SAP experience",
        }
    ])
    monkeypatch.setattr(source_learning, "register_signals", lambda items, category="": registrations.append((items, category)))

    ok, reason = seek_runner._process_seek_job_details(
        {
            "title": "Business Analyst",
            "company": "Acme",
            "location": "Sydney",
            "url": "https://example.com/job/1",
        },
        detail_page=None,
        profile={},
        title_reason="OK",
    )

    assert ok is False
    assert reason == "DESC_HARD_BLOCK_RULE:sap"
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


def test_on_site_role_is_neutral_when_all_work_modes_are_selected():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "fit_highlights": [],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "On-site",
            "salary": "N/A",
            "full_description": "Business analyst duties. " * 40,
            "competitive_signals": [],
        },
        {
            **_test_profile(),
            "match_preferences": {
                **_test_profile()["match_preferences"],
                "work_mode_preference": ["remote", "hybrid", "onsite"],
            },
            "scoring_rules": {
                "work_mode": {
                    "selected_mode_match": 5,
                },
            },
        },
    )

    assert _breakdown_value(breakdown, "Work mode neutral because all modes were selected") == 0


def test_fit_score_breakdown_can_use_profile_scoring_rule_overrides():
    profile = {
        **_test_profile(),
        "match_preferences": {
            **_test_profile()["match_preferences"],
            "work_mode_preference": ["hybrid"],
        },
        "scoring_rules": {
            "fit_breakdown": {
                "title_direct": 20,
            },
            "work_mode": {
                "selected_mode_match": 6,
            },
        },
    }

    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "title_match_metadata": {
                "match_family": "primary",
                "title_seniority": "plain",
                "primary_pattern_has_seniority": False,
                "seniority_adjustment": 0,
            },
            "fit_highlights": [],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analyst duties. " * 40,
            "competitive_signals": [],
        },
        profile,
    )

    assert _breakdown_value(breakdown, "Preferred role-family match") == 20
    assert _breakdown_value(breakdown, "Work mode confirmed selected mode bonus") == 6


def test_fit_score_breakdown_applies_primary_seniority_adjustment_only_for_primary_matches():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Senior Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "title_match_metadata": {
                "match_family": "primary",
                "title_seniority": "preferred",
                "primary_pattern_has_seniority": True,
                "seniority_adjustment": 3,
            },
            "fit_highlights": [],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analyst duties. " * 40,
            "competitive_signals": [],
        },
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "Preferred role-family match") == 15
    assert _breakdown_value(breakdown, "Preferred seniority adjustment") == 3


def test_fit_score_breakdown_applies_primary_seniority_penalty_only_for_primary_matches():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Junior Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "title_match_metadata": {
                "match_family": "primary",
                "title_seniority": "lower",
                "primary_pattern_has_seniority": True,
                "seniority_adjustment": -5,
            },
            "fit_highlights": [],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Business analyst duties. " * 40,
            "competitive_signals": [],
        },
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "Preferred role-family match") == 15
    assert _breakdown_value(breakdown, "Preferred seniority adjustment") == -5


def test_fit_score_breakdown_keeps_secondary_role_family_clean():
    breakdown = fit_scoring.fit_score_breakdown(
        {
            "title": "Lead Project Coordinator",
            "title_reason": "TITLE_POTENTIAL_MATCH",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "title_match_metadata": {
                "match_family": "secondary",
                "title_seniority": "preferred",
                "primary_pattern_has_seniority": False,
                "seniority_adjustment": 0,
            },
            "fit_highlights": [],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Project coordinator duties. " * 40,
            "competitive_signals": [],
        },
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "Alternative role-family match") == 4
    assert _breakdown_value(breakdown, "Preferred seniority adjustment") is None


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


def test_job_card_shows_reviewed_signal_transparency_groups(monkeypatch):
    _registry = lambda: {
        "stakeholder management": {"signal": "stakeholder management", "decision": "use", "original_texts": ["stakeholder management"]},
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

    assert "<strong>Matched signals</strong>" in html
    assert "<li>Stakeholder management</li>" in html
    assert "<li>Jira</li>" in html
    assert "<strong>Ignored</strong>" in html
    assert "<li>Project</li>" in html
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


def test_posting_channel_badge_uses_fallback_review_class(monkeypatch):
    monkeypatch.setattr(workspace_renderer, "fit_score", lambda record, profile=None: 0)
    monkeypatch.setattr(workspace_renderer, "fit_score_breakdown", lambda record, profile=None: [])

    html = workspace_renderer.render_job_card(
        {
            "job_key": "test-posting-channel-badge",
            "title": "Business Analyst",
            "company": "Preacta Recruitment",
            "url": "https://example.com/job",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "full_description": "Our client is seeking a business analyst. Contact our recruitment team for details. " * 20,
            "fit_highlights": [],
            "source": "seek",
            "posting_channel_evidence": {
                "trusted_metadata": [],
                "weak_text_matches": ["our client", "contact (?:our )?(?:consultant|recruiter|recruitment team)"],
                "needs_review": True,
            },
        },
        _test_profile(),
    )

    assert 'badge-warning" title="Posting channel unconfirmed' in html
    assert "Posting evidence" in html
    assert "badge-sector-government" not in html


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

    applied_html = workspace_renderer.render_job_card({**base_record, "applied": True}, _test_profile())
    hidden_html = workspace_renderer.render_job_card({**base_record, "hidden": True}, _test_profile())

    assert 'data-review-action="unapply"' in applied_html
    assert "Undo Applied" in applied_html
    assert 'data-review-action="unhide"' in hidden_html
    assert ">Unhide<" in hidden_html


def test_possible_repost_card_carries_duplicate_apply_warning_details():
    # find_confirmed_duplicate only matches confirmed duplicates (same job_key or URL).
    # Use the same job_key in the applied pool to trigger the "Possible Repost" badge.
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

    assert "Possible Repost" in html
    assert 'data-similar-applied-warning="1"' in html
    assert 'data-similar-applied-job-key="seek:repost"' in html
    assert 'data-similar-applied-title="Business Analyst Senior"' in html
    assert "Alert: This looks like a role you already marked as applied at this company." in html


def test_potential_duplicate_card_shows_visible_callout_and_help_text():
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

    assert "Related cards" in html
    assert "Open matching card" in html
    assert "This is the matching card in your workspace" in html
    assert 'href="#job-card-linkedin-2"' in html
    assert "senior business analyst @ acme" in html.lower()


def test_positive_note_does_not_repeat_first_why_it_fits_bullet():
    profile = {
        **_test_profile(),
        "capability_profile_rules": [
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
            "full_description": "Requirements elicitation across multiple client transition projects. " * 40,
            "fit_highlights": [],
            "source": "seek",
        },
        profile,
    )

    assert "Strongest fit:" not in html
    assert html.count("Strong capability match: Multi-client delivery") == 1


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

    assert "Description Issue" in html
    assert html.count("<strong>Description issue</strong>") == 1
    assert "<strong>Missing evidence</strong>" not in html
    assert "Risks &amp; missing evidence" not in html


def test_deterministic_review_counts_only_capability_highlights():
    from job_hunter_agent.source_learning import deterministic_review_outcome
    assert deterministic_review_outcome(
        {"title_reason": "OK"},
        {},
        [
            "Government context",
            "12+ month contract",
            "Sector",
            "Location matches primary preference: Sydney NSW",
        ],
        [],
        [],
    ) == {"decision": "KEEP", "grade": "SOLID", "det_rule": "solid"}
    assert deterministic_review_outcome(
        {"title_reason": "OK"},
        {},
        [
            "Strong capability match: Delivery teams",
            "Strong capability match: Process improvement",
            "Strong capability match: Process improvement", # This is fine, not related to sector
            "Strong capability match: Stakeholder management",
        ],
        [],
        [],


def test_llm_description_fit_entry_requires_grade():
    with pytest.raises(ValueError, match="llm_fit_grade is required"):
        fit_scoring.llm_description_fit_entry({"llm_decision": "KEEP"}, _test_profile())


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


def test_contract_preference_treats_hyphenated_full_time_as_permanent():
    from job_hunter_agent.preferences import assess_contract_preference
    assert assess_contract_preference(
        {"work_type": "Full-time", "salary": "N/A"},
        {
            **_test_profile(),
            "match_preferences": {
                **_test_profile()["match_preferences"],
                "engagement_type": ["permanent"],
            },
        },
    ) == {"label": "Work type confirmed selected work type bonus: Permanent role", "value": 10}


def test_scoring_helpers_ignore_display_only_fit_highlights():
    profile = {
        **_test_profile(),
        "match_preferences": {
            **_test_profile()["match_preferences"],
            "prefer_sector": True,
        },
    }
    record = {
        "title": "Lead Business Analyst",
        "company": "Acme",
        "location": "Sydney NSW",
        "work_type": "Contract/Temp",
        "work_mode": "Hybrid",
        "role_snapshot": "Business analyst role.",
        "teaser": "Delivery role.",
        "fit_highlights": [
            "Government context",
            "12 month contract",
        ],
    }

    from job_hunter_agent.preferences import assess_sector_preference, assess_contract_preference
    assert assess_sector_preference(record, profile) == {
        "label": "Sector unknown",
        "value": 0,
    }
    assert assess_contract_preference(record, profile) == {
        "label": "Work type neutral because all work types were selected",
        "value": 0,
    }


def test_scoring_helpers_skip_contract_signal_when_both_selected():
    profile = {
        **_test_profile(),
        "match_preferences": {
            **_test_profile()["match_preferences"],
            "prefer_sector": True,
        },
    }
    record = {
        "title": "Lead Business Analyst",
        "company": "Acme",
        "location": "Sydney NSW",
        "work_type": "Contract/Temp",
        "work_mode": "Hybrid",
        "fit_source_text": "Federal government department. 12 month contract with extension option.",
        "fit_highlights": [],
    }

    from job_hunter_agent.preferences import assess_sector_preference, assess_contract_preference
    assert assess_sector_preference(record, profile) == {
        "label": "Sector preference matched: Public sector",
        "value": 4,
    }
    assert assess_contract_preference(record, profile) == {
        "label": "Work type neutral because all work types were selected",
        "value": 0,
    }


def test_contract_preference_scores_contract_roles_when_contract_only_selected():
    profile = {
        **_test_profile(),
        "match_preferences": {
            **_test_profile()["match_preferences"],
            "engagement_type": ["contract"],
        },
    }
    record = {
        "title": "Lead Business Analyst",
        "company": "Acme",
        "location": "Sydney NSW",
        "work_type": "Contract/Temp",
        "work_mode": "Hybrid",
        "fit_source_text": "Federal government department. 12 month contract with extension option.",
        "fit_highlights": [],
    }

    from job_hunter_agent.preferences import assess_contract_preference
    assert assess_contract_preference(record, profile) == {
        "label": "Work type confirmed selected work type bonus: 12+ month contract with extension potential",
        "value": 9,
    }


def test_profile_recency_multiplier_uses_tiered_evidence_dates():
    current_year = datetime.now().year
    profile = {
        **_test_profile(),
        KEY_EVIDENCE_TIERS: {
            KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT: f"{current_year - 1} - present: delivery leadership",
            KEY_SECONDARY_CANDIDATE_PROFILE_CONTEXT: "",
            KEY_SUPPLEMENTARY_CANDIDATE_PROFILE_CONTEXT: "",
        },
    }

    from job_hunter_agent.scoring_utils import find_profile_experience_year_in_text, profile_recency_multiplier
    assert find_profile_experience_year_in_text(
        profile[KEY_EVIDENCE_TIERS][KEY_PRIMARY_CANDIDATE_PROFILE_CONTEXT],
        ["delivery leadership"],
    ) == current_year
    assert profile_recency_multiplier(profile, ["delivery leadership"]) == 1.0


def test_workspace_record_sets_rank_current_records_by_score_before_age(monkeypatch):
    monkeypatch.setattr(workspace_service, "fit_score", lambda record, profile=None: int(record["score"]))
    monkeypatch.setattr(workspace_service, "is_workspace_eligible", lambda record, profile=None, workspace_min_score=None: True)

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


def test_is_workspace_eligible_uses_saved_workspace_minimum_score(monkeypatch):
    monkeypatch.setattr(workspace_service, "passes_title_filters", lambda title: (True, "OK"))
    monkeypatch.setattr(workspace_service, "fit_score", lambda record, profile=None: int(record["score"]))
    monkeypatch.setattr(workspace_service, "get_workspace_minimum_score", lambda: 60)

    from job_hunter_agent.workspace_service import is_workspace_eligible
    assert is_workspace_eligible({"title": "Business Analyst", "score": 60}) is True
    assert is_workspace_eligible({"title": "Business Analyst", "score": 59}) is False


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
    assert "Last 14 days (3)" in options_html
    #assert "Last 30 days (3)" in options_html


def test_freshness_breakdown_uses_managed_bucket_cutoffs():
    scoring_rules = json.loads(SCORING_RULES_PATH.read_text(encoding="utf-8"))
    weights = {"freshness": 1.0}

    assert _breakdown_value(fit_scoring.build_freshness_breakdown(scoring_rules, weights, 0.02), "Posted within the last hour") == 10
    assert _breakdown_value(fit_scoring.build_freshness_breakdown(scoring_rules, weights, 2), "Posted within the last 3 days") == 5
    assert _breakdown_value(fit_scoring.build_freshness_breakdown(scoring_rules, weights, 10), "Still relatively recent") == 1
    assert fit_scoring.build_freshness_breakdown(scoring_rules, weights, 20) == []


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

    assert "Potential Red Flag" in html
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

    assert label == "19 Apr 2026 (3 days ago)"


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

    assert label == "21 Apr 2026 (yesterday)"


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

    assert label == "22 Apr 2026 (today)"


def test_hard_blocked_job_still_shows_other_fit_evidence(monkeypatch):
    monkeypatch.setattr(fit_scoring, "capability_evidence_score", lambda record, profile=None: (0, []))

    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
        "title_match_metadata": {"match_family": "primary", "seniority_adjustment": 0},
        "content_reason": "OK",
        "llm_fit_grade": "SOLID",
        "location": "Sydney NSW",
        "work_type": "Full Time",
        "work_mode": "Hybrid",
        "salary": "N/A",
        "competitive_signals": [],
        "hard_block_reasons": ["requires SAP experience"],
    }

    breakdown = fit_scoring.fit_score_breakdown(record, _test_profile())
    labels = [item["label"] for item in breakdown]

    assert any("Hard blocker" in label for label in labels)
    assert "Preferred role-family match" in labels
    assert any("fit" in label.lower() for label in labels)


def test_score_equivalent_where_no_hard_blockers(monkeypatch):
    monkeypatch.setattr(fit_scoring, "capability_evidence_score", lambda record, profile=None: (0, []))

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
    assert not any("Hard blocker" in item["label"] for item in b
