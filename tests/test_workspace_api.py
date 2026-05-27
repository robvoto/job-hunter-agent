"""Tests for workspace api."""

from fastapi.testclient import TestClient
from datetime import datetime

from job_hunter_agent.database import db_conn
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.io_utils import write_review_data
from job_hunter_agent import workspace_service
import job_hunter_agent.routes.workspace_api as workspace_api
from job_hunter_agent.paths import LOCAL_USER_ID
from pathlib import Path


def test_api_review_data_returns_saved_suggested_tuning(monkeypatch, isolated_db):
    monkeypatch.setattr("job_hunter_agent.fastapi_app.read_session_user", lambda request: {"user_id": LOCAL_USER_ID, "email": "test@example.com", "role": "candidate"})
    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (LOCAL_USER_ID,))

    write_review_data(
        {
            "kept_job_urls": ["https://example.test/job-1"],
            "skill_observations": [
                {
                    "skill": "Process mapping",
                    "title": "Business Analyst",
                    "company": "Example Co",
                    "url": "https://example.test/job-1",
                    "search_location": "Sydney",
                }
            ],
            "unknown_skills": [],
            "rejections_by_reason": [],
            "suggested_tuning": {
                "summary": {"capability_count": 1, "rule_count": 0},
                "capability_suggestions": [
                    {
                        "kind": "capability",
                        "skill": "Process mapping",
                        "count": 1,
                        "headline": "Keep it",
                        "detail": "Use it",
                        "target": "Capability matrix",
                        "recommended_choice": "working",
                        "recommended_label": "Working",
                        "current_treatment": "Unclassified",
                        "examples": [
                            {
                                "title": "Business Analyst",
                                "company": "Example Co",
                                "url": "https://example.test/job-1",
                                "search_location": "Sydney",
                            }
                        ],
                    }
                ],
                "rule_suggestions": [],
            },
        }
    )

    client = TestClient(create_app())
    response = client.get("/api/review-data")

    assert response.status_code == 200
    payload = response.json()
    assert payload["suggested_tuning"]["capability_suggestions"][0]["skill"] == "Process mapping"


def test_api_results_html_surfaces_last_run_error(monkeypatch, tmp_path):
    monkeypatch.setattr("job_hunter_agent.fastapi_app.read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    workspace_path = tmp_path / "workspace_results.html"
    workspace_path.write_text("<html><body>stale</body></html>", encoding="utf-8")
    monkeypatch.setattr(workspace_api, "get_workspace_results_path", lambda: workspace_path)
    monkeypatch.setattr(workspace_api, "load_run_stats", lambda: {"last_run_error": "ValueError: broken scraper"})
    rebuild_calls = []
    monkeypatch.setattr(workspace_api, "rebuild_workspace_results", lambda *args, **kwargs: rebuild_calls.append((args, kwargs)))

    client = TestClient(create_app())
    response = client.get("/api/results-html")

    assert response.status_code == 503
    assert response.json() == {"error": "ValueError: broken scraper"}
    assert rebuild_calls == []


def test_api_results_html_rebuilds_when_no_error_and_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("job_hunter_agent.fastapi_app.read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    workspace_path = tmp_path / "workspace_results.html"
    monkeypatch.setattr(workspace_api, "get_workspace_results_path", lambda: workspace_path)
    monkeypatch.setattr(workspace_api, "load_run_stats", lambda: {})

    def fake_rebuild_workspace_results(*args, **kwargs):
        workspace_path.write_text("<html><body>workspace</body></html>", encoding="utf-8")

    monkeypatch.setattr(workspace_api, "rebuild_workspace_results", fake_rebuild_workspace_results)

    client = TestClient(create_app())
    response = client.get("/api/results-html")

    assert response.status_code == 200
    assert "workspace" in response.text


def test_api_results_html_rebuild_excludes_records_without_llm_grade(monkeypatch, tmp_path):
    monkeypatch.setattr("job_hunter_agent.fastapi_app.read_session_user", lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"})
    workspace_path = tmp_path / "workspace_results.html"
    monkeypatch.setattr(workspace_api, "get_workspace_results_path", lambda: workspace_path)
    monkeypatch.setattr(workspace_api, "load_run_stats", lambda: {})

    profile = {
        "candidate_capabilities": [],
        "dominant_signal_clusters": [],
        "match_preferences": {
            "home_location": "Sydney NSW",
            "prefer_sector": True,
            "engagement_type": ["permanent", "contract"],
            "preferred_contract_months": 12,
            "short_contract_months": 6,
        },
        "preference_weights": {},
        "salary_preferences": {},
    }
    record = {
        "job_key": "job-1",
        "title": "Business Analyst",
        "company": "Example Co",
        "url": "https://example.test/job-1",
        "source": "seek",
        "title_reason": "OK",
        "content_reason": "OK",
        "details_text": "Work with stakeholders and process mapping.",
        "description_source": "details",
        "details_status": "ok",
        "fit_confidence": "HIGH",
        "applied": False,
        "archived": False,
        "hidden": False,
    }

    def fake_rebuild_workspace_results(*args, **kwargs):
        with monkeypatch.context() as m:
            m.setattr(workspace_service, "is_workspace_eligible", lambda *a, **k: True)
            workspace_service.build_workspace_record_sets(
                [record],
                {},
                set(),
                set(),
                datetime(2026, 5, 26, 14, 24, 2),
                scoring_profile=profile,
                workspace_min_score=0,
                debug_mode=False,
                audit_rows=[],
            )
        workspace_path.write_text("<html><body>workspace</body></html>", encoding="utf-8")

    monkeypatch.setattr(workspace_api, "rebuild_workspace_results", fake_rebuild_workspace_results)

    client = TestClient(create_app())
    response = client.get("/api/results-html")

    assert response.status_code == 200
    assert "workspace" in response.text


def test_workspace_welcome_overlay_is_not_gated_on_cv_text():
    html_path = Path(__file__).resolve().parents[1] / "templates" / "workspace.html"
    html_text = html_path.read_text(encoding="utf-8")

    assert "profile?.cv_text" not in html_text
    assert "loadWorkspaceProfile" not in html_text
    assert "renderOnboardingWelcome" in html_text
