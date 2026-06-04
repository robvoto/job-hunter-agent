"""Tests for salary preferences."""



import json

import logging



from job_hunter_agent import filters, fit_scoring, workspace_renderer

from job_hunter_agent import preferences

from job_hunter_agent.preferences import assess_contract_preference, display_work_type_label, passes_preference_filters, salary_fit_adjustment





def _profile():

    return {

        "salary_preferences": {

            "minimum_salary_yearly": 150000,

            "minimum_daily_rate": 800,

        },

        "scoring_rules": {

            "salary": {

                "meeting_target": 8,

                "below_target_near_min_ratio": 0.9,

                "below_target_near_adjustment": -1,

                "below_target_mid_min_ratio": 0.75,

                "below_target_mid_adjustment": -2,

                "below_target_far_adjustment": -3,

            },

        },

    }





def test_salary_fit_adjustment_uses_job_type_specific_thresholds():

    profile = _profile()



    annual_record = {

        "work_type": "Full time",

        "salary": "$160,000 p.a.",

    }

    contract_record = {

        "work_type": "Contractor",

        "salary": "$900 per day",

    }



    assert salary_fit_adjustment(annual_record, profile) == 8

    assert salary_fit_adjustment(contract_record, profile) == 8





def test_salary_fit_adjustment_is_neutral_when_salary_is_missing():

    profile = _profile()



    assert salary_fit_adjustment({"work_type": "Contract"}, profile) == 0





def test_salary_fit_adjustment_is_neutral_for_unsupported_periods():

    profile = _profile()



    assert salary_fit_adjustment({"work_type": "Full time", "salary": "$80 per hour"}, profile) == 0

    assert salary_fit_adjustment({"work_type": "Contract", "salary": "$3,200 per week"}, profile) == 0

    assert salary_fit_adjustment({"work_type": "Full time", "salary": "$14,000 per month"}, profile) == 0





def test_unknown_work_type_returns_neutral_signal():

    profile = {

        "match_preferences": {

            "engagement_type": ["permanent", "contract", "full_time_contract"],

            "preferred_contract_months": 12,

            "short_contract_months": 6,

        },

        "scoring_rules": {

            "contract": {

                "permanent_match": 1,

                "long_with_extension": 4,

                "long_contract": 3,

                "medium_contract": 2,

                "short_contract": -1,

            },

        },

    }



    assert assess_contract_preference({"work_type": ""}, profile) == {

        "label": "Work type unknown — couldn't determine from ad",

        "value": 0,

    }

    assert assess_contract_preference({"work_type": "unknown"}, profile) == {

        "label": "Work type unknown — couldn't determine from ad",

        "value": 0,

    }





def test_unknown_work_type_still_passes_quick_card_filter(monkeypatch):

    monkeypatch.setattr(

        filters,

        "load_profile",

        lambda: {

            "target_roles": [r"software engineer"],

            "also_consider_roles": [],

            "reject_title_rules": [],

            "cheap_reject_metadata_rules": [],

            "cheap_keep_counter_patterns": [],

        },

    )



    ok, reason = filters.passes_quick_card_filters(

        title="Software Engineer",

        teaser="Build and maintain internal tooling.",

        company="Example Co",

        location="Sydney",

        work_type="unknown",

    )



    assert ok is True

    assert reason == "OK"





def test_unknown_work_type_logs_uncertainty(tmp_path, monkeypatch, caplog):

    log_path = tmp_path / "uncertainty.jsonl"

    monkeypatch.setattr(preferences, "UNCERTAINTY_LOG_PATH", log_path)

    monkeypatch.setattr(

        preferences,

        "load_profile",

        lambda: {

            "match_preferences": {

                "engagement_type": ["contract"],

            },

        },

    )



    with caplog.at_level(logging.WARNING, logger="job_hunter_agent.preferences"):

        ok, reason = passes_preference_filters({"job_key": "seek:123", "work_type": "unknown"}, None)



    assert ok is True

    assert reason == "OK"

    assert "WORK_TYPE_UNCLEAR" in caplog.text

    assert "Unable to classify work_type" in caplog.text



    payload = json.loads(log_path.read_text(encoding="utf-8").strip())

    assert payload["reason_code"] == "WORK_TYPE_UNCLEAR"

    assert payload["stage"] == "preference_filter"

    assert payload["field"] == "work_type"

    assert payload["job_key"] == "seek:123"

    assert payload["normalized_value"] == "unknown"





def test_display_work_type_label_normalizes_full_time_contract_to_ftc():

    assert display_work_type_label({"work_type": "Full Time Contract"}) == "FTC"



def test_permanent_only_rejects_ftc_work_type():

    profile = {

        "match_preferences": {

            "engagement_type": ["permanent"],

        },

    }



    ok, reason = passes_preference_filters({"work_type": "Full Time Contract"}, profile)



    assert ok is False

    assert reason == "PREF_CONTRACT_TYPE"



def test_contract_only_rejects_ftc_work_type_when_ftc_is_not_selected():

    profile = {

        "match_preferences": {

            "engagement_type": ["contract"],

        },

    }



    ok, reason = passes_preference_filters({"work_type": "Full Time Contract"}, profile)



    assert ok is False

    assert reason == "PREF_CONTRACT_TYPE"



def test_ftc_only_accepts_ftc_work_type():

    profile = {

        "match_preferences": {

            "engagement_type": ["full_time_contract"],

        },

    }



    ok, reason = passes_preference_filters({"work_type": "Full Time Contract"}, profile)



    assert ok is True

    assert reason == "OK"



def test_display_work_type_label_normalizes_full_time_to_permanent():

    assert display_work_type_label({"work_type": "Full time"}) == "Permanent"



def test_display_work_type_label_normalizes_contract_to_contract():

    assert display_work_type_label({"work_type": "Contract"}) == "Contract"





def test_display_work_type_label_returns_empty_for_unknown():

    assert display_work_type_label({"work_type": "unknown"}) == ""





def test_single_selected_work_type_blocks_confirmed_full_time_role():

    profile = {

        "match_preferences": {

            "engagement_type": ["contract"],

        },

    }



    ok, reason = passes_preference_filters({"work_type": "Full time"}, profile)



    assert ok is False

    assert reason == "PREF_CONTRACT_TYPE"

    assert workspace_renderer.humanize_reject_reason(reason) == "Rejected because work type is outside selected work types."





def test_single_selected_work_type_scores_confirmed_contract_role():

    profile = {

        "match_preferences": {

            "engagement_type": ["contract"],

            "preferred_contract_months": 12,

            "short_contract_months": 6,

        },

        "scoring_rules": {

            "contract": {

                "permanent_match": 1,

                "long_with_extension": 4,

                "long_contract": 3,

                "medium_contract": 2,

                "short_contract": -1,

            },

        },

    }



    item = assess_contract_preference(

        {

            "work_type": "Contract/Temp",

            "fit_source_text": "12 month contract with extension option.",

        },

        profile,

    )



    assert item == {

        "label": "Work type matches your preference: 12+ month contract with extension potential",

        "value": 4,

    }





def test_multiple_selected_work_types_are_neutral_for_scoring():

    profile = {

        "match_preferences": {

            "engagement_type": ["permanent", "contract", "full_time_contract"],

            "preferred_contract_months": 12,

            "short_contract_months": 6,

        },

        "scoring_rules": {

            "contract": {

                "permanent_match": 1,

                "long_with_extension": 4,

                "long_contract": 3,

                "medium_contract": 2,

                "short_contract": -1,

            },

        },

    }



    assert assess_contract_preference({"work_type": "Full time"}, profile) == {

        "label": "Work type neutral because all work types were selected",

        "value": 0,

    }

    assert assess_contract_preference({"work_type": "Contract/Temp", "fit_source_text": "12 month contract."}, profile) == {

        "label": "Work type neutral because all work types were selected",

        "value": 0,

    }





def test_work_mode_preference_blocks_mismatched_known_modes():

    profile = {

        "match_preferences": {

            "work_mode_preference": ["remote"],

        },

    }



    ok, reason = passes_preference_filters({"work_mode": "Hybrid"}, profile)



    assert ok is False

    assert reason == "PREF_WORK_MODE"

    assert workspace_renderer.humanize_reject_reason(reason) == "Rejected because work mode is outside selected modes."





def test_work_mode_preference_allows_any_selected_mode():

    profile = {

        "match_preferences": {

            "work_mode_preference": ["remote", "hybrid", "onsite"],

        },

    }



    ok, reason = passes_preference_filters({"work_mode": "On-site"}, profile)



    assert ok is True

    assert reason == "OK"





def test_all_work_modes_selected_keeps_onsite_neutral_for_scoring():

    profile = {

        "match_preferences": {

            "work_mode_preference": ["remote", "hybrid", "onsite"],

        },

        "scoring_rules": {

            "work_mode": {

                "selected_mode_match": 5,

            },

        },

    }



    breakdown = fit_scoring.fit_score_breakdown(

        {

            "title": "Business Analyst",

            "title_reason": "OK",

            "content_reason": "OK",

            "llm_fit_grade": "SOLID",

            "location": "Sydney",

            "work_type": "Contract",

            "work_mode": "On-site",

            "salary": "N/A",

            "full_description": "Business analyst duties. " * 40,

            "competitive_signals": [],

        },

        profile,

    )



    assert any(item["label"] == "Work mode neutral because all work modes were selected" and item["value"] == 0 for item in breakdown)





def test_work_mode_selection_bonus_applies_only_to_single_selected_mode():

    profile = {

        "match_preferences": {

            "work_mode_preference": ["remote"],

        },

        "scoring_rules": {

            "work_mode": {

                "selected_mode_match": 5,

            },

        },

    }



    breakdown = fit_scoring.fit_score_breakdown(

        {

            "title": "Business Analyst",

            "title_reason": "OK",

            "content_reason": "OK",

            "llm_fit_grade": "SOLID",

            "location": "Sydney",

            "work_type": "Contract",

            "work_mode": "Remote",

            "salary": "N/A",

            "full_description": "Business analyst duties. " * 40,

            "competitive_signals": [],

        },

        profile,

    )



    assert any(item["label"] == "Work mode matches your preference" and item["value"] == 5 for item in breakdown)





def test_multiple_selected_work_modes_are_neutral_for_scoring():

    profile = {

        "match_preferences": {

            "work_mode_preference": ["remote", "onsite"],

        },

        "scoring_rules": {

            "work_mode": {

                "selected_mode_match": 5,

            },

        },

    }



    remote_breakdown = fit_scoring.fit_score_breakdown(

        {

            "title": "Business Analyst",

            "title_reason": "OK",

            "content_reason": "OK",

            "llm_fit_grade": "SOLID",

            "location": "Sydney",

            "work_type": "Contract",

            "work_mode": "Remote",

            "salary": "N/A",

            "full_description": "Business analyst duties. " * 40,

            "competitive_signals": [],

        },

        profile,

    )

    onsite_breakdown = fit_scoring.fit_score_breakdown(

        {

            "title": "Business Analyst",

            "title_reason": "OK",

            "content_reason": "OK",

            "llm_fit_grade": "SOLID",

            "location": "Sydney",

            "work_type": "Contract",

            "work_mode": "On-site",

            "salary": "N/A",

            "full_description": "Business analyst duties. " * 40,

            "competitive_signals": [],

        },

        profile,

    )



    assert any(item["label"] == "Work mode neutral — you've selected multiple" and item["value"] == 0 for item in remote_breakdown)

    assert any(item["label"] == "Work mode neutral — you've selected multiple" and item["value"] == 0 for item in onsite_breakdown)





def test_unknown_work_mode_stays_neutral():

    profile = {

        "match_preferences": {

            "work_mode_preference": ["remote"],

        },

        "scoring_rules": {

            "work_mode": {

                "selected_mode_match": 5,

            },

        },

    }



    ok, reason = passes_preference_filters({"work_mode": "unknown"}, profile)

    breakdown = fit_scoring.fit_score_breakdown(

        {

            "title": "Business Analyst",

            "title_reason": "OK",

            "content_reason": "OK",

            "llm_fit_grade": "SOLID",

            "location": "Sydney",

            "work_type": "Contract",

            "work_mode": "unknown",

            "salary": "N/A",

            "full_description": "Business analyst duties. " * 40,

            "competitive_signals": [],

        },

        profile,

    )



    assert ok is True

    assert reason == "OK"

    assert any(item["label"] == "Work mode unknown — couldn't determine from ad" and item["value"] == 0 for item in breakdown)

