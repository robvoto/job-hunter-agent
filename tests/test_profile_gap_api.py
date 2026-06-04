"""Tests for POST /api/profile-gap endpoint."""

import pytest
from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.record_schema import (
    RECORD_LAST_KEPT_SNAPSHOT_KEY,
    RECORD_REQUIREMENT_COVERAGE_KEY,
)

_FAKE_USER = {"user_id": "test", "email": "test@example.com", "role": "admin"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    # Bypass CSRF so tests can POST without a real session cookie
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    return TestClient(create_app())


def _job_history_with_requirement_coverage(job_key, coverage_items):
    return {
        job_key: {
            RECORD_LAST_KEPT_SNAPSHOT_KEY: {
                RECORD_REQUIREMENT_COVERAGE_KEY: list(coverage_items),
            }
        }
    }


def test_profile_gap_decide_later_is_noop(client, monkeypatch):
    saved = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": "job-1",
            "capability_name": "Cloud computing (AWS)",
            "action": "decide_later",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert saved == [], "decide_later must not save the profile"


def test_profile_gap_confirm_have_adds_canonical_capability(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Cloud computing (AWS) experience",
                    "status": "not_evidenced",
                    "capability_name": "Cloud computing (AWS)",
                    "matched_job_text": "AWS platform experience",
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [
            {"name": "stakeholder engagement", "level": "strong", "aliases": []},
        ],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile))
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"job_key": job_key, "capability_name": "cloud computing (aws)", "action": "confirm_have"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert saved_profiles, "profile must have been saved"
    rules = saved_profiles[0]["candidate_capabilities"]
    added = next(r for r in rules if r["name"] == "Cloud computing (AWS)")
    assert added["fit"] == "supporting"
    assert added["level"] == "working"
    assert added["icon_key"] == "generic_capability"


def test_profile_gap_confirm_have_is_idempotent(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Cloud computing (AWS) experience",
                    "status": "not_evidenced",
                    "capability_name": "Cloud computing (AWS)",
                    "matched_job_text": "AWS platform experience",
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [
            {"name": "Cloud computing (AWS)", "level": "strong", "aliases": []},
        ],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile))
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"job_key": job_key, "capability_name": "cloud computing (aws)", "action": "confirm_have"},
    )
    assert resp.status_code == 200
    assert saved_profiles == [], "no save when capability already exists"


def test_profile_gap_confirm_have_rejects_non_capability_string(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Permanent full-time role",
                    "status": "not_evidenced",
                    "capability_name": "",
                    "matched_job_text": "Permanent full-time role",
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile))
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"job_key": job_key, "capability_name": "Permanent full-time role", "action": "confirm_have"},
    )
    assert resp.status_code == 400
    assert "confirmable requirement coverage item" in resp.json()["error"]
    assert saved_profiles == []


def test_profile_gap_confirm_do_not_have_adds_to_must_not_require(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "AHPRA registration",
                    "status": "not_evidenced",
                    "capability_name": "AHPRA registration",
                    "matched_job_text": "AHPRA registration",
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile))
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"job_key": job_key, "capability_name": "AHPRA registration", "action": "confirm_do_not_have"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "AHPRA registration" in saved_profiles[0]["must_not_require_skills"]


def test_profile_gap_confirm_do_not_have_is_idempotent(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "AHPRA registration",
                    "status": "not_evidenced",
                    "capability_name": "AHPRA registration",
                    "matched_job_text": "AHPRA registration",
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [],
        "must_not_require_skills": ["AHPRA registration"],
    }
    saved_profiles = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile))
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"job_key": job_key, "capability_name": "AHPRA registration", "action": "confirm_do_not_have"},
    )
    assert resp.status_code == 200
    assert saved_profiles == [], "no save when term already in must_not_require_skills"


def test_profile_gap_missing_capability_name_returns_400(client):
    resp = client.post(
        "/api/profile-gap",
        json={"job_key": "job-1", "action": "confirm_have"},
    )
    assert resp.status_code == 400
    assert "capability_name" in resp.json()["error"]


def test_profile_gap_invalid_action_returns_400(client):
    resp = client.post(
        "/api/profile-gap",
        json={"job_key": "job-1", "capability_name": "Something", "action": "unknown_action"},
    )
    assert resp.status_code == 400
    assert "invalid action" in resp.json()["error"]
