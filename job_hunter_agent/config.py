# config.py
import os
import argparse

OUTPUT_HTML = "output/dashboard.html"

# Server settings
SERVER_HOST = os.getenv("JOB_HUNTER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("JOB_HUNTER_PORT", "8765"))

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
HEALTH_CHECK_PATH = "/api/health"
