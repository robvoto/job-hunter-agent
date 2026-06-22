#!/usr/bin/env bash
set -euo pipefail

# Helper: show recent systemd and file logs for the Job Hunter service.
# Installs as `/usr/local/bin/jobhunter-logs` via `install-helpers.sh`.
# Usage: `jobhunter-logs` or `jobhunter-logs --follow` to tail live output.

SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"

# Show latest systemd journal entries for the service (safe if journalctl fails).
sudo journalctl -u "$SERVICE" -n 200 --no-pager || true

echo
printf '==> App file log: %s/server.log\n' "$OUTPUT_DIR"
# Show the tail of the application log file; file may be missing in some setups.
sudo tail -n 200 "$OUTPUT_DIR/server.log" || true

if [[ "${1:-}" == "-f" || "${1:-}" == "--follow" ]]; then
  echo
  echo "==> Following systemd log (Ctrl+C to stop)"
  sudo journalctl -u "$SERVICE" -f
fi
