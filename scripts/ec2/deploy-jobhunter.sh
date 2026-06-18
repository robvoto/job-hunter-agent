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
  2. confirms Git working tree state
  3. pulls latest GitHub code using --ff-only
  4. syncs dependencies from pyproject.toml using uv
  5. loads /etc/job-hunter/job-hunter.env
  6. applies production runtime path defaults
  7. runs db_seed --upgrade
  8. verifies required production knowledge files
  9. verifies the repo-managed AWS service contract is installed
  10. restarts job-hunter.service
  11. waits briefly, then proves the app is alive with curl

Usage:
  deploy-jobhunter
  deploy-jobhunter --help

Important:
  - This is the normal update/deploy command, not a first-install script.
  - Do not manually pip install production dependencies on AWS.
  - Dependencies belong in pyproject.toml and uv.lock.
HELP
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

echo "==> Deploying Job Hunter"
echo "Teaching: deployment must pull GitHub and sync from pyproject.toml with uv."

cd "$APP_DIR"

echo "==> Git status before pull"
git status --short

echo "==> Pull latest code"
git pull --ff-only

echo "==> Check uv"
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: uv is required but was not found on PATH." >&2
  exit 1
fi

echo "==> Sync production dependencies"
uv sync --no-dev

echo "==> Install/update Playwright Chromium"
uv run playwright install chromium

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

echo "==> Verify AWS service contract"
service_cat="$(sudo systemctl cat "$SERVICE")"
if ! grep -q '^ExecStart=/usr/bin/xvfb-run ' <<<"$service_cat"; then
  echo "ERROR: $SERVICE.service is not using /usr/bin/xvfb-run. Run: sudo -E $APP_DIR/scripts/ec2/install-jobhunter-service.sh" >&2
  exit 1
fi
if ! grep -q '^Environment="PATH=.*/usr/bin' <<<"$service_cat"; then
  echo "ERROR: $SERVICE.service PATH does not include system binary paths. Run: sudo -E $APP_DIR/scripts/ec2/install-jobhunter-service.sh" >&2
  exit 1
fi

echo "==> Restart service"
sudo systemctl restart "$SERVICE"

echo "==> Wait for app startup"
sleep 3

echo "==> Service status"
sudo systemctl status "$SERVICE" --no-pager

echo "==> Recent logs"
sudo journalctl -u "$SERVICE" -n 80 --no-pager

echo "==> HTTP health check"
curl -I "$HEALTH_URL"

echo "==> Done"
