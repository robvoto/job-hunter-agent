#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
SERVICE_NAME="${JOB_HUNTER_SERVICE:-job-hunter}"
SERVICE_SOURCE="$APP_DIR/scripts/ec2/job-hunter.service"
SERVICE_TARGET="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Install the repo-managed Job Hunter systemd service."
  echo "Usage: sudo bash scripts/ec2/install-jobhunter-service.sh"
  exit 0
fi

[[ -f "$SERVICE_SOURCE" ]] || { echo "ERROR: Missing $SERVICE_SOURCE" >&2; exit 1; }

[[ -f "$SERVICE_TARGET" ]] && cp "$SERVICE_TARGET" "${SERVICE_TARGET}.bak.$(date +%Y%m%d-%H%M%S)"

install -m 0644 "$SERVICE_SOURCE" "$SERVICE_TARGET"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

grep -q '^ExecStart=/usr/bin/xvfb-run ' "$SERVICE_TARGET" \
  || { echo "ERROR: service ExecStart must use xvfb-run" >&2; exit 1; }

echo "Service installed: $SERVICE_TARGET"
