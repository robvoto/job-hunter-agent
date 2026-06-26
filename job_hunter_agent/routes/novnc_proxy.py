"""Reverse-proxy for the on-EC2 noVNC / websockify endpoint.

Routes:
  GET /aws-novnc/{path}      — noVNC static assets (HTML, JS, CSS, …)
  WS  /aws-novnc/websockify  — VNC WebSocket stream

Both routes require an active admin session cookie.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import Response
from websockets.asyncio.client import connect as ws_connect

from job_hunter_agent.auth import is_admin, read_session_user
from job_hunter_agent.config import NOVNC_PORT

logger = logging.getLogger(__name__)

router = APIRouter()

_HTTP_UPSTREAM = f"http://localhost:{NOVNC_PORT}"
_WS_UPSTREAM = f"ws://localhost:{NOVNC_PORT}"

_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)


@router.get("/aws-novnc/{path:path}")
async def proxy_novnc_http(path: str, request: Request) -> Response:
    if not is_admin(request):
        return Response("Forbidden", status_code=403)

    upstream_url = f"{_HTTP_UPSTREAM}/{path}"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(
                upstream_url,
                params=dict(request.query_params),
                timeout=10,
            )
        except httpx.ConnectError:
            return Response(
                "noVNC is not reachable on this host — is websockify running on port "
                f"{NOVNC_PORT}?",
                status_code=503,
            )

    headers = {k: v for k, v in resp.headers.items() if k.lower() not in _HOP_BY_HOP}
    return Response(content=resp.content, status_code=resp.status_code, headers=headers)


@router.websocket("/aws-novnc/websockify")
async def proxy_novnc_ws(websocket: WebSocket) -> None:
    user = read_session_user(websocket)
    if user is None or user.get("role") != "admin":
        await websocket.close(code=1008)
        return

    subprotocols = [
        s.strip()
        for s in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if s.strip()
    ]
    await websocket.accept(subprotocol=subprotocols[0] if subprotocols else None)

    upstream_headers = {}
    if subprotocols:
        upstream_headers["Sec-WebSocket-Protocol"] = ", ".join(subprotocols)

    try:
        async with ws_connect(_WS_UPSTREAM, additional_headers=upstream_headers) as upstream:

            async def client_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg.get("bytes") is not None:
                            await upstream.send(msg["bytes"])
                        elif msg.get("text") is not None:
                            await upstream.send(msg["text"])
                        elif msg.get("type") == "websocket.disconnect":
                            break
                except Exception:
                    pass

            async def upstream_to_client() -> None:
                try:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)
                except Exception:
                    pass

            tasks = [
                asyncio.create_task(client_to_upstream()),
                asyncio.create_task(upstream_to_client()),
            ]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    except Exception as exc:
        logger.warning("[NOVNC_PROXY] WebSocket bridge error: %s", exc)

    try:
        await websocket.close()
    except Exception:
        pass
