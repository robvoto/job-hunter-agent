import json

from job_hunter_agent import server_helpers
from job_hunter_agent import server_review
from job_hunter_agent import signal_registry


def test_rejection_rule_category_knowledge_file_contains_enabled_entries():
    payload = json.loads(server_helpers.REJECTION_RULE_CATEGORY_KNOWLEDGE_PATH.read_text(encoding="utf-8"))

    assert payload["kind"] == "managed_knowledge"
    assert any(entry.get("enabled") for entry in payload["entries"])
    assert "other" in server_helpers._VALID_REJECTION_RULE_CATEGORIES
    assert "not me" in server_helpers._REJECTION_RULE_JUNK_VALUES


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


def test_save_requirement_blockers_feedback_adds_blocker_and_suggests_title_followup(tmp_path, monkeypatch):
    profile = {
        "must_not_require_skills": [],
        "reject_title_rules": [],
    }
    rebuilds = []
    events = []

    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(signal_registry, "_REGISTRY_PATH", tmp_path / "signal_registry.json")
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
    monkeypatch.setattr(server_review, "rebuild_dashboard_after_rule_change", lambda reason="": rebuilds.append(reason))
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


def test_save_requirement_blockers_feedback_skips_title_followup_when_kept_history_matches(monkeypatch):
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
    monkeypatch.setattr(server_review, "rebuild_dashboard_after_rule_change", lambda reason="": None)

    result = server_review.save_requirement_blockers_feedback(
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

    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(server_review, "_load_audit_rows", lambda: [])
    monkeypatch.setattr(server_review, "load_job_history", lambda: {})
    monkeypatch.setattr(server_review, "persist_review_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(server_review, "rebuild_dashboard_after_rule_change", lambda reason="": rebuilds.append(reason))

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


def test_save_requirement_blockers_feedback_suggests_description_block_when_only_rejected_descriptions_match(monkeypatch):
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
    monkeypatch.setattr(server_review, "rebuild_dashboard_after_rule_change", lambda reason="": None)

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


def test_save_requirement_blockers_feedback_can_apply_description_block_in_same_flow(monkeypatch):
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
    monkeypatch.setattr(server_review, "rebuild_dashboard_after_rule_change", lambda reason="": rebuilds.append(reason))

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
