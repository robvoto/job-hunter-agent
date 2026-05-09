"""FastAPI ASGI application for the local dashboard and settings server.

Route handlers live under ``job_hunter_agent.routes``; this module wires the app,
exception handlers, and CORS-style middleware.

Entry point:
    python -m job_hunter_agent.fastapi_app [--debug] [--rebuild]

Flags:
    --debug     Enable debug mode: verbose logging, exposes test-only endpoints,
                injects debug banner into dashboard templates.
    --rebuild   Rebuild the dashboard HTML from last saved run on startup.
                Can be combined with --debug.
"""

from __future__ import annotations

import logging
import logging.config
import sys

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from job_hunter_agent.auth import configure_auth, read_session_username, verify_csrf_token
from job_hunter_agent.routes import register_routes
from job_hunter_agent.routes.responses import json_response
from job_hunter_agent.paths import OUTPUT_DIR, SERVER_LOG_PATH


class _LineLoggingStream:
    def __init__(self, logger: logging.Logger, level: int) -> None:
        self._logger = logger
        self._level = level
        self._buffer = ""

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._logger.log(self._level, line.rstrip("\r"))
        return len(text)

    def flush(self) -> None:
        line = self._buffer.strip("\r")
        self._buffer = ""
        if line.strip():
            self._logger.log(self._level, line)

    def isatty(self) -> bool:
        return False


def _configure_server_logging() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": "%(asctime)s %(levelname)s %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "level": "INFO",
                "formatter": "standard",
                "stream": "ext://sys.__stdout__",
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
        "loggers": {
            "uvicorn": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn.error": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False,
            },
            "uvicorn.access": {
                "level": "INFO",
                "handlers": ["console", "file"],
                "propagate": False,
            },
        },
    }
    logging.config.dictConfig(logging_config)

    app_logger = logging.getLogger("job_hunter_agent.app")
    sys.stdout = _LineLoggingStream(app_logger, logging.INFO)
    sys.stderr = _LineLoggingStream(app_logger, logging.ERROR)


def create_app() -> FastAPI:
    # Leave `/docs` free for the project's markdown-docs JSON API (not OpenAPI Swagger).
    app = FastAPI(docs_url="/swagger-ui", redoc_url="/swagger-redoc")
    configure_auth(app)

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http_exc(request: Request, exc: StarletteHTTPException):  # type: ignore[no-untyped-def]
        if exc.status_code == 404:
            return json_response({"error": "Not found"}, 404)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": str(exc.detail)},
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, PUT, PATCH, POST, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            },
        )

    @app.middleware("http")
    async def cors_options(request, call_next):  # type: ignore[no-untyped-def]
        if request.method == "OPTIONS":
            return JSONResponse(
                content={"ok": True},
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, PUT, PATCH, POST, DELETE, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                },
            )
        response = await call_next(request)
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        response.headers.setdefault(
            "Access-Control-Allow-Methods",
            "GET, PUT, PATCH, POST, DELETE, OPTIONS",
        )
        response.headers.setdefault("Access-Control-Allow-Headers", "Content-Type")
        return response

    @app.middleware("http")
    async def csrf_protection(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        if request.url.path == "/api/debug/browser-log":
            return await call_next(request)
        if read_session_username(request) is None:
            return await call_next(request)
        if not verify_csrf_token(request, request.headers.get("x-csrf-token")):
            return json_response({"error": "CSRF token missing or invalid"}, 403)
        return await call_next(request)

    register_routes(app)
    return app


if __name__ == "__main__":
    import argparse

    import uvicorn

    from job_hunter_agent import server_helpers as srv
    from job_hunter_agent.config import SERVER_HOST as HOST, SERVER_PORT as PORT

    parser = argparse.ArgumentParser(description="Job Hunter Agent local server")
    parser.add_argument(
        "--debug",
        action="store_true",
        dest="debug",
        help="Enable debug mode: verbose logging and test-only endpoints.",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the dashboard from the last saved run before starting.",
    )
    args = parser.parse_args()

    _configure_server_logging()

    if args.rebuild or args.debug:
        srv._rebuild_dashboard_on_startup()

    print(f"Local server running at http://{HOST}:{PORT}")
    print(f"Debug mode:  {'ON (--debug)' if srv.DEBUG_MODE else 'OFF'}")
    print(f"Workspace:   http://{HOST}:{PORT}/")
    print(f"Settings:    http://{HOST}:{PORT}/settings")
    print(f"Onboarding:  http://{HOST}:{PORT}/start")
    print(f"Docs API:    http://{HOST}:{PORT}/docs")
    print(f"Swagger UI:  http://{HOST}:{PORT}/swagger-ui")

    uvicorn.run(
        create_app(),
        host=HOST,
        port=PORT,
        log_level="debug" if srv.DEBUG_MODE else "info",
        access_log=srv.DEBUG_MODE,
        log_config=None,
    )
