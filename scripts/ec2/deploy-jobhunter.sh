#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
ENV_FILE="${JOB_HUNTER_ENV_FILE:-/etc/job-hunter/job-hunter.env}"
SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
HEALTH_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"

# Old one-off scripts that used to live on the server but are no longer needed.
OLD_SERVER_SCRIPTS=(
  "$APP_DIR/scripts/ec2/restartServer.sh"
  "$APP_DIR/scripts/ec2/start-ngrok.sh"
  "$APP_DIR/scripts/ec2/status-ngrok.sh"
  "$APP_DIR/scripts/ec2/stop-ngrok.sh"
)

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<HELP
Deploy Job Hunter on AWS EC2. Safe to run on every update.

Steps:
  1. Remove known-old server scripts
  2. Reset any tracked file edits, pull latest code from GitHub
  3. Sync Python dependencies (uv)
  4. Install Playwright Chromium browser + OS system libraries
  5. Install repo-managed helper commands into /usr/local/bin
  6. Install repo-managed systemd service (xvfb-run)
  7. Run db_seed --upgrade
  8. Restart job-hunter.service and health-check
HELP
  exit 0
fi

# uv installs per-user; ensure it's on PATH
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

echo "==> Job Hunter deploy"

cd "$APP_DIR"

echo "==> Remove old server scripts"
for f in "${OLD_SERVER_SCRIPTS[@]}"; do
  [[ -f "$f" ]] && rm -f "$f" && echo "  removed: $f" || true
done

echo "==> Reset local changes and pull"
git checkout -- . 2>/dev/null || true
git pull --ff-only

echo "==> Check uv"
if ! command -v uv >/dev/null 2>&1; then
  echo "==> Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "  uv $(uv --version)"

echo "==> Sync dependencies"
uv sync --no-dev

echo "==> Playwright browser"
uv run playwright install chromium

echo "==> Playwright OS deps"
sudo "$(uv run which python)" -m playwright install-deps chromium

echo "==> Install helpers"
sudo bash "$APP_DIR/scripts/ec2/install-helpers.sh"

echo "==> Install service"
sudo bash "$APP_DIR/scripts/ec2/install-jobhunter-service.sh"

echo "==> Load env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Missing $ENV_FILE" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export JOB_HUNTER_DATA_DIR="${JOB_HUNTER_DATA_DIR:-/var/lib/job-hunter/data}"
export JOB_HUNTER_OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"
export JOB_HUNTER_DB_PATH="${JOB_HUNTER_DB_PATH:-/var/lib/job-hunter/data/job_hunter.db}"

echo "  DATA_DIR=$JOB_HUNTER_DATA_DIR"
echo "  DB_PATH=$JOB_HUNTER_DB_PATH"

echo "==> Ensure runtime dirs"
sudo mkdir -p "$JOB_HUNTER_DATA_DIR" "$JOB_HUNTER_OUTPUT_DIR"
sudo chown -R ubuntu:ubuntu "$JOB_HUNTER_DATA_DIR" "$JOB_HUNTER_OUTPUT_DIR"

echo "==> DB seed"
uv run python -m job_hunter_agent.db_seed --upgrade

echo "==> Verify runtime files"
for f in \
  "$JOB_HUNTER_DATA_DIR/knowledge/locations_au.json" \
  "$JOB_HUNTER_DATA_DIR/knowledge/salary.json" \
  "$JOB_HUNTER_DATA_DIR/knowledge/occupation_taxonomy/onet_index.json"; do
  test -f "$f" && echo "  ok: $f" || { echo "MISSING: $f" >&2; exit 1; }
done

echo "==> Restart service"
sudo systemctl restart "$SERVICE"
sleep 5

echo "==> Status"
sudo systemctl status "$SERVICE" --no-pager
sudo journalctl -u "$SERVICE" -n 30 --no-pager

echo "==> Health check"
curl -sI "$HEALTH_URL" | head -3

echo "==> Done"
