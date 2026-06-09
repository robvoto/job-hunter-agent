"""Tests for onboarding."""

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from job_hunter_agent import server_helpers
from job_hunter_agent import profile_learning
from job_hunter_agent import server_review
from job_hunter_agent import source_documents
from job_hunter_agent import profile_store
from job_hunter_agent import review_history_service
from job_hunter_agent import workspace_refresh_service
from job_hunter_agent.fastapi_app import create_app
import job_hunter_agent.fastapi_app as _fa
import job_hunter_agent.routes.pages as _pages
from job_hunter_agent.routes import onboarding_api
from job_hunter_agent.routes import profile_materials
from job_hunter_agent.routes import scrape_debug


def test_normalize_onboarding_search_preferences_trims_and_normalizes():
    normalized = server_helpers._normalize_onboarding_search_preferences(
        {
            "keywords": "  business analyst  ",
            "locations": [" Sydney ", "", "Melbourne"],
            "engagement_type": " Permanent ",
        }
    )

    assert normalized == {
        "keywords": "business analyst",
        "locations": ["Sydney", "Melbourne"],
        "engagement_type": ["permanent"],
    }


def test_onboarding_page_uses_shared_choice_strip_widget(monkeypatch):
    monkeypatch.setattr(_fa, "read_session_user", lambda request: {"user_id": "test-user", "email": "test@example.com", "role": "candidate"})
    monkeypatch.setattr(_pages.srv, "_onboarding_complete", lambda: False)
    monkeypatch.setattr(_pages, "get_user_id_for_runtime", lambda: "test-user")

    client = TestClient(create_app())
    html = client.get("/onboarding").text

    assert 'Preferred roles' in html
    assert 'Alternative roles' in html
    assert 'Search keyword' in html
    assert 'placeholder="e.g. Business Analyst"' in html
    assert 'Add a preferred role' in html
    assert 'Add an alternative role' in html
    assert 'id="engagement_type_label"' in html
    assert 'id="min_contract_months"' in html
    assert 'class="choice-strip"' in html
    assert 'class="choice-card choice-card--work-mode"' in html
    assert 'name="work_mode_preference" value="remote" checked' in html
    assert 'name="work_mode_preference" value="hybrid" checked' in html
    assert 'name="work_mode_preference" value="onsite" checked' in html
    assert 'input type="checkbox" name="engagement_type"' in html
    assert 'input type="checkbox" name="work_mode_preference"' in html
    assert 'field-info-drawer' in html
    assert 'job-hunter-account-bar' in html
    assert 'btn-add' in html
    assert 'btn-add token-input-action' in html
    assert '>+<' in html
    assert 'Upload CV' in html
    assert 'Review Draft' in html
    assert 'Search Basics' in html
    assert 'Check Setup' in html
    assert '0 shown' in html
    assert 'id="review_capability_helper"' in html
    assert 'review-capability-filter-shell' in html
    assert 'window.__JOB_HUNTER_ONBOARDING_PAGE_LABELS__' in html
    assert 'window.__JOB_HUNTER_ONBOARDING_FLOW_LABELS__' in html
    assert 'window.__JOB_HUNTER_USER_ID__ = "test-user"' in html
    assert 'window.__JOB_HUNTER_CAPABILITY_UI_LABELS__' in html
    assert 'window.__JOB_HUNTER_SHARED_UI_LABELS__' in html
    assert '/static/onboarding/onboarding-page.css' in html
    assert '/static/onboarding/onboarding-review.css' in html


def test_onboarding_flow_keyword_helper_is_owned_by_page_module():
    page_js_path = Path(__file__).resolve().parents[1] / "templates" / "static" / "onboarding" / "onboarding-page.js"
    search_js_path = Path(__file__).resolve().parents[1] / "templates" / "static" / "onboarding" / "onboarding-search.js"
    page_js_text = page_js_path.read_text(encoding="utf-8")
    search_js_text = search_js_path.read_text(encoding="utf-8")

    assert "defaultSearchKeywordFromTargetRoles" in page_js_text
    assert "export function defaultSearchKeywordFromTargetRoles" not in search_js_text
    assert "onboardingPage.defaultSearchKeywordFromTargetRoles(profile)" in search_js_text
    assert "reviewTargetTitles.join(', ')" not in page_js_text
    assert "defaultSearchKeywordsFromReviewedTitles" not in page_js_text


def test_onboarding_work_mode_hydration_always_applies_saved_values():
    page_js_path = Path(__file__).resolve().parents[1] / "templates" / "static" / "onboarding" / "onboarding-page.js"
    search_js_path = Path(__file__).resolve().parents[1] / "templates" / "static" / "onboarding" / "onboarding-search.js"
    page_js_text = page_js_path.read_text(encoding="utf-8")
    search_js_text = search_js_path.read_text(encoding="utf-8")

    assert "setOnboardingWorkModePreferenceValues(matchPreferences.work_mode_preference);" in page_js_text
    assert "setWorkModePreferenceValues(matchPreferences.work_mode_preference || []);" in search_js_text
    assert "if (!getOnboardingWorkModePreferenceValues().length)" not in page_js_text
    assert "if (!getWorkModePreferenceValues().length)" not in search_js_text


def test_onboarding_template_uses_shared_primary_cv_copy_placeholders():
    html_path = Path(__file__).resolve().parents[1] / "templates" / "onboarding.html"
    html_text = html_path.read_text(encoding="utf-8")

    assert '<div id="cv_drop_zone_content" class="drop-zone-content-shell">' in html_text
    assert "__JOB_HUNTER_ONBOARDING_PAGE_CV_DROP_ZONE_EMPTY_TITLE__" in html_text
    assert "__JOB_HUNTER_ONBOARDING_PAGE_CV_DROP_ZONE_EMPTY_HINT__" in html_text


def test_onboarding_flow_labels_include_capability_review_copy():
    labels = server_helpers.load_onboarding_flow_labels()

    assert labels["review_capability_helper_copy"] == "Review the capability groups extracted from your CV."
    assert labels["review_capability_extracted_skills_label_one"] == "1 extracted skill"
    assert labels["review_capability_extracted_skills_label_many"] == "{count} extracted skills"


def test_onboarding_import_summary_labels_include_cost_copy():
    labels = server_helpers.load_onboarding_import_summary_labels()

    assert labels["llm_cost_label"] == "LLM cost this run:"


def test_onboarding_capability_cards_use_one_shared_generic_icon():
    repo_root = Path(__file__).resolve().parents[1]
    capability_ui_js = (repo_root / "templates" / "static" / "common" / "capability-ui.js").read_text(encoding="utf-8")
    onboarding_flow_js = (repo_root / "templates" / "static" / "onboarding" / "onboarding-flow.js").read_text(encoding="utf-8")
    theme_widgets = (repo_root / "templates" / "static" / "theme" / "themes.widgets.css").read_text(encoding="utf-8")

    assert "genericCapabilityIconHtml" in capability_ui_js
    assert "review-capability-title-row" in onboarding_flow_js
    assert "const extractedSkillPreview" not in onboarding_flow_js
    assert '<p class="help">${extractedSkillPreview}</p>' not in onboarding_flow_js
    assert "capability-card-icon" in theme_widgets


def test_capability_ui_keeps_all_shared_icon_keys():
    repo_root = Path(__file__).resolve().parents[1]
    capability_ui_js = (repo_root / "templates" / "static" / "common" / "capability-ui.js").read_text(encoding="utf-8")

    assert "capability-card-icon--${genericCapabilityIconKey}" in capability_ui_js
    assert "M12 7.2 13.5 10h3l-2.4 1.8.9 2.9L12 13l-3 1.7.9-2.9L7.5 10h3z" in capability_ui_js
    for icon_key in [
        "people_support:",
        "communication_stakeholders:",
        "analysis_requirements:",
        "operations_process:",
        "delivery_project:",
        "technical_build:",
        "systems_platforms:",
        "data_reporting:",
        "finance_commercial:",
        "risk_compliance_security:",
        "creative_marketing_content:",
    ]:
        assert icon_key not in capability_ui_js
    assert "genericCapabilityIconKey" in capability_ui_js


def test_shared_ui_styles_are_centralised():
    repo_root = Path(__file__).resolve().parents[1]
    theme_primitives = (repo_root / "templates" / "static" / "theme" / "themes.primitives.css").read_text(encoding="utf-8")
    theme_widgets = (repo_root / "templates" / "static" / "theme" / "themes.widgets.css").read_text(encoding="utf-8")
    onboarding_page_css = (repo_root / "templates" / "static" / "onboarding" / "onboarding-page.css").read_text(encoding="utf-8")
    onboarding_review_css = (repo_root / "templates" / "static" / "onboarding" / "onboarding-review.css").read_text(encoding="utf-8")
    settings_page_css = (repo_root / "templates" / "static" / "settings" / "shared" / "settings-page.css").read_text(encoding="utf-8")
    onboarding_html = (repo_root / "templates" / "onboarding.html").read_text(encoding="utf-8")
    settings_admin_html = (repo_root / "templates" / "partials" / "settings" / "global" / "settings-admin.html").read_text(encoding="utf-8")
    settings_learning_html = (repo_root / "templates" / "partials" / "settings" / "global" / "settings-learning.html").read_text(encoding="utf-8")

    assert ".page input," in theme_primitives
    assert ".currency-input-wrap input," in theme_primitives
    assert ".summary-line {" in theme_widgets
    assert ".settings-form-field--summary" not in theme_widgets
    assert ".help {" in theme_widgets
    assert ".check-card-head h3" not in theme_widgets
    assert ".check-list dd" not in theme_widgets
    assert 'class="summary-line"' in onboarding_html
    assert 'class="summary-line"' in (repo_root / "templates" / "partials" / "settings" / "standard" / "settings-search.html").read_text(encoding="utf-8")
    assert 'class="help"' in onboarding_html
    assert 'class="help"' in settings_admin_html
    assert 'class="help"' in settings_learning_html
    assert ".page input," not in onboarding_page_css
    assert ".help {" not in onboarding_page_css
    assert ".currency-input-wrap input" not in onboarding_review_css
    assert ".help {" not in settings_page_css
    assert ".currency-input-wrap input" not in settings_page_css
    assert ".nav-item.is-active {" in settings_page_css
    assert "color: var(--selection-accent);" in settings_page_css
    assert ".nav-item-workspace {" in settings_page_css
    assert "color: var(--text-muted);" in settings_page_css
    assert ".nav-item-admin {" in settings_page_css
    assert "color: var(--text-muted);" in settings_page_css
    assert ".nav-item-optimise" not in settings_page_css
    assert ".search-settings-grid .settings-form-field--summary" in settings_page_css
    assert "#seek_max_pages_choices.choice-strip" in settings_page_css
    assert "min-height: var(--control-height-2xl);" in settings_page_css
    assert "#contract_duration_row" in settings_page_css
    assert "position: absolute;" in settings_page_css
    assert "text-align: center;" in settings_page_css
    assert ".search-source-panel .toggle-switch" in theme_widgets


def test_settings_search_work_type_popup_uses_shared_labels_and_local_layout():
    repo_root = Path(__file__).resolve().parents[1]
    settings_html = (repo_root / "templates" / "partials" / "settings" / "standard" / "settings-search.html").read_text(encoding="utf-8")
    settings_js = (repo_root / "templates" / "static" / "settings" / "shared" / "settings-page.js").read_text(encoding="utf-8")

    assert settings_html.index('id="contract_duration_row"') < settings_html.index('id="engagement_type_summary"')
    assert "__JOB_HUNTER_MIN_CONTRACT_MONTH_HELP__" in settings_html
    assert "window.__JOB_HUNTER_ONBOARDING_PAGE_LABELS__" in settings_js
    assert "positionContractDurationRow" in settings_js
    assert "updateMinContractMonthState" in settings_js
    assert "work_type_summary_contract_length_label" in settings_js
    assert "summary_any_length_label" in settings_js


def test_onboarding_contract_duration_row_floats_and_hides_on_blur():
    repo_root = Path(__file__).resolve().parents[1]
    css_path = repo_root / "templates" / "static" / "onboarding" / "onboarding-page.css"
    page_js_path = repo_root / "templates" / "static" / "onboarding" / "onboarding-page.js"
    storage_js_path = repo_root / "templates" / "static" / "onboarding" / "onboarding-storage.js"
    css_text = css_path.read_text(encoding="utf-8")
    page_js_text = page_js_path.read_text(encoding="utf-8")
    storage_js_text = storage_js_path.read_text(encoding="utf-8")

    assert ".onb-field .contract-duration-row" in css_text
    assert "position: absolute;" in css_text
    assert "contractRow.hidden = true;" in page_js_text
    assert "minContractMonthsEl.addEventListener('change'" in storage_js_text


def test_onboarding_flow_import_summary_uses_shared_labels_and_skips_empty_output():
    js_path = Path(__file__).resolve().parents[1] / "templates" / "static" / "onboarding" / "onboarding-flow.js"
    js_text = js_path.read_text(encoding="utf-8")

    assert "window.__JOB_HUNTER_ONBOARDING_IMPORT_SUMMARY_LABELS__" in js_text
    assert "onboardingImportSummaryLabels.lead_in" in js_text
    assert "formatImportSuccessSummary" in js_text
    assert "showStatus(extractionMessage, 'success')" in js_text
    assert "if (!parts.length)" in js_text
    assert "if (extractionMessage)" in js_text


def test_onboarding_flow_uses_profile_readiness_status_fields():
    js_path = Path(__file__).resolve().parents[1] / "templates" / "static" / "onboarding" / "onboarding-flow.js"
    js_text = js_path.read_text(encoding="utf-8")

    assert "profile_ready_for_review" in js_text
    assert "blocking_reason" in js_text
    assert "aria-disabled" in js_text


def test_api_profile_status_reports_readiness(monkeypatch):
    monkeypatch.setattr(profile_store, "profile_exists", lambda: True)
    monkeypatch.setattr(profile_store, "load_profile", lambda: {"candidate_capabilities": []})

    response = profile_materials.api_profile_status_get()

    assert response.status_code == 200
    assert json.loads(response.body.decode("utf-8")) == {
        "has_profile": True,
        "has_candidate_capabilities": False,
        "candidate_capability_count": 0,
        "profile_ready_for_review": False,
        "blocking_reason": "Your profile has no capability rules. Rebuild onboarding before reviewing jobs.",
    }


def test_api_onboarding_import_accepts_supported_text_suffix(monkeypatch):
    monkeypatch.setattr(onboarding_api, "persist_uploaded_source_pack", lambda files: {"profile_sources": [], "cv_variants": []})
    monkeypatch.setattr(
        onboarding_api,
        "run_onboarding",
        lambda materials, search_preferences=None, onboarding_settings=None: {
            "ok": True,
            "materials": materials,
            "profile": {
                "candidate_capabilities": [
                    {
                        "name": "stakeholder engagement",
                        "level": "strong",
                        "aliases": [],
                        "needs_review": False,
                        "icon_key": "communication_stakeholders",
                    }
                ]
            },
        },
    )
    monkeypatch.setattr(onboarding_api, "get_session_cost_usd", lambda: 0.00112)
    monkeypatch.setattr(onboarding_api.srv, "patch_profile", lambda patch: patch)

    response = onboarding_api.api_onboarding_import(
        {
            "files": [
                {
                    "filename": "cv.txt",
                    "content_base64": base64.b64encode(b"header,value\n").decode("ascii"),
                }
            ],
            "search_preferences": {
                "keywords": "business analyst",
                "locations": ["Sydney"],
                "engagement_type": ["permanent", "contract"],
                "min_contract_months": 6,
            },
            "onboarding_settings": {
                "capability_strength_preset": "balanced",
            },
        }
    )

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["profile"]["candidate_capabilities"][0]["icon_key"] == "communication_stakeholders"
    assert payload["llm_cost_usd"] == 0.00112


def test_api_onboarding_import_logs_selected_capability_strength_preset(monkeypatch, caplog):
    import logging
    monkeypatch.setattr(onboarding_api, "persist_uploaded_source_pack", lambda files: {"profile_sources": [], "cv_variants": []})
    monkeypatch.setattr(onboarding_api, "run_onboarding", lambda materials, search_preferences=None, onboarding_settings=None: {"ok": True, "materials": materials})
    monkeypatch.setattr(onboarding_api.srv, "_validate_onboarding_settings_inputs", lambda payload: None)
    monkeypatch.setattr(onboarding_api.srv, "patch_profile", lambda patch: patch)

    with caplog.at_level(logging.INFO):
        response = onboarding_api.api_onboarding_import(
            {
                "files": [
                    {
                        "filename": "cv.txt",
                        "content_base64": base64.b64encode(b"header,value\n").decode("ascii"),
                    }
                ],
                "search_preferences": {
                    "keywords": "business analyst",
                    "locations": ["Sydney"],
                    "engagement_type": ["permanent", "contract"],
                },
                "onboarding_settings": {
                    "capability_strength_preset": "balanced",
                },
            }
        )

    assert response.status_code == 200
    assert "ONBOARDING_IMPORT" in caplog.text
    assert "balanced" in caplog.text


def test_api_onboarding_confirm_allows_no_sector_preference(monkeypatch):
    captured = {}
    monkeypatch.setattr(onboarding_api.srv, "load_profile", lambda: {"match_preferences": {}, "search_settings": {}})
    monkeypatch.setattr(onboarding_api.srv, "patch_profile", lambda patch: captured.setdefault("patch", patch) or patch)

    response = onboarding_api.api_onboarding_confirm(
        {
            "target_roles": ["Business Analyst"],
            "also_consider_roles": [],
            "search_keyword": "business analyst",
            "search_locations": ["Sydney"],
            "engagement_type": ["permanent", "contract"],
            "min_contract_months": 6,
            "prefer_sector": ["government", "private"],
            "minimum_salary_yearly": 0,
            "minimum_daily_rate": 0,
            "candidate_capabilities": [{"name": "stakeholder engagement", "level": "strong", "aliases": [], "icon_key": "communication_stakeholders"}],
        }
    )

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert captured["patch"]["match_preferences"]["prefer_sector"] == ["government", "private"]
    assert captured["patch"]["match_preferences"]["min_contract_months"] == 6
    assert captured["patch"]["candidate_capabilities"][0]["icon_key"] == "communication_stakeholders"


def test_api_onboarding_confirm_saves_work_mode_preference(monkeypatch):
    captured = {}
    monkeypatch.setattr(onboarding_api.srv, "load_profile", lambda: {"match_preferences": {}, "search_settings": {}})
    monkeypatch.setattr(onboarding_api.srv, "patch_profile", lambda patch: captured.setdefault("patch", patch) or patch)

    response = onboarding_api.api_onboarding_confirm(
        {
            "target_roles": ["Business Analyst"],
            "also_consider_roles": [],
            "search_keyword": "business analyst",
            "search_locations": ["Sydney"],
            "engagement_type": ["permanent", "contract"],
            "work_mode_preference": ["remote", "hybrid"],
            "prefer_sector": ["government"],
            "minimum_salary_yearly": 0,
            "minimum_daily_rate": 0,
            "candidate_capabilities": [{"name": "stakeholder engagement", "level": "strong", "aliases": [], "icon_key": "communication_stakeholders"}],
        }
    )

    assert response.status_code == 200
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["ok"] is True
    assert captured["patch"]["match_preferences"]["work_mode_preference"] == ["remote", "hybrid"]


def test_run_onboarding_logs_read_summary(monkeypatch, capsys, caplog, tmp_path):
    import logging as _logging
    caplog.set_level(_logging.INFO)
    fixture = {
        "capabilities": [
            {"name": "business analysis", "level": "strong", "aliases": [], "icon_key": "analysis_requirements", "needs_review": False},
        ],
        "role_titles": ["Business Analyst"],
        "target_occupation_queries": ["Business Analyst"],
        "match_preferences": {},
    }

    monkeypatch.setattr(profile_learning, "signal_in_approved_knowledge", lambda category, name, aliases=None: (False, ""))
    monkeypatch.setattr(profile_learning, "_llm_extract_from_cv", lambda text, lookback_years, alias_limit: fixture)
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(source_documents, "load_profile", lambda: {"search_settings": {}, "match_preferences": {}, "onboarding_settings": {"capability_strength_preset": "balanced"}})
    monkeypatch.setattr(source_documents, "clear_onboarding_runtime_outputs", lambda: None)
    monkeypatch.setattr(source_documents, "clear_capability_debug_log", lambda: None)

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": "A" * 5000}]},
        search_preferences={
            "keywords": "business analyst",
            "locations": ["Sydney"],
            "engagement_type": ["permanent"],
        },
        onboarding_settings={
            "capability_strength_preset": "balanced",
            "cv_max_pages": 5,
        },
    )

    import logging as _logging
    output = capsys.readouterr().out
    log_text = caplog.text
    combined = output + log_text
    assert result["ok"] is True
    assert "[ONBOARDING] Extraction input" in combined
    assert "chars read" in combined
    assert "approx pages" in combined
    assert "[ONBOARDING] CV source read" in combined
    assert "[ONBOARDING][LLM_CALL_DONE] purpose=cv_extraction" in combined
    assert "occupation_query_count=1" in combined


def test_api_onboarding_confirm_ignores_min_contract_months_when_contract_not_selected(monkeypatch):
    captured = {}
    monkeypatch.setattr(onboarding_api.srv, "load_profile", lambda: {"match_preferences": {}, "search_settings": {}})
    monkeypatch.setattr(onboarding_api.srv, "patch_profile", lambda patch: captured.setdefault("patch", patch) or patch)

    response = onboarding_api.api_onboarding_confirm(
        {
            "target_roles": ["Business Analyst"],
            "also_consider_roles": [],
            "search_keyword": "business analyst",
            "search_locations": ["Sydney"],
            "engagement_type": ["permanent"],
            "min_contract_months": 6,
            "prefer_sector": ["private"],
            "minimum_salary_yearly": 0,
            "minimum_daily_rate": 0,
            "candidate_capabilities": [{"name": "stakeholder engagement", "level": "strong", "aliases": [], "icon_key": "communication_stakeholders"}],
        }
    )

    assert response.status_code == 200
    assert captured["patch"]["match_preferences"]["min_contract_months"] is None


def test_api_onboarding_confirm_rejects_empty_candidate_capabilities(monkeypatch):
    monkeypatch.setattr(onboarding_api.srv, "load_profile", lambda: {"match_preferences": {}, "search_settings": {}})

    response = onboarding_api.api_onboarding_confirm(
        {
            "target_roles": ["Business Analyst"],
            "also_consider_roles": [],
            "search_keyword": "business analyst",
            "search_locations": ["Sydney"],
            "engagement_type": ["permanent", "contract"],
            "prefer_sector": ["government"],
            "minimum_salary_yearly": 0,
            "minimum_daily_rate": 0,
            "candidate_capabilities": [],
        }
    )

    assert response.status_code == 400
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["error"] == "Your profile has no capability rules. Rebuild onboarding before reviewing jobs."


def test_api_run_rejects_incomplete_profile_before_thread_start(monkeypatch):
    monkeypatch.setattr(profile_store, "profile_exists", lambda: True)
    monkeypatch.setattr(profile_store, "load_profile", lambda: {"candidate_capabilities": []})
    monkeypatch.setattr(scrape_debug.srv, "_onboarding_complete", lambda: True)
    monkeypatch.setattr(scrape_debug.srv, "_try_mark_run_started", lambda: (_ for _ in ()).throw(AssertionError("run must not start when profile is incomplete")))

    thread_started = []

    class _FailingThread:
        def __init__(self, *args, **kwargs):
            thread_started.append(True)
            raise AssertionError("run thread must not start when profile is incomplete")

    monkeypatch.setattr(scrape_debug.threading, "Thread", _FailingThread)

    response = scrape_debug.api_run({})

    assert response.status_code == 400
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["error"] == "Your profile has no capability rules. Rebuild onboarding before reviewing jobs."
    assert thread_started == []


def test_validate_required_onboarding_inputs_requires_locations_and_engagement():
    try:
        server_helpers._validate_required_onboarding_inputs(
            {
                "keywords": "",
                "locations": [],
                "engagement_type": [],
            },
            {},
        )
    except ValueError as exc:
        assert "location" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError for missing onboarding inputs")


def test_validate_required_onboarding_inputs_allows_blank_keywords():
    server_helpers._validate_required_onboarding_inputs(
            {
                "keywords": "",
                "locations": ["Sydney"],
                "engagement_type": ["permanent", "contract"],
            },
        {
            "extraction_lookback_years": 12,
            "title_extraction_min_months": 6,
        },
    )


def test_validate_required_onboarding_inputs_rejects_bad_boundaries():
    try:
        server_helpers._validate_required_onboarding_inputs(
            {
                "keywords": "x",
                "locations": ["Sydney", "!" * 5],
                "engagement_type": ["permanent", "contract"],
            },
            {
                "extraction_lookback_years": 99,
                "title_extraction_min_months": 0,
            },
        )
    except ValueError as exc:
        assert str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid onboarding boundaries")


def test_normalize_onboarding_settings_payload_supports_current_key():
    normalized = server_helpers._normalize_onboarding_settings_payload(
        {
            "extraction_lookback_years": 12,
            "title_extraction_min_months": 9,
            "max_target_patterns": 10,
            "max_secondary_patterns": 7,
            "capability_alias_limit": 6,
            "signal_cluster_min_alias_hits": 3,
            "signal_cluster_min_snippet_hits": 4,
            "signal_cluster_dense_snippet_alias_hits": 5,
        }
    )

    assert normalized["extraction_lookback_years"] == 12
    assert normalized["title_extraction_min_months"] == 9
    assert normalized["max_target_patterns"] == 10
    assert normalized["max_secondary_patterns"] == 7
    assert normalized["capability_alias_limit"] == 6
    assert normalized["signal_cluster_min_alias_hits"] == 3
    assert normalized["signal_cluster_min_snippet_hits"] == 4
    assert normalized["signal_cluster_dense_snippet_alias_hits"] == 5


def test_normalize_onboarding_settings_payload_clamps_current_keys(monkeypatch):
    monkeypatch.setattr(server_helpers, "load_profile", lambda: {"onboarding_settings": {}})

    normalized = server_helpers._normalize_onboarding_settings_payload(
        {
            "extraction_lookback_years": 999,
            "title_extraction_min_months": 0,
            "max_target_patterns": -1,
            "max_secondary_patterns": 999,
            "capability_alias_limit": 999,
            "signal_cluster_min_alias_hits": 0,
            "signal_cluster_min_snippet_hits": 0,
            "signal_cluster_dense_snippet_alias_hits": 999,
        }
    )

    assert normalized["extraction_lookback_years"] == 20
    assert normalized["title_extraction_min_months"] == 1
    assert normalized["max_target_patterns"] == 1
    assert normalized["max_secondary_patterns"] == 20
    assert normalized["capability_alias_limit"] == 20
    assert normalized["signal_cluster_min_alias_hits"] == 1
    assert normalized["signal_cluster_min_snippet_hits"] == 1
    assert normalized["signal_cluster_dense_snippet_alias_hits"] == 20


def test_run_onboarding_uses_saved_onboarding_settings_when_argument_missing(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    cv_path = tmp_path / "cv.txt"
    cv_path.write_text("# Professional Experience\nAcme - Delivery Lead (2020 - 2024)\n", encoding="utf-8")

    monkeypatch.setattr(
        source_documents,
        "load_profile",
        lambda: {
            "search_settings": {},
            "match_preferences": {},
            "onboarding_settings": {
                "extraction_lookback_years": 11,
                "title_extraction_min_months": 5,
                "max_target_patterns": 9,
                "max_secondary_patterns": 4,
                "capability_alias_limit": 7,
                "signal_cluster_min_alias_hits": 3,
                "signal_cluster_min_snippet_hits": 4,
                "signal_cluster_dense_snippet_alias_hits": 5,
            },
        },
    )
    monkeypatch.setattr(source_documents, "patch_profile", lambda patch: patch)
    monkeypatch.setattr(profile_learning, "signal_in_approved_knowledge", lambda category, name, aliases=None: (False, ""))

    def fake_llm_extract_from_cv(text, lookback_years, alias_limit):
        captured["onboarding_settings"] = {
            "lookback_years": lookback_years,
            "alias_limit": alias_limit,
        }
        return {
            "capabilities": [
                {"name": "delivery", "level": "working", "aliases": [], "icon_key": "delivery_project", "needs_review": False}
            ],
            "role_titles": ["Delivery Lead"],
            "target_occupation_queries": ["Delivery Lead"],
            "match_preferences": {},
        }

    monkeypatch.setattr(profile_learning, "_llm_extract_from_cv", fake_llm_extract_from_cv)

    result = source_documents.run_onboarding(
        {"profile_sources": [{"label": "Primary CV", "filename": "cv.txt", "content": "# Professional Experience\nAcme - Delivery Lead (2020 - 2024)\n"}]}
    )

    assert result["ok"] is True
    assert captured["onboarding_settings"]["lookback_years"] == 11
    assert captured["onboarding_settings"]["alias_limit"] == 7


def test_normalize_full_profile_preserves_selected_title_categories():
    normalized = profile_store.normalize_full_profile(
        {
            "target_roles": ["senior business analyst"],
            "also_consider_roles": ["scrum master"],
        }
    )

    assert normalized["target_roles"] == ["senior business analyst"]
    assert normalized["also_consider_roles"] == ["scrum master"]


def test_normalize_full_profile_removes_exact_duplicate_title_from_secondary():
    normalized = profile_store.normalize_full_profile(
        {
            "target_roles": ["senior business analyst"],
            "also_consider_roles": ["Senior Business Analyst", "scrum master"],
        }
    )

    assert normalized["target_roles"] == ["senior business analyst"]
    assert normalized["also_consider_roles"] == ["scrum master"]


def test_normalize_full_profile_preserves_clean_target_occupation_queries():
    normalized = profile_store.normalize_full_profile(
        {
            "target_occupation_queries": [
                "  Software Engineer  ",
                "software engineer",
                "DevOps Engineer\nCloud Engineer",
            ]
        }
    )

    assert normalized["target_occupation_queries"] == [
        "Software Engineer",
        "DevOps Engineer",
        "Cloud Engineer",
    ]


def test_normalize_full_profile_mirrors_primary_search_location_into_match_preferences():
    normalized = profile_store.normalize_full_profile(
        {
            "search_settings": {
                "locations": ["Sydney"],
            },
            "match_preferences": {
                "secondary_location": "Melbourne",
            },
        }
    )

    assert normalized["search_settings"]["locations"] == ["Sydney"]
    assert normalized["match_preferences"]["home_location"] == "Sydney"
    assert normalized["match_preferences"]["secondary_location"] == "Melbourne"


def test_normalize_full_profile_preserves_candidate_capabilities():
    """normalize_full_profile must not wipe candidate_capabilities.
    """
    caps = [
        {"name": "financial reporting", "level": "proficient", "aliases": [], "icon_key": "finance_commercial"},
        {"name": "accounts payable & receivable", "level": "working", "aliases": ["AP", "AR"], "icon_key": "finance_commercial"},
    ]
    normalized = profile_store.normalize_full_profile({"candidate_capabilities": caps})
    result_names = [r["name"] for r in normalized["candidate_capabilities"]]
    assert "financial reporting" in result_names
    assert "accounts payable & receivable" in result_names
    assert len(normalized["candidate_capabilities"]) == 2
    assert all(rule["icon_key"] == "finance_commercial" for rule in normalized["candidate_capabilities"])


def test_user_settings_schedule_payload_is_sanitized_and_exposed():
    sanitized = server_helpers.SettingsHandler._sanitize_user_settings_payload(
        {
            "workspace": {
                "minimum_score": 150,
            },
            "schedule": {
                "daily_time_local": "09:45",
                "loop_sleep_seconds": 30,
            }
        }
    )

    assert sanitized["workspace"] == {
        "minimum_score": 100,
    }
    assert sanitized["schedule"] == {
        "daily_time_local": "09:45",
        "loop_sleep_seconds": 60,
    }

    public_payload = server_helpers.SettingsHandler._public_user_settings_payload(
        {
            "workspace": {
                "minimum_score": 61,
            },
            "schedule": {
                "daily_time_local": "09:45",
                "loop_sleep_seconds": 120,
            }
        }
    )

    assert public_payload["workspace"] == {
        "minimum_score": 61,
    }
    assert public_payload["schedule"] == {
        "daily_time_local": "09:45",
        "loop_sleep_seconds": 120,
    }


def test_user_settings_model_uses_advanced_setting_options(monkeypatch):
    monkeypatch.setattr(
        server_helpers,
        "load_global_settings",
        lambda: {
            "llm_settings": {
                "model_options": ["gpt-4o-mini", "gpt-4o"],
            },
        },
    )

    sanitized = server_helpers.SettingsHandler._sanitize_user_settings_payload(
        {
            "llm": {
                "model": "gpt-4o",
            }
        }
    )

    assert sanitized["llm"] == {"model": "gpt-4o"}

    with pytest.raises(ValueError, match="Global Settings"):
        server_helpers.SettingsHandler._sanitize_user_settings_payload(
            {
                "llm": {
                    "model": "gpt-4.1",
                }
            }
        )


def test_user_settings_schedule_payload_rejects_bad_time_format():
    try:
        server_helpers.SettingsHandler._sanitize_user_settings_payload(
            {
                "schedule": {
                    "daily_time_local": "9:45 am",
                }
            }
        )
    except ValueError as exc:
        assert "HH:MM" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid schedule time")


def test_remove_review_key_supports_unapply(monkeypatch):
    saved_profile = {
        "review_controls": {
            "applied_job_keys": ["job-1", "job-2"],
            "hidden_job_keys": ["job-3"],
        }
    }
    events = []

    monkeypatch.setattr(review_history_service, "load_profile", lambda: saved_profile)
    monkeypatch.setattr(review_history_service, "save_profile", lambda profile: profile)
    monkeypatch.setattr(review_history_service, "persist_review_event", lambda *args, **kwargs: events.append((args, kwargs)))
    monkeypatch.setattr(review_history_service, "rebuild_workspace_after_rule_change", lambda reason="": events.append(((f"rebuild:{reason}",), {})))

    result = review_history_service.remove_review_key("unapply", "job-1")

    assert result["ok"] is True
    assert result["reload_workspace"] is True
    assert saved_profile["review_controls"]["applied_job_keys"] == ["job-2"]
    assert saved_profile["review_controls"]["hidden_job_keys"] == ["job-3"]
    assert events[0][0][0] == "unapply"
    assert str(events[1][0][0]).startswith("rebuild:review action saved: unapply")


def test_matching_rules_changed_detects_capability_matrix_change():
    assert server_helpers.SettingsHandler._matching_rules_changed({}, {"candidate_capabilities": [{"name": "x"}]}) is True

def test_matching_rules_changed_ignores_identical_values():
    caps = [{"name": "x"}]
    assert server_helpers.SettingsHandler._matching_rules_changed({"candidate_capabilities": caps}, {"candidate_capabilities": caps}) is False


def test_rebuild_workspace_after_rule_change_runs_in_background(monkeypatch, tmp_path):
    started = []
    rebuilds = []

    class FakeThread:
        def __init__(self, target=None, args=None, daemon=None, name=None):
            self.target = target
            self.args = args or ()
            self.daemon = daemon
            self.name = name

        def start(self):
            started.append({"daemon": self.daemon, "name": self.name})
            if self.target:
                self.target(*self.args)

    monkeypatch.setattr(workspace_refresh_service, "get_workspace_results_path", lambda: tmp_path / "workspace.html")
    (tmp_path / "workspace.html").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(workspace_refresh_service.threading, "Thread", FakeThread)
    monkeypatch.setattr(workspace_refresh_service, "rebuild_workspace_results", lambda reason="": rebuilds.append(reason))

    workspace_refresh_service.rebuild_workspace_after_rule_change("profile matching rules saved")

    assert started == [{"daemon": True, "name": "job-hunter-workspace-rebuild"}]
    assert rebuilds == ["profile matching rules saved; applying saved filters to current results"]


def test_rebuild_workspace_on_startup_runs_when_data_exists(monkeypatch, tmp_path):
    rebuilds = []

    monkeypatch.setattr(server_helpers, "get_workspace_results_path", lambda: tmp_path / "workspace.html")
    monkeypatch.setattr(server_helpers, "load_run_stats", lambda: {"run_started_at": "2026-05-16T08:00:00"})
    monkeypatch.setattr(
        server_helpers,
        "rebuild_workspace_results",
        lambda reason="", user_id=None: rebuilds.append((reason, user_id)),
    )

    server_helpers._rebuild_workspace_on_startup("test-user")

    assert rebuilds == [("server startup rebuild", "test-user")]


def test_reset_current_user_state_clears_local_profile_and_feedback(monkeypatch, tmp_path):
    saved_profiles = []
    saved_materials = []
    cleared = []

    fake_users_dir = tmp_path / "users"
    fake_local_dir = fake_users_dir / "test_user"
    fake_local_dir.mkdir(parents=True, exist_ok=True)

    workspace_path = tmp_path / "workspace.html"

    monkeypatch.setattr(server_helpers, "USERS_DIR", fake_users_dir)
    monkeypatch.setattr(server_helpers, "save_profile", lambda profile: saved_profiles.append(profile) or profile)
    monkeypatch.setattr(server_helpers, "save_source_materials", lambda payload: saved_materials.append(payload) or payload)
    monkeypatch.setattr(server_helpers, "clear_job_history", lambda: cleared.append("job_history"))
    monkeypatch.setattr(server_helpers, "clear_user_settings", lambda: cleared.append("user_settings"))
    monkeypatch.setattr(server_helpers, "clear_workspace_pool", lambda: cleared.append("workspace_pool"))
    monkeypatch.setattr(server_helpers, "clear_agent_state", lambda: cleared.append("agent_state"))
    monkeypatch.setattr(server_helpers, "clear_review_data", lambda: cleared.append("review_data"))
    monkeypatch.setattr(server_helpers, "clear_run_stats", lambda: cleared.append("run_stats"))
    monkeypatch.setattr(server_helpers, "clear_audit_rows", lambda: cleared.append("audit_rows"))
    monkeypatch.setattr(server_helpers, "get_workspace_results_path", lambda: workspace_path)

    workspace_path.write_text("old workspace", encoding="utf-8")

    result = server_helpers.SettingsHandler._reset_current_user_state()

    assert result["ok"] is True
    assert result["redirect_to"] == "/start?fresh=1"
    assert not fake_local_dir.exists()
    assert saved_profiles == [server_helpers.DEFAULT_PROFILE]
    assert saved_materials == [server_helpers.DEFAULT_SOURCE_MATERIALS]
    assert not workspace_path.exists()
    assert "job_history" in cleared
    assert "user_settings" in cleared
    assert "workspace_pool" in cleared
    assert "agent_state" in cleared
    assert "review_data" in cleared
    assert "run_stats" in cleared
    assert "audit_rows" in cleared


def test_reset_global_learning_clears_shared_signal_registry(monkeypatch):
    calls = []

    def fake_clear_signal_learning_state():
        calls.append(True)

    monkeypatch.setattr("job_hunter_agent.signal_registry.clear_signal_learning_state", fake_clear_signal_learning_state)

    result = server_helpers.SettingsHandler._reset_global_learning()

    assert result["ok"] is True
    assert calls == [True]
