"""Click-test: settings save round-trip through the real API and DOM, the way
a human toggling a checkbox and clicking Save would experience it."""

from __future__ import annotations

import os

from playwright.sync_api import expect


def _seed_candidate_capabilities(email: str, capabilities: list[dict[str, object]]) -> None:
    from job_hunter_agent.auth import get_or_create_user
    from job_hunter_agent.profile_store import KEY_ONBOARDING_COMPLETE, patch_profile
    from job_hunter_agent.user_context import set_user_id

    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    user = get_or_create_user(email, admin_email)
    set_user_id(user["user_id"])
    try:
        patch_profile(
            {
                KEY_ONBOARDING_COMPLETE: True,
                "candidate_capabilities": capabilities,
            }
        )
    finally:
        set_user_id(None)


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

    preview = card.locator(".capability-alias-preview")
    expect(preview).to_contain_text("scrum")
    expect(preview).to_contain_text("lean delivery")
    assert preview.locator(".cap-alias-chip--preview").count() == 2

    summary = card.locator(".capability-summary-label")
    expect(summary).to_have_text("View 6 related skills")
    assert "+4 more" not in (card.text_content() or "")

    drawer = card.locator("details.capability-alias-drawer")
    card.locator(".cap-alias-summary").click()
    expect(drawer).to_have_attribute("open", "")
    expanded_aliases = drawer.locator(".cap-alias-chips")
    expect(expanded_aliases).to_contain_text("sprint delivery")
    expect(expanded_aliases).to_contain_text("agile project management")
