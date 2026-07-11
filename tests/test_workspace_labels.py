"""Tests for workspace labels."""

from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent import workspace_renderer


def test_workspace_job_requirements_summary_label_comes_from_ui_labels():
    labels = load_ui_labels()["workspace_card_labels"]

    assert labels["full_description_summary"] == "Full job description"
    assert labels["job_requirements_summary"] == "Job Requirements"
    assert labels["risk_panel_summary"] == "Checks before applying"
    assert labels["debug_score_breakdown_summary"] == "Score breakdown"
    assert labels["debug_llm_time_label"] == "LLM time"
    assert labels["debug_llm_cost_label"] == "LLM cost"
    assert labels["debug_llm_input_tokens_label"] == "Input tokens"
    assert labels["debug_llm_output_tokens_label"] == "Output tokens"
    assert labels["debug_reviewed_signal_summary"] == "Reviewed signal evidence"
    assert (
        workspace_renderer._workspace_label(
            "workspace_card_labels",
            "job_requirements_summary",
            "Requirements",
        )
        == "Job Requirements"
    )
