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
    assert "Include SEEK in search" in html
    assert "Include LinkedIn in search" in html
    assert "Shared search inputs that apply across all enabled sources." in html
    assert "Job board search" in html
    assert '>Add<' not in html
    assert '<label for="locations">Location</label>' in html
    assert 'id="min_contract_months"' in html
    assert '6+ months' in html
    assert 'job-hunter-account-bar' in html
    assert 'account-bar-shortcut' in html
    assert 'class="btn-add"' in html
    assert 'capability-add-button' not in html
    assert 'capability-editor' in html
    assert '>+<' in html
    assert 'window.__JOB_HUNTER_CAPABILITY_UI_LABELS__' in html
    assert 'window.__JOB_HUNTER_SHARED_UI_LABELS__' in html
