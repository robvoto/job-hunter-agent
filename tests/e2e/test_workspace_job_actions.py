"""Click-test: per-job-card actions on /workspace -- viewing the score, saving
("applied"), and dismissing ("hidden") a job. test_workspace_flow.py only
exercises the filter dropdowns, which never touch a real job card since the
default candidate's workspace is empty; this file seeds one job (via the
workspace_job_page fixture in conftest.py) and clicks through the actions a
human actually uses on a card.
"""

from __future__ import annotations

from playwright.sync_api import expect


def _wait_for_action_button(page, action: str, *, attempts: int = 15):
    """Review actions rebuild the cached workspace HTML on a background thread
    (see workspace_refresh_service.rebuild_workspace_after_rule_change), so the
    client's post-save reload can race that rebuild and briefly still show the
    pre-action state. Poll by reloading until the expected button appears.
    """
    selector = f'[data-review-action="{action}"]'
    locator = page.locator(selector)
    for _ in range(attempts):
        if locator.count() > 0:
            return locator
        page.wait_for_timeout(200)
        page.reload()
    locator.wait_for(state="attached", timeout=2000)
    return locator


def test_workspace_job_card_shows_score(workspace_job_page):
    page = workspace_job_page
    page.goto("/workspace")

    card = page.locator("[data-fit-score]").first
    card.wait_for(state="visible")
    assert card.get_attribute("data-fit-score") == "95"
    expect(card.locator(".match-tile-label")).to_be_visible()


def test_workspace_save_action_round_trips(workspace_job_page):
    page = workspace_job_page
    page.goto("/workspace")

    apply_button = page.locator('[data-review-action="applied"]')
    apply_button.wait_for(state="visible")
    with page.expect_response("**/api/review") as response_info:
        apply_button.click()
    assert response_info.value.ok, (
        f"applied action failed: {response_info.value.status} {response_info.value.text()}"
    )

    _wait_for_action_button(page, "unapply")
    # The scope-tab bar is re-rendered once per section, so all three sections'
    # copies share the same data-workspace-target -- any of them toggles the
    # same active-section state, so .first is fine.
    page.locator('[data-workspace-target="applied"]').first.click()
    expect(page.locator('[data-review-action="unapply"]')).to_be_visible()

    with page.expect_response("**/api/review") as response_info:
        page.locator('[data-review-action="unapply"]').click()
    assert response_info.value.ok, (
        f"unapply action failed: {response_info.value.status} {response_info.value.text()}"
    )

    _wait_for_action_button(page, "applied")


def test_workspace_dismiss_action_round_trips(workspace_job_page):
    page = workspace_job_page
    page.goto("/workspace")

    hide_button = page.locator('[data-review-action="hidden"]')
    hide_button.wait_for(state="visible")
    with page.expect_response("**/api/review") as response_info:
        hide_button.click()
    assert response_info.value.ok, (
        f"hidden action failed: {response_info.value.status} {response_info.value.text()}"
    )

    _wait_for_action_button(page, "unhide")
    page.locator('[data-workspace-target="hidden"]').first.click()
    expect(page.locator('[data-review-action="unhide"]')).to_be_visible()

    with page.expect_response("**/api/review") as response_info:
        page.locator('[data-review-action="unhide"]').click()
    assert response_info.value.ok, (
        f"unhide action failed: {response_info.value.status} {response_info.value.text()}"
    )

    _wait_for_action_button(page, "hidden")
