from datetime import datetime
import json

from job_hunter_agent import source_connector
from job_hunter_agent.utils import extract_work_mode


def _test_profile():
    return {
        "capability_profile_rules": [],
        "dominant_signal_clusters": [],
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_government": True,
            "engagement_type": "both",
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


def test_infer_posting_channel_ignores_current_state_phrase():
    channel = source_connector.infer_posting_channel(
        {"company": "Preacta Recruitment"},
        "Join a global consultancy. Analyse current-state data capability and maturity.",
    )

    assert channel == {
        "kind": "recruiter",
        "label": "Recruiter posting",
        "confidence": "medium",
    }


def test_infer_role_sector_only_claims_government_when_explicit():
    assert source_connector.infer_role_sector(
        {"company": "Standards Australia Ltd"},
        "Project coordination role supporting internal standards delivery.",
    ) == {
        "kind": "unknown",
        "label": "",
        "confidence": "unknown",
    }


def test_score_to_match_label_uses_central_match_band_mapping():
    assert source_connector.score_to_match_label(92) == "Strong match"
    assert source_connector.score_to_match_label(74) == "Good match"
    assert source_connector.score_to_match_label(61) == "Worth a look"
    assert source_connector.score_to_match_label(40) == "Stretch"


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

    assert source_connector.score_filter_option_label(90, profile) == "Top tier only"
    assert source_connector.score_filter_option_label(65, profile) == "Review next or better"
    assert source_connector.score_to_match_label(67, profile["match_levels"]) == "Review next"
    assert source_connector.score_to_tone_class(67, profile) == "tone-good"


def test_has_government_context_detects_real_public_sector_language():
    assert source_connector.has_government_context(
        "Federal government department delivering a public sector program."
    )


def test_has_government_context_ignores_privacy_notice_government_id_phrase():
    assert not source_connector.has_government_context(
        "Please do not submit sensitive personal data such as government ID numbers."
    )


def test_government_context_knowledge_file_contains_pattern_lists():
    payload = json.loads(source_connector._GOVERNMENT_CONTEXT_KNOWLEDGE_PATH.read_text(encoding="utf-8"))

    assert payload["kind"] == "managed_knowledge"
    assert "\\bgovernment\\b" in payload["positive_patterns"]
    assert "\\bgovernment-issued\\s+id(?:entification)?\\b" in payload["false_positive_patterns"]


def test_legacy_linkedin_fit_source_text_can_restore_description_confidence():
    record = {
        "details_status": "ok",
        "fit_source_text": "Business analyst duties. " * 40,
    }

    assert source_connector.full_description_confidence(record) == "HIGH"
    assert source_connector.get_trusted_full_description(record).startswith("Business analyst duties.")


def test_extract_work_mode_prioritises_strict_office_requirement_over_delivery_method():
    assert extract_work_mode("Familiarity with Agile, Waterfall, or hybrid delivery environments. This role is 5 days in office.") == "On-site"


def test_build_role_summary_prefers_description_snippet_over_generic_sector_stub():
    summary = source_connector.build_role_summary(
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
    html = source_connector.render_job_card(
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
            "details_status": "ok",
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "Private sector role" not in html
    assert ">Government<" not in html


def test_visible_fit_reasons_backfills_from_positive_score_drivers():
    reasons = source_connector.visible_fit_reasons(
        ["Strong capability match: Delivery teams"],
        [
            {"label": "Direct target title match", "value": 14},
            {"label": "Description fit is strong", "value": 16},
            {"label": "Fit evidence bullets", "value": 3},
            {"label": "Posted within the last day", "value": 9},
            {"label": "Hybrid work available", "value": 1},
        ],
    )

    assert reasons == [
        "Strong capability match: Delivery teams",
        "Direct target title match",
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

    highlights = source_connector.build_fit_highlights(
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
    monkeypatch.setattr(
        source_connector,
        "load_registry",
        lambda: {
            "stakeholder management": {"signal": "stakeholder management", "decision": "use", "original_texts": ["stakeholder management"]},
            "jira": {"signal": "jira", "decision": "use", "original_texts": ["jira"]},
            "banking": {"signal": "banking", "decision": "review", "original_texts": ["banking"]},
            "project": {"signal": "project", "decision": "ignore", "original_texts": ["project"]},
            "delivery": {"signal": "delivery", "decision": "evidence_only", "original_texts": ["delivery"]},
        },
    )

    matches = source_connector.reviewed_signal_matches_for_text(
        "Stakeholder management, Jira, banking, project, and delivery are all mentioned in the role."
    )

    assert matches == {
        "matched": ["stakeholder management", "jira"],
        "evidence_only": ["delivery"],
        "ignored": ["project"],
        "unresolved": ["banking"],
    }


def test_fit_score_breakdown_adds_positive_reviewed_signal_matches_only(monkeypatch):
    monkeypatch.setattr(
        source_connector,
        "load_registry",
        lambda: {
            "jira": {"signal": "jira", "decision": "use", "original_texts": ["jira"]},
            "banking": {"signal": "banking", "decision": "review", "original_texts": ["banking"]},
            "project": {"signal": "project", "decision": "ignore", "original_texts": ["project"]},
        },
    )

    breakdown = source_connector.fit_score_breakdown(
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
            "details_status": "ok",
        },
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "Reviewed signal matches") == 1


def test_fit_score_evidence_ignores_display_only_fit_highlights():
    breakdown = source_connector.fit_score_breakdown(
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

    assert _breakdown_value(breakdown, "Fit evidence bullets") is None


def test_fit_score_evidence_uses_full_capability_match_set():
    breakdown = source_connector.fit_score_breakdown(
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

    assert _breakdown_value(breakdown, "Fit evidence bullets") is None


def test_fit_score_evidence_does_not_count_alias_only_mentions():
    breakdown = source_connector.fit_score_breakdown(
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
                "Lead scrum ceremonies, manage kanban flow, coordinate UAT, "
                "and facilitate workshops with business stakeholders."
            ),
            "competitive_signals": [],
        },
        _capability_profile(),
    )

    assert _breakdown_value(breakdown, "Fit evidence bullets") is None


def test_fit_score_evidence_can_still_count_canonical_capability_mentions():
    breakdown = source_connector.fit_score_breakdown(
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

    assert _breakdown_value(breakdown, "Fit evidence bullets") == 12


def test_strong_high_confidence_fit_gets_convergence_bonus():
    profile = _capability_profile()
    record = {
        "title": "Business Analyst",
        "title_reason": "OK",
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

    breakdown = source_connector.fit_score_breakdown(record, profile)

    assert _breakdown_value(breakdown, "Multiple strong signals align") == 5
    assert source_connector.fit_score(record, profile) >= 70


def test_required_blocker_watchouts_do_not_mark_desirable_mentions_as_missing():
    watchouts = source_connector.description_watchout_reasons(
        "ERP experience is desirable for this business analyst role.",
        {
            "must_not_require_skills": ["ERP"],
            "reject_description_phrase_rules": [],
            "reject_title_rules": [],
        },
    )
    risks, missing = source_connector.build_risk_and_missing_evidence(
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


def test_on_site_role_gets_visible_score_penalty():
    breakdown = source_connector.fit_score_breakdown(
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
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "On-site role") == -2


def test_fit_score_breakdown_can_use_profile_scoring_rule_overrides():
    profile = {
        **_test_profile(),
        "scoring_rules": {
            "fit_breakdown": {
                "title_direct": 20,
            },
            "work_mode": {
                "hybrid": 6,
            },
        },
    }

    breakdown = source_connector.fit_score_breakdown(
        {
            "title": "Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
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

    assert _breakdown_value(breakdown, "Direct target title match") == 20
    assert _breakdown_value(breakdown, "Hybrid work available") == 6


def test_job_card_shows_negative_score_factors_without_debug_mode():
    html = source_connector.render_job_card(
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

    assert "<strong>What lowers it</strong>" in html
    assert "On-site role" in html
    assert "Score penalties" not in html


def test_job_card_shows_reviewed_signal_transparency_groups(monkeypatch):
    monkeypatch.setattr(
        source_connector,
        "load_registry",
        lambda: {
            "stakeholder management": {"signal": "stakeholder management", "decision": "use", "original_texts": ["stakeholder management"]},
            "jira": {"signal": "jira", "decision": "use", "original_texts": ["jira"]},
            "banking": {"signal": "banking", "decision": "review", "original_texts": ["banking"]},
            "project": {"signal": "project", "decision": "ignore", "original_texts": ["project"]},
        },
    )

    html = source_connector.render_job_card(
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
            "details_status": "ok",
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "<strong>Matched signals</strong>" in html
    assert "<li>stakeholder management</li>" in html
    assert "<li>jira</li>" in html
    assert "<strong>Unresolved signals</strong>" in html
    assert "<li>banking</li>" in html
    assert "<strong>Ignored</strong>" in html
    assert "<li>project</li>" in html


def test_job_card_uses_score_tone_as_card_accent_class():
    html = source_connector.render_job_card(
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


def test_recruiter_badge_uses_distinct_class():
    html = source_connector.render_job_card(
        {
            "job_key": "test-recruiter-badge",
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
            "full_description": "Leading consultancy seeks a business analyst to run agile workshops and stakeholder discovery. " * 20,
            "fit_highlights": [],
            "source": "seek",
        },
        _test_profile(),
    )

    assert "badge-channel-recruiter" in html
    assert "badge-sector-government" not in html


def test_score_to_tone_class_uses_same_bands_as_match_labels():
    assert source_connector.score_to_tone_class(84) == "tone-good"
    assert source_connector.score_to_tone_class(69) == "tone-borderline"
    assert source_connector.score_to_tone_class(54) == "tone-low"


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

    applied_html = source_connector.render_job_card({**base_record, "applied": True}, _test_profile())
    hidden_html = source_connector.render_job_card({**base_record, "hidden": True}, _test_profile())

    assert 'data-review-action="unapply"' in applied_html
    assert "Undo Applied" in applied_html
    assert 'data-review-action="unhide"' in hidden_html
    assert ">Unhide<" in hidden_html


def test_possible_repost_card_carries_duplicate_apply_warning_details():
    html = source_connector.render_job_card(
        {
            "job_key": "seek:new",
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
                "job_key": "seek:old",
                "title": "Business Analyst Senior",
                "company": "Acme",
                "source": "seek",
            }
        ],
    )

    assert "Possible Repost" in html
    assert 'data-similar-applied-warning="1"' in html
    assert 'data-similar-applied-job-key="seek:old"' in html
    assert 'data-similar-applied-title="Business Analyst Senior"' in html
    assert "Alert: This looks like a role you already marked as applied at this company." in html


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
    html = source_connector.render_job_card(
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
    html = source_connector.render_job_card(
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
    assert source_connector.deterministic_review_outcome(
        {"title_reason": "OK"},
        [
            "Government context",
            "12+ month contract",
            "Location matches primary preference: Sydney NSW",
        ],
        [],
        [],
    ) is None

    assert source_connector.deterministic_review_outcome(
        {"title_reason": "OK"},
        [
            "Strong capability match: Delivery teams",
            "Strong capability match: Process improvement",
            "Strong capability match: Stakeholder management",
        ],
        [],
        [],
    ) == {"decision": "KEEP", "grade": "SOLID"}


def test_salary_fit_label_marks_scores_above_target_as_meets():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }

    assert source_connector.salary_fit_label({"salary": "$130k-$145k p.a."}, profile) == "meets"
    assert source_connector.salary_fit_label({"salary": "$750 per day"}, profile) == "meets"
    assert source_connector.salary_fit_label({"salary": "$100k p.a."}, profile) == "below"
    assert source_connector.salary_fit_label({"salary": "$650 per day"}, profile) == "below"


def test_salary_fit_ignores_non_comparable_hourly_and_monthly_rates():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }

    assert source_connector.salary_fit_adjustment({"salary": "$90/hr"}, profile) == 0
    assert source_connector.salary_fit_adjustment({"salary": "$8,000 per month"}, profile) == 0
    assert source_connector.salary_fit_adjustment({"salary": "$650 p/d"}, profile) < 0


def test_salary_fit_ignores_yearly_package_and_including_super_amounts():
    profile = {
        **_test_profile(),
        "salary_preferences": {
            "minimum_salary_yearly": 120000,
            "minimum_daily_rate": 700,
        },
    }

    assert source_connector.salary_fit_adjustment({"salary": "$130k package"}, profile) == 0
    assert source_connector.salary_fit_adjustment({"salary": "$130k incl super"}, profile) == 0
    assert source_connector.salary_fit_label({"salary": "$130k + super"}, profile) == "listed"


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

    assert source_connector.salary_fit_adjustment({"salary": "$130k-$145k p.a."}, profile) == 11
    assert source_connector.salary_fit_adjustment({"salary": "$110k p.a."}, profile) == -2


def test_contract_preference_treats_hyphenated_full_time_as_permanent():
    assert source_connector.assess_contract_preference(
        {"work_type": "Full-time", "salary": "N/A"},
        _test_profile(),
    ) == {"label": "Permanent role", "value": 10}


def test_scoring_helpers_ignore_display_only_fit_highlights():
    profile = {
        **_test_profile(),
        "match_preferences": {
            **_test_profile()["match_preferences"],
            "prefer_government": True,
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

    assert source_connector.assess_government_preference(record, profile) is None
    assert source_connector.assess_contract_preference(record, profile) is None


def test_scoring_helpers_still_use_real_source_text():
    profile = {
        **_test_profile(),
        "match_preferences": {
            **_test_profile()["match_preferences"],
            "prefer_government": True,
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

    assert source_connector.assess_government_preference(record, profile) == {
        "label": "Government context",
        "value": 4,
    }
    assert source_connector.assess_contract_preference(record, profile) == {
        "label": "12+ month contract with extension potential",
        "value": 9,
    }


def test_profile_recency_multiplier_uses_tiered_evidence_dates():
    current_year = source_connector.datetime.now().year
    profile = {
        **_test_profile(),
        "evidence_tiers": {
            "primary_current_evidence": f"{current_year - 1} - present: delivery leadership",
            "secondary_older_evidence": "",
            "background_optional_evidence": "",
        },
    }

    assert source_connector.find_profile_experience_year_in_text(
        profile["evidence_tiers"]["primary_current_evidence"],
        ["delivery leadership"],
    ) == current_year
    assert source_connector.profile_recency_multiplier(profile, ["delivery leadership"]) == 1.0


def test_dashboard_record_sets_rank_current_records_by_score_before_age(monkeypatch):
    monkeypatch.setattr(source_connector, "fit_score", lambda record, profile=None: int(record["score"]))
    monkeypatch.setattr(source_connector, "is_dashboard_eligible", lambda record, profile=None: True)

    records = [
        {"job_key": "fresh-low", "score": 55, "posted_age_days": 0.1, "times_viewed": 0},
        {"job_key": "older-high", "score": 90, "posted_age_days": 5, "times_viewed": 0},
        {"job_key": "fresh-mid", "score": 70, "posted_age_days": 0.2, "times_viewed": 0},
    ]

    dashboard_records = source_connector.build_dashboard_record_sets(
        records,
        job_history={},
        applied_job_keys=set(),
        hidden_job_keys=set(),
        reference_time=datetime(2026, 4, 21),
        scoring_profile={},
    )

    assert [record["job_key"] for record in dashboard_records["current_records"]] == [
        "older-high",
        "fresh-mid",
        "fresh-low",
    ]


def test_score_filter_thresholds_hide_lowest_band_when_no_borderline_roles(monkeypatch):
    monkeypatch.setattr(source_connector, "fit_score", lambda record, profile=None: int(record["score"]))

    thresholds = source_connector.score_filter_thresholds(
        [{"score": 85}, {"score": 70}, {"score": 55}],
        scoring_profile={},
        include_borderline=False,
    )

    assert thresholds == [85, 70, 55]


def test_score_filter_thresholds_show_lowest_band_when_borderline_roles_are_present(monkeypatch):
    monkeypatch.setattr(source_connector, "fit_score", lambda record, profile=None: int(record["score"]))

    thresholds = source_connector.score_filter_thresholds(
        [{"score": 58}, {"score": 43}],
        scoring_profile={},
        include_borderline=False,
    )

    assert thresholds == [85, 70, 55, 0]


def test_score_filter_options_use_match_labels_not_raw_thresholds(monkeypatch):
    monkeypatch.setattr(source_connector, "fit_score", lambda record, profile=None: int(record["score"]))

    options_html = source_connector.render_score_filter_options(
        [{"score": 85}, {"score": 70}, {"score": 55}],
        scoring_profile={},
        include_borderline=False,
    )

    assert "All match levels" in options_html
    assert "Strong match only" in options_html
    assert "Good match or better" in options_html
    assert "Worth a look or better" in options_html
    assert "50+ only" not in options_html


def test_score_filter_options_include_lowest_match_band_when_lower_scores_exist(monkeypatch):
    monkeypatch.setattr(source_connector, "fit_score", lambda record, profile=None: int(record["score"]))

    options_html = source_connector.render_score_filter_options(
        [{"score": 58}, {"score": 43}],
        scoring_profile={},
        include_borderline=False,
    )

    assert "Stretch or better" in options_html


def test_posted_filter_options_show_explicit_day_windows():
    options_html = source_connector.render_posted_filter_options(
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
    assert "Last 30 days (3)" in options_html


def test_repeated_listing_history_adds_candidate_warning():
    html = source_connector.render_job_card(
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
    label = source_connector.posted_display_label(
        {
            "posted": "2d ago",
            "posted_age_days": 2,
            "run_started_at": "2026-04-21T09:00:00+10:00",
        },
        now=datetime.fromisoformat("2026-04-22T12:00:00+10:00"),
    )

    assert label == "19 Apr 2026 (3 days ago)"


def test_posted_display_converts_today_to_retrieved_date():
    label = source_connector.posted_display_label(
        {
            "posted": "today",
            "posted_age_days": 0,
            "run_started_at": "2026-04-21T09:00:00+10:00",
        },
        now=datetime.fromisoformat("2026-04-22T12:00:00+10:00"),
    )

    assert label == "21 Apr 2026 (yesterday)"


def test_posted_display_shows_today_against_current_render_date():
    label = source_connector.posted_display_label(
        {
            "posted": "3h ago",
            "posted_age_days": 0.125,
            "run_started_at": "2026-04-22T09:00:00+10:00",
        },
        now=datetime.fromisoformat("2026-04-22T12:00:00+10:00"),
    )

    assert label == "22 Apr 2026 (today)"
