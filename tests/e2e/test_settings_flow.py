"""Click-test: settings save round-trip through the real API and DOM, the way
a human toggling a checkbox and clicking Save would experience it."""

from __future__ import annotations

import os
import re

from playwright.sync_api import expect


def _seed_contract_preferences(email: str) -> None:
    from job_hunter_agent.auth import get_or_create_user
    from job_hunter_agent.profile_store import (
        ENGAGEMENT_TYPE_DEFAULT_VALUES,
        KEY_ENGAGEMENT_TYPE,
        KEY_MATCH_PREFS,
        patch_profile,
    )
    from job_hunter_agent.user_context import set_user_id

    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    user = get_or_create_user(email, admin_email)
    set_user_id(user["user_id"])
    try:
        patch_profile(
            {
                KEY_MATCH_PREFS: {
                    KEY_ENGAGEMENT_TYPE: ENGAGEMENT_TYPE_DEFAULT_VALUES,
                    "min_contract_months": None,
                }
            }
        )
    finally:
        set_user_id(None)


def _seed_candidate_capabilities(email: str, capabilities: list[dict[str, object]]) -> None:
    from job_hunter_agent.auth import get_or_create_user
    from job_hunter_agent.profile_store import KEY_ONBOARDING_COMPLETE, load_profile, save_profile
    from job_hunter_agent.user_context import set_user_id

    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    user = get_or_create_user(email, admin_email)
    set_user_id(user["user_id"])
    try:
        profile = load_profile()
        profile[KEY_ONBOARDING_COMPLETE] = True
        profile["candidate_capabilities"] = capabilities
        save_profile(
            profile,
            # These rows are deterministic fixture data for testing the
            # Settings renderer, not inputs to the capability-atomicity LLM.
            prevalidated_capability_names={
                str(item.get("name") or "").strip()
                for item in capabilities
                if str(item.get("name") or "").strip()
            },
        )
    finally:
        set_user_id(None)


def _seed_schedule_enabled(email: str) -> None:
    """Enable Schedule Run so the test exercises scheduler availability, not the off state."""
    from job_hunter_agent.auth import get_or_create_user
    from job_hunter_agent.user_settings import save_user_settings

    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    user = get_or_create_user(email, admin_email)
    save_user_settings(user["user_id"], {"schedule": {"enabled": True}})


def test_external_plan_token_can_be_created_and_revoked(candidate_page):
    page = candidate_page
    page.goto("/settings")
    page.locator('[data-section="section-alerts"]').click()

    panel = page.locator("#agent_tokens_panel")
    expect(panel).to_be_visible()
    panel.locator("#generate_agent_token").click()

    secret = panel.locator("#agent_token_secret")
    expect(secret).to_be_visible()
    assert secret.input_value().startswith("jh_at_")
    expect(panel).to_contain_text("Career Search Plans")
    expect(panel.locator("#copy_agent_token")).to_be_visible()

    revoke = panel.locator("[data-revoke-agent-token]").first
    expect(revoke).to_be_visible()
    revoke.click()
    expect(panel).to_contain_text("No active plan tokens.")


def test_contract_length_uses_light_dismiss_popover(candidate_page):
    _seed_contract_preferences("candidate@e2e.test")

    page = candidate_page
    page.goto("/settings")

    contract_input = page.locator('input[name="engagement_type"][value="contract"]')
    contract_chip = page.locator('label.choice-card:has(input[name="engagement_type"][value="contract"])')
    popover = page.locator("#contract_duration_row")

    expect(contract_input).to_be_checked()
    expect(contract_chip).to_contain_text("Contract (all)")
    expect(popover).to_be_hidden()

    contract_chip.click()
    expect(popover).to_be_visible()
    expect(contract_input).to_be_checked()
    expect(popover.locator(".field-info-drawer")).to_have_count(0)

    chip_box = contract_chip.bounding_box()
    popover_box = popover.bounding_box()
    field_box = page.locator("#engagement_type_label").locator("xpath=../..").bounding_box()
    assert chip_box and popover_box and field_box
    assert popover_box["width"] < field_box["width"] * 0.6
    assert popover_box["height"] < chip_box["height"] * 3
    is_below = popover_box["y"] >= chip_box["y"] + chip_box["height"]
    is_above = popover_box["y"] + popover_box["height"] <= chip_box["y"]
    assert is_below or is_above

    page.locator("#work_mode_preference_label").click()
    expect(popover).to_be_hidden()
    expect(contract_input).to_be_checked()
    expect(contract_chip).to_contain_text("Contract (all)")


def test_settings_toggle_persists_after_reload(candidate_page):
    page = candidate_page
    page.goto("/settings")
    page.locator('[data-section="section-alerts"]').click()

    checkbox = page.locator("#telegram_disable_link_preview")
    checkbox.wait_for(state="attached")
    was_checked = checkbox.is_checked()
    # The checkbox is visually replaced by a custom toggle-switch span, so a
    # human clicks the switch label (there's also a plain text label with the
    # same `for=`), not the covered input.
    page.locator('label.toggle-switch[for="telegram_disable_link_preview"]').click()

    save_btn = page.locator("#save_settings_btn")
    expect(save_btn).to_be_enabled()
    save_btn.click()
    # The inline #global_save_status span is set to "Settings saved." and then
    # immediately cleared by clearDirty() in the same save flow, so the only
    # stable human-visible confirmation is the #status toast banner.
    expect(page.locator("#status")).to_contain_text("Settings saved successfully.")

    page.reload()
    page.locator('[data-section="section-alerts"]').click()
    reloaded_checkbox = page.locator("#telegram_disable_link_preview")
    reloaded_checkbox.wait_for(state="visible")
    assert reloaded_checkbox.is_checked() != was_checked, (
        "checkbox state did not persist across reload"
    )


def test_schedule_toggle_persists_after_reload(candidate_page):
    page = candidate_page
    page.goto("/settings")

    checkbox = page.locator("#schedule_enabled")
    checkbox.wait_for(state="attached")
    was_checked = checkbox.is_checked()
    page.locator('label.toggle-switch[for="schedule_enabled"]').click()

    save_btn = page.locator("#save_settings_btn")
    expect(save_btn).to_be_enabled()
    save_btn.click()
    expect(page.locator("#status")).to_contain_text("Settings saved successfully.")

    page.reload()
    reloaded_checkbox = page.locator("#schedule_enabled")
    reloaded_checkbox.wait_for(state="visible")
    assert reloaded_checkbox.is_checked() != was_checked, (
        "schedule toggle state did not persist across reload"
    )


def test_schedule_status_does_not_claim_next_run_when_scheduler_is_inactive(candidate_page):
    _seed_schedule_enabled("candidate@e2e.test")

    page = candidate_page
    page.goto("/settings#section-search")

    status = page.locator("#schedule_runtime_status")
    status.wait_for(state="visible")
    expect(status).to_have_text("Scheduler unavailable — automatic runs will not start.")
    assert "Next run:" not in (status.text_content() or "")


def test_settings_save_confirmation_shows_linkedin_before_and_after(candidate_page):
    page = candidate_page
    page.goto("/settings#section-search")

    results_input = page.locator("#linkedin_results_per_search")
    results_input.wait_for(state="visible")
    # The control exists before the asynchronous profile load finishes. Wait for
    # hydration rather than treating DOM visibility as proof that data is ready.
    page.wait_for_function(
        "() => document.getElementById('linkedin_results_per_search')?.value !== ''"
    )
    before = int(results_input.input_value())
    after = before - 1 if before > 5 else before + 1
    results_input.fill(str(after))

    page.locator("#save_settings_btn").click()
    expect(page.locator("#status")).to_contain_text("Settings saved successfully.")


def test_capability_alias_preview_uses_related_skills_copy(candidate_page):
    _seed_candidate_capabilities(
        "candidate@e2e.test",
        [
            {
                "name": "agile delivery",
                "level": "strong",
                "aliases": [
                    "scrum",
                    "lean delivery",
                    "sprint delivery",
                    "backlog refinement",
                    "agile project management",
                    "scrum master",
                ],
                "icon_key": "delivery_project",
            }
        ],
    )

    page = candidate_page
    page.goto("/settings#section-matrix")

    card = page.locator("#capability_matrix_editor .capability-card").first
    card.wait_for(state="visible")

    meter = card.locator(".capability-strength-meter")
    expect(meter.locator(".capability-strength-dot")).to_have_count(3)
    expect(meter.locator(".capability-strength-dot.is-filled")).to_have_count(3)
    expect(meter.locator(".capability-strength-label")).to_have_text("Strong")

    # Capability Matrix keeps the capability name and saved strength on one compact row.
    name_box = card.locator(".capability-card-head").bounding_box()
    meter_box = meter.bounding_box()
    assert name_box and meter_box
    assert abs((name_box["y"] + name_box["height"] / 2) - (meter_box["y"] + meter_box["height"] / 2)) <= 3

    tooltip = meter.locator(".capability-strength-tooltip")
    expect(tooltip).to_have_css("visibility", "hidden")
    meter.hover()
    page.wait_for_timeout(400)
    expect(tooltip).to_have_css("visibility", "hidden")
    page.wait_for_timeout(2800)
    expect(tooltip).to_have_css("visibility", "visible")
    page.mouse.move(0, 0)
    expect(tooltip).to_have_css("visibility", "hidden")

    expect(card.locator(".capability-alias-label")).to_have_text("Related skills")
    preview = card.locator(".capability-alias-preview")
    expect(preview).to_contain_text("scrum")
    expect(preview).to_contain_text("lean delivery")
    assert preview.locator(".cap-alias-chip--preview").count() == 2

    summary = card.locator(".capability-summary-label--closed")
    expect(summary).to_have_text("+4 more")
    assert "Show 4 more" not in (card.text_content() or "")

    drawer = card.locator("details.capability-alias-drawer")
    card.locator(".cap-alias-summary").click()
    expect(drawer).to_have_attribute("open", "")
    expect(card.locator(".capability-summary-label--open")).to_have_text("Hide 4")
    expanded_aliases = drawer.locator(".cap-alias-chips")
    expect(expanded_aliases.locator(".cap-alias-chip-label")).to_have_text(
        [
            "sprint delivery",
            "backlog refinement",
            "agile project management",
            "scrum master",
        ]
    )
    card.locator(".cap-alias-summary").click()
    expect(drawer).not_to_have_attribute("open", "")
    expect(summary).to_have_text("+4 more")


def test_capability_related_skills_disclosure_hides_only_actual_remaining_skills(candidate_page):
    _seed_candidate_capabilities(
        "candidate@e2e.test",
        [
            {
                "name": "no hidden skills",
                "level": "strong",
                "aliases": ["skill one", "skill two"],
                "icon_key": "delivery_project",
            },
            {
                "name": "one hidden skill",
                "level": "working",
                "aliases": ["skill one", "skill two", "skill three"],
                "icon_key": "delivery_project",
            },
        ],
    )

    page = candidate_page
    page.goto("/settings#section-matrix")
    cards = page.locator("#capability_matrix_editor .capability-card")
    cards.first.wait_for(state="visible")

    no_hidden_card = page.locator(
        'input.capability-card-name[value="No Hidden Skills"]'
    ).locator("xpath=ancestor::article[contains(@class, 'capability-card')]")
    expect(no_hidden_card.locator(".capability-alias-preview .cap-alias-chip")).to_have_count(2)
    expect(no_hidden_card.locator("details.capability-alias-drawer")).to_have_count(0)

    one_hidden_card = page.locator(
        'input.capability-card-name[value="One Hidden Skill"]'
    ).locator("xpath=ancestor::article[contains(@class, 'capability-card')]")
    expect(one_hidden_card.locator(".capability-alias-preview .cap-alias-chip")).to_have_count(2)
    expect(one_hidden_card.locator(".capability-summary-label--closed")).to_have_text("+1 more")
    preview_box = one_hidden_card.locator(".capability-alias-preview").bounding_box()
    more_box = one_hidden_card.locator(".cap-alias-summary").bounding_box()
    assert preview_box and more_box
    assert abs((preview_box["y"] + preview_box["height"] / 2) - (more_box["y"] + more_box["height"] / 2)) <= 4
    assert more_box["x"] > preview_box["x"]


def test_settings_label_info_rows_share_alignment_and_single_spacing(candidate_page):
    page = candidate_page
    page.goto("/settings#section-matrix")

    preferred_row = page.locator('label[for="target_roles_add"]').locator("xpath=parent::*")
    expect(preferred_row).to_have_class(re.compile(r"\bfield-label-row\b"))
    label_box = preferred_row.locator('label[for="target_roles_add"]').bounding_box()
    info_box = preferred_row.locator('.field-info').bounding_box()
    assert label_box and info_box
    assert abs((label_box["y"] + label_box["height"] / 2) - (info_box["y"] + info_box["height"] / 2)) <= 2

    preferred_field = preferred_row.locator("xpath=parent::*")
    row_box = preferred_row.bounding_box()
    badge_box = preferred_field.locator('.badge-editor').bounding_box()
    assert row_box and badge_box
    # One shared field gap: no second hard-coded 12px margin may stack on top.
    assert 8 <= badge_box["y"] - (row_box["y"] + row_box["height"]) <= 16

    role_copy = page.locator('#section-matrix .search-settings-subcard').first.locator(':scope > .panel-copy')
    role_copy_box = role_copy.bounding_box()
    preferred_box = preferred_row.bounding_box()
    assert role_copy_box and preferred_box
    assert preferred_box["y"] - (role_copy_box["y"] + role_copy_box["height"]) >= 12

    page.locator('[data-section="section-rules"]').click()
    for control_id in ("must_not_require_skills_add", "reject_description_phrase_rules_add"):
        row = page.locator(f'label[for="{control_id}"]').locator("xpath=parent::*")
        expect(row).to_have_class(re.compile(r"\bfield-label-row\b"))
        label = row.locator(f'label[for="{control_id}"]').bounding_box()
        info = row.locator('.field-info').bounding_box()
        assert label and info
        assert abs((label["y"] + label["height"] / 2) - (info["y"] + info["height"] / 2)) <= 3


def test_capability_related_skills_beyond_alias_limit_survive_settings_save(candidate_page):
    # capability_alias_limit only bounds automatic CV-extraction; a save/reload
    # round trip through the real Settings UI must never truncate a capability's
    # already-confirmed Related Skills down to that limit.
    related_skills = [
        "scrum",
        "lean delivery",
        "sprint delivery",
        "backlog refinement",
        "agile project management",
        "scrum master",
        "kanban",
        "release planning",
        "story mapping",
        "velocity tracking",
        "retrospectives",
        "product backlog",
    ]
    _seed_candidate_capabilities(
        "candidate@e2e.test",
        [
            {
                "name": "agile delivery",
                "level": "strong",
                "aliases": related_skills,
                "icon_key": "delivery_project",
            }
        ],
    )

    page = candidate_page
    page.goto("/settings#section-matrix")

    card = page.locator("#capability_matrix_editor .capability-card").first
    card.wait_for(state="visible")

    # The capability matrix editor itself isn't touched here, so mark the form
    # dirty (as a human would by changing some unrelated field) to enable Save
    # and exercise the same serialize-whole-profile round trip a real save does.
    page.locator('[data-section="section-alerts"]').click()
    page.locator('label.toggle-switch[for="telegram_disable_link_preview"]').click()
    page.locator('[data-section="section-matrix"]').click()

    save_btn = page.locator("#save_settings_btn")
    expect(save_btn).to_be_enabled()
    save_btn.click()
    expect(page.locator("#status")).to_contain_text("Settings saved successfully.")

    page.reload()
    reloaded_card = page.locator("#capability_matrix_editor .capability-card").first
    reloaded_card.wait_for(state="visible")

    summary = reloaded_card.locator(".capability-summary-label--closed")
    expect(summary).to_have_text(f"+{len(related_skills) - 2} more")

    drawer = reloaded_card.locator("details.capability-alias-drawer")
    reloaded_card.locator(".cap-alias-summary").click()
    expect(drawer).to_have_attribute("open", "")
    expanded_aliases = drawer.locator(".cap-alias-chips")
    assert expanded_aliases.locator(".cap-alias-chip-label").count() == len(
        related_skills
    ) - 2, "all confirmed Related Skills beyond the preview must survive the round trip"


def test_role_entry_adds_directly_without_role_family_popup(candidate_page):
    page = candidate_page
    dialogs: list[str] = []
    page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))

    page.goto("/settings#section-matrix")
    role_help = page.locator("#section-matrix .search-settings-subcard").first.locator(".panel-copy").first
    expect(role_help).to_contain_text("Job Hunter searches each preferred and alternative role separately")
    expect(role_help).not_to_contain_text("__JOB_HUNTER_TITLE_TIER_ROLE_SEARCH_HELP__")

    role_input = page.locator("#target_roles_add")
    role_input.fill("Implementation Consultant")
    page.locator('[data-add-chip="target_roles"]').click()

    expect(page.locator("#target_roles_chips")).to_contain_text("Implementation Consultant")
    assert dialogs == []

    alternative_input = page.locator("#also_consider_roles_add")
    alternative_input.fill("SAP S/4HANA Consultant")
    page.locator('[data-add-chip="also_consider_roles"]').click()

    expect(page.locator("#also_consider_roles_chips")).to_contain_text("SAP S/4HANA Consultant")
    assert dialogs == []

    save_btn = page.locator("#save_settings_btn")
    expect(save_btn).to_be_enabled()
    save_btn.click()
    expect(page.locator("#status")).to_contain_text("Settings saved successfully.")

    page.reload()
    expect(page.locator("#target_roles_chips")).to_contain_text("Implementation Consultant")
    expect(page.locator("#also_consider_roles_chips")).to_contain_text("SAP S/4HANA Consultant")


def test_capability_matrix_grid_adapts_to_available_width(candidate_page):
    _seed_candidate_capabilities(
        "candidate@e2e.test",
        [
            {"name": "capability one", "level": "strong", "aliases": ["one"], "icon_key": "generic"},
            {"name": "capability two", "level": "working", "aliases": ["two"], "icon_key": "generic"},
            {"name": "capability three", "level": "basic", "aliases": ["three"], "icon_key": "generic"},
            {"name": "capability four", "level": "strong", "aliases": ["four"], "icon_key": "generic"},
        ],
    )

    page = candidate_page
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto("/settings#section-matrix")
    cards = page.locator("#capability_matrix_editor .capability-card")
    expect(cards).to_have_count(4)

    wide_boxes = [cards.nth(i).bounding_box() for i in range(3)]
    assert all(wide_boxes)
    assert max(abs(box["y"] - wide_boxes[0]["y"]) for box in wide_boxes[1:]) <= 3

    page.set_viewport_size({"width": 1400, "height": 1000})
    desktop_boxes = [cards.nth(i).bounding_box() for i in range(3)]
    assert all(desktop_boxes)
    assert abs(desktop_boxes[0]["y"] - desktop_boxes[1]["y"]) <= 3
    assert desktop_boxes[2]["y"] > desktop_boxes[0]["y"] + 20

    page.set_viewport_size({"width": 820, "height": 1000})
    narrow_boxes = [cards.nth(i).bounding_box() for i in range(3)]
    assert all(narrow_boxes)
    assert narrow_boxes[1]["y"] > narrow_boxes[0]["y"] + 20
    assert narrow_boxes[2]["y"] > narrow_boxes[1]["y"] + 20


def test_suggested_tuning_separates_factual_no_from_dismiss(candidate_page):
    page = candidate_page
    decisions = []
    returned_profile = None
    review_payload = {
        "suggested_tuning": {
            "capability_suggestions": [
                {
                    "skill": "Power BI",
                    "count": 2,
                    "recommended_choice": "working",
                    "recommended_label": "Working",
                    "examples": [],
                },
                {
                    "skill": "Mentoring",
                    "count": 2,
                    "recommended_choice": "working",
                    "recommended_label": "Working",
                    "examples": [],
                },
                {
                    "skill": "Technical documentation",
                    "count": 2,
                    "recommended_choice": "working",
                    "recommended_label": "Working",
                    "examples": [],
                },
            ],
            "requirement_suggestions": [
                {
                    "kind": "requirement",
                    "skill": "Power BI",
                    "count": 3,
                    "aliases": ["Power BI required"],
                    "examples": [
                        {
                            "title": "Senior Business Analyst",
                            "company": "Example Co",
                            "url": "https://example.test/power-bi",
                            "search_location": "Sydney",
                        }
                    ],
                }
            ],
            "optimization_suggestions": [],
            "rule_suggestions": [],
            "summary": {"capability_count": 1},
        }
    }

    def handle_review_data(route):
        route.fulfill(status=200, content_type="application/json", json=review_payload)

    def handle_tuning_decision(route):
        decisions.append(route.request.post_data_json)
        route.fulfill(
            status=200,
            content_type="application/json",
            json={"ok": True, "profile": returned_profile},
        )

    page.route("**/api/review-data", handle_review_data)
    page.route("**/api/tuning-decisions", handle_tuning_decision)
    page.goto("/settings")
    returned_profile = page.evaluate("async () => await (await fetch('/api/profile')).json()")
    returned_profile["candidate_capabilities"] = [
        *(returned_profile.get("candidate_capabilities") or []),
        {"name": "Power BI", "level": "working", "aliases": ["Power BI required"], "icon_key": "generic"},
    ]
    page.locator('[data-section="section-optimise"]').click()

    review_head = page.locator("#section-optimise .search-settings-subcard > .settings-card-title-row")
    expect(review_head.locator("h3")).to_have_text("Review Suggestions (3)")
    count = review_head.locator(".settings-heading-count")
    heading_size = float(review_head.locator("h3").evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
    count_size = float(count.evaluate("el => parseFloat(getComputedStyle(el).fontSize)"))
    assert count_size < heading_size
    info = review_head.locator(".field-info-drawer")
    expect(info).to_have_count(1)
    expect(info.locator("summary")).to_have_attribute("aria-label", "About review suggestions")
    expect(info.locator(".field-info-panel")).to_contain_text("Matching → Capability Matrix")
    expect(info.locator(".field-info-panel")).to_contain_text("will not be suggested again")
    expect(page.locator("#section-optimise .optimise-review-info")).to_have_count(0)
    expect(page.locator("#section-optimise")).not_to_contain_text("These are suggestions only")
    expect(page.locator("#tuning_suggestions_panel")).not_to_contain_text("Capabilities are the proven work strengths")
    expect(page.locator("#tuning_suggestions_panel")).not_to_contain_text("Capabilities to review")
    expect(page.locator("#tuning_suggestions_panel")).not_to_contain_text("Capabilities to verify")
    expect(page.locator("#tuning_suggestions_panel")).not_to_contain_text("Things Job Hunter found repeatedly that may belong in your Capability Matrix.")

    title_box = review_head.locator("h3").bounding_box()
    info_box = review_head.locator(".field-info").bounding_box()
    assert title_box and info_box
    assert abs((title_box["y"] + title_box["height"] / 2) - (info_box["y"] + info_box["height"] / 2)) <= 2

    capability_cards = page.locator('#tuning_suggestions_panel .review-list > .review-card[data-review-kind="capability"]')
    expect(capability_cards).to_have_count(3)

    # Optimise adapts to available width instead of hard-coding two cards per row.
    page.set_viewport_size({"width": 1920, "height": 1080})
    wide_boxes = [capability_cards.nth(i).bounding_box() for i in range(3)]
    assert all(wide_boxes)
    assert max(abs(box["y"] - wide_boxes[0]["y"]) for box in wide_boxes[1:]) <= 3

    page.set_viewport_size({"width": 1400, "height": 1000})
    desktop_boxes = [capability_cards.nth(i).bounding_box() for i in range(3)]
    assert all(desktop_boxes)
    assert abs(desktop_boxes[0]["y"] - desktop_boxes[1]["y"]) <= 3
    assert desktop_boxes[2]["y"] > desktop_boxes[0]["y"] + 20

    page.set_viewport_size({"width": 820, "height": 1000})
    narrow_boxes = [capability_cards.nth(i).bounding_box() for i in range(3)]
    assert all(narrow_boxes)
    assert narrow_boxes[1]["y"] > narrow_boxes[0]["y"] + 20
    assert narrow_boxes[2]["y"] > narrow_boxes[1]["y"] + 20
    page.set_viewport_size({"width": 1400, "height": 1000})

    card = page.locator("#tuning_suggestions_panel .review-card").filter(has_text="Power BI")
    expect(card).to_be_visible()
    no_button = card.locator(".do-not-have-skill-btn")
    dismiss_button = card.locator(".decline-skill-btn")
    expect(no_button).to_have_text("No, I don't have this")
    expect(dismiss_button).to_have_text("Ignore suggestion")
    expect(card).not_to_contain_text("Suggested: Working")
    expect(card).not_to_contain_text("What this choice means")
    expect(card.locator(".review-card-count")).to_have_text("Seen in 3 kept roles")
    expect(card).not_to_contain_text("How strong is this capability for you?")
    expect(card.locator(".review-strength-question")).to_have_count(0)
    meter = card.locator(".capability-strength-meter")
    expect(meter.locator(".capability-strength-dot")).to_have_count(3)
    expect(meter.locator(".capability-strength-label")).to_have_text("Select strength")
    expect(card.locator('input[type="radio"]:checked')).to_have_count(0)

    # Optimise uses the same compact decision-row pattern: title + strength, count at right.
    capability_title_box = card.locator(".review-card-heading h3").bounding_box()
    suggestion_meter_box = meter.bounding_box()
    count_box = card.locator(".review-card-count").bounding_box()
    assert capability_title_box and suggestion_meter_box and count_box
    title_center_y = capability_title_box["y"] + capability_title_box["height"] / 2
    meter_center_y = suggestion_meter_box["y"] + suggestion_meter_box["height"] / 2
    count_center_y = count_box["y"] + count_box["height"] / 2
    assert abs(title_center_y - meter_center_y) <= 3
    assert abs(title_center_y - count_center_y) <= 3
    assert count_box["x"] > suggestion_meter_box["x"]
    confirm_button = card.locator(".confirm-skill-btn")
    expect(confirm_button).to_be_disabled()
    card.locator('label[for="skill-choice-0_working"]').click()
    expect(card.locator('input[value="working"]')).to_be_checked()
    expect(meter.locator(".capability-strength-label")).to_have_text("Working")
    expect(meter.locator(".capability-strength-dot.is-filled")).to_have_count(2)
    expect(confirm_button).to_be_enabled()
    expect(card.locator(".review-evidence summary")).to_have_text("Why Job Hunter suggested this")
    card.locator(".review-evidence summary").click()
    expect(card.locator(".review-evidence")).to_contain_text("Found repeatedly across 3 jobs you kept.")
    expect(card.locator(".review-evidence")).to_contain_text("Job ads explicitly asked for:")
    expect(card.locator(".review-evidence")).to_contain_text("Power BI required")
    expect(page.locator("#tuning_suggestions_panel .review-card").filter(has_text="Power BI")).to_have_count(1)

    with page.expect_request("**/api/tuning-decisions") as confirm_request:
        confirm_button.click()
    assert confirm_request.value.post_data_json["decisions"][0]["choice"] == "working"
    expect(page.locator("#status")).to_contain_text("Added Power BI — Working.")
    expect(page.locator("#status")).not_to_contain_text("fillForm is not defined")
    expect(card).to_have_count(0)

    # Exercise factual absence from a fresh render.
    page.reload()
    page.locator('[data-section="section-optimise"]').click()
    card = page.locator("#tuning_suggestions_panel .review-card").filter(has_text="Power BI")
    expect(card).to_be_visible()
    no_button = card.locator(".do-not-have-skill-btn")
    dismiss_button = card.locator(".decline-skill-btn")

    no_box = no_button.bounding_box()
    dismiss_box = dismiss_button.bounding_box()
    assert no_box and dismiss_box
    assert no_box["width"] > 0 and dismiss_box["width"] > 0

    with page.expect_request("**/api/tuning-decisions") as no_request:
        no_button.click()
    assert no_request.value.post_data_json["decisions"][0]["choice"] == "do_not_have"
    expect(card).to_have_count(0)

    # Exercise Ignore suggestion from a fresh render.
    page.reload()
    page.locator('[data-section="section-optimise"]').click()
    card = page.locator("#tuning_suggestions_panel .review-card").filter(has_text="Power BI")
    expect(card).to_be_visible()
    with page.expect_request("**/api/tuning-decisions") as dismiss_request:
        card.locator(".decline-skill-btn").click()
    assert dismiss_request.value.post_data_json["decisions"][0]["choice"] == "dismiss"


def test_search_basics_shared_layout_stays_balanced_at_settings_width(candidate_page):
    """Protect the shared Search Basics geometry inside the narrower Settings shell."""
    page = candidate_page
    page.set_viewport_size({"width": 1400, "height": 1000})
    page.goto("/settings#section-search")

    locations = page.locator("#locations")
    groups = locations.locator(".location-checkbox-group")
    expect(groups).to_have_count(3)

    def box(locator):
        result = locator.bounding_box()
        assert result is not None
        return result

    # Settings has enough room for all three location groups. Never orphan
    # Territories on a centred second row.
    group_boxes = [box(groups.nth(i)) for i in range(3)]
    assert max(abs(group_boxes[i]["y"] - group_boxes[0]["y"]) for i in range(1, 3)) < 8

    basics = page.locator(".search-basics-fields")
    preference_groups = basics.locator(".search-preference-groups")
    compensation = basics.locator(".search-compensation-group")
    preference_items = preference_groups.locator(":scope > .settings-form-field")
    expect(preference_items).to_have_count(3)

    # In the narrower Settings shell, compensation drops below so the three
    # search preference controls keep one coherent row.
    pref_box = box(preference_groups)
    compensation_box = box(compensation)
    assert compensation_box["y"] > pref_box["y"] + pref_box["height"] - 8
    item_boxes = [box(preference_items.nth(i)) for i in range(3)]
    assert max(abs(item_boxes[i]["y"] - item_boxes[0]["y"]) for i in range(1, 3)) < 8

    salary_fields = compensation.locator(".salary-preference-fields > .settings-form-field")
    expect(salary_fields).to_have_count(2)
    annual_box = box(salary_fields.nth(0))
    daily_box = box(salary_fields.nth(1))
    assert abs(annual_box["y"] - daily_box["y"]) < 8
    salary_gap = daily_box["x"] - (annual_box["x"] + annual_box["width"])
    assert 16 <= salary_gap <= 64, f"salary field gap is {salary_gap}px"

    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    assert overflow <= 1, f"settings search horizontal overflow is {overflow}px"
