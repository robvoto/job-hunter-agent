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


def test_onboarding_review_related_skills_drawer_only_shows_remaining_aliases(
    fresh_candidate_page, monkeypatch
):
    from job_hunter_agent.routes import onboarding_api

    monkeypatch.setattr(
        onboarding_api,
        "run_onboarding",
        lambda materials, search_preferences=None, onboarding_settings=None: {
            "ok": True,
            "profile": {
                "target_roles": ["Backend Engineer"],
                "also_consider_roles": ["Platform Engineer"],
                "candidate_capabilities": [
                    {
                        "name": "python backend development",
                        "level": "strong",
                        "aliases": ["python", "fastapi", "postgresql", "docker"],
                        "needs_review": False,
                        "icon_key": "engineering_backend",
                    }
                ],
            },
            "extraction_counts": {"target_titles": 1, "capabilities": 1},
            "page_limit_notice": "",
            "materials": materials,
        },
    )

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

    card = page.locator("#review_capability_cards .capability-card").first
    card.wait_for(state="visible")

    preview = card.locator(".capability-alias-preview")
    expect(preview.locator(".cap-alias-chip-label")).to_have_text(["python", "fastapi"])

    drawer = card.locator("details.capability-alias-drawer")
    expect(card.locator(".capability-summary-label--closed")).to_have_text("Show 2 more")
    card.locator(".cap-alias-summary").click()
    expect(drawer).to_have_attribute("open", "")
    expect(card.locator(".capability-summary-label--open")).to_have_text("Show less")
    expect(drawer.locator(".cap-alias-chip-label")).to_have_text(["postgresql", "docker"])
    card.locator(".cap-alias-summary").click()
    expect(drawer).not_to_have_attribute("open", "")
    expect(card.locator(".capability-summary-label--closed")).to_have_text("Show 2 more")


def test_onboarding_progress_header_reopens_previously_visited_search_basics(
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
    assert response_info.value.ok

    review_step = page.locator('[data-step="2"]')
    search_step = page.locator('[data-step="3"]')
    search_nav = page.locator('[data-step-nav="3"]')

    expect(review_step).to_be_visible()
    # A not-yet-reached forward step is still locked.
    expect(search_nav).to_be_disabled()

    page.locator("#continue_to_search_basics").click()
    expect(search_step).to_be_visible()
    expect(search_nav).to_be_enabled()

    page.locator("#back_to_review_footer").click()
    expect(review_step).to_be_visible()
    # Once legitimately reached, Search Basics stays clickable while editing Review Draft.
    expect(search_nav).to_be_enabled()

    search_nav.click()
    expect(search_step).to_be_visible()


def test_onboarding_revisiting_check_setup_uses_search_save_transition(
    fresh_candidate_page, monkeypatch
):
    from job_hunter_agent.routes import onboarding_api

    monkeypatch.setattr(onboarding_api, "run_onboarding", _stub_run_onboarding)

    page = fresh_candidate_page
    page.goto("/start")
    page.locator("#primary_cv").set_input_files(
        files=[{
            "name": "tiny_cv.txt",
            "mimeType": "text/plain",
            "buffer": b"Jane Doe\nSenior Backend Engineer\n",
        }]
    )
    with page.expect_response("**/api/onboarding/import") as response_info:
        page.locator("#create_profile").click()
    assert response_info.value.ok

    page.locator("#continue_to_search_basics").click()
    page.locator('[data-step="3"]').wait_for(state="visible")

    # Provide valid Search Basics values and reach Check Setup normally first.
    page.locator('#location_search input[data-location-value="Sydney"]').check()
    page.locator("#review_minimum_salary_yearly").fill("100000")
    page.locator("#continue_to_check").click()
    page.locator('[data-step="4"]').wait_for(state="visible")
    expect(page.locator("#check_locations")).to_contain_text("Sydney")

    # Edit Search Basics, then revisit step 4 through the progress header. The
    # header must execute the same save/validation/summary transition as Continue.
    page.locator("#edit_search_basics").click()
    page.locator('[data-step="3"]').wait_for(state="visible")
    page.locator('#location_search input[data-location-value="Sydney"]').uncheck()
    page.locator('#location_search input[data-location-value="Melbourne"]').check()
    page.locator("#review_minimum_salary_yearly").fill("120000")

    with page.expect_response("**/api/profile") as save_response_info:
        page.locator('[data-step-nav="4"]').click()
    assert save_response_info.value.ok
    page.locator('[data-step="4"]').wait_for(state="visible")
    expect(page.locator("#check_locations")).to_contain_text("Melbourne")
    expect(page.locator("#check_locations")).not_to_contain_text("Sydney")
    expect(page.locator("#check_salary_yearly")).to_contain_text("120,000")
