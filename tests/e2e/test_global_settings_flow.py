"""Click-tests for the admin global-settings page."""

from __future__ import annotations

from uuid import uuid4

from playwright.sync_api import expect


def _toggle_switch(page, control_id: str) -> None:
    # The real clickable surface is the styled label, not the covered checkbox.
    page.locator(f'label.toggle-switch[for="{control_id}"]').click()


def _seed_system_warning(
    message: str,
    *,
    severity: str = "warning",
    category: str = "e2e_admin_flow",
    source: str = "playwright",
) -> None:
    from job_hunter_agent.system_warnings import (
        make_system_warning_fingerprint,
        record_system_warning,
    )

    record_system_warning(
        severity=severity,
        category=category,
        source=source,
        message=message,
        fingerprint=make_system_warning_fingerprint("e2e-admin-flow", category, source, message),
        context={"test": "global_settings_system_health"},
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


def test_admin_system_incident_can_be_acknowledged(admin_page):
    message = f"E2E system warning {uuid4()}"
    _seed_system_warning(message)

    page = admin_page
    page.goto("/global-settings")

    warning_card = page.locator(".system-warning-card").filter(has_text=message)
    expect(warning_card).to_have_count(1)

    with page.expect_response("**/api/admin/system-warnings/*") as response_info:
        warning_card.locator('[data-system-warning-action="acknowledge"]').click()
    assert response_info.value.ok, (
        "system incident acknowledgement failed: "
        f"{response_info.value.status} {response_info.value.text()}"
    )

    expect(page.locator("#system_warnings_status")).to_contain_text("Acknowledged.")
    expect(page.locator(".system-warning-card").filter(has_text=message)).to_have_count(0)


def test_admin_system_health_aggregates_job_uncertainty_as_diagnostics(admin_page):
    first_message = f"Work mode unclear one {uuid4()}"
    second_message = f"Work mode unclear two {uuid4()}"
    for message in (first_message, second_message):
        _seed_system_warning(
            message,
            category="preference_uncertainty",
            source="passes_preference_filters",
        )

    page = admin_page
    page.goto("/global-settings")

    active_list = page.locator("#system_warnings_list")
    expect(active_list.filter(has_text=first_message)).to_have_count(0)
    expect(active_list.filter(has_text=second_message)).to_have_count(0)

    page.locator("#system_diagnostics_toggle_button").click()
    expect(page.locator("#system_diagnostics_section")).to_be_visible()

    group = page.locator(
        '[data-system-diagnostic-group="preference_uncertainty|passes_preference_filters"]'
    )
    expect(group).to_have_count(1)
    expect(group).to_contain_text("preference uncertainty")
    expect(group).to_contain_text("passes_preference_filters")
    expect(group).to_contain_text("Records:")
    expect(group).to_contain_text("Occurrences:")


def test_admin_source_problem_runs_existing_scraper_validation(admin_page):
    message = f"SEEK source failure {uuid4()}"
    _seed_system_warning(
        message,
        severity="error",
        category="source_failure",
        source="seek",
    )

    page = admin_page
    validation_requests = []

    def _fulfil_validation(route):
        validation_requests.append(route.request.method)
        route.fulfill(
            status=200,
            content_type="application/json",
            body='{"ok":true,"summary":"Validation complete.","results":[],"warnings_recorded":0}',
        )

    page.route("**/api/admin/scraper-config-validation", _fulfil_validation)
    page.goto("/global-settings")

    warning_card = page.locator("#system_warnings_list .system-warning-card").filter(
        has_text=message
    )
    expect(warning_card).to_have_count(1)
    warning_card.locator('[data-system-warning-action="run_scraper_validation"]').click()

    expect(page.locator("#system_warnings_status")).to_contain_text(
        "Scraper validation completed."
    )
    assert validation_requests == ["POST"]
