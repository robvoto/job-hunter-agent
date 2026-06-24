#!/usr/bin/env bash
# Compatibility wrapper kept as the systemd service entrypoint.
# It delegates to the AWS browser-session launcher so the service and smoke
# tests share the same display/VNC/noVNC setup.
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"

exec "$APP_DIR/scripts/ec2/start-aws-browser-session.sh" "$@"
