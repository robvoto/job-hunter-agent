"""Helpers for logging utils."""

from __future__ import annotations

import contextvars
import logging
import re

HUMAN_LOGGER_NAME = "job_hunter.human"
TECHNICAL_LOGGER_NAME = "job_hunter.technical"
HUMAN_LOG_SEPARATOR = "-" * 80

# Console-only: fragments of raw per-stage pipeline trace that duplicate the
# human-readable per-job summary block. Still written to server.log at INFO
# for post-run debugging — only the terminal display is suppressed.
CONSOLE_SUPPRESSED_FRAGMENTS = (
    "[CAPABILITY_SCORING][BELOW_THRESHOLD]",
    "PIPELINE][ONET_TITLE_CLASSIFY",
    "PIPELINE][ONET_DECISION",
    "PIPELINE][LLM_TITLE_JUDGMENT",
    "PIPELINE][DETAIL_FETCH_START",
    "PIPELINE][DETAIL_FETCH_DONE",
    "PIPELINE][FINAL_DECISION",
    "WORK_TYPE][INFERENCE",
    "[REVIEW][PAYLOAD]",
    "[LLM][MODEL]",
    "[LLM][REQUEST]",
    "[CAPABILITY_SUPPORT]",
)

HUMAN_LOG_SUPPRESSED_FRAGMENTS = CONSOLE_SUPPRESSED_FRAGMENTS + (
    "[DEBUG_LOG][",
    " title: ",
    "✗ REJECTED — title filtered out",
    "✗ REJECTED before reading —",
    " llm fit_review: elapsed=",
    "HTTP Request: POST https://api.openai.com",
    "HTTP Request: GET https://api.openai.com",
    "[LLM][COST]",
    "[LLM][RESULT]",
    "[LLM][CACHE]",
    "[LLM][WARN]",
    "[LLM][FAIL]",
    "[DEBUG][",
    "[RUN_SUMMARY]",
    "[RUN][SOURCE_FINAL_STATS",
    "[Pool]",
    "Saved ",
    "workspace_visible=",
    "The previous workspace state was preserved.",
    "Workspace results preserved at",
)

_DUPLICATE_JOB_RESULT_RE = re.compile(
    r"^\[[^\]]+\]\s+(REJECTED\s+\(|KEPT\s+).+",
    re.IGNORECASE,
)

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


class ConsoleNoiseFilter(logging.Filter):
    """Console-only filter: hides verbose per-stage pipeline trace.

    These lines are still written to the file log at INFO level for post-run
    analysis. Only the terminal display is suppressed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(fragment in msg for fragment in CONSOLE_SUPPRESSED_FRAGMENTS)


class HumanReadableLogFilter(logging.Filter):
    """Keep server.log and console focused on human-readable job/run summaries."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        if any(fragment in msg for fragment in HUMAN_LOG_SUPPRESSED_FRAGMENTS):
            return False
        if _DUPLICATE_JOB_RESULT_RE.match(msg.strip()):
            return False
        return True


def format_log_block(title: str, fields: dict[str, object]) -> str:
    if not fields:
        return f"[{title}]"
    width = max(len(k) for k in fields)
    lines = [f"[{title}]"]
    for key, value in fields.items():
        lines.append(f"  {key:<{width}} = {value}")
    return "\n".join(lines)


def format_debug_marker(marker: str, fields: dict[str, object]) -> str:
    """Structured debug-only marker for server-debug.log."""

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
) -> str:
    source_label = str(source_name or "UNKNOWN").strip().upper() or "UNKNOWN"
    return (
        f"\n{HUMAN_LOG_SEPARATOR}\n"
        f"BOARD FINAL {source_label}\n"
        f"Seen: {int(seen)} | Read: {int(read)} | Pages: {int(pages)} | "
        f"Kept: {int(kept)} | Rejected: {int(rejected)}\n"
        f"{HUMAN_LOG_SEPARATOR}"
    )


def get_human_logger() -> logging.Logger:
    return logging.getLogger(HUMAN_LOGGER_NAME)


def install_log_handler_filters() -> None:
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.addFilter(SourceScopeFilter())


def setup_cli_logging() -> None:
    """Configure root logger for CLI runs.

    Human-readable output goes to console + ``output/server.log``.
    Full technical output goes to ``output/server-debug.log``.

    Mirrors the FastAPI logging config so CLI and server produce identical output.
    No-op when handlers are already configured (e.g. running inside the server).
    """
    import logging.config

    from job_hunter_agent.paths import SERVER_DEBUG_LOG_PATH, SERVER_LOG_PATH

    if logging.getLogger().handlers:
        return

    SERVER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "human": {
                    "format": "%(message)s",
                },
                "standard": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(source_scope_prefix)s%(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                "human_console": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "formatter": "human",
                    "stream": "ext://sys.stdout",
                },
                "human_file": {
                    "class": "logging.FileHandler",
                    "level": "INFO",
                    "formatter": "human",
                    "filename": str(SERVER_LOG_PATH),
                    "encoding": "utf-8",
                },
                "debug_file": {
                    "class": "logging.FileHandler",
                    "level": "INFO",
                    "formatter": "standard",
                    "filename": str(SERVER_DEBUG_LOG_PATH),
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["debug_file"],
            },
            "loggers": {
                HUMAN_LOGGER_NAME: {
                    "level": "INFO",
                    "handlers": ["human_console", "human_file"],
                    "propagate": False,
                },
            },
        }
    )
    install_log_handler_filters()
