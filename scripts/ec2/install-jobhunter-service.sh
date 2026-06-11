#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
SERVICE_NAME="${JOB_HUNTER_SERVICE:-job-hunter}"
SERVICE_SOURCE="$APP_DIR/scripts/ec2/job-hunter.service"
SERVICE_TARGET="/etc/systemd/system/${SERVICE_NAME}.service"

show_help() {
  cat <<HELP
Install the repo-managed Job Hunter systemd service on AWS EC2.

What this does:
  1. verifies the repo-managed service template exists
  2. backs up the current systemd service file if one exists
  3. installs scripts/ec2/job-hunter.service to /etc/systemd/system/${SERVICE_NAME}.service
  4. reloads systemd
  5. enables the service
  6. verifies the service uses full Linux PATH and xvfb-run for non-headless Playwright

Usage:
  sudo -E ./scripts/ec2/install-jobhunter-service.sh
  sudo -E ./scripts/ec2/install-jobhunter-service.sh --help

Important:
  - Do not hand-edit the production service as the permanent fix.
  - Change the repo-managed template, commit, push, deploy, then reinstall the service.
HELP
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

echo "==> Installing repo-managed Job Hunter systemd service"
echo "Teaching: systemd config is production runtime code. It belongs in the repo, not only in manual AWS edits."

if [[ ! -f "$SERVICE_SOURCE" ]]; then
  echo "ERROR: Missing service template: $SERVICE_SOURCE" >&2
  exit 1
fi

if [[ -f "$SERVICE_TARGET" ]]; then
  backup_path="${SERVICE_TARGET}.bak.$(date +%Y%m%d-%H%M%S)"
  echo "==> Backup current service to $backup_path"
  cp "$SERVICE_TARGET" "$backup_path"
fi

echo "==> Install $SERVICE_SOURCE -> $SERVICE_TARGET"
install -m 0644 "$SERVICE_SOURCE" "$SERVICE_TARGET"

echo "==> Reload and enable service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

echo "==> Verify service runtime contract"
if ! grep -q '^ExecStart=/usr/bin/xvfb-run ' "$SERVICE_TARGET"; then
  echo "ERROR: Service ExecStart must use /usr/bin/xvfb-run for AWS non-headless scraping." >&2
  exit 1
fi

if ! grep -q '^Environment="PATH=.*/usr/bin' "$SERVICE_TARGET"; then
  echo "ERROR: Service PATH must include system binary paths so xvfb-run can find xauth/Xvfb." >&2
  exit 1
fi

echo "==> Installed service:"
systemctl cat "$SERVICE_NAME"

echo "==> Done"
