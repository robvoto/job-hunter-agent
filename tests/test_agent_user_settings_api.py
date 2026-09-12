"""Tests for user settings API schedule persistence."""

from fastapi.testclient import TestClient

from job_hunter_agent.database import db_conn
from job_hunter_agent.fastapi_app import create_app
from job_hunter_agent.user_settings import list_approved_user_setting_user_ids, save_user_settings


def test_approved_user_settings_ids_exclude_pending_users(isolated_db):
    from job_hunter_agent.database import ensure_user_row

    ensure_user_row("approved-user", access_status="approved")
    ensure_user_row("pending-user", access_status="pending")
    save_user_settings("approved-user", {})
    save_user_settings("pending-user", {})

    assert list_approved_user_setting_user_ids() == ["approved-user"]


def test_user_settings_schedule_enabled_round_trips(monkeypatch, isolated_db):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {
            "user_id": "test-user",
            "email": "test@example.com",
            "role": "candidate",
            "access_status": "approved",
        },
    )
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.verify_csrf_token", lambda request, token: True
    )

    with db_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", ("test-user",))

    client = TestClient(create_app())

    patch_response = client.patch(
        "/api/user-settings",
        json={
            "schedule": {
                "enabled": True,
                "daily_time_local": "18:30",
                "loop_sleep_seconds": 300,
            }
        },
    )

    assert patch_response.status_code == 200
    assert patch_response.json()["schedule"] == {
        "enabled": True,
        "daily_time_local": "18:30",
        "loop_sleep_seconds": 300,
    }

    get_response = client.get("/api/user-settings")

    assert get_response.status_code == 200
    assert get_response.json()["schedule"] == {
        "enabled": True,
        "daily_time_local": "18:30",
        "loop_sleep_seconds": 300,
    }


def test_source_materials_round_trip(monkeypatch, isolated_db):
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.read_session_user",
        lambda request: {
            "user_id": "test-user",
            "email": "test@example.com",
            "role": "candidate",
            "access_status": "approved",
        },
    )
    monkeypatch.setattr(
        "job_hunter_agent.fastapi_app.verify_csrf_token", lambda request, token: True
    )

    client = TestClient(create_app())

    put_response = client.put(
        "/api/source-materials",
        json={
            "profile_sources": [
                {
                    "label": "Primary CV",
                    "filename": "cv.txt",
                    "content": "Example CV content",
                }
            ],
            "cv_variants": [],
        },
    )

    assert put_response.status_code == 200
    assert put_response.json()["profile_sources"][0]["content"] == "Example CV content"

    get_response = client.get("/api/source-materials")

    assert get_response.status_code == 200
    assert get_response.json()["profile_sources"][0]["content"] == "Example CV content"
