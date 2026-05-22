from pytest import MonkeyPatch

from job_hunter_agent import server_helpers
from job_hunter_agent import server_review
from job_hunter_agent import signal_registry



def test_validate_llm_suggestion_approvals_requires_token_for_cached_suggestion():
    server_helpers._rejection_suggestions_cache.clear()
    server_helpers._rejection_suggestions_cache["job-1"] = {
        "suggestions": ["sap"],
        "approval_tokens": server_helpers.SettingsHandler._issue_rejection_suggestion_approval_tokens("job-1", ["sap"]),
    }

    try:
        server_helpers.SettingsHandler._validate_llm_suggestion_approvals("job-1", ["sap"], {})
    except ValueError as exc:
        assert "Missing explicit approval" in str(exc)
    else:
        raise AssertionError("Expected approval validation to fail without token")


def test_validate_llm_suggestion_approvals_accepts_matching_token():
    server_helpers._rejection_suggestions_cache.clear()
    tokens = server_helpers.SettingsHandler._issue_rejection_suggestion_approval_tokens("job-1", ["sap"])
    server_helpers._rejection_suggestions_cache["job-1"] = {
        "suggestions": ["sap"],
        "approval_tokens": tokens,
    }

    server_helpers.SettingsHandler._validate_llm_suggestion_approvals("job-1", ["sap"], tokens)


def test_save_requirement_blockers_feedback_adds_blocker_and_suggests_title_followup(isolated_db, monkeypatch: MonkeyPatch):
    signal_registry.save_registry({})
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
    }
    rebuilds = []
    events = []

    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(
        server_review,
        "_load_audit_rows",
        lambda: [
            {"job_key": "rej-1", "title": "Senior Business Analyst - SAP", "company": "Acme", "decision": "REJECT"},
            {"job_key": "rej-2", "title": "Delivery Lead | SAP Finance", "company": "Beta", "decision": "REJECT"},
        ],
    )
    monkeypatch.setattr(server_review, "load_job_history", lambda: {})
    monkeypatch.setattr(server_review, "persist_review_event", lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(server_review, "rebuild_workspace_after_rule_change", lambda reason="": rebuilds.append(reason))
    result = server_review.save_requirement_blockers_feedback(
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
    assert signal_registry.load_registry() == {}


def test_save_requirement_blockers_feedback_skips_title_followup_when_kept_history_matches(monkeypatch: MonkeyPatch):
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
    }

    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(
        server_review,
        "_load_audit_rows",
        lambda: [
            {"job_key": "rej-1", "title": "Senior Business Analyst - SAP", "company": "Acme", "decision": "REJECT"},
            {"job_key": "rej-2", "title": "Delivery Lead | SAP Finance", "company": "Beta", "decision": "REJECT"},
        ],
    )
    monkeypatch.setattr(
        server_review,
        "load_job_history",
        lambda: {
            "keep-1": {
                "times_kept": 1,
                "title": "SAP Business Analyst",
                "company": "Trusted Co",
            }
        },
    )
    monkeypatch.setattr(server_review, "persist_review_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_review, "rebuild_workspace_after_rule_change", lambda reason="": None)

    result = server_review.save_requirement_blockers_feedback(
        "job-1",
        title="Business Analyst - SAP",
        blockers=["sap"],
    )

    assert profile["must_not_require_skills"] == ["sap"]
    assert result["title_block_suggestions"] == []


def test_save_requirement_blockers_feedback_can_apply_title_block_in_same_flow(monkeypatch: MonkeyPatch):
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
    }
    rebuilds = []

    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(server_review, "_load_audit_rows", lambda: [])
    monkeypatch.setattr(server_review, "load_job_history", lambda: {})
    monkeypatch.setattr(server_review, "persist_review_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_review, "rebuild_workspace_after_rule_change", lambda reason="": rebuilds.append(reason))

    result = server_review.save_requirement_blockers_feedback(
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


def test_save_requirement_blockers_feedback_suggests_description_block_when_only_rejected_descriptions_match(monkeypatch: MonkeyPatch):
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
        "reject_description_phrase_rules": [],
    }

    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(
        server_review,
        "_load_audit_rows",
        lambda: [
            {
                "job_key": "rej-1",
                "title": "Senior Business Analyst",
                "company": "Acme",
                "decision": "REJECT",
                "full_description": "Strong SAP experience is mandatory for this role.",
            },
            {
                "job_key": "rej-2",
                "title": "Delivery Lead",
                "company": "Beta",
                "decision": "REJECT",
                "full_description": "The role needs SAP rollout experience across finance.",
            },
        ],
    )
    monkeypatch.setattr(server_review, "load_job_history", lambda: {})
    monkeypatch.setattr(server_review, "persist_review_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_review, "rebuild_workspace_after_rule_change", lambda reason="": None)

    result = server_review.save_requirement_blockers_feedback(
        "job-1",
        title="Business Analyst - SAP",
        blockers=["sap"],
    )

    assert profile["must_not_require_skills"] == ["sap"]
    assert result["applied_description_block_phrases"] == []
    assert result["description_block_suggestions"] == [
        {
            "phrase": "sap",
            "matched_rejected_count": 2,
            "matched_kept_count": 0,
            "sample_rejected_titles": [
                {"title": "Senior Business Analyst", "company": "Acme"},
                {"title": "Delivery Lead", "company": "Beta"},
            ],
            "sample_kept_titles": [],
        }
    ]


def test_save_requirement_blockers_feedback_can_apply_description_block_in_same_flow(monkeypatch: MonkeyPatch):
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
        "reject_description_phrase_rules": [],
    }
    rebuilds = []

    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(server_review, "_load_audit_rows", lambda: [])
    monkeypatch.setattr(server_review, "load_job_history", lambda: {})
    monkeypatch.setattr(server_review, "persist_review_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_review, "rebuild_workspace_after_rule_change", lambda reason="": rebuilds.append(reason))

    result = server_review.save_requirement_blockers_feedback(
        "job-1",
        title="Business Analyst - SAP",
        blockers=["sap"],
        description_block_phrases=["sap"],
    )

    assert profile["must_not_require_skills"] == ["sap"]
    assert profile["reject_description_phrase_rules"] == [
        {
            "phrase": "sap",
            "reason": "DESC_REJECT:sap",
        }
    ]
    assert result["applied_description_block_phrases"] == ["sap"]
    assert result["description_block_suggestions"] == []
    assert len(rebuilds) == 1
    assert "description phrase rule added for sap" in rebuilds[0]


def test_save_requirement_blockers_feedback_applies_both_title_and_description_blocks_in_same_flow(isolated_db, monkeypatch: MonkeyPatch):
    signal_registry.save_registry({})
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
        "reject_description_phrase_rules": [],
    }
    rebuilds = []
    events = []

    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(
        server_review,
        "_load_audit_rows",
        lambda: [
            {
                "job_key": "rej-1",
                "title": "Senior Business Analyst - SAP",
                "company": "Acme",
                "decision": "REJECT",
                "full_description": "Strong SAP experience is mandatory for this role. Also requires Salesforce.",
            },
            {
                "job_key": "rej-2",
                "title": "Delivery Lead | SAP Finance",
                "company": "Beta",
                "decision": "REJECT",
                "full_description": "The role needs SAP rollout experience across finance. Salesforce is a plus.",
            },
            {
                "job_key": "rej-3",
                "title": "Project Manager - Salesforce",
                "company": "Gamma",
                "decision": "REJECT",
                "full_description": "Mandatory Salesforce certification.",
            },
        ],
    )
    monkeypatch.setattr(server_review, "load_job_history", lambda: {})
    monkeypatch.setattr(server_review, "persist_review_event", lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(server_review, "rebuild_workspace_after_rule_change", lambda reason="": rebuilds.append(reason))

    result = server_review.save_requirement_blockers_feedback(
        "job-1",
        title="Business Analyst - SAP",
        blockers=["sap", "salesforce"],
        title_block_phrases=["sap"],
        description_block_phrases=["salesforce"],
    )

    # Assert profile updates
    assert profile["must_not_require_skills"] == ["sap", "salesforce"]
    assert profile["reject_title_rules"] == [
        {
            "pattern": r"\bsap\b",
            "reason": "TITLE_BAD_KEYWORD:sap",
        }
    ]
    assert profile["reject_description_phrase_rules"] == [
        {
            "phrase": "salesforce",
            "reason": "DESC_REJECT:salesforce",
        }
    ]

    # Assert result payload
    assert result["added_blockers"] == ["sap", "salesforce"]
    assert result["applied_title_block_phrases"] == ["sap"]
    assert result["applied_description_block_phrases"] == ["salesforce"]
    assert result["title_block_suggestions"] == []  # Applied, so no suggestions
    assert result["description_block_suggestions"] == []  # Applied, so no suggestions
    assert "Added 2 mandatory requirement blockers" in result["message"]
    assert "Added 1 title block" in result["message"]
    assert "Added 1 description block" in result["message"]

    # Assert side effects
    assert len(rebuilds) == 2  # One for title, one for description
    assert "title block added for sap" in rebuilds[0]
    assert "description phrase rule added for salesforce" in rebuilds[1]
    # Events order: block_title, block_description, block_requirement
    assert any(e[0][0] == "block_requirement" for e in events)
    assert signal_registry.load_registry() == {}
