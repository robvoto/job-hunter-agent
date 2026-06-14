"""Per-request user context using Python ContextVar.

Set once by the user-context middleware in fastapi_app.py for each HTTP request.
All per-user path helpers in paths.py read from this context to resolve the
correct data directory for the active user.

Non-request code (agent_runner, CLI) must call set_user_id() explicitly before
performing file operations.
"""

from __future__ import annotations

from contextvars import ContextVar

_user_id: ContextVar[str | None] = ContextVar("job_hunter_user_id", default=None)


def set_user_id(user_id: str | None) -> None:
    _user_id.set(user_id)


def get_user_id() -> str | None:
    return _user_id.get()


def get_user_id_for_runtime() -> str:
    user_id = get_user_id()
    if user_id:
        return user_id
    raise RuntimeError(
        "No active user id is set. Call set_user_id() before performing file operations.",
    )
