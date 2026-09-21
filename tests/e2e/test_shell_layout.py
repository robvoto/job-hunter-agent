"""Responsive shell contracts for Settings and Onboarding."""

from __future__ import annotations


def _horizontal_overflow(page) -> float:
    return float(
        page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    )


def test_settings_uses_wide_shell_without_narrow_horizontal_scrolling(candidate_page):
    page = candidate_page

    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto("/settings")
    page.locator('[data-section="section-matrix"]').click()

    content = page.locator(".settings-content-area").bounding_box()
    matching = page.locator("#section-matrix .advanced-shell").bounding_box()
    assert content and matching
    assert content["width"] >= 1500, content
    assert matching["width"] >= 1450, matching

    for width in (820, 720):
        page.set_viewport_size({"width": width, "height": 1000})
        assert _horizontal_overflow(page) <= 1, (
            width,
            page.evaluate("document.documentElement.scrollWidth"),
        )
        nav_metrics = page.locator(".sidebar-nav").evaluate(
            "el => ({scrollWidth: el.scrollWidth, clientWidth: el.clientWidth, overflowX: getComputedStyle(el).overflowX})"
        )
        assert nav_metrics["scrollWidth"] <= nav_metrics["clientWidth"] + 1, nav_metrics
        assert nav_metrics["overflowX"] != "auto", nav_metrics

    account_justify = page.locator(
        ".settings-header__inner .job-hunter-account-bar"
    ).evaluate("el => getComputedStyle(el).justifyContent")
    assert account_justify == "flex-start"


def test_onboarding_uses_wide_shell_and_stays_phone_safe(fresh_candidate_page):
    page = fresh_candidate_page

    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto("/start")

    shell = page.locator(".page").bounding_box()
    header = page.locator(".onb-header__inner").bounding_box()
    assert shell and header
    assert shell["width"] >= 1500, shell
    assert header["width"] >= 1500, header

    page.set_viewport_size({"width": 390, "height": 1000})
    assert _horizontal_overflow(page) <= 1
