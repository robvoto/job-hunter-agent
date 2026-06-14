"""Tests for work mode extraction."""

from job_hunter_agent.work_mode_extraction import display_work_mode_label


def test_display_work_mode_label_shows_canonical_labels():
    assert display_work_mode_label({"work_mode": "remote"}) == "Remote"
    assert display_work_mode_label({"work_mode": "Hybrid"}) == "Hybrid"
    assert display_work_mode_label({"work_mode": "On-site"}) == "On-site"


def test_display_work_mode_label_hides_unknown_values():
    assert display_work_mode_label({"work_mode": "unknown"}) == ""
    assert display_work_mode_label({"work_mode": ""}) == ""
