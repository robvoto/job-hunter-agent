#!/usr/bin/env bash
# Starts the AWS browser session used by headed Playwright runs.
# The service and manual smoke tests both launch through this wrapper so the
# DISPLAY, VNC bridge, and persistent Playwright profile stay aligned.
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"
DATA_DIR="${JOB_HUNTER_DATA_DIR:-/var/lib/job-hunter/data}"
DISPLAY_NUM="${JOB_HUNTER_AWS_BROWSER_DISPLAY_NUM:-99}"
DISPLAY=":${DISPLAY_NUM}"
SCREEN="${JOB_HUNTER_AWS_BROWSER_SCREEN:-1400x900x24}"
VNC_PORT="${JOB_HUNTER_AWS_BROWSER_VNC_PORT:-5901}"
NOVNC_PORT="${JOB_HUNTER_AWS_BROWSER_NOVNC_PORT:-7900}"
NOVNC_WEB_ROOT="${JOB_HUNTER_NOVNC_WEB_ROOT:-/usr/share/novnc}"
XVFB_LOG="${OUTPUT_DIR}/xvfb.log"
OPENBOX_LOG="${OUTPUT_DIR}/openbox.log"
X11VNC_LOG="${OUTPUT_DIR}/x11vnc.log"
WEBSOCKIFY_LOG="${OUTPUT_DIR}/novnc.log"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<HELP
Start the AWS browser session and then run the given command.

If no command is provided, the Job Hunter FastAPI service is launched.
HELP
  exit 0
fi

mkdir -p "$OUTPUT_DIR" "$DATA_DIR"
mkdir -p "$DATA_DIR/playwright_user_data"

cleanup() {
  local exit_code=$?
  for pid in "${WEBSOCKIFY_PID:-}" "${X11VNC_PID:-}" "${OPENBOX_PID:-}" "${XVFB_PID:-}"; do
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
  wait >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

export DISPLAY
export JOB_HUNTER_DATA_DIR="$DATA_DIR"
export JOB_HUNTER_OUTPUT_DIR="$OUTPUT_DIR"
export PLAYWRIGHT_USER_DATA_DIR="${PLAYWRIGHT_USER_DATA_DIR:-$DATA_DIR/playwright_user_data}"

Xvfb "$DISPLAY" -screen 0 "$SCREEN" -ac -nolisten tcp >"$XVFB_LOG" 2>&1 &
XVFB_PID=$!

sleep 1

openbox >"$OPENBOX_LOG" 2>&1 &
OPENBOX_PID=$!

x11vnc -display "$DISPLAY" -localhost -rfbport "$VNC_PORT" -shared -forever -nopw \
  >"$X11VNC_LOG" 2>&1 &
X11VNC_PID=$!

websockify --web="$NOVNC_WEB_ROOT" "127.0.0.1:${NOVNC_PORT}" "127.0.0.1:${VNC_PORT}" \
  >"$WEBSOCKIFY_LOG" 2>&1 &
WEBSOCKIFY_PID=$!

cd "$APP_DIR"
if [[ $# -eq 0 ]]; then
  # The workspace HTML is a generated artifact. Rebuild it on each service
  # start so deploy/restart always serves the current renderer output.
  set -- python -m job_hunter_agent.fastapi_app --rebuild
fi
"$@"
