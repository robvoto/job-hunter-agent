"""Tests for workspace labels."""

import pytest

from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent import workspace_renderer


def test_workspace_job_requirements_summary_label_comes_from_ui_labels():
    labels = load_ui_labels()["workspace_card_labels"]
    page_labels = load_ui_labels()["workspace_page_labels"]

    assert labels["full_description_summary"] == "Full job description"
    assert labels["job_requirements_summary"] == "Job Requirements"
    assert labels["risk_panel_summary"] == "Checks before applying"
    assert labels["debug_score_breakdown_summary"] == "Score breakdown"
    assert labels["debug_llm_time_label"] == "LLM time"
    # LLM cost/token labels are shared with the last-run summary, sourced from
    # workspace_page_labels (see _workspace_label calls in workspace_renderer.py).
    assert page_labels["last_run_llm_cost_label"] == "LLM cost"
    assert page_labels["last_run_input_tokens_label"] == "Input tokens"
    assert page_labels["last_run_output_tokens_label"] == "Output tokens"
    assert labels["debug_reviewed_signal_summary"] == "Reviewed signal evidence"
    assert (
        workspace_renderer._workspace_label(
            "workspace_card_labels",
            "job_requirements_summary",
        )
        == "Job Requirements"
    )


def test_workspace_archive_and_alert_labels_come_from_ui_labels():
    labels = load_ui_labels()

    workspace_page_labels = labels["workspace_page_labels"]
    settings_alerts_labels = labels["settings_alerts_labels"]

    assert workspace_page_labels["archive_label"] == "Saved from earlier run"
    assert workspace_page_labels["potential_jobs_empty_state"].startswith(
        "No shortlist matches right now."
    )
    assert workspace_renderer.ARCHIVE_LABEL == "Saved from earlier run"
    assert settings_alerts_labels["section_title"] == "Messaging"
    assert settings_alerts_labels["section_copy"] == (
        "Connect Telegram alerts. Admins can also choose the model used for fit decisions."
    )
    assert settings_alerts_labels["telegram_disable_link_preview_label"] == "Hide link preview"
    assert settings_alerts_labels["telegram_disable_link_preview_help"] == (
        "When on, Telegram sends workspace links without a preview card."
    )


def test_workspace_label_raises_when_label_is_missing(monkeypatch):
    monkeypatch.setattr(
        workspace_renderer,
        "_workspace_ui_labels",
        lambda: {"workspace_card_labels": {}},
    )

    with pytest.raises(ValueError, match=r"missing workspace_card_labels\.job_requirements_summary"):
        workspace_renderer._workspace_label(
            "workspace_card_labels",
            "job_requirements_summary",
        )
