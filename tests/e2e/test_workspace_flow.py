"""Click-test: workspace page loads and filter controls are interactive without
throwing JS errors or hitting failing API calls -- exactly what a human would
notice by clicking around, that a mocked unit test would never catch."""

from __future__ import annotations


def test_workspace_loads_and_filters_are_interactive(candidate_page):
    page = candidate_page
    page.goto("/workspace")

    sort_select = page.locator("#sort_select")
    sort_select.wait_for(state="visible")

    for select_id in ("#posted_filter", "#work_type_filter", "#score_filter"):
        locator = page.locator(select_id)
        options = locator.locator("option").all()
        if len(options) > 1:
            value = options[1].get_attribute("value")
            if value is not None:
                locator.select_option(value)

    page.locator("#reset_workspace_filters").click()


def test_workspace_structured_wait_state_renders_all_sources(candidate_page):
    """Drive the real Workspace module through every structured wait-state variant."""
    import json
    from pathlib import Path

    page = candidate_page
    artifacts = Path(__file__).resolve().parent / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    state = {
        "payload": {
            "ok": True,
            "status": "running",
            "stop_requested": False,
            "progress": "LinkedIn target 2/7\nReviewing job 4/6",
            "progress_detail": {
                "stage": "source_collection",
                "source": "linkedin",
                "headline": "LinkedIn target 2 of 7",
                "detail": "Reviewing job 4 of 6",
                "current": 2,
                "total": 7,
                "item_current": 4,
                "item_total": 6,
                "determinate": True,
            },
            "elapsed_seconds": 82,
            "elapsed_text": "1m 22s",
            "last_run_at": None,
            "has_run": False,
            "scheduler": {"active": True},
        }
    }

    def run_status(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps(state["payload"]))

    def stop_status(route):
        payload = {**state["payload"], "status": "stopping", "stop_requested": True}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route("**/api/run-status", run_status)
    page.route("**/api/run/stop", stop_status)
    page.goto("/workspace")

    page.locator(".wait-state__title").wait_for(state="visible")
    assert page.locator(".wait-state__title").inner_text() == "Search in progress"
    assert page.locator(".source-status-badge--linkedin").inner_text().strip() == "in"
    assert page.locator(".search-progress-source__title").inner_text() == "LinkedIn target 2 of 7"
    assert page.locator(".search-progress-source__detail").inner_text() == "Reviewing job 4 of 6"
    progress = page.locator(".jh-progress")
    assert progress.get_attribute("aria-valuemin") == "0"
    assert progress.get_attribute("aria-valuemax") == "7"
    assert progress.get_attribute("aria-valuenow") == "2"
    assert page.locator(".search-progress-elapsed").inner_text() == "1m 22s elapsed"
    assert page.locator(".wait-state__activity").count() == 0
    assert page.get_by_text("Current step:").count() == 0
    page.screenshot(path=str(artifacts / "jh279-linkedin-progress.png"))

    explainer = page.locator(".wait-state__explainer")
    explainer.locator("summary").click()
    assert explainer.get_attribute("open") is not None
    assert "multiple sources" in explainer.locator(".wait-state__explainer-copy").inner_text()
    border_width = explainer.evaluate("element => getComputedStyle(element).borderTopWidth")
    assert border_width == "0px"

    state["payload"] = {
        **state["payload"],
        "progress": "SEEK page 1/3",
        "progress_detail": {
            "stage": "source_collection",
            "source": "seek",
            "headline": "SEEK page 1 of 3",
            "detail": "Senior Analyst at Acme",
            "current": 1,
            "total": 3,
            "item_current": None,
            "item_total": None,
            "determinate": True,
        },
    }
    page.reload()
    assert page.locator(".source-status-badge--seek").inner_text().strip() == "S"
    assert page.locator(".search-progress-source__detail").inner_text() == "Senior Analyst at Acme"

    state["payload"] = {
        **state["payload"],
        "progress": "APSJobs search 1/2\nPolicy Officer",
        "progress_detail": {
            "stage": "source_collection",
            "source": "apsjobs",
            "headline": "APS Jobs search 1 of 2",
            "detail": "Policy Officer",
            "current": 1,
            "total": 2,
            "item_current": None,
            "item_total": None,
            "determinate": True,
        },
    }
    page.reload()
    assert page.locator(".source-status-badge--apsjobs").inner_text().strip() == "AU"
    assert page.locator(".search-progress-source__title").inner_text() == "APS Jobs search 1 of 2"

    state["payload"] = {
        **state["payload"],
        "progress": "Reviewing job 2 of page 3",
        "progress_detail": {
            "stage": "relevance_analysis",
            "source": "job_market_map",
            "headline": "Reviewing job 2 of page 3",
            "detail": "Business Analyst 42",
            "current": 2,
            "total": 4,
            "item_current": None,
            "item_total": None,
            "determinate": True,
        },
    }
    page.reload()
    assert page.locator(".source-status-badge--job-market-map").inner_text().strip() == "JMM"
    assert page.locator(".search-progress-source__title").inner_text() == "Reviewing job 2 of page 3"
    assert page.locator(".search-progress-source__detail").inner_text() == "Business Analyst 42"
    assert page.locator(".jh-progress").get_attribute("aria-valuemax") == "4"
    assert page.locator(".jh-progress").get_attribute("aria-valuenow") == "2"

    state["payload"] = {
        **state["payload"],
        "progress": "Finalising results\nPreparing workspace data",
        "progress_detail": {
            "stage": "finalising",
            "source": "generic",
            "headline": "Finalising results",
            "detail": "Preparing workspace data",
            "current": None,
            "total": None,
            "item_current": None,
            "item_total": None,
            "determinate": False,
        },
    }
    page.reload()
    indeterminate = page.locator(".jh-progress--indeterminate")
    assert indeterminate.count() == 1
    assert indeterminate.get_attribute("aria-valuenow") is None
    assert page.locator(".source-status-badge--generic svg").count() == 1
    page.screenshot(path=str(artifacts / "jh279-finalising-progress.png"))

    page.set_viewport_size({"width": 390, "height": 844})
    page.reload()
    shell_box = page.locator(".job-hunter-wait-shell").bounding_box()
    assert shell_box is not None
    assert shell_box["width"] <= 350
    page.screenshot(path=str(artifacts / "jh279-mobile-progress.png"))

    state["payload"] = {**state["payload"], "status": "stopping", "stop_requested": True}
    page.evaluate(
        """() => {
          window.__jh279LastAlert = null;
          window.alert = message => {
            window.__jh279LastAlert = { message: String(message), stack: new Error().stack };
          };
        }"""
    )
    with page.expect_response("**/api/run/stop") as stop_response_info:
        page.locator("#ws_stop_search_btn").click()
    assert stop_response_info.value.status == 200
    assert stop_response_info.value.json()["status"] == "stopping"
    page.wait_for_timeout(250)
    captured_alert = page.evaluate("window.__jh279LastAlert || null")
    assert captured_alert is None, captured_alert
    current_title = page.locator(".wait-state__title").inner_text()
    assert current_title == "Run stopped by request", page.locator("#ws_wait_mount").inner_html()
    assert page.locator("#ws_stop_search_btn").count() == 0

    state["payload"] = {
        **state["payload"],
        "status": "stopped",
        "stop_requested": False,
        "progress": None,
        "progress_detail": None,
        "elapsed_seconds": 90,
        "elapsed_text": "1m 30s",
    }
    final_elapsed = page.get_by_text("1m 30s elapsed")
    final_elapsed.wait_for(state="visible", timeout=5000)
    assert page.locator(".wait-state__title").inner_text() == "Run stopped by request"
    assert final_elapsed.inner_text() == "1m 30s elapsed"
