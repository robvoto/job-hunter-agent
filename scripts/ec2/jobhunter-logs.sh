#!/usr/bin/env bash
set -euo pipefail

SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"

sudo journalctl -u "$SERVICE" -n 200 --no-pager || true

echo
printf '==> App file log: %s/server.log\n' "$OUTPUT_DIR"
sudo tail -n 200 "$OUTPUT_DIR/server.log" || true

if [[ "${1:-}" == "-f" || "${1:-}" == "--follow" ]]; then
  echo
  echo "==> Following systemd log (Ctrl+C to stop)"
  sudo journalctl -u "$SERVICE" -f
fi
