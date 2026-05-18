from fastapi.testclient import TestClient

from job_hunter_agent.fastapi_app import create_app
import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages


def test_settings_page_renders_keyword_label_and_location_field(monkeypatch):
    monkeypatch.setattr(_fa, "is_auth_disabled", lambda: True)
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: True)

    client = TestClient(create_app())
    html = client.get("/settings").text

    assert "__JOB_HUNTER_TITLE_TIER_SEARCH_KEYWORD_LABEL__" not in html
    assert "Search keyword" in html
    assert '<label for="locations">Location</label>' in html
