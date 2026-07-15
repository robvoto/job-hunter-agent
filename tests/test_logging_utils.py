"""Tests for logging source-scope helpers."""

from __future__ import annotations

import logging

from job_hunter_agent import logging_utils


def test_source_scope_filter_adds_prefix_when_scope_is_bound():
    record = logging.LogRecord(
        name="job_hunter_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello from worker",
        args=(),
        exc_info=None,
    )
    scope_filter = logging_utils.SourceScopeFilter()
    token = logging_utils.set_log_source_scope("seek")

    try:
        assert scope_filter.filter(record) is True
    finally:
        logging_utils.reset_log_source_scope(token)

    assert record.source_scope == "SEEK"
    assert record.source_scope_prefix == "[SEEK] "


def test_source_scope_filter_avoids_duplicate_prefix_for_already_tagged_message():
    record = logging.LogRecord(
        name="job_hunter_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="[SEEK] already tagged",
        args=(),
        exc_info=None,
    )
    scope_filter = logging_utils.SourceScopeFilter()
    token = logging_utils.set_log_source_scope("seek")

    try:
        assert scope_filter.filter(record) is True
    finally:
        logging_utils.reset_log_source_scope(token)

    assert record.source_scope == "SEEK"
    assert record.source_scope_prefix == ""


def test_human_readable_log_filter_suppresses_debug_and_duplicate_result_lines():
    human_filter = logging_utils.HumanReadableLogFilter()

    debug_record = logging.LogRecord(
        name="job_hunter_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="[LLM][COST] purpose=fit_review",
        args=(),
        exc_info=None,
    )
    duplicate_record = logging.LogRecord(
        name="job_hunter_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="[APSJOBS] REJECTED (llm title) [LLM_TITLE_NOT_TARGET] Example role",
        args=(),
        exc_info=None,
    )
    human_record = logging.LogRecord(
        name="job_hunter_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="JOB   Senior Business Analyst @ Example Co",
        args=(),
        exc_info=None,
    )
    title_stage_record = logging.LogRecord(
        name="job_hunter_agent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="[APSJOBS]   [APSJOBS] title: title not in your target roles — needs title review",
        args=(),
        exc_info=None,
    )

    assert human_filter.filter(debug_record) is False
    assert human_filter.filter(duplicate_record) is False
    assert human_filter.filter(title_stage_record) is False
    assert human_filter.filter(human_record) is True


def test_format_debug_marker_uses_debug_log_prefix():
    marker = logging_utils.format_debug_marker(
        "job_start",
        {"source": "LINKEDIN", "job_key": "linkedin:1"},
    )

    assert marker.startswith("[DEBUG_LOG][JOB_START]")
    assert "source  = LINKEDIN" in marker
    assert "job_key = linkedin:1" in marker
