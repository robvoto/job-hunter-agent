"""Click-test: session/auth gating behaves the way a human user would see it."""

from __future__ import annotations


def test_unauthenticated_user_is_redirected_to_login(anon_page):
    anon_page.goto("/start")
    assert "/login" in anon_page.url


def test_authenticated_candidate_reaches_onboarding(fresh_candidate_page):
    fresh_candidate_page.goto("/start")
    assert "/login" not in fresh_candidate_page.url
    fresh_candidate_page.locator("#create_profile").wait_for(state="visible")


def test_candidate_is_blocked_from_global_settings(candidate_page):
    candidate_page.goto("/global-settings")
    assert "/login" in candidate_page.url


def test_admin_can_reach_global_settings(admin_page):
    admin_page.goto("/global-settings")
    assert "/login" not in admin_page.url
    admin_page.locator("#save_admin_btn").wait_for(state="attached")
