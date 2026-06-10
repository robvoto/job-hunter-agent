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
  4. activates the project virtual environment
  5. installs dependencies from requirements.txt
  6. loads /etc/job-hunter/job-hunter.env
  7. applies the same production runtime path defaults used by systemd
  8. runs db_seed --upgrade so runtime files land in the real production data dir
  9. restarts job-hunter.service
  10. waits briefly, then proves the app is alive with curl

Usage:
  deploy-jobhunter
  deploy-jobhunter --help

Important:
  - This is the normal update/deploy command, not a first-install script.
  - Do not manually pip install production dependencies on AWS.
  - Do not manually copy runtime JSON files as the permanent solution.
  - Add dependencies/runtime seed rules to the repo, commit, push, then run this command.
HELP
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

echo "==> Deploying Job Hunter"
echo "Teaching: deployment must pull GitHub and install from requirements.txt so AWS matches the repo."

cd "$APP_DIR"

echo "==> Git status before pull"
git status --short

echo "==> Pull latest code"
git pull --ff-only

echo "==> Activate venv"
# shellcheck disable=SC1091
source "$APP_DIR/.venv/bin/activate"

echo "==> Install/update dependencies"
python -m pip install -r requirements.txt

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
echo "Teaching: this copies repo-managed runtime files, including locations_au.json, into JOB_HUNTER_DATA_DIR."
python -m job_hunter_agent.db_seed --upgrade

echo "==> Verify required runtime files"
test -f "$JOB_HUNTER_DATA_DIR/knowledge/locations_au.json"
echo "Found: $JOB_HUNTER_DATA_DIR/knowledge/locations_au.json"

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