#!/usr/bin/env bash
set -euo pipefail

# Helper: show recent systemd and file logs for the Job Hunter service.
# Installs as `/usr/local/bin/jobhunter-logs` via `install-helpers.sh`.
# Usage:
#   `jobhunter-logs`
#   `jobhunter-logs --since "2026-07-31 06:20:00" --until "2026-07-31 06:49:30"`
#   `jobhunter-logs --follow`

SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"
HUMAN_LOG="$OUTPUT_DIR/server-human.log"
DEBUG_LOG="$OUTPUT_DIR/server-debug.log"
FOLLOW=0
SINCE=""
UNTIL=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--follow)
      FOLLOW=1
      shift
      ;;
    --since)
      SINCE="${2:-}"
      shift 2
      ;;
    --until)
      UNTIL="${2:-}"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

journal_cmd=(sudo journalctl -u "$SERVICE" --no-pager)
if [[ -n "$SINCE" ]]; then
  journal_cmd+=(--since "$SINCE")
fi
if [[ -n "$UNTIL" ]]; then
  journal_cmd+=(--until "$UNTIL")
fi
if [[ -z "$SINCE" && -z "$UNTIL" ]]; then
  journal_cmd+=(-n 200)
fi

# Show latest systemd journal entries for the service (safe if journalctl fails).
"${journal_cmd[@]}" || true

echo
printf '==> App human log: %s\n' "$HUMAN_LOG"
sudo tail -n 200 "$HUMAN_LOG" || true

echo
printf '==> App debug log: %s\n' "$DEBUG_LOG"
sudo tail -n 200 "$DEBUG_LOG" || true

if [[ "$FOLLOW" -eq 1 ]]; then
  echo
  echo "==> Following systemd + app logs (Ctrl+C to stop)"
  tail_pid=""
  cleanup() {
    if [[ -n "$tail_pid" ]]; then
      sudo kill "$tail_pid" >/dev/null 2>&1 || true
    fi
  }
  trap cleanup EXIT INT TERM

  sudo tail -n 0 -F "$HUMAN_LOG" "$DEBUG_LOG" &
  tail_pid="$!"
  sudo journalctl -u "$SERVICE" -f
fi
