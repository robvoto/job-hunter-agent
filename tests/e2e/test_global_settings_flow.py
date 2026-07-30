"""Click-tests for the admin global-settings page."""

from __future__ import annotations

from uuid import uuid4

from playwright.sync_api import expect


def _toggle_switch(page, control_id: str) -> None:
    # The real clickable surface is the styled label, not the covered checkbox.
    page.locator(f'label.toggle-switch[for="{control_id}"]').click()


def _seed_system_warning(message: str) -> None:
    from job_hunter_agent.system_warnings import (
        make_system_warning_fingerprint,
        record_system_warning,
    )

    record_system_warning(
        severity="warning",
        category="e2e_admin_flow",
        source="playwright",
        message=message,
        fingerprint=make_system_warning_fingerprint("e2e-admin-flow", message),
        context={"test": "test_admin_system_warning_can_be_reviewed"},
    )


def test_admin_headless_toggle_persists_after_reload(admin_page):
    page = admin_page
    page.goto("/global-settings")

    checkbox = page.locator("#playwright_headless")
    checkbox.wait_for(state="attached")
    original_value = checkbox.is_checked()

    _toggle_switch(page, "playwright_headless")

    save_btn = page.locator("#save_admin_btn")
    expect(save_btn).to_be_enabled()
    with page.expect_response("**/api/global-settings") as response_info:
        save_btn.click()
    assert response_info.value.ok, (
        f"global settings save failed: {response_info.value.status} {response_info.value.text()}"
    )
    expect(page.locator("#status")).to_contain_text("Global settings saved successfully.")

    page.reload()
    reloaded_checkbox = page.locator("#playwright_headless")
    reloaded_checkbox.wait_for(state="visible")
    assert reloaded_checkbox.is_checked() != original_value, (
        "headless toggle state did not persist across reload"
    )

    _toggle_switch(page, "playwright_headless")
    with page.expect_response("**/api/global-settings") as response_info:
        page.locator("#save_admin_btn").click()
    assert response_info.value.ok, (
        f"global settings restore failed: {response_info.value.status} {response_info.value.text()}"
    )
    page.reload()
    assert page.locator("#playwright_headless").is_checked() == original_value


def test_admin_discard_changes_restores_original_value(admin_page):
    page = admin_page
    page.goto("/global-settings")

    checkbox = page.locator("#playwright_headless")
    checkbox.wait_for(state="attached")
    original_value = checkbox.is_checked()

    _toggle_switch(page, "playwright_headless")
    expect(page.locator("#save_admin_btn")).to_be_enabled()
    expect(page.locator("#sticky_save_bar")).to_be_visible()

    page.locator("#discard_admin_changes_btn").click()
    page.wait_for_load_state("networkidle")

    reloaded_checkbox = page.locator("#playwright_headless")
    reloaded_checkbox.wait_for(state="visible")
    assert reloaded_checkbox.is_checked() == original_value
    expect(page.locator("#save_admin_btn")).to_be_disabled()
    expect(page.locator("#sticky_save_bar")).to_be_hidden()


def test_admin_system_warning_can_be_reviewed(admin_page):
    message = f"E2E system warning {uuid4()}"
    _seed_system_warning(message)

    page = admin_page
    page.goto("/global-settings")

    warning_card = page.locator(".system-warning-card").filter(has_text=message)
    expect(warning_card).to_have_count(1)

    with page.expect_response("**/api/admin/system-warnings/*") as response_info:
        warning_card.locator('[data-system-warning-action="review"]').click()
    assert response_info.value.ok, (
        "system warning review failed: "
        f"{response_info.value.status} {response_info.value.text()}"
    )

    expect(page.locator("#system_warnings_status")).to_contain_text("System warning updated.")
    expect(page.locator(".system-warning-card").filter(has_text=message)).to_have_count(0)
