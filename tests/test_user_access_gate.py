"""Regression coverage for the application-level user approval gate."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient
from starlette.requests import Request

from job_hunter_agent.auth import (
    _build_session_cookie_value,
    get_or_create_user,
    issue_csrf_token,
    read_session_user,
)
from job_hunter_agent.database import (
    db_conn,
    init_db,
    request_user_access,
    update_user_access_status,
)
from job_hunter_agent.fastapi_app import create_app

ADMIN_EMAIL = "rob.voto.au@gmail.com"
SESSION_SECRET = "approval-gate-test-secret"


def _client_for_user(monkeypatch, isolated_db, email: str, status: str = "verified"):
    monkeypatch.setenv("JOB_HUNTER_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("JOB_HUNTER_AUTH_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("JOB_HUNTER_GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("JOB_HUNTER_GOOGLE_CLIENT_SECRET", "test-secret")
    app = create_app()
    user = get_or_create_user(email, ADMIN_EMAIL)
    if status != user["access_status"]:
        update_user_access_status(user["user_id"], status, ADMIN_EMAIL)
    client = TestClient(app)
    client.cookies.set("job_hunter_session", _build_session_cookie_value(user, SESSION_SECRET))
    return app, client, user


def _session_request(app, client: TestClient) -> Request:
    cookie = str(client.cookies.get("job_hunter_session") or "")
    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"cookie", f"job_hunter_session={cookie}".encode("utf-8"))],
        "app": app,
    }
    return Request(scope)


def test_new_google_user_defaults_to_verified(isolated_db, monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_ADMIN_EMAIL", ADMIN_EMAIL)
    user = get_or_create_user("new-tester@example.com", ADMIN_EMAIL)

    assert user["access_status"] == "verified"
    with db_conn(isolated_db) as conn:
        row = conn.execute(
            "SELECT access_status FROM users WHERE user_id = ?",
            (user["user_id"],),
        ).fetchone()
    assert row["access_status"] == "verified"


def test_existing_users_migrate_without_deleting_history(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy.db"
    monkeypatch.setenv("JOB_HUNTER_ADMIN_EMAIL", ADMIN_EMAIL)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                email TEXT,
                display_name TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            INSERT INTO users (user_id, email, display_name)
            VALUES ('admin-id', 'rob.voto.au@gmail.com', 'Rob'),
                   ('candidate-id', 'old-user@example.com', 'Old User');
            """
        )
    init_db(db_path)

    with db_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT user_id, access_status FROM users ORDER BY user_id"
        ).fetchall()
    assert [(row["user_id"], row["access_status"]) for row in rows] == [
        ("admin-id", "approved"),
        ("candidate-id", "verified"),
    ]


def test_verified_user_must_explicitly_request_access(isolated_db, monkeypatch):
    app, client, user = _client_for_user(
        monkeypatch, isolated_db, "verified@example.com", "verified"
    )

    protected = client.get("/docs", follow_redirects=False)
    assert protected.status_code == 302
    assert protected.headers["location"] == "/request-access"

    request_page = client.get("/request-access")
    assert request_page.status_code == 200
    assert "Request access" in request_page.text
    assert "Access requested" not in request_page.text
    assert "© 2025–2026 Roberto Hernan Voto. All rights reserved." in request_page.text
    assert "__JOB_HUNTER_" not in request_page.text

    csrf_token = issue_csrf_token(_session_request(app, client))
    submitted = client.post(
        "/request-access",
        data={"csrf_token": csrf_token or ""},
        follow_redirects=False,
    )
    assert submitted.status_code == 303
    assert submitted.headers["location"] == "/waitlist"

    session_user = read_session_user(_session_request(app, client))
    assert session_user is not None
    assert session_user["user_id"] == user["user_id"]
    assert session_user["access_status"] == "pending"

    waitlist = client.get("/waitlist")
    assert waitlist.status_code == 200
    assert "Access requested" in waitlist.text
    assert "© 2025–2026 Roberto Hernan Voto. All rights reserved." in waitlist.text
    assert "__JOB_HUNTER_" not in waitlist.text


def test_pending_user_reaches_waitlist_and_cannot_reach_protected_page(
    isolated_db, monkeypatch
):
    _app, client, _user = _client_for_user(
        monkeypatch, isolated_db, "pending@example.com", "pending"
    )

    response = client.get("/docs", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/waitlist"

    waitlist = client.get("/waitlist")
    assert waitlist.status_code == 200
    assert "Access requested" in waitlist.text


def test_pending_user_cannot_access_protected_api_or_trigger_work(
    isolated_db, monkeypatch
):
    _app, client, _user = _client_for_user(
        monkeypatch, isolated_db, "pending-api@example.com", "pending"
    )

    assert client.get("/api/profile").status_code == 403
    assert client.post("/api/run", json={}).status_code == 403
    assert client.get("/api/llm-costs").status_code == 403


def test_approved_user_gets_normal_application_access(isolated_db, monkeypatch):
    _app, client, _user = _client_for_user(
        monkeypatch, isolated_db, "approved@example.com", "approved"
    )

    response = client.get("/docs")
    assert response.status_code == 200
    assert "docs" in response.json()


def test_blocked_user_loses_access_on_next_request_with_same_cookie(
    isolated_db, monkeypatch
):
    _app, client, user = _client_for_user(
        monkeypatch, isolated_db, "blocked-next-request@example.com", "approved"
    )
    assert client.get("/docs").status_code == 200

    update_user_access_status(user["user_id"], "blocked", ADMIN_EMAIL)
    session_user = read_session_user(_session_request(_app, client))
    assert session_user is not None
    assert session_user["access_status"] == "blocked"

    response = client.get("/docs", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/access-denied"


def test_blocked_user_reaches_access_denied_page(isolated_db, monkeypatch):
    _app, client, _user = _client_for_user(
        monkeypatch, isolated_db, "blocked-page@example.com", "blocked"
    )

    response = client.get("/access-denied")
    assert response.status_code == 200
    assert "Access unavailable" in response.text
    assert "© 2025–2026 Roberto Hernan Voto. All rights reserved." in response.text
    assert "__JOB_HUNTER_" not in response.text


def test_admin_is_always_approved_and_cannot_be_blocked(isolated_db, monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_ADMIN_EMAIL", ADMIN_EMAIL)
    admin = get_or_create_user(ADMIN_EMAIL, ADMIN_EMAIL)
    assert admin["role"] == "admin"
    assert admin["access_status"] == "approved"

    try:
        update_user_access_status(admin["user_id"], "blocked", ADMIN_EMAIL)
    except ValueError as exc:
        assert "administrator" in str(exc).lower()
    else:
        raise AssertionError("The configured administrator must not be blockable")


def test_user_access_management_is_admin_only_and_uses_csrf(
    isolated_db, monkeypatch
):
    _app, candidate_client, _candidate = _client_for_user(
        monkeypatch, isolated_db, "approved-candidate@example.com", "approved"
    )
    assert candidate_client.get("/api/admin/user-access").status_code == 401

    app, admin_client, admin = _client_for_user(monkeypatch, isolated_db, ADMIN_EMAIL, "approved")
    target = get_or_create_user("access-target@example.com", ADMIN_EMAIL)
    listing = admin_client.get("/api/admin/user-access")
    assert listing.status_code == 200
    assert target["user_id"] not in {item["user_id"] for item in listing.json()["users"]}

    request_user_access(target["user_id"])
    listing = admin_client.get("/api/admin/user-access")
    assert listing.status_code == 200
    listed_users = listing.json()["users"]
    assert listed_users[0]["user_id"] == target["user_id"]
    target_row = next(item for item in listed_users if item["user_id"] == target["user_id"])
    assert target_row["access_status"] == "pending"

    csrf_token = issue_csrf_token(_session_request(app, admin_client))
    updated = admin_client.patch(
        f"/api/admin/user-access/{target['user_id']}",
        json={"status": "approved"},
        headers={"X-CSRF-Token": csrf_token or ""},
    )
    assert updated.status_code == 200
    assert updated.json()["user"]["access_status"] == "approved"

    protected = admin_client.patch(
        f"/api/admin/user-access/{admin['user_id']}",
        json={"status": "blocked"},
        headers={"X-CSRF-Token": csrf_token or ""},
    )
    assert protected.status_code == 400


def test_anonymous_user_keeps_existing_authentication_behaviour(isolated_db, monkeypatch):
    monkeypatch.setenv("JOB_HUNTER_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("JOB_HUNTER_AUTH_SESSION_SECRET", SESSION_SECRET)
    monkeypatch.setenv("JOB_HUNTER_GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setenv("JOB_HUNTER_GOOGLE_CLIENT_SECRET", "test-secret")
    client = TestClient(create_app())

    page = client.get("/docs", follow_redirects=False)
    api = client.get("/api/profile")
    assert page.status_code == 302
    assert page.headers["location"] == "/login?next=%2Fdocs"
    assert api.status_code == 401
