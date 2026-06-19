#!/usr/bin/env bash
set -euo pipefail

SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
HEALTH_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"
PUBLIC_URL="${JOB_HUNTER_PUBLIC_HEALTH_URL:-https://jobhunter.robvoto.com/start}"

sudo systemctl status "$SERVICE" --no-pager || true
echo
sudo journalctl -u "$SERVICE" -n 60 --no-pager || true
echo
curl -sI "$HEALTH_URL" | head -3 || true
echo
curl -sI "$PUBLIC_URL" | head -3 || true
