from job_hunter_agent import filters
from job_hunter_agent.preferences import assess_contract_preference, passes_preference_filters, salary_fit_adjustment


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


def test_unknown_work_type_does_not_create_a_contract_signal():
    profile = {
        "match_preferences": {
            "engagement_type": "both",
            "preferred_contract_months": 12,
            "short_contract_months": 6,
        },
        "scoring_rules": {
            "contract": {
                "permanent_match": 1,
                "permanent_when_contract_preferred": -1,
                "contract_when_permanent_preferred": -1,
                "long_with_extension": 4,
                "long_contract": 3,
                "medium_contract": 2,
                "short_contract": -1,
            },
        },
    }

    assert assess_contract_preference({"work_type": ""}, profile) is None
    assert assess_contract_preference({"work_type": "unknown"}, profile) is None


def test_unknown_work_type_still_passes_quick_card_filter(monkeypatch):
    monkeypatch.setattr(
        filters,
        "load_profile",
        lambda: {
            "primary_job_title_pattern": [r"software engineer"],
            "secondary_title_patterns": [],
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


def test_work_mode_preference_blocks_mismatched_known_modes():
    profile = {
        "match_preferences": {
            "work_mode_preference": ["remote"],
        },
    }

    ok, reason = passes_preference_filters({"work_mode": "Hybrid"}, profile)

    assert ok is False
    assert reason == "PREF_WORK_MODE"


def test_work_mode_preference_allows_any_selected_mode():
    profile = {
        "match_preferences": {
            "work_mode_preference": ["remote", "hybrid"],
        },
    }

    ok, reason = passes_preference_filters({"work_mode": "Hybrid"}, profile)

    assert ok is True
    assert reason == "OK"
