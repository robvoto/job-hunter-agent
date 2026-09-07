"""FastAPI ASGI application for the local workspace and settings server.

Route handlers live under ``job_hunter_agent.routes``; this module wires the app,
exception handlers, and CORS-style middleware.

Entry point:
    python -m job_hunter_agent.fastapi_app [--debug] [--rebuild] [--step]

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

from contextlib import asynccontextmanager
from datetime import datetime
import errno
import logging
import os
import socket
import re
import sys
import threading
from urllib.parse import parse_qsl, quote, urlsplit

from job_hunter_agent.runtime_helpers import load_repo_dotenv

load_repo_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from job_hunter_agent import config as app_config
from job_hunter_agent.auth import (
    OPEN_PATHS,
    access_gate_response,
    configure_auth,
    read_session_user,
    verify_csrf_token,
)
from job_hunter_agent.config import (
    JOB_HUNTER_BASE_URL,
    LOGIN_PATH,
    LOGOUT_PATH,
    ONBOARDING_DEBUG_ALIAS_PATH,
    ONBOARDING_PATH,
    ACCESS_DENIED_PATH,
    REQUEST_ACCESS_PATH,
    USER_ACCESS_APPROVED,
    USER_ACCESS_BLOCKED,
    USER_ACCESS_PENDING,
    USER_ACCESS_VERIFIED,
    WAITLIST_PATH,
)
from job_hunter_agent.logging_utils import render_server_session_start_block, setup_logging
from job_hunter_agent.user_context import set_user_id
from job_hunter_agent.run_control import enable_step_through

_logger = logging.getLogger(__name__)
_SERVER_SHUTDOWN_SIGNAL_RECORDED = False

_CORS_METHODS = "GET, PUT, PATCH, POST, DELETE, OPTIONS"
_CORS_HEADERS = "Content-Type"
_TELEGRAM_POLLER: "_TelegramPollThread | None" = None
_SCHEDULED_AGENT_LOOP: "_ScheduledAgentLoopThread | None" = None
_SERVER_TELEGRAM_POLLER_ENV = "JOB_HUNTER_ENABLE_SERVER_TELEGRAM_POLLER"


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

    @staticmethod
    def _level_for_line(line: str, default_level: int) -> int:
        """Respect embedded severity tags from wrapped stderr/stdout lines."""
        match = re.match(
            r"^\d{4}-\d{2}-\d{2}.* - (DEBUG|INFO|WARNING|ERROR|CRITICAL) - ",
            line.strip(),
        )
        if not match:
            return default_level
        return getattr(logging, match.group(1), default_level)

    def write(self, text: str) -> int:
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                level = self._level_for_line(line, self._level)
                self._logger.log(level, line.rstrip("\r"))
        return len(text)

    def flush(self) -> None:
        line = self._buffer.strip("\r")
        self._buffer = ""
        if line.strip():
            level = self._level_for_line(line, self._level)
            self._logger.log(level, line)

    def isatty(self) -> bool:
        return False


_SUPPRESSED_ACCESS_PATHS = frozenset(
    [
        "/api/run-status",
        "/api/run-status/",
    ]
)


def _explicit_env_flag(name: str) -> bool:
    """Parse a boolean env var strictly so bad deploy values fail fast."""
    raw_value = str(os.environ.get(name, "")).strip()
    if not raw_value:
        return False
    normalized = raw_value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Invalid {name} value {raw_value!r}. Use true/false, 1/0, yes/no, or on/off.")


def _server_background_service_enabled(name: str) -> bool:
    """Only run long-lived background services in the web app when explicitly enabled."""
    if os.environ.get("JOB_HUNTER_DESKTOP_MODE") == "1":
        return False
    return _explicit_env_flag(name)


class _AccessLogFilter(logging.Filter):
    """Drops uvicorn access log lines for high-frequency polling endpoints."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(path in msg for path in _SUPPRESSED_ACCESS_PATHS)


def _configure_server_logging() -> None:
    setup_logging(debug=app_config.DEBUG_MODE)
    logging.getLogger("uvicorn.access").addFilter(_AccessLogFilter())

    sys.stdout = _LineLoggingStream(_logger, logging.INFO)
    sys.stderr = _LineLoggingStream(_logger, logging.ERROR)


class ServerAddressInUseError(RuntimeError):
    """Raised before ASGI startup when another process already owns the server address."""


def _bind_server_socket(host: str, port: int) -> socket.socket:
    """Reserve the listen address before FastAPI lifespan services start.

    Uvicorn normally binds only after ASGI startup, which means a duplicate launch
    can start scheduler/background threads and then immediately shut them down on
    EADDRINUSE. Pre-binding makes single-instance failure deterministic and keeps
    the already-running server untouched. The bound socket is handed to Uvicorn.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family=family, type=socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, int(port)))
    except OSError as exc:
        sock.close()
        if exc.errno == errno.EADDRINUSE:
            raise ServerAddressInUseError(
                f"Job Hunter startup skipped: {host}:{port} is already in use. "
                "The existing listener was not touched."
            ) from exc
        raise
    # Listening now, before ASGI lifespan starts, makes the address reservation
    # exclusive even with SO_REUSEADDR. asyncio/Uvicorn can adopt this socket.
    sock.listen()
    sock.set_inheritable(True)
    return sock


def _log_server_shutdown_signal(signal_number: int) -> None:
    global _SERVER_SHUTDOWN_SIGNAL_RECORDED
    if _SERVER_SHUTDOWN_SIGNAL_RECORDED:
        return
    _SERVER_SHUTDOWN_SIGNAL_RECORDED = True

    from job_hunter_agent import server_helpers as srv

    _logger.warning(
        "[SERVER_SHUTDOWN_SIGNAL] pid=%d ppid=%d signal=%s",
        os.getpid(),
        os.getppid(),
        srv._signal_name(signal_number),
    )


def _log_server_session_start(*, debug: bool, rebuild: bool, step: bool) -> None:
    _logger.info(
        render_server_session_start_block(
            started_at=datetime.now().astimezone(),
            pid=os.getpid(),
            parent_pid=os.getppid(),
            invocation=" ".join(sys.argv),
            debug_mode=debug,
            rebuild_on_startup=rebuild,
            step_through=step,
        )
    )


def _bootstrap_runtime_knowledge() -> None:
    from job_hunter_agent.database import init_db
    from job_hunter_agent.global_settings import seed_global_settings_from_file
    from job_hunter_agent.knowledge_store import upgrade_knowledge_from_dir
    from job_hunter_agent.paths import REPO_ROOT as _REPO_ROOT
    from job_hunter_agent.runtime_seed_manifest import (
        APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
        APPROVED_SIGNAL_JSON_REL_PATHS,
        resolve_seed_json_paths,
    )

    init_db()
    seed_global_settings_from_file()
    upgrade_knowledge_from_dir(
        _REPO_ROOT / "data" / "knowledge",
        json_files=resolve_seed_json_paths(
            _REPO_ROOT / "data" / "knowledge",
            APPROVED_DB_KNOWLEDGE_JSON_REL_PATHS,
        ),
    )
    upgrade_knowledge_from_dir(
        _REPO_ROOT / "data" / "signals",
        json_files=resolve_seed_json_paths(
            _REPO_ROOT / "data" / "signals",
            APPROVED_SIGNAL_JSON_REL_PATHS,
        ),
    )


def _apply_startup_flags(*, step: bool) -> None:
    """Apply entry-point runtime flags before the server starts accepting work."""
    if step:
        enable_step_through()


class _TelegramPollThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="telegram-poller")
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        import json

        from job_hunter_agent.notifiers.telegram_notifier import sync_telegram_subscribers
        from job_hunter_agent.user_settings import (
            list_user_setting_user_ids,
            load_user_settings,
            save_user_settings,
        )

        while not self._stop_event.is_set():
            try:
                user_ids = list_user_setting_user_ids()
                for user_id in user_ids:
                    if self._stop_event.is_set():
                        break
                    settings = load_user_settings(user_id, create_if_missing=False)
                    telegram_settings = settings.get("telegram", {})
                    if not isinstance(telegram_settings, dict):
                        continue
                    if not bool(telegram_settings.get("enabled", False)):
                        continue
                    bot_token = str(telegram_settings.get("bot_token") or "").strip()
                    if not bot_token:
                        continue
                    set_user_id(user_id)
                    try:
                        before_snapshot = json.dumps(settings, sort_keys=True, ensure_ascii=False)
                        result = sync_telegram_subscribers(telegram_settings, user_id=user_id)
                        after_snapshot = json.dumps(settings, sort_keys=True, ensure_ascii=False)
                        if after_snapshot != before_snapshot:
                            save_user_settings(user_id, settings)
                        if result.get("commands_processed"):
                            _logger.info(
                                "[TELEGRAM] processed %s command(s) for %s",
                                result.get("commands_processed"),
                                user_id,
                            )
                    finally:
                        set_user_id(None)
            except Exception as exc:
                _logger.warning("[TELEGRAM][WARN] Telegram poll cycle failed: %s", exc)
            self._stop_event.wait(10.0)


class _ScheduledAgentLoopThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="scheduled-agent-loop")
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        from job_hunter_agent.agent_runner import run_agent_loop
        from job_hunter_agent.user_context import set_user_context_from_admin_env

        try:
            set_user_context_from_admin_env()
            run_agent_loop(self._stop_event)
        except Exception as exc:
            _logger.warning("[AGENT_RUNNER][WARN] Scheduled agent loop stopped unexpectedly: %s", exc)
        finally:
            set_user_id(None)


def _start_shared_telegram_poller() -> None:
    global _TELEGRAM_POLLER
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if os.environ.get("JOB_HUNTER_DESKTOP_MODE") == "1":
        return
    if _TELEGRAM_POLLER and _TELEGRAM_POLLER.is_alive():
        return
    _TELEGRAM_POLLER = _TelegramPollThread()
    _TELEGRAM_POLLER.start()
    _logger.info("[TELEGRAM] Background Telegram poller started.")


def _stop_shared_telegram_poller() -> None:
    global _TELEGRAM_POLLER
    if not _TELEGRAM_POLLER:
        return
    _TELEGRAM_POLLER.stop()
    _TELEGRAM_POLLER.join(timeout=5.0)
    _TELEGRAM_POLLER = None
    _logger.info("[TELEGRAM] Background Telegram poller stopped.")


def _start_shared_scheduled_agent_loop() -> None:
    global _SCHEDULED_AGENT_LOOP
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    if os.environ.get("JOB_HUNTER_DESKTOP_MODE") == "1":
        return
    if _SCHEDULED_AGENT_LOOP and _SCHEDULED_AGENT_LOOP.is_alive():
        return
    _SCHEDULED_AGENT_LOOP = _ScheduledAgentLoopThread()
    _SCHEDULED_AGENT_LOOP.start()
    _logger.info("[AGENT_RUNNER] Background scheduled agent loop started.")


def _stop_shared_scheduled_agent_loop() -> None:
    global _SCHEDULED_AGENT_LOOP
    if not _SCHEDULED_AGENT_LOOP:
        return
    _SCHEDULED_AGENT_LOOP.stop()
    _SCHEDULED_AGENT_LOOP.join(timeout=5.0)
    _SCHEDULED_AGENT_LOOP = None
    _logger.info("[AGENT_RUNNER] Background scheduled agent loop stopped.")


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    telegram_enabled = _server_background_service_enabled(_SERVER_TELEGRAM_POLLER_ENV)
    if telegram_enabled:
        _start_shared_telegram_poller()

    # The normal Job Hunter web runtime owns local scheduling because Schedule Run is
    # a first-class user setting in this app.  The saved schedule remains authoritative;
    # this thread only watches that live setting and does not persist a second enable flag.
    # Desktop mode is still excluded inside _start_shared_scheduled_agent_loop() because
    # that launcher owns its own process lifecycle.  AWS can later move to an external
    # trigger (JH-264) without making the local Settings control depend on a hidden process.
    _start_shared_scheduled_agent_loop()
    try:
        yield
    finally:
        # This also covers ASGI lifespan shutdowns that are not attributable to
        # an OS signal. The Uvicorn signal hook records SIGINT/SIGTERM when it
        # can; this idempotent fallback deliberately reports the signal as
        # unknown rather than guessing a cause.
        from job_hunter_agent import server_helpers as srv

        srv._handle_server_shutdown()
        _stop_shared_scheduled_agent_loop()
        if telegram_enabled:
            _stop_shared_telegram_poller()


def create_app() -> FastAPI:
    _bootstrap_runtime_knowledge()

    from job_hunter_agent.routes import register_routes
    from job_hunter_agent.routes.responses import json_response

    # Leave `/docs` free for the project's markdown-docs JSON API (not OpenAPI Swagger).
    app = FastAPI(docs_url="/swagger-ui", redoc_url="/swagger-redoc", lifespan=_app_lifespan)
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
        if not presented_token and request.url.path in {LOGOUT_PATH, REQUEST_ACCESS_PATH}:
            body = (await request.body()).decode("utf-8", errors="ignore")
            form_fields = dict(parse_qsl(body, keep_blank_values=True))
            presented_token = str(form_fields.get("csrf_token") or "")
        if not verify_csrf_token(request, presented_token):
            return json_response({"error": "CSRF token missing or invalid"}, 403)
        return await call_next(request)

    @app.middleware("http")
    async def auth_enforcement(request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path in OPEN_PATHS or path == "/favicon.ico" or path.startswith("/static/"):
            return await call_next(request)
        user = read_session_user(request)
        if user is None:
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
        access_status = str(user.get("access_status") or "").strip().lower()
        if not access_status and user.get("role") == "admin":
            access_status = USER_ACCESS_APPROVED
        if not access_status:
            access_status = USER_ACCESS_VERIFIED
        if path == REQUEST_ACCESS_PATH:
            if access_status in {USER_ACCESS_VERIFIED, USER_ACCESS_PENDING}:
                if access_status == USER_ACCESS_PENDING and request.method == "GET":
                    return RedirectResponse(WAITLIST_PATH, status_code=302)
                return await call_next(request)
            destination = ACCESS_DENIED_PATH if access_status == USER_ACCESS_BLOCKED else "/"
            return RedirectResponse(destination, status_code=302)
        if path == WAITLIST_PATH:
            if access_status == USER_ACCESS_PENDING:
                return await call_next(request)
            if access_status == USER_ACCESS_VERIFIED:
                return RedirectResponse(REQUEST_ACCESS_PATH, status_code=302)
            destination = ACCESS_DENIED_PATH if access_status == USER_ACCESS_BLOCKED else "/"
            return RedirectResponse(destination, status_code=302)
        if path == ACCESS_DENIED_PATH:
            if access_status == USER_ACCESS_BLOCKED:
                return await call_next(request)
            if access_status == USER_ACCESS_VERIFIED:
                destination = REQUEST_ACCESS_PATH
            elif access_status == USER_ACCESS_PENDING:
                destination = WAITLIST_PATH
            else:
                destination = "/"
            return RedirectResponse(destination, status_code=302)
        if access_status != USER_ACCESS_APPROVED:
            return access_gate_response(
                access_status,
                path,
                accepts_html=not path.startswith("/api/"),
            )
        return await call_next(request)

    register_routes(app)
    return app


if __name__ == "__main__":
    import argparse

    import uvicorn

    from job_hunter_agent.config import SERVER_HOST as HOST
    from job_hunter_agent.config import SERVER_PORT as PORT

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
        "--step",
        action="store_true",
        help=(
            "Pause after each job's analysis is printed so it can be checked "
            "job by job before a scrape continues. Temporary debug aid."
        ),
    )
    args = parser.parse_args()

    _configure_server_logging()
    try:
        server_socket = _bind_server_socket(HOST, PORT)
    except ServerAddressInUseError as exc:
        _logger.error("[SERVER_START_SKIPPED] %s", exc)
        raise SystemExit(2)

    _bootstrap_runtime_knowledge()
    _apply_startup_flags(step=args.step)
    _log_server_session_start(
        debug=app_config.DEBUG_MODE,
        rebuild=args.rebuild,
        step=args.step,
    )

    from job_hunter_agent import server_helpers as srv

    srv._log_previous_interrupted_runs()
    if args.rebuild:
        srv._rebuild_workspace_on_startup()

    print(f"Local server running at http://{HOST}:{PORT}")
    print(f"Debug mode:  {'ON (--debug)' if srv.DEBUG_MODE else 'OFF'}")
    print(f"Workspace:   http://{HOST}:{PORT}/")
    print(f"Settings:    http://{HOST}:{PORT}/settings")
    print(
        f"Onboarding:  http://{HOST}:{PORT}{ONBOARDING_PATH} (alias {ONBOARDING_DEBUG_ALIAS_PATH})"
    )
    print(f"Docs API:    http://{HOST}:{PORT}/docs")
    print(f"Swagger UI:  http://{HOST}:{PORT}/swagger-ui")

    class _JobHunterUvicornServer(uvicorn.Server):
        def handle_exit(self, sig, frame):  # type: ignore[no-untyped-def]
            _log_server_shutdown_signal(sig)
            srv._handle_server_shutdown(sig)
            super().handle_exit(sig, frame)

    server = _JobHunterUvicornServer(
        uvicorn.Config(
            create_app(),
            host=HOST,
            port=PORT,
            log_level="debug" if srv.DEBUG_MODE else "info",
            access_log=srv.DEBUG_MODE,
            log_config=None,
        )
    )
    try:
        server.run(sockets=[server_socket])
    finally:
        server_socket.close()
