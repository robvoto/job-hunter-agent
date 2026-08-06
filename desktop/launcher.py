"""Desktop system tray launcher for Job Hunter Agent.

Run via:
    pythonw.exe desktop\\launcher.py

Sets JOB_HUNTER_DB_PATH relative to the app directory before importing
any job_hunter_agent modules, then starts uvicorn in a background thread
and displays a system tray icon.
"""

from __future__ import annotations

import ctypes
import json
import io
import logging
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

# Under pythonw.exe, sys.stdout/sys.stderr are None. Anything that logs a line
# during startup (uvicorn, dependencies) then raises AttributeError on the None
# write, silently killing the server thread before it binds its port. Give them
# a harmless sink so accidental output can't crash the app.
if sys.stdout is None:
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
if sys.stderr is None:
    sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")

logger = logging.getLogger(__name__)


def _set_env_defaults() -> None:
    """Set per-user data paths to %APPDATA%\\JobHunterAgent if not already overridden.

    Installed path layout:
      %APPDATA%\\JobHunterAgent\\data\\   — knowledge, config, defaults, users, runtime
      %APPDATA%\\JobHunterAgent\\output\\ — server logs and artefacts
      %APPDATA%\\JobHunterAgent\\app.db   — SQLite database

    The app code and knowledge seeds stay in the install directory; this function
    seeds missing JSON files into AppData so direct-read modules (salary, locations,
    global_settings) find them before the server starts.
    """
    import shutil

    appdata = Path(os.environ.get("APPDATA", Path.home()))
    app_dir = Path(__file__).resolve().parent.parent
    os.environ.setdefault("JOB_HUNTER_DESKTOP_MODE", "1")

    data_dir = Path(os.environ.setdefault(
        "JOB_HUNTER_DATA_DIR", str(appdata / "JobHunterAgent" / "data")
    ))
    output_dir = Path(os.environ.setdefault(
        "JOB_HUNTER_OUTPUT_DIR", str(appdata / "JobHunterAgent" / "output")
    ))
    os.environ.setdefault("JOB_HUNTER_DB_PATH", str(data_dir / "app.db"))

    # Create writable subdirectories.
    for subdir in ("config", "defaults", "knowledge", "signals", "users", "runtime"):
        (data_dir / subdir).mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    desktop_config_path = data_dir / "config" / "desktop.json"
    if desktop_config_path.exists():
        try:
            desktop_config = json.loads(desktop_config_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[DESKTOP][WARN] Could not read %s: %s", desktop_config_path, exc)
        else:
            workspace_export_dir = str(
                desktop_config.get("workspace_export_dir") if isinstance(desktop_config, dict) else ""
            ).strip()
            if workspace_export_dir:
                os.environ.setdefault("JOB_HUNTER_WORKSPACE_EXPORT_DIR", workspace_export_dir)

    # Seed JSON files that modules read directly from DATA_DIR on first run.
    # The installer handles this for fresh installs; this covers developer runs
    # and any edge case where installer seeding was skipped.
    seed_src = app_dir / "data"
    for subdir in ("config", "defaults", "knowledge", "signals"):
        src_dir = seed_src / subdir
        dst_dir = data_dir / subdir
        if not src_dir.exists():
            continue
        for src_file in src_dir.glob("*.json"):
            dst_file = dst_dir / src_file.name
            if not dst_file.exists():
                shutil.copy2(src_file, dst_file)


# Must run before any job_hunter_agent imports — config.py and paths.py read
# env vars at module import time.
_set_env_defaults()

from job_hunter_agent.config import DEBUG_MODE
from job_hunter_agent.logging_utils import setup_logging

setup_logging(debug=DEBUG_MODE)

import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import pystray
import uvicorn

APP_NAME = "Job Hunter Agent"
_HOST = os.environ.get("JOB_HUNTER_HOST", "127.0.0.1")
_PORT = int(os.environ.get("JOB_HUNTER_PORT", "8765"))
APP_URL = f"http://{_HOST}:{_PORT}"
_HEALTH_URL = f"{APP_URL}/api/health"
_MUTEX_NAME = "Local\\JobHunterAgentMutex"
_ERROR_ALREADY_EXISTS = 183
_MUTEX_HANDLE = None  # Must outlive the function to keep the mutex alive


def _acquire_single_instance() -> bool:
    """Return True if this is the only running instance (Windows named mutex).

    The handle is kept in _MUTEX_HANDLE so the GC does not release it.
    """
    global _MUTEX_HANDLE
    _MUTEX_HANDLE = ctypes.windll.kernel32.CreateMutexW(None, True, _MUTEX_NAME)
    return ctypes.windll.kernel32.GetLastError() != _ERROR_ALREADY_EXISTS


def _playwright_chromium_installed() -> bool:
    """Return True if Playwright's Chromium browser binary is present."""
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if not localappdata:
        return False
    ms_playwright = Path(localappdata) / "ms-playwright"
    if not ms_playwright.exists():
        return False
    return any(d.name.startswith("chromium-") for d in ms_playwright.iterdir() if d.is_dir())


def _msgbox(title: str, text: str) -> None:
    # MB_ICONINFORMATION | MB_TOPMOST | MB_SETFOREGROUND — without these, pythonw has no
    # taskbar entry and the dialog can pop up behind other windows unnoticed, leaving the
    # process blocked (and the single-instance mutex held) with nothing visible to the user.
    ctypes.windll.user32.MessageBoxW(0, text, title, 0x40 | 0x40000 | 0x10000)


def _wait_for_server(timeout: float = 30.0) -> bool:
    """Poll the health endpoint until the server responds or timeout is reached."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(_HEALTH_URL, timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def _make_tray_icon() -> PIL.Image.Image:
    asset = Path(__file__).resolve().parent.parent / "templates" / "static" / "assets" / "job_hunter_img.png"
    if asset.exists():
        img = PIL.Image.open(asset).convert("RGBA").resize((64, 64), PIL.Image.LANCZOS)
        return img
    # Fallback if asset missing
    img = PIL.Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = PIL.ImageDraw.Draw(img)
    draw.ellipse([2, 2, 62, 62], fill=(37, 99, 235))
    try:
        font = PIL.ImageFont.load_default(size=24)
    except TypeError:
        font = PIL.ImageFont.load_default()
    draw.text((14, 18), "JH", fill="white", font=font)
    return img


class _ServerThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="uvicorn")
        self._server: uvicorn.Server | None = None

    def run(self) -> None:
        # Ensure the app package is importable from the install/repo root.
        app_root = str(Path(__file__).resolve().parent.parent)
        if app_root not in sys.path:
            sys.path.insert(0, app_root)

        from job_hunter_agent.fastapi_app import create_app

        cfg = uvicorn.Config(
            create_app(),
            host=_HOST,
            port=_PORT,
            log_level="warning",
        )
        self._server = uvicorn.Server(cfg)
        self._server.run()

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True


class _TelegramPollThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="telegram-poller")
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        from job_hunter_agent.notifiers.telegram_notifier import sync_telegram_subscribers
        from job_hunter_agent.user_context import set_user_id
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
                            logger.info(
                                "[TELEGRAM] processed %s command(s) for %s",
                                result.get("commands_processed"),
                                user_id,
                            )
                    finally:
                        set_user_id(None)
            except Exception as exc:
                logger.warning("[TELEGRAM][WARN] Telegram poll cycle failed: %s", exc)
            self._stop_event.wait(10.0)


def main() -> None:
    if not _acquire_single_instance():
        # Already running elsewhere — just bring the existing instance's page back up
        # instead of showing a dialog that can get lost behind other windows.
        webbrowser.open(APP_URL)
        return

    if not _playwright_chromium_installed():
        _msgbox(
            "Playwright Setup Required",
            "Chromium is not installed for Playwright scraping.\n\n"
            "Run this command once, then restart Job Hunter Agent:\n\n"
            "    python -m playwright install chromium\n\n"
            "The app will still start — scraping will fail until Chromium is installed.",
        )

    server = _ServerThread()
    server.start()

    if not _wait_for_server(timeout=60.0):
        _msgbox(
            APP_NAME,
            "Server failed to start within 30 seconds.\n\n"
            "Run from a terminal to see the error:\n\n"
            "    python\\python.exe -m job_hunter_agent.fastapi_app",
        )
        server.stop()
        return

    telegram_poller = _TelegramPollThread()
    telegram_poller.start()

    webbrowser.open(APP_URL)

    def on_open(_icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        webbrowser.open(APP_URL)

    def on_quit(icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        telegram_poller.stop()
        server.stop()
        telegram_poller.join(timeout=5.0)
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open in Browser", on_open, default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon(APP_NAME, _make_tray_icon(), APP_NAME, menu)
    icon.run()


if __name__ == "__main__":
    main()
