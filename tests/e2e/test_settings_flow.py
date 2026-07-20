"""Click-test: settings save round-trip through the real API and DOM, the way
a human toggling a checkbox and clicking Save would experience it."""

from __future__ import annotations

from playwright.sync_api import expect


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
