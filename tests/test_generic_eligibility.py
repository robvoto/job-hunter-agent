"""Tests for generic Eligibility facts kept separate from managed Clearances."""

from pathlib import Path

from fastapi.testclient import TestClient

import job_hunter_agent.fastapi_app as _fa
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.profile_gaps import STATUS_CONFIRMED_HAVE, classify_requirement_status
from job_hunter_agent.profile_store import (
    KEY_CANDIDATE_ELIGIBILITY,
    KEY_CANDIDATE_ELIGIBILITY_FACTS,
    normalize_full_profile,
)
from job_hunter_agent.routes import profile_materials

_STATIC_DIR = Path(__file__).resolve().parent.parent / "templates" / "static" / "settings" / "shared"


def test_generic_facts_normalize_without_touching_clearances():
    clearances = [{"name": "PV clearance", "value": True, "evidence": []}]
    profile = normalize_full_profile(
        {
            KEY_CANDIDATE_ELIGIBILITY: clearances,
            KEY_CANDIDATE_ELIGIBILITY_FACTS: [
                {"name": "AHPRA registration", "value": True},
                {"name": "AHPRA registration", "value": True},
            ],
        }
    )

    assert profile[KEY_CANDIDATE_ELIGIBILITY][0]["name"] == "PV clearance"
    assert profile[KEY_CANDIDATE_ELIGIBILITY_FACTS] == [
        {
            "name": "AHPRA registration",
            "value": True,
            "evidence": [],
        }
    ]


def test_generic_eligibility_matching_uses_the_exact_candidate_fact_name():
    facts = [{"name": "Australian citizenship", "value": True}]
    assert (
        classify_requirement_status(
            "Must be an Australian citizenship holder",
            [],
            [],
            [],
            facts,
            requirement_type="eligibility",
        )
        == STATUS_CONFIRMED_HAVE
    )


def test_generic_eligibility_endpoint_saves_the_fact_without_calling_the_llm(monkeypatch):
    # Regression guard: adding an eligibility fact used to trigger a
    # suggest_eligibility_aliases LLM call on every save, which is what made
    # the "Add" button feel slow. The fit-review LLM call already does the
    # real semantic eligibility check per job, so saving a fact must now be a
    # plain, fast profile write with no LLM involved.
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test", "role": "admin"})
    monkeypatch.setattr(_fa, "verify_csrf_token", lambda request, token: True)
    saved = []
    profile = {KEY_CANDIDATE_ELIGIBILITY: [], KEY_CANDIDATE_ELIGIBILITY_FACTS: []}
    monkeypatch.setattr("job_hunter_agent.server_helpers.load_profile", lambda: profile.copy())
    monkeypatch.setattr("job_hunter_agent.server_helpers.save_profile", lambda item: saved.append(item) or item)

    response = TestClient(create_app()).post(
        "/api/profile/eligibility",
        json={"name": "Australian citizenship"},
    )

    assert response.status_code == 200
    assert saved[0][KEY_CANDIDATE_ELIGIBILITY] == []
    fact = saved[0][KEY_CANDIDATE_ELIGIBILITY_FACTS][0]
    assert fact == {"name": "Australian citizenship", "value": True, "evidence": []}
    assert "alias_generation" not in response.json()


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


def test_eligibility_normalizer_rejects_non_boolean_value():
    from job_hunter_agent.eligibility_profile import normalize_eligibility_facts

    try:
        normalize_eligibility_facts([{"name": "Australian citizenship", "value": "yes", "evidence": []}])
    except ValueError as exc:
        assert "must be a boolean" in str(exc)
    else:
        raise AssertionError("invalid eligibility boolean was silently coerced")


def test_eligibility_editor_reuses_shared_trash_action():
    source = (_STATIC_DIR / "settings-eligibility-editor.js").read_text(encoding="utf-8")

    assert "renderTrashActionButton" in source
    assert "'data-eligibility-field': 'remove'" in source
    assert 'cap-remove-btn' not in source
    assert 'jh-button--danger jh-button--compact' not in source


def test_settings_add_flow_calls_the_shared_save_endpoint_not_a_local_only_push():
    # Regression guard: the Settings "Add" button used to push a fact straight
    # into local state instead of calling saveEligibilityFact(), which POSTs
    # to the shared /api/profile/eligibility endpoint.
    source = (_STATIC_DIR / "settings-eligibility-editor.js").read_text(encoding="utf-8")

    assert "saveEligibilityFact" in source
    assert "/api/profile/eligibility" in source
    assert 'aliases: []' not in source


def test_eligibility_editor_uses_its_own_layout_not_the_compact_clearance_card():
    # The Eligibility editor previously reused .capability-card.clearance-card,
    # which is a compact layout designed for fixed clearance rows. It must
    # render with its own eligibility-* classes instead.
    js_source = (_STATIC_DIR / "settings-eligibility-editor.js").read_text(encoding="utf-8")

    assert "clearance-card" not in js_source
    assert "clearance-grid" not in js_source
    assert "eligibility-card" in js_source
    assert "eligibility-grid" in js_source

    css_source = (_STATIC_DIR / "settings-page.css").read_text(encoding="utf-8")
    assert ".eligibility-grid" in css_source


def test_eligibility_editor_never_renders_aliases_or_the_review_message():
    # Regression guard: aliases are candidate-facing data the LLM manages
    # silently for matching, not something the user edits or reviews. An
    # earlier fix for alias generation accidentally reintroduced the aliases
    # input and review message into the card markup after they had been
    # deliberately hidden. Both must stay out of the DOM.
    js_source = (_STATIC_DIR / "settings-eligibility-editor.js").read_text(encoding="utf-8")

    assert "eligibility_aliases_" not in js_source
    assert "data-eligibility-field=\"aliases\"" not in js_source
    assert "needs_review ?" not in js_source
    assert "eligibility-card-review" not in js_source
