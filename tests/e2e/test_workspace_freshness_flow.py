"""Click-test: LinkedIn freshness risk renders clearly on a real workspace card."""

from __future__ import annotations

from playwright.sync_api import expect


def test_linkedin_unverified_freshness_is_visible_on_workspace_card(
    workspace_linkedin_freshness_page,
):
    page = workspace_linkedin_freshness_page
    page.goto("/workspace")

    card = page.locator('[data-source="linkedin"]').first
    card.wait_for(state="visible")

    expect(card.locator(".job-meta-item").first).to_contain_text("LinkedIn listed")
    expect(card).to_contain_text("15 hours ago")
    expect(card).to_contain_text("Checks before applying")
    expect(card).to_contain_text("Freshness may be unreliable")
    expect(card).not_to_contain_text("Originally posted")
