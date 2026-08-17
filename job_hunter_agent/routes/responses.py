"""Shared HTTP helpers for FastAPI workspace routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.responses import HTMLResponse, JSONResponse

_MIME_OVERRIDES = {
    ".css": "text/css",
    ".js": "text/javascript",
    ".png": "image/png",
}


def json_response(payload: dict[str, Any], status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=payload,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def html_response(html: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        status_code=status_code,
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def guess_media_type(path: Path) -> str:
    mime_type = _MIME_OVERRIDES.get(path.suffix.lower())
    if mime_type:
        return mime_type
    import mimetypes

    guessed, _ = mimetypes.guess_type(str(path))
    content_type = guessed or "application/octet-stream"
    if content_type.startswith("text/") or content_type == "application/javascript":
        return f"{content_type}; charset=utf-8"
    return content_type
