"""Tests for settings change logging."""

from __future__ import annotations

import logging

from job_hunter_agent import global_settings, profile_store, user_settings


def _messages(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def test_save_global_settings_logs_before_and_after(isolated_db, caplog):
    global_settings.load_global_settings.cache_clear()

    with caplog.at_level(logging.INFO):
        global_settings.save_global_settings(
            {"search_settings": {"date_range_days": 6}},
        )

    messages = _messages(caplog)
    assert any("[GLOBAL_SETTINGS] settings changed" in message for message in messages)
    assert any("search_settings.date_range_days: 3 -> 6" in message for message in messages)


def test_save_profile_logs_before_and_after(isolated_db, caplog):
    with caplog.at_level(logging.INFO):
        profile_store.save_profile(
            {
                "search_settings": {
                    "keywords": "Business Analyst",
                    "locations": ["Sydney"],
                    "date_range_days": 5,
                },
            }
        )

    messages = _messages(caplog)
    assert any("[PROFILE_SETTINGS] settings changed" in message for message in messages)
    assert any("search_settings.date_range_days: 3 -> 5" in message for message in messages)


def test_save_user_settings_logs_before_and_after_and_redacts_secrets(
    isolated_db, caplog
):
    with caplog.at_level(logging.INFO):
        user_settings.save_user_settings(
            None,
            {
                "workspace": {"minimum_score": 72},
                "telegram": {
                    "bot_token": "super-secret-token",
                    "enabled": True,
                },
            },
        )

    messages = _messages(caplog)
    assert any("[USER_SETTINGS] settings changed" in message for message in messages)
    assert any("workspace.minimum_score: 30 -> 72" in message for message in messages)
    assert any("telegram.bot_token: <redacted> -> <redacted>" in message for message in messages)


def test_save_user_settings_preserves_existing_fields_on_partial_update(isolated_db):
    user_settings.save_user_settings(
        None,
        {
            "workspace": {"minimum_score": 55},
            "telegram": {"enabled": False},
        },
    )

    user_settings.save_user_settings(None, {"telegram": {"enabled": True}})

    saved = user_settings.load_user_settings(None, create_if_missing=False)
    assert saved["workspace"]["minimum_score"] == 55
    assert saved["telegram"]["enabled"] is True


def test_save_user_settings_no_change_log_identifies_unchanged_scope(isolated_db, caplog):
    with caplog.at_level(logging.INFO):
        user_settings.save_user_settings(None, {})

    messages = _messages(caplog)
    assert any(
        "[USER_SETTINGS] settings save completed; no effective changes in this scope" in message
        for message in messages
    )
