"""Click-test: workspace page loads and filter controls are interactive without
throwing JS errors or hitting failing API calls -- exactly what a human would
notice by clicking around, that a mocked unit test would never catch."""

from __future__ import annotations


def test_workspace_loads_and_filters_are_interactive(candidate_page):
    page = candidate_page
    page.goto("/workspace")

    sort_select = page.locator("#sort_select")
    sort_select.wait_for(state="visible")

    for select_id in ("#scope_filter", "#posted_filter", "#work_type_filter", "#score_filter"):
        locator = page.locator(select_id)
        options = locator.locator("option").all()
        if len(options) > 1:
            value = options[1].get_attribute("value")
            if value is not None:
                locator.select_option(value)

    page.locator("#reset_workspace_filters").click()
