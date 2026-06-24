#!/usr/bin/env bash
# Installs the AWS browser-session dependencies used by the Job Hunter service
# and the manual SEEK smoke-test session.
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<HELP
Install AWS browser session dependencies.

This installs the virtual display, lightweight window manager, and local
VNC/noVNC bridge required for the headed SEEK browser session.
HELP
  exit 0
fi

sudo apt-get update
sudo apt-get install -y xvfb openbox x11vnc novnc websockify

sudo install -d -m 0755 /var/lib/job-hunter/data /var/lib/job-hunter/output
sudo chown -R ubuntu:ubuntu /var/lib/job-hunter

echo "AWS browser session dependencies installed for $APP_DIR"
