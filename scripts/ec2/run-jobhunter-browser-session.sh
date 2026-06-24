#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"
DISPLAY_NUM="${JOB_HUNTER_AWS_BROWSER_DISPLAY_NUM:-99}"
DISPLAY=":${DISPLAY_NUM}"
SCREEN="${JOB_HUNTER_AWS_BROWSER_SCREEN:-1400x900x24}"
VNC_PORT="${JOB_HUNTER_AWS_BROWSER_VNC_PORT:-5901}"
NOVNC_PORT="${JOB_HUNTER_AWS_BROWSER_NOVNC_PORT:-7900}"
NOVNC_WEB_ROOT="${JOB_HUNTER_NOVNC_WEB_ROOT:-/usr/share/novnc}"
XVFB_LOG="${OUTPUT_DIR}/xvfb.log"
X11VNC_LOG="${OUTPUT_DIR}/x11vnc.log"
WEBSOCKIFY_LOG="${OUTPUT_DIR}/novnc.log"

mkdir -p "$OUTPUT_DIR"

cleanup() {
  local exit_code=$?
  for pid in "${WEBSOCKIFY_PID:-}" "${X11VNC_PID:-}" "${XVFB_PID:-}"; do
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
  wait >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

Xvfb "$DISPLAY" -screen 0 "$SCREEN" -ac -nolisten tcp >"$XVFB_LOG" 2>&1 &
XVFB_PID=$!

sleep 1

export DISPLAY
x11vnc -display "$DISPLAY" -localhost -rfbport "$VNC_PORT" -shared -forever -nopw \
  >"$X11VNC_LOG" 2>&1 &
X11VNC_PID=$!

websockify --web="$NOVNC_WEB_ROOT" "127.0.0.1:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" \
  >"$WEBSOCKIFY_LOG" 2>&1 &
WEBSOCKIFY_PID=$!

cd "$APP_DIR"
python -m job_hunter_agent.fastapi_app
