"""Tests for logging source-scope helpers."""

from __future__ import annotations

import logging
from datetime import datetime

import pytest

from job_hunter_agent import logging_utils


@pytest.fixture
def bare_root_logger():
    """Strip the root logger's handlers for the test body (call phase).

    pytest's own logging plugin re-attaches a capture handler at the start of
    each test's call phase, after fixture setup runs — so handlers must be
    cleared from within the test body itself, not from fixture setup code.
    """
    root = logging.getLogger()
    restore: list[logging.Handler] = []

    def _clear() -> None:
        restore.extend(root.handlers)
        for handler in list(root.handlers):
            root.removeHandler(handler)

    original_level = root.level
    yield _clear
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in restore:
        root.addHandler(handler)
    root.setLevel(original_level)


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


def test_format_debug_marker_uses_debug_log_prefix():
    marker = logging_utils.format_debug_marker(
        "job_start",
        {"source": "LINKEDIN", "job_key": "linkedin:1"},
    )

    assert marker.startswith("[DEBUG_LOG][JOB_START]")
    assert "source  = LINKEDIN" in marker
    assert "job_key = linkedin:1" in marker


def test_render_board_final_block_uses_human_summary_layout():
    block = logging_utils.render_board_final_block(
        "apsjobs",
        seen=7,
        read=5,
        pages=1,
        kept=2,
        rejected=5,
    )

    assert "BOARD FINAL APSJOBS" in block
    assert "Seen: 7 | Read: 5 | Pages: 1 | Kept: 2 | Rejected: 5" in block
    assert block.count(logging_utils.LOG_BLOCK_SEPARATOR) == 2


def test_render_server_session_start_block_is_large_and_searchable():
    block = logging_utils.render_server_session_start_block(
        started_at=datetime(2026, 7, 30, 11, 45, 0),
        pid=4321,
        debug_mode=True,
        rebuild_on_startup=True,
        step_through=False,
    )

    assert "NEW SERVER SESSION STARTED" in block
    assert "Started at       : 2026-07-30 11:45:00" in block
    assert "PID              : 4321" in block
    assert "Debug mode       : ON (--debug)" in block
    assert "Startup rebuild  : YES (--rebuild)" in block
    assert "Step-through     : OFF" in block
    assert block.count(logging_utils.LOG_BLOCK_SEPARATOR) == 2


def test_setup_logging_writes_single_file_at_info_level_by_default(
    bare_root_logger, monkeypatch, tmp_path
):
    log_path = tmp_path / "server.log"
    monkeypatch.setattr("job_hunter_agent.paths.SERVER_LOG_PATH", log_path)

    bare_root_logger()
    logging_utils.setup_logging(debug=False)

    logger = logging.getLogger("job_hunter_agent.some_module")
    logger.info("curated info line")
    logger.debug("verbose debug line")

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "curated info line" in content
    assert "verbose debug line" not in content
    assert logging.getLogger().level == logging.INFO


def test_setup_logging_suppresses_transport_chatter_by_default(
    bare_root_logger, monkeypatch, tmp_path
):
    log_path = tmp_path / "server.log"
    monkeypatch.setattr("job_hunter_agent.paths.SERVER_LOG_PATH", log_path)

    transport_loggers = {
        "httpcore": logging.getLogger("httpcore"),
        "httpx": logging.getLogger("httpx"),
        "openai": logging.getLogger("openai"),
    }
    original_levels = {name: logger.level for name, logger in transport_loggers.items()}

    try:
        bare_root_logger()
        logging_utils.setup_logging(debug=False)

        transport_loggers["httpcore"].debug("TLS transport detail")
        transport_loggers["httpx"].info("HTTP Request: POST ... 200 OK")
        transport_loggers["openai"].debug("OpenAI request payload")
        transport_loggers["httpx"].warning("HTTP transport warning")

        for handler in logging.getLogger().handlers:
            handler.flush()

        content = log_path.read_text(encoding="utf-8")
        assert "TLS transport detail" not in content
        assert "HTTP Request: POST ... 200 OK" not in content
        assert "OpenAI request payload" not in content
        assert "HTTP transport warning" in content
    finally:
        for name, logger in transport_loggers.items():
            logger.setLevel(original_levels[name])


def test_setup_logging_suppresses_transport_chatter_even_in_debug_mode(
    bare_root_logger, monkeypatch, tmp_path
):
    log_path = tmp_path / "server.log"
    monkeypatch.setattr("job_hunter_agent.paths.SERVER_LOG_PATH", log_path)

    transport_loggers = {
        "httpcore": logging.getLogger("httpcore"),
        "httpx": logging.getLogger("httpx"),
        "openai": logging.getLogger("openai"),
    }
    original_levels = {name: logger.level for name, logger in transport_loggers.items()}

    try:
        bare_root_logger()
        logging_utils.setup_logging(debug=True)

        transport_loggers["httpcore"].debug("TLS transport detail")
        transport_loggers["httpx"].info("HTTP Request: POST ... 200 OK")
        transport_loggers["openai"].debug("OpenAI request payload")
        logging.getLogger("job_hunter_agent.some_module").debug(
            "Application debug detail"
        )

        for handler in logging.getLogger().handlers:
            handler.flush()

        content = log_path.read_text(encoding="utf-8")
        assert "TLS transport detail" not in content
        assert "HTTP Request: POST ... 200 OK" not in content
        assert "OpenAI request payload" not in content
        assert "Application debug detail" in content
        assert not log_path.with_name("server.debug.log").exists()
    finally:
        for name, logger in transport_loggers.items():
            logger.setLevel(original_levels[name])


def test_setup_logging_debug_true_shows_debug_lines(bare_root_logger, monkeypatch, tmp_path):
    log_path = tmp_path / "server.log"
    monkeypatch.setattr("job_hunter_agent.paths.SERVER_LOG_PATH", log_path)

    bare_root_logger()
    logging_utils.setup_logging(debug=True)

    logger = logging.getLogger("job_hunter_agent.some_module")
    logger.debug("verbose debug line")

    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "verbose debug line" in content
    assert logging.getLogger().level == logging.DEBUG


def test_setup_logging_is_noop_when_handlers_already_configured(
    bare_root_logger, monkeypatch, tmp_path
):
    log_path = tmp_path / "server.log"
    monkeypatch.setattr("job_hunter_agent.paths.SERVER_LOG_PATH", log_path)

    bare_root_logger()
    sentinel_handler = logging.NullHandler()
    logging.getLogger().addHandler(sentinel_handler)

    logging_utils.setup_logging(debug=True)

    assert logging.getLogger().handlers == [sentinel_handler]
    assert not log_path.exists()
