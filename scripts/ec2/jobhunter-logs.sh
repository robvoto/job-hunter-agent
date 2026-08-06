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
APP_LOG="$OUTPUT_DIR/server.log"
FOLLOW=0
SINCE=""
UNTIL=""
FOLLOW_VIEW="combined"

usage() {
  cat <<'EOF'
Usage: jobhunter-logs [--follow] [--app|--journal|--combined] [--since "..."] [--until "..."]

Defaults:
  - snapshot mode shows journal + app log
  - follow mode tails journal + app log together

Examples:
  jobhunter-logs
  jobhunter-logs --follow
  jobhunter-logs --follow --combined
  jobhunter-logs --follow --app
  jobhunter-logs --follow --journal
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -f|--follow)
      FOLLOW=1
      shift
      ;;
    --app)
      FOLLOW_VIEW="app"
      shift
      ;;
    --journal)
      FOLLOW_VIEW="journal"
      shift
      ;;
    --combined|--all)
      FOLLOW_VIEW="combined"
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
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
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
printf '==> App log: %s\n' "$APP_LOG"
sudo tail -n 200 "$APP_LOG" || true

if [[ "$FOLLOW" -eq 1 ]]; then
  echo
  case "$FOLLOW_VIEW" in
    combined)
      echo "==> Following app log (Ctrl+C to stop)"
      sudo tail -n 0 -F "$APP_LOG"
      ;;
    app)
      echo "==> Following app log (Ctrl+C to stop)"
      sudo tail -n 0 -F "$APP_LOG"
      ;;
    journal)
      echo "==> Following systemd journal only (Ctrl+C to stop)"
      sudo journalctl -u "$SERVICE" -f
      ;;
  esac
fi
