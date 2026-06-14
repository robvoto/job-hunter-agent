#!/usr/bin/env bash
set -euo pipefail

SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
HEALTH_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"
PUBLIC_URL="${JOB_HUNTER_PUBLIC_HEALTH_URL:-http://jobhunter.robvoto.com/start}"

echo "==> Job Hunter service status"
echo "Teaching: systemctl shows whether systemd thinks the service is running."
sudo systemctl status "$SERVICE" --no-pager || true

echo
echo "==> Recent Job Hunter logs"
echo "Teaching: journalctl shows Python tracebacks and startup messages."
sudo journalctl -u "$SERVICE" -n 100 --no-pager || true

echo
echo "==> Local EC2 health check"
echo "Teaching: 127.0.0.1 here means localhost inside the EC2 server, behind Nginx."
curl -I "$HEALTH_URL" || true

echo
echo "==> Public route health check"
echo "Teaching: this proves Nginx/domain routing reaches the FastAPI app."
curl -I "$PUBLIC_URL" || true
