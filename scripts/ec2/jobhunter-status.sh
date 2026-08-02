#!/usr/bin/env bash
set -euo pipefail

SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
HEALTH_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"
PUBLIC_URL="${JOB_HUNTER_PUBLIC_HEALTH_URL:-https://jobhunter.robvoto.com/start}"
MODE="${1:-}"

usage() {
  cat <<'HELP'
Usage:
  jobhunter-status
  jobhunter-status --verbose
  jobhunter-status --follow

Default:
  Show a concise service and health summary.

Options:
  --verbose  Show full systemd status plus recent service logs.
  --follow   Tail live service logs after the summary.
HELP
}

status_line() {
  local url="$1"
  local line=""
  line="$(curl -fsSI "$url" 2>/dev/null | head -1 || true)"
  if [[ -n "$line" ]]; then
    printf '%s\n' "$line"
    return 0
  fi
  printf 'unreachable\n'
}

case "$MODE" in
  ""|--verbose|-v|--follow|-f)
    ;;
  --help|-h)
    usage
    exit 0
    ;;
  *)
    echo "Unknown option: $MODE" >&2
    echo >&2
    usage >&2
    exit 1
    ;;
esac

active_state="$(sudo systemctl show -p ActiveState --value "$SERVICE" 2>/dev/null || true)"
sub_state="$(sudo systemctl show -p SubState --value "$SERVICE" 2>/dev/null || true)"
unit_file_state="$(sudo systemctl show -p UnitFileState --value "$SERVICE" 2>/dev/null || true)"
main_pid="$(sudo systemctl show -p MainPID --value "$SERVICE" 2>/dev/null || true)"
active_since="$(sudo systemctl show -p ActiveEnterTimestamp --value "$SERVICE" 2>/dev/null || true)"
release_tag="$(git -c "safe.directory=$APP_DIR" -C "$APP_DIR" describe --tags --exact-match HEAD 2>/dev/null || true)"
release_commit="$(git -c "safe.directory=$APP_DIR" -C "$APP_DIR" rev-parse --short=12 HEAD 2>/dev/null || true)"

echo "Service: ${SERVICE}.service"
echo "Release: ${release_tag:-unreleased}"
echo "Commit:  ${release_commit:-unknown}"
echo "State:   ${active_state:-unknown}${sub_state:+ ($sub_state)}"
echo "Enabled: ${unit_file_state:-unknown}"
echo "PID:     ${main_pid:-unknown}"
echo "Since:   ${active_since:-unknown}"
echo
echo "Local:   $(status_line "$HEALTH_URL")"
echo "Public:  $(status_line "$PUBLIC_URL")"

if [[ "$MODE" == "--verbose" || "$MODE" == "-v" ]]; then
  echo
  sudo systemctl status "$SERVICE" --no-pager || true
  echo
  sudo journalctl -u "$SERVICE" -n 30 --no-pager || true
fi

if [[ "$MODE" == "-f" || "$MODE" == "--follow" ]]; then
  echo
  echo "==> Tailing log (Ctrl+C to stop)"
  sudo journalctl -u "$SERVICE" -f
fi
