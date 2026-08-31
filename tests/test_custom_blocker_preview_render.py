"""Rendering tests for workspace_renderer.render_custom_blocker_preview.

Covers the rejected ("no_match") state: the copy must tell the user what to
do next, and the debug block must not render empty rows for the resolution
fields a rejected term leaves blank.
"""

from job_hunter_agent.profile_gaps import CUSTOM_BLOCKER_REASON_NO_MATCH
from job_hunter_agent.workspace_renderer import render_custom_blocker_preview


def _no_match_resolution():
    return {
        "ok": False,
        "reason_code": CUSTOM_BLOCKER_REASON_NO_MATCH,
        "raw_input": "intern",
        "canonical_requirement": "",
        "requirement_type": "",
        "importance": "",
        "matched_job_text": "",
    }


def test_no_match_copy_is_actionable():
    html = render_custom_blocker_preview(_no_match_resolution(), debug_mode=False)
    assert "custom-blocker-preview--rejected" in html
    # Points the user at the suggested-terms chips rather than dead-ending.
    assert "suggested required terms" in html.lower()


def test_no_match_debug_omits_blank_rows():
    html = render_custom_blocker_preview(_no_match_resolution(), debug_mode=True)
    # Populated rows stay.
    assert "Raw input" in html
    assert "Validation result" in html
    assert "Profile field" in html
    # Rows that carry no value on a rejected term are dropped.
    assert "Resolved canonical requirement" not in html
    assert "Matched job evidence" not in html
    assert "Exact persisted value" not in html


def test_resolved_debug_keeps_all_rows():
    resolution = {
        "ok": True,
        "reason_code": "resolved",
        "raw_input": "salesforce",
        "canonical_requirement": "Salesforce",
        "requirement_type": "capability",
        "importance": "required",
        "matched_job_text": "Salesforce experience",
    }
    html = render_custom_blocker_preview(resolution, debug_mode=True)
    assert "Resolved canonical requirement" in html
    assert "Matched job evidence" in html
    assert "Exact persisted value" in html
