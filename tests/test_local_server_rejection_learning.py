from job_hunter_agent import local_server


def test_save_requirement_blockers_feedback_adds_blocker_and_suggests_title_followup(monkeypatch):
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
    }
    rebuilds = []
    events = []

    monkeypatch.setattr(local_server, "load_profile", lambda: profile)
    monkeypatch.setattr(local_server, "save_profile", lambda payload: payload)
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_load_audit_rows",
        staticmethod(
            lambda: [
                {"job_key": "rej-1", "title": "Senior Business Analyst - SAP", "company": "Acme", "decision": "REJECT"},
                {"job_key": "rej-2", "title": "Delivery Lead | SAP Finance", "company": "Beta", "decision": "REJECT"},
            ]
        ),
    )
    monkeypatch.setattr(local_server.SettingsHandler, "_load_job_history", staticmethod(lambda: {}))
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_persist_review_event",
        classmethod(lambda cls, *args, **kwargs: events.append((args, kwargs))),
    )
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_rebuild_dashboard_after_rule_change",
        staticmethod(lambda reason="": rebuilds.append(reason)),
    )

    result = local_server.SettingsHandler._save_requirement_blockers_feedback(
        "job-1",
        title="Business Analyst - SAP",
        blockers=["sap"],
    )

    assert profile["must_not_require_skills"] == ["sap"]
    assert result["added_blockers"] == ["sap"]
    assert result["applied_title_block_phrases"] == []
    assert result["title_block_suggestions"] == [
        {
            "phrase": "sap",
            "matched_rejected_count": 2,
            "matched_kept_count": 0,
            "sample_rejected_titles": [
                {"title": "Senior Business Analyst - SAP", "company": "Acme"},
                {"title": "Delivery Lead | SAP Finance", "company": "Beta"},
            ],
            "sample_kept_titles": [],
        }
    ]
    assert rebuilds == []
    assert events[0][0][0] == "block_requirement"


def test_save_requirement_blockers_feedback_skips_title_followup_when_kept_history_matches(monkeypatch):
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
    }

    monkeypatch.setattr(local_server, "load_profile", lambda: profile)
    monkeypatch.setattr(local_server, "save_profile", lambda payload: payload)
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_load_audit_rows",
        staticmethod(
            lambda: [
                {"job_key": "rej-1", "title": "Senior Business Analyst - SAP", "company": "Acme", "decision": "REJECT"},
                {"job_key": "rej-2", "title": "Delivery Lead | SAP Finance", "company": "Beta", "decision": "REJECT"},
            ]
        ),
    )
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_load_job_history",
        staticmethod(
            lambda: {
                "keep-1": {
                    "times_kept": 1,
                    "title": "SAP Business Analyst",
                    "company": "Trusted Co",
                }
            }
        ),
    )
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_persist_review_event",
        classmethod(lambda cls, *args, **kwargs: None),
    )
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_rebuild_dashboard_after_rule_change",
        staticmethod(lambda reason="": None),
    )

    result = local_server.SettingsHandler._save_requirement_blockers_feedback(
        "job-1",
        title="Business Analyst - SAP",
        blockers=["sap"],
    )

    assert profile["must_not_require_skills"] == ["sap"]
    assert result["title_block_suggestions"] == []


def test_save_requirement_blockers_feedback_can_apply_title_block_in_same_flow(monkeypatch):
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
    }
    rebuilds = []

    monkeypatch.setattr(local_server, "load_profile", lambda: profile)
    monkeypatch.setattr(local_server, "save_profile", lambda payload: payload)
    monkeypatch.setattr(local_server.SettingsHandler, "_load_audit_rows", staticmethod(lambda: []))
    monkeypatch.setattr(local_server.SettingsHandler, "_load_job_history", staticmethod(lambda: {}))
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_persist_review_event",
        classmethod(lambda cls, *args, **kwargs: None),
    )
    monkeypatch.setattr(
        local_server.SettingsHandler,
        "_rebuild_dashboard_after_rule_change",
        staticmethod(lambda reason="": rebuilds.append(reason)),
    )

    result = local_server.SettingsHandler._save_requirement_blockers_feedback(
        "job-1",
        title="Business Analyst - SAP",
        blockers=["sap"],
        title_block_phrases=["sap"],
    )

    assert profile["must_not_require_skills"] == ["sap"]
    assert profile["reject_title_rules"] == [
        {
            "pattern": r"\bsap\b",
            "reason": "TITLE_BAD_KEYWORD:sap",
        }
    ]
    assert result["applied_title_block_phrases"] == ["sap"]
    assert result["title_block_suggestions"] == []
    assert len(rebuilds) == 1
    assert "title block added for sap" in rebuilds[0]
