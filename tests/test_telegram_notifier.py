from __future__ import annotations

import logging

import job_hunter_agent.notifiers.telegram_notifier as telegram_notifier


def test_sync_telegram_subscribers_routes_commands(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="job_hunter_agent.notifiers.telegram_notifier")
    sent_messages: list[dict] = []

    updates = [
        {
            "update_id": 1,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "from": {"username": "tester", "is_bot": False},
                "text": "/start",
            },
        },
        {
            "update_id": 2,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "from": {"username": "tester", "is_bot": False},
                "text": "/filters",
            },
        },
        {
            "update_id": 3,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "from": {"username": "tester", "is_bot": False},
                "text": "/summary",
            },
        },
        {
            "update_id": 4,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "from": {"username": "tester", "is_bot": False},
                "text": "/export fresh",
            },
        },
        {
            "update_id": 5,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "from": {"username": "tester", "is_bot": False},
                "text": "/run",
            },
        },
    ]

    def fake_api_request(bot_token, method, payload=None, timeout=30):  # noqa: ANN001
        if method == "getMe":
            return {"ok": True, "result": {"username": "jobbot"}}
        if method == "getUpdates":
            return {"ok": True, "result": updates}
        if method == "sendMessage":
            sent_messages.append(dict(payload or {}))
            return {"ok": True, "result": {}}
        raise AssertionError(method)

    monkeypatch.setattr(telegram_notifier, "_telegram_api_request", fake_api_request)
    monkeypatch.setattr(telegram_notifier, "_build_latest_summary_text", lambda: "LATEST SUMMARY")
    monkeypatch.setattr(telegram_notifier, "_build_search_settings_text", lambda: "SEARCH SETTINGS")
    monkeypatch.setattr(
        telegram_notifier,
        "export_workspace_jobs",
        lambda mode="merge": {"job_count": 4, "json_path": "/tmp/jobs.json", "mode": mode},
    )
    monkeypatch.setattr(
        telegram_notifier,
        "_start_default_search",
        lambda user_id: f"SEARCH STARTED {user_id}",
    )

    settings = {"bot_token": "token", "last_update_id": 0, "subscribers": []}

    result = telegram_notifier.sync_telegram_subscribers(settings, user_id="user-1")

    assert result["total_subscribers"] == 1
    assert result["commands_processed"] == 5
    assert settings["last_update_id"] == 5
    assert result["subscribers"][0]["chat_id"] == "123"
    assert [payload["text"] for payload in sent_messages] == [
        telegram_notifier._telegram_start_text(),
        "SEARCH SETTINGS",
        "LATEST SUMMARY",
        "/export only writes the current workspace to the cowork handoff file.\nIt does not run a new search.\nUse /run to fetch fresh jobs, then /export to hand them off.",
        "SEARCH STARTED user-1",
    ]
    assert "command requested: /export via bot @jobbot by @tester chat_id=123" in caplog.text
