"""Click-test: the onboarding wizard's upload -> extract -> review-step
transition.

This exercises the real upload UI, the real create-profile click handler,
the real /api/onboarding/import route (including its own request validation
and profile-store writes), and the real review-step rendering -- everything
except the actual OpenAI call inside run_onboarding, which is stubbed with a
deterministic canned result so this stays free and fast enough to run in the
default e2e suite. The real-LLM call itself is covered separately (and only
opt-in, since it costs money) by test_onboarding_llm_flow.py.
"""

from __future__ import annotations

from playwright.sync_api import expect

STUB_EXTRACTION_RESULT = {
    "ok": True,
    "profile": {
        "target_roles": ["Backend Engineer"],
        "also_consider_roles": ["Platform Engineer"],
        "candidate_capabilities": [
            {
                "name": "python backend development",
                "level": "strong",
                "aliases": ["python", "fastapi"],
                "needs_review": False,
                "icon_key": "engineering_backend",
            }
        ],
    },
    "extraction_counts": {"target_titles": 1, "capabilities": 1},
    "page_limit_notice": "",
}


def _stub_run_onboarding(materials, search_preferences=None, onboarding_settings=None):
    return {**STUB_EXTRACTION_RESULT, "materials": materials}


def test_onboarding_wizard_upload_and_extract_reaches_review_step(
    fresh_candidate_page, monkeypatch
):
    from job_hunter_agent.routes import onboarding_api

    monkeypatch.setattr(onboarding_api, "run_onboarding", _stub_run_onboarding)

    page = fresh_candidate_page
    page.goto("/start")
    page.locator("#primary_cv").set_input_files(
        files=[
            {
                "name": "tiny_cv.txt",
                "mimeType": "text/plain",
                "buffer": b"Jane Doe\nSenior Backend Engineer\n",
            }
        ]
    )

    with page.expect_response("**/api/onboarding/import") as response_info:
        page.locator("#create_profile").click()
    response = response_info.value
    assert response.ok, f"onboarding import failed: {response.status} {response.text()}"

    page.locator('[data-step="2"]').wait_for(state="visible")
    expect(page.locator("#review_target_titles_list")).to_contain_text("Backend Engineer")
    page.locator("#review_capability_cards").wait_for(state="visible")
