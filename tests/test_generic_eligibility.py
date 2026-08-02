"""Tests for generic Eligibility facts kept separate from managed Clearances."""

from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
from job_hunter_agent.eligibility_profile import normalize_eligibility_facts
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.profile_gaps import STATUS_CONFIRMED_HAVE, classify_requirement_status
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_ELIGIBILITY_FACTS,
    normalize_full_profile,
)


def test_generic_facts_normalize_aliases_without_touching_clearances():
    clearances = [{"name": "PV clearance", "value": True, "evidence": []}]
    profile = normalize_full_profile(
        {
            KEY_CANDIDATE_ELIGIBILITY: clearances,
            KEY_CANDIDATE_ELIGIBILITY_FACTS: [
                {
                    "name": "AHPRA registration",
                    "value": True,
                    "aliases": ["AHPRA", "registration", "AHPRA"],
                },
                {"name": "AHPRA", "value": True, "aliases": []},
            ],
        }
    )

    assert profile[KEY_CANDIDATE_ELIGIBILITY][0]["name"] == "PV clearance"
    assert profile[KEY_CANDIDATE_ELIGIBILITY_FACTS] == [
        {
            "name": "AHPRA registration",
            "value": True,
            "aliases": ["ahpra", "registration"],
            "evidence": [],
            "needs_review": False,
        }
    ]


def test_generic_aliases_are_used_for_deterministic_eligibility_matching():
    facts = [{"name": "Australian citizenship", "value": True, "aliases": ["Australian citizen"]}]
    assert (
        classify_requirement_status(
            "Must be an Australian citizen",
            [],
            [],
            [],
            facts,
            requirement_type="eligibility",
        )
        == STATUS_CONFIRMED_HAVE
    )


def test_generic_eligibility_endpoint_uses_shared_save_and_alias_generation(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "role": "admin"})
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    saved = []
    profile = {KEY_CANDIDATE_ELIGIBILITY: [], KEY_CANDIDATE_ELIGIBILITY_FACTS: []}
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: profile.copy())
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda item: saved.append(item) or item)
    monkeypatch.setattr(
        "job_hunter_agent.llm_gate.suggest_eligibility_aliases",
        lambda name: {
            "aliases": ["Australian citizen"],
            "subtype": "citizenship",
            "status": "generated",
            "needs_review": True,
            "aliases_auto_generated": True,
        },
    )

    response = TestClient(create_app()).post(
        "/api/profile/eligibility",
        json={"name": "Australian citizenship"},
    )

    assert response.status_code == 200
    assert saved[0][KEY_CANDIDATE_ELIGIBILITY] == []
    fact = saved[0][KEY_CANDIDATE_ELIGIBILITY_FACTS][0]
    assert fact["name"] == "Australian citizenship"
    assert fact["aliases"] == ["australian citizen"]
    assert fact["subtype"] == "citizenship"
    assert response.json()["alias_generation"]["status"] == "generated"


def test_alias_generation_failure_keeps_exact_fact_visible(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "role": "admin"})
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    saved = []
    profile = {KEY_CANDIDATE_ELIGIBILITY: [], KEY_CANDIDATE_ELIGIBILITY_FACTS: []}
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: profile.copy())
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda item: saved.append(item) or item)
    monkeypatch.setattr(
        "job_hunter_agent.llm_gate.suggest_eligibility_aliases",
        lambda name: {"aliases": [], "subtype": "", "status": "failed", "needs_review": True},
    )

    response = TestClient(create_app()).post(
        "/api/profile/eligibility",
        json={"name": "Unfamiliar professional registration"},
    )

    assert response.status_code == 200
    assert saved[0][KEY_CANDIDATE_ELIGIBILITY_FACTS][0]["name"] == "Unfamiliar professional registration"
    assert response.json()["alias_generation"]["status"] == "failed"


def test_generic_endpoint_does_not_create_managed_clearance_levels(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "role": "admin"})
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    saved = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile",
        lambda: {KEY_CANDIDATE_ELIGIBILITY: [], KEY_CANDIDATE_ELIGIBILITY_FACTS: []},
    )
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda item: saved.append(item) or item)

    response = TestClient(create_app()).post(
        "/api/profile/eligibility",
        json={"name": "NV1"},
    )

    assert response.status_code == 400
    assert saved == []
