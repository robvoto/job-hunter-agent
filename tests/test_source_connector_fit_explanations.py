from job_hunter_agent import source_connector


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
