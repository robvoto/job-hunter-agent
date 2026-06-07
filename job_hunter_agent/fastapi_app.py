"""FastAPI ASGI application for the local workspace and settings server.

Route handlers live under ``job_hunter_agent.routes``; this module wires the app,
exception handlers, and CORS-style middleware.

Entry point:
    python -m job_hunter_agent.fastapi_app [--debug] [--rebuild]

Flags:
    --debug     Enable debug mode: verbose logging, exposes test-only endpoints,
                injects debug banner into workspace templates.
    --rebuild   Rebuild the workspace HTML from last saved run on startup.
                Can be combined with --debug.

CORS:
    In production, set JOB_HUNTER_CORS_ALLOWED_ORIGINS to a comma-separated list
    of allowed origins (e.g. https://example.com). Requests from unlisted origins
    receive no CORS headers and a WARN is logged.
"""

from __future__ import annotations

import logging
import logging.config
import os
import sys

from urllib.parse import parse_qsl, quote, urlsplit

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from job_hunter_agent import config as app_config
from job_hunter_agent.auth import (
    OPEN_PATHS,
    configure_auth,
    read_session_user,
    verify_csrf_token,
)
from job_hunter_agent.config import (
    JOB_HUNTER_BASE_URL,
    LOGIN_PATH,
    LOGOUT_PATH,
    ONBOARDING_PATH,
    ONBOARDING_DEBUG_ALIAS_PATH,
)
from job_hunter_agent.user_context import set_user_id
from job_hunter_agent.paths import OUTPUT_DIR, SERVER_LOG_PATH

_logger = logging.getLogger(__name__)

_CORS_METHODS = "GET, PUT, PATCH, POST, DELETE, OPTIONS"
_CORS_HEADERS = "Content-Type"


def _origin_from_url(value: str) -> str | None:
    """Return scheme://host[:port] for a configured URL/origin value."""
    parsed = urlsplit(str(value or "").strip().rstrip("/"))
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _configured_cors_origins() -> set[str]:
    """Return browser origins allowed to call this app.

    JOB_HUNTER_BASE_URL is the canonical app URL and is always trusted.
    JOB_HUNTER_CORS_ALLOWED_ORIGINS is only for additional frontends/proxies.
    """
    configured = {_origin_from_url(JOB_HUNTER_BASE_URL)}
    raw_extra = os.environ.get("JOB_HUNTER_CORS_ALLOWED_ORIGINS", "")
    configured.update(_origin_from_url(item) for item in raw_extra.split(","))
    return {origin for origin in configured if origin}


def _cors_origin(request: Request) -> str | None:
    """Return the allowed CORS origin to echo, or None to omit the header."""
    origin = _origin_from_url(request.headers.get("origin", ""))
    if not origin:
        return None
    allowed = _configured_cors_origins()
    if origin in allowed:
        return origin
    _logger.warning(
        "CORS: rejected origin %r not in JOB_HUNTER_BASE_URL or JOB_HUNTER_CORS_ALLOWED_ORIGINS",
        origin,
    )
    return None

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


_SUPPRESSED_ACCESS_PATHS = frozenset([
    "/api/run-status",
    "/api/run-status/",
])


class _AccessLogFilter(logging.Filter):
    """Drops uvicorn access log lines for high-frequency polling endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in _SUPPRESSED_ACCESS_PATHS)


_CONSOLE_SUPPRESSED_FRAGMENTS = (
    "[CAPABILITY_SCORING][BELOW_THRESHOLD]",
)


class _ConsoleNoiseFilter(logging.Filter):
    """Console-only filter: hides verbose scoring internals.

    These lines are still written to the file log at INFO level for post-run
    analysis. Only the terminal display is suppressed.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(fragment in msg for fragment in _CONSOLE_SUPPRESSED_FRAGMENTS)


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

    access_filter = _AccessLogFilter()
    logging.getLogger("uvicorn.access").addFilter(access_filter)

    # Console-only noise filter — applied to the handler, not the logger,
    # so the file handler still receives everything at INFO.
    console_handler = next(
        (h for h in logging.getLogger().handlers if isinstance(h, logging.StreamHandler)
         and not isinstance(h, logging.FileHandler)),
        None,
    )
    if console_handler:
        console_handler.addFilter(_ConsoleNoiseFilter())

    app_logger = logging.getLogger("job_hunter_agent.app")
    sys.stdout = _LineLoggingStream(app_logger, logging.INFO)
    sys.stderr = _LineLoggingStream(app_logger, logging.ERROR)


def _bootstrap_runtime_knowledge() -> None:
    from job_hunter_agent.database import init_db
    from job_hunter_agent.global_settings import seed_global_settings_from_file
    from job_hunter_agent.knowledge_store import upgrade_knowledge_from_dir
    from job_hunter_agent.paths import REPO_ROOT as _REPO_ROOT

    init_db()
    seed_global_settings_from_file()
    for _subdir in ("knowledge", "signals"):
        upgrade_knowledge_from_dir(_REPO_ROOT / "data" / _subdir)


def create_app() -> FastAPI:
    from job_hunter_agent.routes import register_routes
    from job_hunter_agent.routes.responses import json_response

    _bootstrap_runtime_knowledge()

    # Leave `/docs` free for the project's markdown-docs JSON API (not OpenAPI Swagger).
    app = FastAPI(docs_url="/swagger-ui", redoc_url="/swagger-redoc")
    configure_auth(app)

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http_exc(request: Request, exc: StarletteHTTPException):  # type: ignore[no-untyped-def]
        if exc.status_code == 404:
            return json_response({"error": "Not found"}, 404)
        cors = _cors_origin(request)
        headers: dict[str, str] = {"Cache-Control": "no-cache, no-store, must-revalidate"}
        if cors:
            headers["Access-Control-Allow-Origin"] = cors
            headers["Access-Control-Allow-Methods"] = _CORS_METHODS
            headers["Access-Control-Allow-Headers"] = _CORS_HEADERS
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": str(exc.detail)},
            headers=headers,
        )

    @app.middleware("http")
    async def cors_options(request, call_next):  # type: ignore[no-untyped-def]
        cors = _cors_origin(request)
        if request.method == "OPTIONS":
            resp_headers: dict[str, str] = {}
            if cors:
                resp_headers["Access-Control-Allow-Origin"] = cors
                resp_headers["Access-Control-Allow-Methods"] = _CORS_METHODS
                resp_headers["Access-Control-Allow-Headers"] = _CORS_HEADERS
            return JSONResponse(content={"ok": True}, headers=resp_headers)
        response = await call_next(request)
        if cors:
            response.headers.setdefault("Access-Control-Allow-Origin", cors)
            response.headers.setdefault("Access-Control-Allow-Methods", _CORS_METHODS)
            response.headers.setdefault("Access-Control-Allow-Headers", _CORS_HEADERS)
        return response

    @app.middleware("http")
    async def user_context_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        user = read_session_user(request)
        set_user_id(user["user_id"] if user else None)
        return await call_next(request)

    @app.middleware("http")
    async def csrf_protection(request: Request, call_next):  # type: ignore[no-untyped-def]
        if app_config.DEBUG_MODE:
            return await call_next(request)
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return await call_next(request)
        if request.url.path == "/api/debug/browser-log":
            return await call_next(request)
        if read_session_user(request) is None:
            return await call_next(request)
        presented_token = request.headers.get("x-csrf-token")
        if not presented_token and request.url.path == LOGOUT_PATH:
            body = (await request.body()).decode("utf-8", errors="ignore")
            form_fields = dict(parse_qsl(body, keep_blank_values=True))
            presented_token = str(form_fields.get("csrf_token") or "")
        if not verify_csrf_token(request, presented_token):
            return json_response({"error": "CSRF token missing or invalid"}, 403)
        return await call_next(request)

    @app.middleware("http")
    async def auth_enforcement(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path in OPEN_PATHS or path.startswith("/static/"):
            return await call_next(request)
        if read_session_user(request) is None:
            if path.startswith("/api/"):
                return JSONResponse(
                    {"ok": False, "error": "Authentication required"},
                    status_code=401,
                    headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
                )
            return RedirectResponse(
                f"{LOGIN_PATH}?next={quote(path, safe='')}",
                status_code=302,
            )
        return await call_next(request)

    register_routes(app)
    return app


if __name__ == "__main__":
    import argparse

    import uvicorn

    from job_hunter_agent import server_helpers as srv
    from job_hunter_agent.config import SERVER_HOST as HOST, SERVER_PORT as PORT
    from job_hunter_agent.paths import LOCAL_USER_ID

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
        help="Rebuild the workspace from the last saved run before starting.",
    )
    parser.add_argument(
        "--user-id",
        dest="user_id",
        default=None,
        help="User ID to rebuild for when using --rebuild. Defaults to the local user.",
    )
    args = parser.parse_args()

    _configure_server_logging()

    if args.rebuild:
        srv._rebuild_workspace_on_startup(args.user_id or LOCAL_USER_ID)

    print(f"Local server running at http://{HOST}:{PORT}")
    print(f"Debug mode:  {'ON (--debug)' if srv.DEBUG_MODE else 'OFF'}")
    print(f"Workspace:   http://{HOST}:{PORT}/")
    print(f"Settings:    http://{HOST}:{PORT}/settings")
    print(f"Onboarding:  http://{HOST}:{PORT}{ONBOARDING_PATH} (alias {ONBOARDING_DEBUG_ALIAS_PATH})")
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

