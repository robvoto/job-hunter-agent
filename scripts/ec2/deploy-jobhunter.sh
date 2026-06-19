#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
ENV_FILE="${JOB_HUNTER_ENV_FILE:-/etc/job-hunter/job-hunter.env}"
SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
HEALTH_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"

show_help() {
  cat <<HELP
Deploy Job Hunter on AWS EC2.

What this does:
  1. moves to the app repo
  2. stashes any local uncommitted changes, then pulls latest GitHub code
  3. syncs dependencies from pyproject.toml using uv
  4. installs Playwright Chromium browser binary
  5. installs Playwright system OS dependencies (libatk, libgbm, etc.)
  6. installs repo-managed helper commands into /usr/local/bin
  7. installs repo-managed systemd service (xvfb-run + full PATH)
  8. loads /etc/job-hunter/job-hunter.env
  9. applies production runtime path defaults
  10. runs db_seed --upgrade
  11. verifies required production knowledge files exist
  12. restarts job-hunter.service
  13. waits briefly, then proves the app is alive with curl

Usage:
  deploy-jobhunter
  deploy-jobhunter --help

Important:
  - Safe to run on every deploy — all steps are idempotent.
  - Do not manually install Python packages on AWS; use pyproject.toml.
HELP
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

echo "==> Deploying Job Hunter"

cd "$APP_DIR"

echo "==> Git status before pull"
git status --short

echo "==> Stash any local changes so pull can proceed"
git stash --include-untracked --quiet && echo "  (stashed)" || true

echo "==> Pull latest code"
git pull --ff-only

echo "==> Check uv"
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is required but was not found on PATH." >&2
  exit 1
fi

echo "==> Sync production dependencies"
uv sync --no-dev

echo "==> Install/update Playwright Chromium browser"
uv run playwright install chromium

echo "==> Install Playwright OS system dependencies"
sudo "$(uv run which python)" -m playwright install-deps chromium

echo "==> Install repo-managed helper commands"
sudo bash "$APP_DIR/scripts/ec2/install-helpers.sh"

echo "==> Install repo-managed systemd service"
sudo bash "$APP_DIR/scripts/ec2/install-jobhunter-service.sh"

echo "==> Load production secrets/env file"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: Missing environment file: $ENV_FILE" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

echo "==> Apply production runtime path defaults"
export JOB_HUNTER_DATA_DIR="${JOB_HUNTER_DATA_DIR:-/var/lib/job-hunter/data}"
export JOB_HUNTER_OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"
export JOB_HUNTER_DB_PATH="${JOB_HUNTER_DB_PATH:-/var/lib/job-hunter/data/job_hunter.db}"

echo "JOB_HUNTER_DATA_DIR=$JOB_HUNTER_DATA_DIR"
echo "JOB_HUNTER_OUTPUT_DIR=$JOB_HUNTER_OUTPUT_DIR"
echo "JOB_HUNTER_DB_PATH=$JOB_HUNTER_DB_PATH"

echo "==> Ensure runtime directories exist"
sudo mkdir -p "$JOB_HUNTER_DATA_DIR" "$JOB_HUNTER_OUTPUT_DIR"
sudo chown -R ubuntu:ubuntu "$JOB_HUNTER_DATA_DIR" "$JOB_HUNTER_OUTPUT_DIR"

echo "==> Upgrade DB/config seed"
uv run python -m job_hunter_agent.db_seed --upgrade

echo "==> Verify required runtime files"
required_runtime_files=(
  "$JOB_HUNTER_DATA_DIR/knowledge/locations_au.json"
  "$JOB_HUNTER_DATA_DIR/knowledge/salary.json"
  "$JOB_HUNTER_DATA_DIR/knowledge/occupation_taxonomy/onet_index.json"
  "$JOB_HUNTER_DATA_DIR/knowledge/occupation_taxonomy/onet_occupations.json"
  "$JOB_HUNTER_DATA_DIR/knowledge/occupation_taxonomy/onet_alternate_titles.json"
)

for required_file in "${required_runtime_files[@]}"; do
  test -f "$required_file"
  echo "Found: $required_file"
done

echo "==> Restart service"
sudo systemctl restart "$SERVICE"

echo "==> Wait for app startup"
sleep 5

echo "==> Service status"
sudo systemctl status "$SERVICE" --no-pager

echo "==> Recent logs"
sudo journalctl -u "$SERVICE" -n 40 --no-pager

echo "==> HTTP health check"
curl -sI "$HEALTH_URL" | head -5

echo "==> Done"
