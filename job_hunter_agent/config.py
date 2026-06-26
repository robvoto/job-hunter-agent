"""Helpers for config."""


# config.py

import argparse
import os

# Server settings

SERVER_HOST = os.getenv("JOB_HUNTER_HOST", "127.0.0.1")

SERVER_PORT = int(os.getenv("JOB_HUNTER_PORT", "8765"))

JOB_HUNTER_BASE_URL = os.getenv("JOB_HUNTER_BASE_URL", f"http://localhost:{SERVER_PORT}").rstrip(
    "/"
)


def _resolve_debug_mode() -> bool:

    # Use parse_known_args to avoid exiting on unknown flags in different run contexts

    parser = argparse.ArgumentParser(add_help=False)

    parser.add_argument("--debug", action="store_true", dest="debug")

    args, _ = parser.parse_known_args()

    return bool(args.debug)


DEBUG_MODE = _resolve_debug_mode()


# Shared URL paths

LOGIN_PATH = "/login"

LOGOUT_PATH = "/logout"

GLOBAL_SETTINGS_PATH = "/global-settings"
AWS_BROWSER_SESSION_PATH = "/aws-browser-session"
AWS_NOVNC_PROXY_PATH = "/aws-novnc"

NOVNC_PORT = int(os.getenv("NOVNC_PORT", "7900"))

ONBOARDING_PATH = "/start"

ONBOARDING_DEBUG_ALIAS_PATH = "/onboarding"

HEALTH_CHECK_PATH = "/api/health"

GOOGLE_AUTH_PATH = "/login/google"

GOOGLE_AUTH_CALLBACK_PATH = "/api/auth/google/callback"


# Security and encoding constants

AUTH_ALGO_SHA256 = "sha256"

AUTH_ENCODING = "utf-8"

DEFAULT_ERRORS = "replace"

CSRF_TOKEN_CONTEXT = "job_hunter_csrf"

SESSION_COOKIE_PATH = "/"

SESSION_COOKIE_DEFAULT_NAME = "job_hunter_session"


# Allowed documentation paths for the API

ALLOWED_DOC_REL_PATHS = (
    "README.md",
    "docs/ARCHITECTURE.md",
    "docs/DEVELOPER_GUIDE.md",
    "docs/OPERATIONS.md",
    "docs/USER_GUIDE.md",
    "docs/SHOWCASE_NOTES.md",
    "docs/SCORING_RATIONALE.md",
)
