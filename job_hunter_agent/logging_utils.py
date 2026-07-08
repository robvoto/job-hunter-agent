"""Helpers for logging utils."""

from __future__ import annotations

import logging

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


class ConsoleNoiseFilter(logging.Filter):
    """Console-only filter: hides verbose per-stage pipeline trace.

    These lines are still written to the file log at INFO level for post-run
    analysis. Only the terminal display is suppressed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(fragment in msg for fragment in CONSOLE_SUPPRESSED_FRAGMENTS)


def format_log_block(title: str, fields: dict[str, object]) -> str:
    if not fields:
        return f"[{title}]"
    width = max(len(k) for k in fields)
    lines = [f"[{title}]"]
    for key, value in fields.items():
        lines.append(f"  {key:<{width}} = {value}")
    return "\n".join(lines)


def setup_cli_logging() -> None:
    """Configure root logger for CLI runs: console (stdout) + server.log file.

    Mirrors the FastAPI logging config so CLI and server produce identical output.
    No-op when handlers are already configured (e.g. running inside the server).
    """
    import logging.config

    from job_hunter_agent.paths import SERVER_LOG_PATH

    if logging.getLogger().handlers:
        return

    SERVER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
                "console": {
                    "format": "%(asctime)s  %(message)s",
                    "datefmt": "%H:%M:%S",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "formatter": "console",
                    "stream": "ext://sys.stdout",
                },
                "file": {
                    "class": "logging.FileHandler",
                    "level": "INFO",
                    "formatter": "standard",
                    "filename": str(SERVER_LOG_PATH),
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["console", "file"],
            },
        }
    )

    console_handler = next(
        (
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        ),
        None,
    )
    if console_handler:
        console_handler.addFilter(ConsoleNoiseFilter())
