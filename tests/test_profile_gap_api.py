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


def _mock_profile_storage_resolution(monkeypatch, resolution, profile_target, related_terms=None):
    # confirm_have is routed through the dedicated click-time LLM resolver
    # (llm_gate.llm_resolve_profile_storage); these tests exercise the route's
    # persistence logic given a resolution, not the LLM call itself.
    monkeypatch.setattr(
        "job_hunter_agent.llm_gate.llm_resolve_profile_storage",
        lambda canonical_item, profile: {
            "resolution": resolution,
            "profile_target": profile_target,
            "related_terms": list(related_terms or []),
        },
    )


def test_profile_gap_decide_later_is_removed(client, monkeypatch):
    saved = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": "job-1",
            "capability_name": "Cloud computing (AWS)",
            "action": "decide_later",
        },
    )
    assert resp.status_code == 400
    assert "invalid action" in resp.json()["error"]
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
                    "status": "not_shown",
                    "capability_name": "Cloud computing (AWS)",
                    "matched_job_text": "AWS platform experience",
                    "profile_action_allowed": True,
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
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )
    _mock_profile_storage_resolution(monkeypatch, "new", "Cloud computing (AWS)")

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "cloud computing (aws)",
            "action": "confirm_have",
        },
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
                    "status": "not_shown",
                    "capability_name": "Cloud computing (AWS)",
                    "matched_job_text": "AWS platform experience",
                    "profile_action_allowed": True,
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
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "cloud computing (aws)",
            "action": "confirm_have",
        },
    )
    assert resp.status_code == 200
    assert saved_profiles == [], "no save when capability already exists"


def test_profile_gap_confirm_have_qualification_uses_canonical_requirement_not_matched_fact(
    client, monkeypatch
):
    # matched_candidate_fact is not vetted by JH-286's profile_action_allowed
    # gate (only canonical_requirement is). The row button sends
    # canonical_requirement, and the save path must trust it, never the raw
    # matched_candidate_fact text even when both are present on the row.
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "CBAP, Agile BA, or equivalent certifications",
                    "requirement_type": "qualification",
                    "status": "not_shown",
                    "canonical_requirement": "CBAP",
                    "matched_candidate_fact": "CBAP, Agile BA, or equivalent certifications",
                    "matched_job_text": "CBAP, Agile BA, or equivalent certifications",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {"candidate_qualifications": []}
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )
    _mock_profile_storage_resolution(monkeypatch, "new", "CBAP")

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "CBAP",
            "action": "confirm_have",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    quals = saved_profiles[0]["candidate_qualifications"]
    assert [q["name"] for q in quals] == ["CBAP"]


def test_profile_gap_confirm_have_qualification_atomic_name_saved_unchanged(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "PRINCE2 certification required",
                    "requirement_type": "qualification",
                    "status": "not_shown",
                    "canonical_requirement": "PRINCE2",
                    "matched_candidate_fact": "PRINCE2",
                    "matched_job_text": "PRINCE2 certification required",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {"candidate_qualifications": []}
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )
    _mock_profile_storage_resolution(monkeypatch, "new", "PRINCE2")

    resp = client.post(
        "/api/profile-gap",
        json={"job_key": job_key, "capability_name": "PRINCE2", "action": "confirm_have"},
    )
    assert resp.status_code == 200
    quals = saved_profiles[0]["candidate_qualifications"]
    assert [q["name"] for q in quals] == ["PRINCE2"]


def test_profile_gap_confirm_have_rejects_non_capability_string(client, monkeypatch):
    job_key = "job-1"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Permanent full-time role",
                    "status": "not_shown",
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
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "Permanent full-time role",
            "action": "confirm_have",
        },
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
                    "status": "not_shown",
                    "capability_name": "AHPRA registration",
                    "matched_job_text": "AHPRA registration",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "AHPRA registration",
            "action": "confirm_do_not_have",
        },
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
                    "status": "not_shown",
                    "capability_name": "AHPRA registration",
                    "matched_job_text": "AHPRA registration",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [],
        "must_not_require_skills": ["AHPRA registration"],
    }
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "AHPRA registration",
            "action": "confirm_do_not_have",
        },
    )
    assert resp.status_code == 200
    assert saved_profiles == [], "no save when term already in must_not_require_skills"


def test_profile_gap_confirm_have_adds_candidate_eligibility(client, monkeypatch):
    job_key = "job-eligibility"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Hold PV security clearance",
                    "status": "not_shown",
                    "requirement_type": "eligibility",
                    "matched_candidate_fact": "PV clearance",
                    "matched_job_text": "Must hold a PV clearance",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [],
        "candidate_eligibility": [],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )
    _mock_profile_storage_resolution(monkeypatch, "new", "PV clearance")

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "PV clearance",
            "action": "confirm_have",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    saved = saved_profiles[0]
    assert saved["candidate_capabilities"] == []
    assert saved["candidate_eligibility"][0]["name"] == "PV clearance"
    assert saved["candidate_eligibility"][0]["value"] is True


def test_profile_gap_confirm_do_not_have_adds_candidate_eligibility_false(client, monkeypatch):
    job_key = "job-eligibility"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Hold PV security clearance",
                    "status": "not_shown",
                    "requirement_type": "eligibility",
                    "matched_candidate_fact": "PV clearance",
                    "matched_job_text": "Must hold a PV clearance",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [],
        "candidate_eligibility": [],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "PV clearance",
            "action": "confirm_do_not_have",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    saved = saved_profiles[0]
    assert saved["candidate_eligibility"][0]["name"] == "PV clearance"
    assert saved["candidate_eligibility"][0]["value"] is False


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


def test_profile_gap_rejects_item_without_profile_action_allowed(client, monkeypatch):
    # A direct API call naming a real requirement_coverage item that the LLM
    # gate never marked profile_action_allowed=True (e.g. a vague "CBAP or
    # equivalent" clause) must be rejected server-side, even though the item
    # exists and its name matches exactly. The UI must not be the only gate.
    job_key = "job-unsafe"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "CBAP, Agile BA, or equivalent certifications",
                    "status": "not_shown",
                    "capability_name": "CBAP",
                    "matched_job_text": "CBAP, Agile BA, or equivalent certifications",
                    "profile_action_allowed": False,
                }
            ],
        ),
    )
    existing_profile = {"candidate_capabilities": [], "must_not_require_skills": []}
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={"job_key": job_key, "capability_name": "CBAP", "action": "confirm_have"},
    )
    assert resp.status_code == 400
    assert "confirmable requirement coverage item" in resp.json()["error"]
    assert saved_profiles == []


def test_profile_gap_rejects_qualification_item_missing_canonical_requirement(client, monkeypatch):
    # Defensive hardening: a stale/malformed historical job record could in
    # theory carry profile_action_allowed=True without canonical_requirement
    # (e.g. from before that field existed). The qualification save path must
    # reject this rather than silently falling back to the unvetted
    # matched_candidate_fact name.
    job_key = "job-malformed"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "CBAP, Agile BA, or equivalent certifications",
                    "requirement_type": "qualification",
                    "status": "not_shown",
                    "matched_candidate_fact": "CBAP, Agile BA, or equivalent certifications",
                    "matched_job_text": "CBAP, Agile BA, or equivalent certifications",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {"candidate_qualifications": []}
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "CBAP, Agile BA, or equivalent certifications",
            "action": "confirm_have",
        },
    )
    assert resp.status_code == 400
    assert "canonical_requirement" in resp.json()["error"]
    assert saved_profiles == []


def test_profile_gap_rejects_item_missing_profile_action_allowed_flag(client, monkeypatch):
    # Same as above but the flag is absent entirely rather than explicitly
    # False — must still be treated as not allowed (strict `is True` check).
    job_key = "job-unsafe-missing-flag"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "CBAP, Agile BA, or equivalent certifications",
                    "status": "not_shown",
                    "capability_name": "CBAP",
                    "matched_job_text": "CBAP, Agile BA, or equivalent certifications",
                }
            ],
        ),
    )
    existing_profile = {"candidate_capabilities": [], "must_not_require_skills": []}
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    resp = client.post(
        "/api/profile-gap",
        json={"job_key": job_key, "capability_name": "CBAP", "action": "confirm_have"},
    )
    assert resp.status_code == 400
    assert saved_profiles == []


def test_profile_gap_confirm_have_existing_resolution_merges_related_terms_into_aliases_without_growing_capability_count(
    client, monkeypatch
):
    job_key = "job-existing"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Write user stories and acceptance criteria",
                    "requirement_type": "capability",
                    "status": "not_shown",
                    "capability_name": "Write user stories and acceptance criteria",
                    "canonical_requirement": "User stories",
                    "matched_job_text": "Write user stories and acceptance criteria",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {
        "candidate_capabilities": [
            {"name": "Business Analysis", "level": "strong", "aliases": []},
        ],
        "must_not_require_skills": [],
    }
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )
    _mock_profile_storage_resolution(
        monkeypatch, "existing", "Business Analysis", related_terms=["User stories"]
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "User stories",
            "action": "confirm_have",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    capabilities = saved_profiles[0]["candidate_capabilities"]
    assert len(capabilities) == 1, "existing resolution must never create a new top-level item"
    assert capabilities[0]["name"] == "Business Analysis"
    assert capabilities[0]["aliases"] == ["User stories"]


def test_profile_gap_confirm_have_existing_resolution_is_idempotent_on_repeat_confirmation(
    client, monkeypatch
):
    job_key = "job-existing-idempotent"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Write user stories and acceptance criteria",
                    "requirement_type": "capability",
                    "status": "not_shown",
                    "capability_name": "Write user stories and acceptance criteria",
                    "canonical_requirement": "User stories",
                    "matched_job_text": "Write user stories and acceptance criteria",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    state = {
        "profile": {
            "candidate_capabilities": [
                {"name": "Business Analysis", "level": "strong", "aliases": []},
            ],
            "must_not_require_skills": [],
        }
    }
    saved_profiles = []

    def _load_profile():
        return dict(state["profile"])

    def _save_profile(profile):
        state["profile"] = profile
        saved_profiles.append(profile)
        return profile

    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", _load_profile)
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", _save_profile)
    _mock_profile_storage_resolution(
        monkeypatch, "existing", "Business Analysis", related_terms=["User stories"]
    )

    payload = {
        "job_key": job_key,
        "capability_name": "User stories",
        "action": "confirm_have",
    }
    first = client.post("/api/profile-gap", json=payload)
    second = client.post("/api/profile-gap", json=payload)

    assert first.status_code == 200 and second.status_code == 200
    capabilities = state["profile"]["candidate_capabilities"]
    assert len(capabilities) == 1
    assert capabilities[0]["aliases"] == ["User stories"], (
        "repeat confirmation must not duplicate the related term"
    )


def test_profile_gap_confirm_have_row_button_resolves_via_canonical_requirement_when_other_fields_are_blank(
    client, monkeypatch
):
    # Reproduces the real shape llm_gate.normalize_llm_requirement_coverage
    # produces for a not_shown row: capability_name/matched_candidate_fact are
    # blanked, only canonical_requirement is populated. The row-level "Add to
    # profile" button sends canonical_requirement as capability_name — the API
    # must resolve this coverage item by canonical_requirement, not the blank
    # legacy fields.
    job_key = "job-row-button"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "AWS cloud platform experience required",
                    "requirement_type": "capability",
                    "status": "not_shown",
                    "capability_name": "",
                    "matched_candidate_fact": "",
                    "canonical_requirement": "Cloud computing (AWS)",
                    "matched_job_text": "AWS platform experience",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {"candidate_capabilities": [], "must_not_require_skills": []}
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )
    _mock_profile_storage_resolution(monkeypatch, "new", "Cloud computing (AWS)")

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "Cloud computing (AWS)",
            "action": "confirm_have",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert saved_profiles[0]["candidate_capabilities"][0]["name"] == "Cloud computing (AWS)"


def test_profile_gap_confirm_have_new_resolution_is_idempotent_on_repeat_confirmation(
    client, monkeypatch
):
    job_key = "job-new-idempotent"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Cloud computing (AWS) experience",
                    "requirement_type": "capability",
                    "status": "not_shown",
                    "capability_name": "Cloud computing (AWS)",
                    "matched_job_text": "AWS platform experience",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    state = {"profile": {"candidate_capabilities": [], "must_not_require_skills": []}}
    saved_profiles = []

    def _load_profile():
        return dict(state["profile"])

    def _save_profile(profile):
        state["profile"] = profile
        saved_profiles.append(profile)
        return profile

    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", _load_profile)
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", _save_profile)
    resolver_calls = []
    monkeypatch.setattr(
        "job_hunter_agent.llm_gate.llm_resolve_profile_storage",
        lambda canonical_item, profile: resolver_calls.append(1)
        or {"resolution": "new", "profile_target": "Cloud computing (AWS)", "related_terms": []},
    )

    payload = {
        "job_key": job_key,
        "capability_name": "cloud computing (aws)",
        "action": "confirm_have",
    }
    first = client.post("/api/profile-gap", json=payload)
    second = client.post("/api/profile-gap", json=payload)

    assert first.status_code == 200 and second.status_code == 200
    assert len(saved_profiles) == 1, "the second, already-satisfied click must not save again"
    assert len(resolver_calls) == 1, "the second click must short-circuit before calling the resolver"
    assert len(state["profile"]["candidate_capabilities"]) == 1


def test_profile_gap_confirm_have_unresolved_resolution_fails_closed_without_saving(
    client, monkeypatch
):
    # profile_action_allowed=True only vets that fit-review considered this one
    # atomic concept. The independent click-time storage resolver can still
    # come back unresolved (e.g. it can't safely place the fact) — that must
    # fail the request rather than silently falling back to a blind append.
    job_key = "job-unresolved"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Cloud computing (AWS) experience",
                    "requirement_type": "capability",
                    "status": "not_shown",
                    "capability_name": "Cloud computing (AWS)",
                    "matched_job_text": "AWS platform experience",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {"candidate_capabilities": [], "must_not_require_skills": []}
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )
    _mock_profile_storage_resolution(monkeypatch, "unresolved", "")

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "cloud computing (aws)",
            "action": "confirm_have",
        },
    )
    assert resp.status_code == 400
    assert saved_profiles == []


def test_profile_gap_confirm_have_invalid_existing_target_fails_closed_without_saving(
    client, monkeypatch
):
    # Simulates the resolver's own deterministic validator refusing a
    # hallucinated existing_name that is not actually profile-owned — the
    # route must surface this as a failure and never touch the profile.
    job_key = "job-hallucinated"
    monkeypatch.setattr(
        "job_hunter_agent.routes.review.load_job_history",
        lambda: _job_history_with_requirement_coverage(
            job_key,
            [
                {
                    "requirement": "Java development experience is required.",
                    "requirement_type": "capability",
                    "status": "not_shown",
                    "capability_name": "Java development experience is required.",
                    "canonical_requirement": "Java",
                    "matched_job_text": "Java development experience is required.",
                    "profile_action_allowed": True,
                }
            ],
        ),
    )
    existing_profile = {"candidate_capabilities": [], "must_not_require_skills": []}
    saved_profiles = []
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.load_profile", lambda: dict(existing_profile)
    )
    monkeypatch.setattr(
        "job_hunter_agent.server_helpers.save_profile", lambda p: saved_profiles.append(p) or p
    )

    def _raise(canonical_item, profile):
        raise ValueError("Existing profile resolution target is not profile-owned")

    monkeypatch.setattr(
        "job_hunter_agent.llm_gate.llm_resolve_profile_storage", _raise
    )

    resp = client.post(
        "/api/profile-gap",
        json={
            "job_key": job_key,
            "capability_name": "Java development experience is required.",
            "action": "confirm_have",
        },
    )
    assert resp.status_code == 400
    assert saved_profiles == []
