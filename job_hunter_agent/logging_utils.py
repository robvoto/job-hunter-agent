"""Helpers for logging utils."""

from __future__ import annotations


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
    import logging
    import logging.config
    from job_hunter_agent.paths import SERVER_LOG_PATH

    if logging.getLogger().handlers:
        return

    SERVER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig({
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
    })
