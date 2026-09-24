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
    expect(card.locator(".capability-summary-label--closed")).to_have_text("+2 more")
    card.locator(".cap-alias-summary").click()
    expect(drawer).to_have_attribute("open", "")
    expect(card.locator(".capability-summary-label--open")).to_have_text("Hide 2")
    expect(drawer.locator(".cap-alias-chip-label")).to_have_text(["postgresql", "docker"])
    card.locator(".cap-alias-summary").click()
    expect(drawer).not_to_have_attribute("open", "")
    expect(card.locator(".capability-summary-label--closed")).to_have_text("+2 more")


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



def test_search_basics_location_layout_stays_compact_and_responsive(
    fresh_candidate_page, monkeypatch
):
    """Protect the actual rendered Location geometry, not just CSS class names."""
    from job_hunter_agent.routes import onboarding_api

    monkeypatch.setattr(onboarding_api, "run_onboarding", _stub_run_onboarding)

    page = fresh_candidate_page
    page.set_viewport_size({"width": 1600, "height": 1000})
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

    location = page.locator("#location_search")
    groups_wrap = location.locator(".location-checkbox-groups")
    groups = location.locator(".location-checkbox-group")
    expect(groups).to_have_count(3)

    def computed(locator, prop):
        return locator.evaluate("(el, prop) => getComputedStyle(el)[prop]", prop)

    def resolved_token(token, prop="fontSize"):
        return page.evaluate(
            """([token, prop]) => {
                const probe = document.createElement('span');
                probe.style.fontSize = `var(${token})`;
                probe.style.fontWeight = `var(${token})`;
                probe.style.lineHeight = `var(${token})`;
                document.body.appendChild(probe);
                const value = getComputedStyle(probe)[prop];
                probe.remove();
                return value;
            }""",
            [token, prop],
        )

    location_value = page.locator(".location-checkbox-option").first
    preference_value = page.locator("#engagement_type_choices .choice-card--work-mode").first
    salary_value = page.locator("#review_minimum_salary_yearly")
    expected_value_size = resolved_token("--text-role-control-value-font-size")
    assert computed(location_value, "fontSize") == expected_value_size
    assert computed(preference_value, "fontSize") == expected_value_size
    assert computed(salary_value, "fontSize") == expected_value_size

    label_selectors = [
        page.locator("#location_search_label"),
        page.locator(".location-checkbox-group legend").first,
        page.locator("#engagement_type_label"),
        page.locator('label[for="review_minimum_salary_yearly"]'),
    ]
    label_sizes = {computed(locator, "fontSize") for locator in label_selectors}
    label_weights = {computed(locator, "fontWeight") for locator in label_selectors}
    assert label_sizes == {resolved_token("--text-role-field-label-font-size")}
    assert label_weights == {resolved_token("--text-role-field-label-font-weight", "fontWeight")}

    def box(locator):
        result = locator.bounding_box()
        assert result is not None
        return result

    step3_grid = page.locator('.review-grid--search-basics')
    step3_sections = step3_grid.locator(':scope > section')
    expect(step3_sections).to_have_count(2)
    desktop_sections = [box(step3_sections.nth(i)) for i in range(2)]
    assert desktop_sections[1]["y"] > desktop_sections[0]["y"]
    assert abs(desktop_sections[0]["width"] - desktop_sections[1]["width"]) < 8

    # Desktop: location fills its section with balanced columns rather than a
    # content-sized cluster stranded at the left of a wide card.
    location_box = box(location)
    wrap_box = box(groups_wrap)
    group_boxes = [box(groups.nth(i)) for i in range(3)]
    assert max(abs(group_boxes[i]["y"] - group_boxes[0]["y"]) for i in range(1, 3)) < 8
    assert max(item["width"] for item in group_boxes) - min(item["width"] for item in group_boxes) < 8
    assert wrap_box["width"] <= location_box["width"]
    assert wrap_box["x"] >= location_box["x"]
    assert wrap_box["x"] + wrap_box["width"] <= location_box["x"] + location_box["width"] + 1

    # Internal two-column lists also remain compact.
    sydney = box(groups.nth(0).locator('.checkbox-list-option:has-text("Sydney")'))
    perth = box(groups.nth(0).locator('.checkbox-list-option:has-text("Perth")'))
    nsw = box(groups.nth(1).locator('.checkbox-list-option:has-text("New South Wales")'))
    sa = box(groups.nth(1).locator('.checkbox-list-option:has-text("South Australia")'))
    assert 8 <= perth["x"] - (sydney["x"] + sydney["width"]) <= 64
    assert 8 <= sa["x"] - (nsw["x"] + nsw["width"]) <= 64

    # Medium desktop: compact content still fits as three groups; do not create
    # the awkward two-groups-plus-centred-Territories orphan row.
    page.set_viewport_size({"width": 1000, "height": 1100})
    group_boxes = [box(groups.nth(i)) for i in range(3)]
    assert max(abs(group_boxes[i]["y"] - group_boxes[0]["y"]) for i in range(1, 3)) < 8
    nsw_box = box(groups.nth(1).locator('.checkbox-list-option:has-text("New South Wales")'))
    # The balanced column can wrap a long state label at medium width; it must
    # grow vertically rather than overlap or force horizontal overflow.
    assert nsw_box["height"] < 48

    # Narrow: switch directly to one stacked column rather than 2 + 1.
    page.set_viewport_size({"width": 760, "height": 1100})
    group_boxes = [box(groups.nth(i)) for i in range(3)]
    assert group_boxes[1]["y"] > group_boxes[0]["y"]
    assert group_boxes[2]["y"] > group_boxes[1]["y"]

    # Phone: groups stay stacked and the page must not overflow horizontally.
    page.set_viewport_size({"width": 390, "height": 1000})
    group_boxes = [box(groups.nth(i)) for i in range(3)]
    assert group_boxes[1]["y"] > group_boxes[0]["y"]
    assert group_boxes[2]["y"] > group_boxes[1]["y"]
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"mobile horizontal overflow is {overflow}px"

    # Search Basics composition: compensation is a compact related subgroup
    # below Work type / Sector / Work mode at desktop widths as well.
    page.set_viewport_size({"width": 1600, "height": 1000})
    preference_groups = page.locator(".search-preference-groups")
    compensation = page.locator(".search-compensation-group")
    salary_fields = compensation.locator(".salary-preference-fields > .onb-field")
    pref_box = box(preference_groups)
    compensation_box = box(compensation)
    preference_items = preference_groups.locator(":scope > .onb-field")
    pref_item_boxes = [box(preference_items.nth(i)) for i in range(3)]
    assert max(abs(pref_item_boxes[i]["y"] - pref_item_boxes[0]["y"]) for i in range(1, 3)) < 8
    assert compensation_box["y"] > pref_box["y"] + pref_box["height"] - 8
    assert abs(compensation_box["x"] - pref_box["x"]) < 8
    annual_box = box(salary_fields.nth(0))
    daily_box = box(salary_fields.nth(1))
    assert abs(annual_box["y"] - daily_box["y"]) < 8
    salary_gap = daily_box["x"] - (annual_box["x"] + annual_box["width"])
    assert 16 <= salary_gap <= 64, f"salary field gap is {salary_gap}px"

    # At medium width the same grouping remains stable and gives Work type /
    # Sector / Work mode the full row.
    page.set_viewport_size({"width": 1100, "height": 1100})
    medium_sections = [box(step3_sections.nth(i)) for i in range(2)]
    assert medium_sections[1]["y"] > medium_sections[0]["y"]
    pref_box = box(preference_groups)
    compensation_box = box(compensation)
    assert compensation_box["y"] > pref_box["y"] + pref_box["height"] - 8
    preference_items = preference_groups.locator(":scope > .onb-field")
    pref_item_boxes = [box(preference_items.nth(i)) for i in range(3)]
    assert max(abs(pref_item_boxes[i]["y"] - pref_item_boxes[0]["y"]) for i in range(1, 3)) < 8
    annual_box = box(salary_fields.nth(0))
    daily_box = box(salary_fields.nth(1))
    assert abs(annual_box["y"] - daily_box["y"]) < 8

    # Phone stacks the two Step 3 cards and every control group.
    page.set_viewport_size({"width": 390, "height": 1000})
    phone_cards = [box(step3_sections.nth(i)) for i in range(2)]
    assert phone_cards[1]["y"] > phone_cards[0]["y"]
    pref_item_boxes = [box(preference_items.nth(i)) for i in range(3)]
    assert pref_item_boxes[1]["y"] > pref_item_boxes[0]["y"]
    assert pref_item_boxes[2]["y"] > pref_item_boxes[1]["y"]

    # Phone stacks the salary fields as well.
    annual_box = box(salary_fields.nth(0))
    daily_box = box(salary_fields.nth(1))
    assert daily_box["y"] > annual_box["y"]
    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"mobile search-basics horizontal overflow is {overflow}px"

def test_onboarding_capability_review_reuses_shared_strength_and_persists_choice(
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

    card = page.locator("#review_capability_cards .capability-card").first
    card.wait_for(state="visible")
    meter = card.locator(".capability-strength-meter")

    # CV extraction supplied Strong, and onboarding exposes that same shared
    # strength control rather than hiding the value from the user.
    expect(meter.locator(".capability-strength-label")).to_have_text("Strong")
    expect(meter.locator(".capability-strength-dot.is-filled")).to_have_count(3)
    expect(card.locator(".capability-alias-label")).to_have_text("Related skills")
    expect(card.locator(".capability-card-icon")).to_have_count(0)
    expect(page.locator("#review_capability_helper")).to_have_count(0)
    expect(page.locator("#continue_to_search_basics")).to_have_text("Continue")

    # User correction is draft state and must survive a reload before Finish Setup.
    meter.locator('label[for$="_working"]').click()
    expect(meter.locator(".capability-strength-label")).to_have_text("Working")
    expect(meter.locator(".capability-strength-dot.is-filled")).to_have_count(2)

    page.reload()
    page.locator('[data-step="2"]').wait_for(state="visible")
    restored_card = page.locator("#review_capability_cards .capability-card").first
    restored_meter = restored_card.locator(".capability-strength-meter")
    expect(restored_meter.locator(".capability-strength-label")).to_have_text("Working")
    expect(restored_meter.locator(".capability-strength-dot.is-filled")).to_have_count(2)


def test_step1_disclosures_share_content_spacing(fresh_candidate_page):
    page = fresh_candidate_page
    page.set_viewport_size({"width": 1400, "height": 1000})
    page.goto('/start')

    drawers = page.locator('.onboarding-upload-card > details.workflow-drawer')
    expect(drawers).to_have_count(2)
    for index in range(2):
        drawers.nth(index).evaluate('el => { el.open = true; }')

    privacy = drawers.nth(0)
    guidance = drawers.nth(1)

    def box(locator):
        result = locator.bounding_box()
        assert result is not None
        return result

    privacy_summary = box(privacy.locator('.workflow-drawer-summary'))
    privacy_first = box(privacy.locator('.workflow-drawer-body > p').first)
    guidance_summary = box(guidance.locator('.workflow-drawer-summary'))
    guidance_first = box(guidance.locator('.guidance-grid h3').first)

    privacy_gap = privacy_first['y'] - (privacy_summary['y'] + privacy_summary['height'])
    guidance_gap = guidance_first['y'] - (guidance_summary['y'] + guidance_summary['height'])
    assert abs(privacy_gap - guidance_gap) <= 2, (privacy_gap, guidance_gap)


def test_step1_cv_lookback_control_exposes_real_extraction_setting(fresh_candidate_page):
    page = fresh_candidate_page
    page.set_viewport_size({"width": 1400, "height": 1000})
    page.goto('/start')

    lookback = page.locator('#os_extraction_lookback_years')
    expect(lookback).to_have_count(1)
    expect(lookback).to_have_value('8')
    expect(lookback).to_have_attribute('min', '1')
    expect(lookback).to_have_attribute('max', '20')
    expect(page.locator('label[for="os_extraction_lookback_years"]')).to_have_text(
        'How far back should Job Hunter analyse your CV?'
    )
    expect(lookback.locator('xpath=..').locator('.field-control-unit')).to_have_text('years')
    expect(page.locator('a[href*="USER_GUIDE.md"]')).to_have_count(0)

    card = lookback.locator('xpath=ancestor::section[1]')
    card.locator('.field-info').click()
    expect(card.locator('.field-info-panel')).to_contain_text('building your draft profile')
    expect(card.locator('.field-info-panel')).not_to_contain_text('matching')
