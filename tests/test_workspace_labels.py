"""Tests for workspace labels."""

from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent import workspace_renderer


def test_workspace_job_requirements_summary_label_comes_from_ui_labels():
    labels = load_ui_labels()["workspace_card_labels"]

    assert labels["job_requirements_summary"] == "Job requirements checked against your profile"
    assert labels["risk_panel_summary"] == "Checks before applying"
    assert (
        workspace_renderer._workspace_label(
            "workspace_card_labels",
            "job_requirements_summary",
            "Requirements",
        )
        == "Job requirements checked against your profile"
    )
