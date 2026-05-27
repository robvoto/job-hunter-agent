"""Tests for POST /api/profile-gap endpoint."""

import pytest
from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
from job_hunter_agent.fastapi_app import create_app

_FAKE_USER = {"user_id": "test", "email": "test@example.com", "role": "admin"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: _FAKE_USER)
    # Bypass CSRF so tests can POST without a real session cookie
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    return TestClient(create_app())


def test_profile_gap_decide_later_is_noop(client, monkeypatch):
    saved = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"requirement": "AHPRA registration", "action": "decide_later"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert saved == [], "decide_later must not save the profile"


def test_profile_gap_confirm_have_adds_capability(client, monkeypatch):
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
        json={"requirement": "Business analysis", "action": "confirm_have"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert saved_profiles, "profile must have been saved"
    rules = saved_profiles[0]["candidate_capabilities"]
    added = next(r for r in rules if r["name"] == "business analysis")
    assert added["fit"] == "supporting"
    assert added["level"] == "working"


def test_profile_gap_confirm_have_is_idempotent(client, monkeypatch):
    existing_profile = {
        "candidate_capabilities": [
            {"name": "business analysis", "level": "strong", "aliases": []},
        ],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile))
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"requirement": "Business analysis", "action": "confirm_have"},
    )
    assert resp.status_code == 200
    # Already exists — no save needed
    assert saved_profiles == [], "no save when capability already exists"


def test_profile_gap_confirm_do_not_have_adds_to_must_not_require(client, monkeypatch):
    existing_profile = {
        "candidate_capabilities": [],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile))
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"requirement": "AHPRA registration", "action": "confirm_do_not_have"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert "AHPRA registration" in saved_profiles[0]["must_not_require_skills"]


def test_profile_gap_confirm_do_not_have_is_idempotent(client, monkeypatch):
    existing_profile = {
        "candidate_capabilities": [],
        "must_not_require_skills": ["AHPRA registration"],
    }
    saved_profiles = []
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile))
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p)

    resp = client.post(
        "/api/profile-gap",
        json={"requirement": "AHPRA registration", "action": "confirm_do_not_have"},
    )
    assert resp.status_code == 200
    assert saved_profiles == [], "no save when term already in must_not_require_skills"


def test_profile_gap_missing_requirement_returns_400(client):
    resp = client.post("/api/profile-gap", json={"action": "confirm_have"})
    assert resp.status_code == 400
    assert "requirement" in resp.json()["error"]


def test_profile_gap_invalid_action_returns_400(client):
    resp = client.post(
        "/api/profile-gap",
        json={"requirement": "Something", "action": "unknown_action"},
    )
    assert resp.status_code == 400
    assert "invalid action" in resp.json()["error"]
