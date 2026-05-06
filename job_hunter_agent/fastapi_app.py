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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from job_hunter_agent.routes import register_routes
from job_hunter_agent.routes.responses import json_response


def create_app() -> FastAPI:
    # Leave `/docs` free for the project's markdown-docs JSON API (not OpenAPI Swagger).
    app = FastAPI(docs_url="/swagger-ui", redoc_url="/swagger-redoc")

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
    )
