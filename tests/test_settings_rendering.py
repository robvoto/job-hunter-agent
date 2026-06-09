"""Tests for settings rendering."""



import json

from pathlib import Path



from fastapi.testclient import TestClient



from job_hunter_agent.fastapi_app import create_app

import job_hunter_agent.fastapi_app as _fa

import job_hunter_agent.routes.pages as _pages

from job_hunter_agent.server_helpers import _SETTINGS_ALERTS_LABEL_KEYS





_KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge"





def test_ui_labels_json_contains_all_settings_alerts_keys():

    data = json.loads((_KNOWLEDGE_DIR / "ui_labels.json").read_text(encoding="utf-8"))

    section = data.get("settings_alerts_labels", {})

    missing = [k for k in _SETTINGS_ALERTS_LABEL_KEYS if not str(section.get(k, "")).strip()]

    assert not missing, f"ui_labels.json is missing settings_alerts_labels keys: {missing}"





def test_settings_page_renders_keyword_label_and_location_field(monkeypatch):

    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test-user", "email": "test@example.com", "role": "candidate"})

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

    assert 'class="nav-item nav-item-workspace">↩ Workspace</a>' in html

    assert 'account-bar-shortcut' not in html

    assert '↩ Workspace' in html

    assert 'class="btn-add"' in html

    assert 'capability-add-button' not in html

    assert 'capability-editor' in html

    assert '>+<' in html

    assert 'window.__JOB_HUNTER_CAPABILITY_UI_LABELS__' in html

    assert 'window.__JOB_HUNTER_SHARED_UI_LABELS__' in html

    assert 'window.__JOB_HUNTER_SETTINGS_ALERTS_LABELS__' in html

    assert "Alerts &amp; AI" in html


def test_settings_capability_editor_preserves_icon_key_state():
    repo_root = Path(__file__).resolve().parents[1]
    js_text = (repo_root / "templates" / "static" / "settings" / "shared" / "settings-capability-editor.js").read_text(encoding="utf-8")

    assert "icon_key: String(rule?.icon_key || '').trim().toLowerCase()," in js_text
    assert "icon_key: genericCapabilityIconKey" in js_text
    assert "genericCapabilityIconKey = capabilityUi.genericCapabilityIconKey;" in js_text
    assert "Missing generic capability icon key." in js_text


def test_settings_utils_review_normaliser_preserves_icon_key():
    repo_root = Path(__file__).resolve().parents[1]
    js_text = (repo_root / "templates" / "static" / "settings" / "shared" / "settings-utils.js").read_text(encoding="utf-8")

    assert "const icon_key = normalizeReviewText(rule?.icon_key || '').toLowerCase();" in js_text
    assert "return { name, level, aliases, icon_key };" in js_text

