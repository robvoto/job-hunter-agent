"""Tests for local-only history integration override."""

from job_hunter_agent import global_settings


def test_local_runtime_history_override_is_applied(monkeypatch, tmp_path):
    section_key = "candidate_application_history"
    override_path = tmp_path / "local_history.json"
    override_path.write_text(
        """
        {
          "candidate_application_history": {
            "spreadsheet_id": "local-sheet-id",
            "tab_name": "Local_Tab"
          }
        }
        """,
        encoding="utf-8",
    )

    monkeypatch.setattr(global_settings, "_LOCAL_CANDIDATE_APPLICATION_HISTORY_OVERRIDE_PATH", override_path)
    monkeypatch.setattr(
        global_settings,
        "load_global_settings",
        lambda: {
            section_key: {
                "enabled": True,
                "source_type": "local_runtime_json",
                "sync_before_run": False,
                "spreadsheet_id": "",
                "tab_name": "",
                "required_headers": ["Status"],
                "content_max_chars": 4000,
            }
        },
    )

    settings = global_settings.get_candidate_application_history_settings()

    assert settings["enabled"] is True
    assert settings["spreadsheet_id"] == "local-sheet-id"
    assert settings["tab_name"] == "Local_Tab"
    assert settings["source_type"] == "local_runtime_json"
