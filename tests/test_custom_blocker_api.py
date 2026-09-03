"""API-level tests for custom "Not For Me" blocker validation.

Covers the preview endpoint and server-side enforcement in
POST /api/rejection-feedback/required-blockers, including a direct API
bypass attempt (an unvalidated custom string posted without going through
the preview step first) to prove client-side validation alone is not
sufficient.
"""

import pytest
from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
from job_hunter_agent import server_helpers, server_review
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.record_schema import (
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)

_FAKE_USER = {"user_id": "test", "email": "test@example.com", "role": "admin"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    server_helpers._rejection_suggestions_cache.clear()
    return TestClient(create_app())


def _job_history_with_requirement_coverage(job_key, coverage_items):
    return {
        job_key: {
            RECORD_LAST_KEPT_SNAPSHOT_KEY: {
                RECORD_REQUIREMENT_COVERAGE_KEY: list(coverage_items),
            }
        }
    }


def _salesforce_coverage():
    return [
        {
            "requirement": "Salesforce experience",
            "requirement_type": "capability",
            "canonical_requirement": "Salesforce",
            "importance": "mandatory",
            "matched_job_text": "Salesforce experience",
            "profile_action_allowed": True,
        }
    ]


def _mock_save_requirement_blockers_feedback_deps(monkeypatch, profile):
    monkeypatch.setattr(server_review, "load_profile", lambda: profile)
    monkeypatch.setattr(server_review, "save_profile", lambda payload: payload)
    monkeypatch.setattr(server_review, "_load_audit_rows", lambda: [])
    monkeypatch.setattr(server_review, "load_job_history", lambda: {})
    monkeypatch.setattr(server_review, "persist_review_event", lambda *a, **k: None)
    monkeypatch.setattr(server_review, "rebuild_workspace_after_rule_change", lambda reason="": None)


def test_custom_blocker_preview_resolves_required_capability(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(job_key, _salesforce_coverage()),
    )

    resp = client.get(
        "/api/rejection-feedback/custom-blocker-preview",
        params={"job_id": job_key, "term": "salesforce"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["canonical_requirement"] == "Salesforce"
    assert body["requirement_type"] == "capability"
    assert "preview_html" in body and body["preview_html"]


def test_custom_blocker_preview_rejects_unrelated_term(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(job_key, _salesforce_coverage()),
    )

    resp = client.get(
        "/api/rejection-feedback/custom-blocker-preview",
        params={"job_id": job_key, "term": "unrelated nonsense"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["canonical_requirement"] == ""


def test_required_blockers_saves_canonical_name_for_valid_custom_term(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(job_key, _salesforce_coverage()),
    )
    profile = {"must_not_require_skills": [], "reject_title_rules": []}
    _mock_save_requirement_blockers_feedback_deps(monkeypatch, profile)

    resp = client.post(
        "/api/rejection-feedback/required-blockers",
        json={"job_id": job_key, "blockers": ["salesforce"]},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert profile["must_not_require_skills"] == ["Salesforce"]


def test_required_blockers_rejects_direct_api_bypass_with_unvalidated_custom_string(
    client, monkeypatch
):
    """A caller skipping the preview step entirely must still be blocked server-side."""
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(job_key, _salesforce_coverage()),
    )
    profile = {"must_not_require_skills": [], "reject_title_rules": []}
    _mock_save_requirement_blockers_feedback_deps(monkeypatch, profile)

    resp = client.post(
        "/api/rejection-feedback/required-blockers",
        json={"job_id": job_key, "blockers": ["some random unvalidated phrase"]},
    )

    assert resp.status_code == 400
    assert profile["must_not_require_skills"] == []


def test_required_blockers_rejects_custom_term_matching_only_preferred_requirement(
    client, monkeypatch
):
    job_key = "job-1"
    coverage = [
        {
            "requirement": "Salesforce preferred",
            "requirement_type": "capability",
            "canonical_requirement": "Salesforce",
            "importance": "preferred",
            "matched_job_text": "Salesforce preferred",
            "profile_action_allowed": True,
        }
    ]
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(job_key, coverage),
    )
    profile = {"must_not_require_skills": [], "reject_title_rules": []}
    _mock_save_requirement_blockers_feedback_deps(monkeypatch, profile)

    resp = client.post(
        "/api/rejection-feedback/required-blockers",
        json={"job_id": job_key, "blockers": ["salesforce"]},
    )

    assert resp.status_code == 400
    assert profile["must_not_require_skills"] == []


def test_required_blockers_keeps_llm_suggested_blocker_approval_behaviour_intact(
    client, monkeypatch
):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(job_key, []),
    )
    profile = {"must_not_require_skills": [], "reject_title_rules": []}
    _mock_save_requirement_blockers_feedback_deps(monkeypatch, profile)

    tokens = server_helpers.SettingsHandler._issue_rejection_suggestion_approval_tokens(
        job_key, ["sap"]
    )
    server_helpers._rejection_suggestions_cache[job_key] = {
        "suggestions": ["sap"],
        "approval_tokens": tokens,
    }

    resp = client.post(
        "/api/rejection-feedback/required-blockers",
        json={
            "job_id": job_key,
            "blockers": ["sap"],
            "approved_suggestion_tokens": tokens,
        },
    )

    assert resp.status_code == 200
    assert profile["must_not_require_skills"] == ["sap"]


def test_required_blockers_still_rejects_unapproved_llm_suggestion(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(job_key, []),
    )
    profile = {"must_not_require_skills": [], "reject_title_rules": []}
    _mock_save_requirement_blockers_feedback_deps(monkeypatch, profile)

    server_helpers._rejection_suggestions_cache[job_key] = {
        "suggestions": ["sap"],
        "approval_tokens": server_helpers.SettingsHandler._issue_rejection_suggestion_approval_tokens(
            job_key, ["sap"]
        ),
    }

    resp = client.post(
        "/api/rejection-feedback/required-blockers",
        json={"job_id": job_key, "blockers": ["sap"]},
    )

    assert resp.status_code == 400
    assert profile["must_not_require_skills"] == []
