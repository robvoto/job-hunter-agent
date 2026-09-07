"""Helpers for logging utils."""

from __future__ import annotations

import contextvars
import logging
from datetime import datetime

LOG_BLOCK_SEPARATOR = "-" * 80

SERVER_LOG_MAX_BYTES = 10 * 1024 * 1024
SERVER_LOG_BACKUP_COUNT = 5

_DEPENDENCY_LOGGERS = ("httpcore", "httpx", "openai")

_LOG_SOURCE_SCOPE: contextvars.ContextVar[str] = contextvars.ContextVar(
    "job_hunter_log_source_scope",
    default="",
)


def set_log_source_scope(source: str) -> contextvars.Token[str]:
    return _LOG_SOURCE_SCOPE.set(str(source or "").strip().upper())


def reset_log_source_scope(token: contextvars.Token[str]) -> None:
    _LOG_SOURCE_SCOPE.reset(token)


def get_log_source_scope() -> str:
    return _LOG_SOURCE_SCOPE.get("")


def _normalize_bracketed_source(value: str) -> str:
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


class SourceScopeFilter(logging.Filter):
    """Adds a source prefix for records emitted inside a source worker scope."""

    def filter(self, record: logging.LogRecord) -> bool:
        source_scope = get_log_source_scope()
        prefix = ""
        if source_scope:
            message = record.getMessage()
            prefix = f"[{source_scope}] "
            if message.startswith("["):
                leading = message.split("]", 1)[0].lstrip("[")
                if _normalize_bracketed_source(leading) == _normalize_bracketed_source(source_scope):
                    prefix = ""
        record.source_scope = source_scope
        record.source_scope_prefix = prefix
        return True


class CuratedLogFilter(logging.Filter):
    """Drop dependency wire-trace noise (raw HTTP headers, connection
    open/close events, retry bookkeeping) that isn't actionable at any
    level. Real problems from these libraries still surface as WARNING+.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        is_dependency_record = any(
            record.name == logger_name or record.name.startswith(f"{logger_name}.")
            for logger_name in _DEPENDENCY_LOGGERS
        )
        return not (is_dependency_record and record.levelno < logging.WARNING)


def format_log_block(title: str, fields: dict[str, object]) -> str:
    if not fields:
        return f"[{title}]"
    width = max(len(k) for k in fields)
    lines = [f"[{title}]"]
    for key, value in fields.items():
        lines.append(f"  {key:<{width}} = {value}")
    return "\n".join(lines)


def format_debug_marker(marker: str, fields: dict[str, object]) -> str:
    """Structured debug-only marker for the server log."""

    normalized_marker = str(marker or "").strip().upper() or "EVENT"
    return format_log_block(f"DEBUG_LOG][{normalized_marker}", fields)


def render_board_final_block(
    source_name: str,
    *,
    seen: int,
    read: int,
    pages: int,
    kept: int,
    rejected: int,
    health: str | None = None,
) -> str:
    source_label = str(source_name or "UNKNOWN").strip().upper() or "UNKNOWN"
    health_line = f"Health: {health}\n" if health else ""
    return (
        f"\n{LOG_BLOCK_SEPARATOR}\n"
        f"BOARD FINAL {source_label}\n"
        f"Seen: {int(seen)} | Read: {int(read)} | Pages: {int(pages)} | "
        f"Kept: {int(kept)} | Rejected: {int(rejected)}\n"
        f"{health_line}"
        f"{LOG_BLOCK_SEPARATOR}"
    )


def render_server_session_start_block(
    *,
    started_at: datetime,
    pid: int,
    parent_pid: int,
    invocation: str,
    debug_mode: bool,
    rebuild_on_startup: bool,
    step_through: bool,
) -> str:
    started_at_label = started_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    return (
        f"\n{LOG_BLOCK_SEPARATOR}\n"
        f"NEW SERVER SESSION STARTED\n"
        f"Started at       : {started_at_label}\n"
        f"PID              : {int(pid)}\n"
        f"Parent PID       : {int(parent_pid)}\n"
        f"Invocation       : {invocation}\n"
        f"Debug mode       : {'ON (--debug)' if debug_mode else 'OFF'}\n"
        f"Startup rebuild  : {'YES (--rebuild)' if rebuild_on_startup else 'NO'}\n"
        f"Step-through     : {'ON (--step)' if step_through else 'OFF'}\n"
        f"{LOG_BLOCK_SEPARATOR}"
    )


def install_log_handler_filters() -> None:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(SourceScopeFilter())


def _configure_dependency_logging() -> None:
    """Dependency wire-trace noise is never useful, in or out of --debug."""

    for logger_name in _DEPENDENCY_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def setup_logging(*, debug: bool = False) -> None:
    """Configure the root logger: one console handler + one file handler.

    Output goes to the console and ``output/server.log`` — a single file,
    always. At the default INFO level this shows curated, human-facing
    lines (per-job results, run summaries, session banners, settings/auth
    changes). Passing ``debug=True`` raises the level to DEBUG, adding
    detailed application trace (LLM calls, pipeline stage-by-stage detail,
    scraper card-by-card detail). Dependency wire-trace noise (raw HTTP
    headers, connection internals from httpx/httpcore/openai/urllib3) is
    dropped at both levels — it's never actionable and clutters the file.

    No-op if handlers are already configured (e.g. running inside tests).
    """
    import logging.config

    from job_hunter_agent.paths import SERVER_LOG_PATH

    if logging.getLogger().handlers:
        return

    SERVER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    level = "DEBUG" if debug else "INFO"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"curated": {"()": CuratedLogFilter}},
            "formatters": {
                "console": {
                    "format": "%(source_scope_prefix)s%(message)s",
                },
                "file": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(source_scope_prefix)s%(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": level,
                    "formatter": "console",
                    "filters": ["curated"],
                    "stream": "ext://sys.__stdout__",
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "level": level,
                    "formatter": "file",
                    "filters": ["curated"],
                    "filename": str(SERVER_LOG_PATH),
                    "encoding": "utf-8",
                    "maxBytes": SERVER_LOG_MAX_BYTES,
                    "backupCount": SERVER_LOG_BACKUP_COUNT,
                },
            },
            "root": {
                "level": level,
                "handlers": ["console", "file"],
            },
        }
    )
    _configure_dependency_logging()
    install_log_handler_filters()
