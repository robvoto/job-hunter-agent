"""Per-request user context using Python ContextVar.

Set once by the user-context middleware in fastapi_app.py for each HTTP request.
All per-user path helpers in paths.py read from this context to resolve the
correct data directory for the active user.

Non-request code (agent_runner, CLI) must call set_user_id() explicitly before
performing file operations. If no signed-in account is available, callers
should prompt the user to log in rather than inventing an identifier.
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
        "No signed-in user is available. Log in to the app and try again.",
    )


def set_user_context_from_admin_env() -> None:
    """Log CLI entry points in as the configured admin account, if any.

    Shared by non-request entry points (agent_runner, source_connector CLI)
    that have no HTTP request to derive a signed-in user from.
    """
    import os

    admin_email = os.getenv("JOB_HUNTER_ADMIN_EMAIL", "").strip().lower()
    if admin_email:
        from job_hunter_agent.auth import user_id_from_email

        set_user_id(user_id_from_email(admin_email))
