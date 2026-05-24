from fastapi.testclient import TestClient

from job_hunter_agent.database import db_conn
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.io_utils import write_review_data
import job_hunter_agent.routes.workspace_api as workspace_api
from job_hunter_agent.paths import LOCAL_USER_ID


def test_api_review_data_returns_saved_suggested_tuning(monkeypatch, isolated_db):
    monkeypatch.setattr("job_hunter_agent.fastapi_app.is_auth_disabled", lambda: True)
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
    monkeypatch.setattr("job_hunter_agent.fastapi_app.read_session_username", lambda request: "test@example.com")
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
    monkeypatch.setattr("job_hunter_agent.fastapi_app.read_session_username", lambda request: "test@example.com")
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
