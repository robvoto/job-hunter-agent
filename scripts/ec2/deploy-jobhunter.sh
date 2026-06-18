#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
ENV_FILE="${JOB_HUNTER_ENV_FILE:-/etc/job-hunter/job-hunter.env}"
SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
HEALTH_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"

show_help() {
  cat <<HELP
Deploy Job Hunter on AWS EC2 using uv.

What this does:
  1. moves to the app repo
  2. confirms Git working tree state
  3. pulls latest GitHub code using --ff-only
  4. ensures uv is installed
  5. syncs the production .venv from pyproject.toml
  6. loads /etc/job-hunter/job-hunter.env
  7. applies the same production runtime path defaults used by systemd
  8. runs db_seed --upgrade so runtime files land in the real production data dir
  9. verifies required production knowledge files, including salary and O*NET taxonomy
  10. verifies the repo-managed AWS service contract is installed
  11. restarts job-hunter.service
  12. waits briefly, then proves the app is alive with curl

Usage:
  deploy-jobhunter
  deploy-jobhunter --help

Important:
  - This is the normal update/deploy command, not a first-install script.
  - Do not manually pip install production dependencies on AWS.
  - Dependencies belong in pyproject.toml and are installed with uv sync.
  - Do not manually copy runtime JSON files as the permanent solution.
  - Add dependencies/runtime seed rules to the repo, commit, push, then run this command.
HELP
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  echo "==> Install uv"
  echo "Teaching: uv is the project dependency manager. It creates/updates .venv from pyproject.toml."
  if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: curl is required to install uv. Install curl first." >&2
    exit 1
  fi
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"

  if ! command -v uv >/dev/null 2>&1; then
    echo "ERROR: uv install completed but uv is still not on PATH." >&2
    exit 1
  fi
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

echo "==> Deploying Job Hunter"
echo "Teaching: deployment must pull GitHub and sync dependencies with uv so AWS matches the repo."

cd "$APP_DIR"

echo "==> Git status before pull"
git status --short

echo "==> Pull latest code"
git pull --ff-only

ensure_uv

echo "==> uv version"
uv --version

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
echo "Teaching: systemd defines these runtime paths for the live service. The seed step must use the same paths."
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
echo "Teaching: this copies all repo-managed runtime knowledge files into JOB_HUNTER_DATA_DIR, including salary rules and O*NET taxonomy indexes."
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
echo "Teaching: deploy must fail if the live service drifts from the repo-managed production runtime contract."
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
echo "Teaching: systemd can say active before Python finishes importing. Wait, then curl proves the app is listening."
sleep 3

echo "==> Service status"
sudo systemctl status "$SERVICE" --no-pager

echo "==> Recent logs"
sudo journalctl -u "$SERVICE" -n 80 --no-pager

echo "==> HTTP health check"
curl -I "$HEALTH_URL"

echo "==> Done"
