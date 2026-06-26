"""Tests for workspace api."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import job_hunter_agent.routes.workspace_api as workspace_api
import job_hunter_agent.routes.scrape_debug as scrape_debug
import job_hunter_agent.paths as paths
from job_hunter_agent import source_connector, workspace_service
from job_hunter_agent.database import db_conn
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.io_utils import write_review_data


def test_api_review_data_returns_saved_suggested_tuning(monkeypatch, isolated_db):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {"user_id": "test_user", "email": "test@example.com", "role": "candidate"},
    )
    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", ("test_user",))

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


def test_api_clean_search_clears_only_search_state(monkeypatch, isolated_db, tmp_path):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {"user_id": "test_user", "email": "test@example.com", "role": "admin"},
    )
    monkeypatch.setattr("job_hunter_agent.fastapi_app.verify_csrf_token", lambda request, token: True)
    monkeypatch.setattr(scrape_debug.srv, "DEBUG_MODE", True)

    fake_users_dir = tmp_path / "users"
    fake_user_dir = fake_users_dir / "test_user"
    fake_user_dir.mkdir(parents=True, exist_ok=True)
    workspace_path = fake_user_dir / "workspace_results.html"
    workspace_path.write_text("<html><body>stale</body></html>", encoding="utf-8")

    monkeypatch.setattr(paths, "USERS_DIR", fake_users_dir)

    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", ("test_user",))
        conn.execute(
            "INSERT INTO user_profile (user_id, data) VALUES (?, ?)",
            ("test_user", "{}"),
        )
        conn.execute(
            "INSERT INTO user_settings (user_id, data) VALUES (?, ?)",
            ("test_user", "{}"),
        )
        conn.execute(
            "INSERT INTO job_history (user_id, job_key, source, platform_id, data) VALUES (?, ?, ?, ?, ?)",
            ("test_user", "seek:1", "seek", "1", "{}"),
        )
        conn.execute(
            "INSERT INTO workspace_pool (user_id, data) VALUES (?, ?)",
            ("test_user", "{}"),
        )
        conn.execute(
            "INSERT INTO review_data (user_id, data) VALUES (?, ?)",
            ("test_user", "{}"),
        )
        conn.execute(
            "INSERT INTO run_stats (user_id, run_id, data) VALUES (?, 'latest', ?)",
            ("test_user", "{}"),
        )
        conn.execute(
            "INSERT INTO audit_records (user_id, event, data) VALUES (?, 'latest_scrape_run', ?)",
            ("test_user", "[]"),
        )
        conn.execute(
            "INSERT INTO candidate_application_history (user_id, job_key, data) VALUES (?, ?, ?)",
            ("test_user", "seek:1", "{}"),
        )

    client = TestClient(create_app())
    response = client.post("/api/test/clean-search", json={})

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "message": "Search results cleared. Profile and settings were preserved.",
        "redirect_to": "/workspace",
    }
    assert not workspace_path.exists()

    with db_conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM job_history WHERE user_id = ?",
            ("test_user",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM workspace_pool WHERE user_id = ?",
            ("test_user",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM review_data WHERE user_id = ?",
            ("test_user",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM run_stats WHERE user_id = ?",
            ("test_user",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM audit_records WHERE user_id = ? AND event = 'latest_scrape_run'",
            ("test_user",),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM user_profile WHERE user_id = ?",
            ("test_user",),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM user_settings WHERE user_id = ?",
            ("test_user",),
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM candidate_application_history WHERE user_id = ?",
            ("test_user",),
        ).fetchone()[0] == 1


def test_api_clean_search_is_debug_only(monkeypatch, isolated_db):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {"user_id": "test_user", "email": "test@example.com", "role": "admin"},
    )
    monkeypatch.setattr("job_hunter_agent.fastapi_app.verify_csrf_token", lambda request, token: True)
    monkeypatch.setattr(scrape_debug.srv, "DEBUG_MODE", False)

    client = TestClient(create_app())
    response = client.post("/api/test/clean-search", json={})

    assert response.status_code == 403
    assert response.json() == {"error": "Test mode only"}


def test_api_results_html_surfaces_last_run_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )
    workspace_path = tmp_path / "workspace_results.html"
    workspace_path.write_text("<html><body>stale</body></html>", encoding="utf-8")
    monkeypatch.setattr(workspace_api, "get_workspace_results_path", lambda: workspace_path)
    monkeypatch.setattr(
        workspace_api, "load_run_stats", lambda: {"last_run_error": "ValueError: broken scraper"}
    )
    rebuild_calls = []
    monkeypatch.setattr(
        workspace_api,
        "rebuild_workspace_results",
        lambda *args, **kwargs: rebuild_calls.append((args, kwargs)),
    )

    client = TestClient(create_app())
    response = client.get("/api/results-html")

    assert response.status_code == 503
    assert response.json() == {"error": "ValueError: broken scraper"}
    assert rebuild_calls == []


def test_api_results_html_rebuilds_when_no_error_and_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )
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
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {"user_id": "test", "email": "test@example.com", "role": "admin"},
    )
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
    assert "loadWorkspaceProfileStatus" in html_text
    assert "renderOnboardingWelcome" in html_text
    assert 'id="ws_profile_status_mount"' in html_text
    assert "/api/profile/status" in html_text
    assert "profile_ready_for_review" in html_text
    assert "blocking_reason" in html_text


def test_workspace_template_includes_stop_search_control():
    html_path = Path(__file__).resolve().parents[1] / "templates" / "workspace.html"
    html_text = html_path.read_text(encoding="utf-8")

    assert "ws_stop_search_btn" in html_text
    assert "/api/run/stop" in html_text
    assert "search_stop_label" in html_text


def test_scrape_jobs_direct_stops_before_run_when_profile_incomplete(monkeypatch):
    monkeypatch.setattr("job_hunter_agent.profile_store.profile_exists", lambda: True)
    monkeypatch.setattr(source_connector, "get_user_id_for_runtime", lambda: "test-user")
    monkeypatch.setattr(source_connector, "load_profile", lambda: {"candidate_capabilities": []})
    monkeypatch.setattr(
        source_connector,
        "build_scrape_run_context",
        lambda argv: SimpleNamespace(
            search_settings={"keywords": "Business Analyst", "locations": ["Sydney"]},
            enabled_sources=["seek"],
            configured_seek_max_pages=1,
            configured_date_range=7,
            dashboard_debug_mode=False,
            no_llm_mode=False,
            dashboard_min_score=0,
            reset_new_to_you=False,
            headless=False,
        ),
    )

    called = []

    def fake_run_enabled_sources(context):
        called.append(context)
        raise AssertionError("run_enabled_sources must not be called for an incomplete profile")

    monkeypatch.setattr(source_connector, "run_enabled_sources", fake_run_enabled_sources)

    with pytest.raises(ValueError) as exc:
        source_connector.scrape_jobs_direct()

    assert (
        str(exc.value)
        == "Your profile has no capability rules. Rebuild onboarding before reviewing jobs."
    )
    assert called == []


def test_scrape_jobs_direct_forces_headed_browser_in_persistent_mode(monkeypatch):
    monkeypatch.setattr("job_hunter_agent.profile_store.profile_exists", lambda: True)
    monkeypatch.setattr(source_connector, "get_user_id_for_runtime", lambda: "test-user")
    monkeypatch.setattr(source_connector, "load_profile", lambda: {"candidate_capabilities": [{}]})
    monkeypatch.setattr(source_connector, "require_profile_ready_for_review", lambda profile: None)
    monkeypatch.setattr(
        source_connector,
        "build_scrape_run_context",
        lambda argv: SimpleNamespace(
            search_settings={"keywords": "Business Analyst", "locations": ["Sydney"]},
            enabled_sources=["seek"],
            configured_seek_max_pages=1,
            configured_date_range=7,
            dashboard_debug_mode=False,
            no_llm_mode=False,
            dashboard_min_score=0,
            reset_new_to_you=False,
            headless=True,
        ),
    )
    monkeypatch.setattr(
        "job_hunter_agent.global_settings.get_playwright_headless", lambda: True
    )
    monkeypatch.setattr(
        "job_hunter_agent.global_settings.get_playwright_browser_mode", lambda: "persistent"
    )

    captured = {}

    def fake_run_enabled_sources(context):
        captured["headless"] = context.headless
        return [], [], []

    monkeypatch.setattr(source_connector, "run_enabled_sources", fake_run_enabled_sources)
    monkeypatch.setattr(source_connector, "finalize_scrape_run", lambda *args, **kwargs: "done")

    result = source_connector.scrape_jobs_direct()

    assert result == "done"
    assert captured["headless"] is False


def test_run_status_and_stop_endpoint_report_stopping(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {"user_id": "test-user", "email": "test@example.com", "role": "candidate"},
    )
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.verify_csrf_token", lambda request, token: True
    )
    monkeypatch.setattr(
        workspace_api.srv, "_read_last_run_timestamp", lambda: "2026-05-26T00:00:00+10:00"
    )
    monkeypatch.setattr(workspace_api.srv, "_is_run_in_progress", lambda: True)
    monkeypatch.setattr(workspace_api, "get_run_progress", lambda: "SEEK page 1/3")
    monkeypatch.setattr(workspace_api, "run_stop_requested", lambda: True)
    stop_calls = []
    monkeypatch.setattr(workspace_api, "request_run_stop", lambda: stop_calls.append(True))

    client = TestClient(create_app())

    status_response = client.get("/api/run-status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "stopping"
    assert status_response.json()["stop_requested"] is True
    assert status_response.json()["progress"] == "SEEK page 1/3"

    stop_response = client.post("/api/run/stop")
    assert stop_response.status_code == 200
    assert stop_response.json()["status"] == "stopping"
    assert stop_response.json()["stop_requested"] is True
    assert stop_response.json()["progress"] == "SEEK page 1/3"
    assert stop_calls == [True]


def test_job_history_endpoint_uses_saved_history(monkeypatch):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {"user_id": "test-user", "email": "test@example.com", "role": "candidate"},
    )
    monkeypatch.setattr(
        workspace_api,
        "load_job_history",
        lambda: {
            "seek:123": {
                "times_viewed": 4,
                "first_viewed_at": "2026-05-26T00:00:00+10:00",
                "last_viewed_at": "2026-05-27T00:00:00+10:00",
            }
        },
    )

    client = TestClient(create_app())
    response = client.get("/api/job-history")

    assert response.status_code == 200
    assert response.json() == {
        "jobs": {
            "seek:123": {
                "times_viewed": 4,
                "first_viewed_at": "2026-05-26T00:00:00+10:00",
                "last_viewed_at": "2026-05-27T00:00:00+10:00",
            }
        }
    }
