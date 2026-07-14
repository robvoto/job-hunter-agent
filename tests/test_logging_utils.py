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
