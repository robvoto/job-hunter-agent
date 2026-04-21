from job_hunter_agent import source_connector


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


def _breakdown_value(breakdown, label):
    for item in breakdown:
        if item["label"] == label:
            return item["value"]
    return None


def test_infer_employer_type_ignores_current_state_phrase():
    employer_type = source_connector.infer_employer_type(
        {"company": "Preacta Recruitment"},
        "Join a global consultancy. Analyse current-state data capability and maturity.",
    )

    assert employer_type == "Recruitment-led role"


def test_has_government_context_detects_real_public_sector_language():
    assert source_connector.has_government_context(
        "Federal government department delivering a public sector program."
    )


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


def test_fit_score_evidence_counts_only_capability_highlights():
    breakdown = source_connector.fit_score_breakdown(
        {
            "title": "Lead Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "fit_highlights": [
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
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "Fit evidence bullets") is None


def test_fit_score_evidence_still_counts_capability_highlights():
    breakdown = source_connector.fit_score_breakdown(
        {
            "title": "Lead Business Analyst",
            "title_reason": "OK",
            "content_reason": "OK",
            "llm_fit_grade": "SOLID",
            "fit_highlights": [
                "Strong capability match: Delivery teams",
                "Government context",
            ],
            "location": "Sydney NSW",
            "work_type": "Full Time",
            "work_mode": "Hybrid",
            "salary": "N/A",
            "competitive_signals": [],
        },
        _test_profile(),
    )

    assert _breakdown_value(breakdown, "Fit evidence bullets") == 3


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
        "value": 6,
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


def test_score_filter_thresholds_hide_35_when_no_borderline_roles(monkeypatch):
    monkeypatch.setattr(source_connector, "TEST_ANY_MODE", False)
    monkeypatch.setattr(source_connector, "fit_score", lambda record, profile=None: int(record["score"]))

    thresholds = source_connector.score_filter_thresholds(
        [{"score": 80}, {"score": 65}, {"score": 50}],
        scoring_profile={},
    )

    assert thresholds == [80, 65, 50]


def test_score_filter_thresholds_show_35_when_borderline_roles_are_present(monkeypatch):
    monkeypatch.setattr(source_connector, "TEST_ANY_MODE", False)
    monkeypatch.setattr(source_connector, "fit_score", lambda record, profile=None: int(record["score"]))

    thresholds = source_connector.score_filter_thresholds(
        [{"score": 58}, {"score": 43}],
        scoring_profile={},
    )

    assert thresholds == [80, 65, 50, 35]


def test_score_filter_options_use_match_labels_not_raw_thresholds(monkeypatch):
    monkeypatch.setattr(source_connector, "TEST_ANY_MODE", False)
    monkeypatch.setattr(source_connector, "fit_score", lambda record, profile=None: int(record["score"]))

    options_html = source_connector.render_score_filter_options(
        [{"score": 80}, {"score": 65}, {"score": 50}],
        scoring_profile={},
    )

    assert "All match levels" in options_html
    assert "Strong match only" in options_html
    assert "Good match or better" in options_html
    assert "Worth a look or better" in options_html
    assert "50+ only" not in options_html


def test_posted_filter_options_show_counts_and_skip_duplicate_windows():
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
    assert "Recent roles (2)" in options_html
    assert "This week (3)" in options_html
    assert "Last two weeks" not in options_html
    assert "This month" not in options_html
