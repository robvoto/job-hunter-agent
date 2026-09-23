"""Click-test: per-job-card actions on /workspace -- viewing the score, saving
("applied"), and dismissing ("hidden") a job. test_workspace_flow.py only
exercises the filter dropdowns, which never touch a real job card since the
default candidate's workspace is empty; this file seeds one job (via the
workspace_job_page fixture in conftest.py) and clicks through the actions a
human actually uses on a card.
"""

from __future__ import annotations

import os

from playwright.sync_api import expect

from tests.e2e.conftest import WORKSPACE_CANDIDATE_EMAIL, _seed_kept_job


def _wait_for_action_button(page, action: str):
    """Wait for the post-review reload to expose the persisted action."""
    selector = f'[data-review-action="{action}"]'
    locator = page.locator(selector)
    locator.first.wait_for(state="attached", timeout=5000)
    return locator


def test_workspace_job_card_shows_score(workspace_job_page):
    page = workspace_job_page
    page.goto("/workspace")

    card = page.locator("[data-fit-score]").first
    card.wait_for(state="visible")
    assert card.get_attribute("data-fit-score") == "95"
    expect(card.locator(".match-tile-label")).to_be_visible()


def test_workspace_search_and_page_size_persist_on_potential(workspace_job_page):
    page = workspace_job_page
    page.goto("/workspace")

    card = page.locator("[data-fit-score]").first
    search = page.locator("#job_search_input")
    page_size = page.locator(".workspace-page-size-select").first
    expect(search).to_be_visible()
    expect(page_size).to_be_visible()

    search.fill("Acme")
    expect(card).to_be_visible()
    search.fill("Company That Does Not Exist")
    expect(card).to_be_hidden()
    search.fill("")
    expect(card).to_be_visible()

    page_size.select_option("24")
    expect(page_size).to_have_value("24")
    scope = page.evaluate("window.__JOB_HUNTER_USER_SCOPE__")
    stored = page.evaluate(
        "scope => localStorage.getItem(`jobHunter.workspace.pageSize.${scope}`)", scope
    )
    assert stored == "24"

    page.reload()
    expect(page.locator(".workspace-page-size-select").first).to_have_value("24")


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

    # The scope-tab bar is re-rendered once per section, so all three sections'
    # copies share the same data-workspace-target -- any of them toggles the
    # same active-section state, so .first is fine.
    page.locator('[data-workspace-target="applied"]').first.click()

    search = page.locator("#job_search_input")
    expect(search).to_be_visible()
    expect(page.locator("#posted_filter")).to_be_hidden()
    search.fill("Acme")
    expect(page.locator('[data-record-kind="applied"]')).to_be_visible()
    search.fill("Company That Does Not Exist")
    expect(page.locator('[data-record-kind="applied"]')).to_be_hidden()
    search.fill("")

    # The seeded workspace has exactly one job, so the Applied tab is empty
    # before this click. moveCardAfterReview() used to clone its replacement
    # action buttons from a card already sitting in the destination tab; with
    # no such card to clone from, the moved card kept its stale
    # applied/not_for_me/hidden buttons instead of swapping to "unapply" until
    # a full page reload later picked up the server-rendered card. Assert the
    # swap immediately, with no reload, so this can't hide behind
    # _wait_for_action_button's reload-based polling for eventual consistency.
    expect(page.locator('[data-review-action="unapply"]')).to_be_visible(timeout=2000)
    expect(page.locator('[data-review-action="applied"]')).to_have_count(0)

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

    page.locator('[data-workspace-target="hidden"]').first.click()

    search = page.locator("#job_search_input")
    expect(search).to_be_visible()
    expect(page.locator("#posted_filter")).to_be_hidden()
    search.fill("Acme")
    expect(page.locator('[data-record-kind="hidden"]')).to_be_visible()
    search.fill("Company That Does Not Exist")
    expect(page.locator('[data-record-kind="hidden"]')).to_be_hidden()
    search.fill("")

    # Same empty-destination-tab case as the applied round trip above: the
    # Hidden tab starts empty for this seeded job. Assert immediately, with
    # no reload, so the check can't hide behind eventual consistency.
    expect(page.locator('[data-review-action="unhide"]')).to_be_visible(timeout=2000)
    expect(page.locator('[data-review-action="hidden"]')).to_have_count(0)

    with page.expect_response("**/api/review") as response_info:
        page.locator('[data-review-action="unhide"]').click()
    assert response_info.value.ok, (
        f"unhide action failed: {response_info.value.status} {response_info.value.text()}"
    )

    _wait_for_action_button(page, "hidden")


def test_static_export_is_read_only_and_never_calls_api(browser, live_server):
    """workspace_results.html (rendered by results.html) is written to disk per
    user by rebuild_workspace_results and can be double-clicked open directly
    (file://), completely outside the authenticated /workspace session -- that
    origin has no session cookie, and root-relative asset paths like
    /static/results/results-page.js resolve against the filesystem root and
    404, so the interactive script never loads. Previously the exported page's
    Applied button looked clickable but silently produced a browser-level
    "Failed to fetch" with zero trace in the server logs. The inline guard in
    results.html has no external dependency and always runs: it must disable
    every review action button and explain why, and no request may ever reach
    the real backend.
    """
    from job_hunter_agent.auth import get_or_create_user
    from job_hunter_agent.paths import get_workspace_results_path
    from job_hunter_agent.user_context import set_user_id

    _seed_kept_job(WORKSPACE_CANDIDATE_EMAIL)

    admin_email = os.environ["JOB_HUNTER_ADMIN_EMAIL"]
    user = get_or_create_user(WORKSPACE_CANDIDATE_EMAIL, admin_email)
    set_user_id(user["user_id"])
    try:
        results_path = get_workspace_results_path()
    finally:
        set_user_id(None)
    assert results_path.exists(), f"expected workspace export at {results_path}"

    context = browser.new_context()
    page = context.new_page()
    api_requests = []
    page.on(
        "request",
        lambda request: api_requests.append(request.url) if "/api/" in request.url else None,
    )
    try:
        page.goto(results_path.as_uri())

        banner = page.locator("#static_export_banner")
        expect(banner).to_be_visible()
        expect(banner).to_contain_text("saved copy of your workspace")
        expect(banner).to_contain_text("/workspace")

        expect(page.locator('[data-review-action="applied"]')).to_be_disabled()
    finally:
        context.close()

    assert not api_requests, f"static export must never call the API, got: {api_requests}"
