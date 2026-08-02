#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
ENV_FILE="${JOB_HUNTER_ENV_FILE:-/etc/job-hunter/job-hunter.env}"
SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
HEALTH_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"
DEFAULT_REF="${JOB_HUNTER_DEPLOY_DEFAULT_REF:-main}"
RELEASE_TAG_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+$'

OLD_SERVER_SCRIPTS=(
  "$APP_DIR/scripts/ec2/restartServer.sh"
  "$APP_DIR/scripts/ec2/start-ngrok.sh"
  "$APP_DIR/scripts/ec2/status-ngrok.sh"
  "$APP_DIR/scripts/ec2/stop-ngrok.sh"
)

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<HELP
Deploy a non-production Job Hunter branch or commit ref on AWS EC2.

Usage:
  deploy-jobhunter-latest
  deploy-jobhunter-latest <branch-or-sha>

Examples:
  deploy-jobhunter-latest
  deploy-jobhunter-latest main
  deploy-jobhunter-latest feature/my-fix
  deploy-jobhunter-latest ef720a7

Notes:
  - With no argument, this deploys the latest commit from: ${DEFAULT_REF}
  - This command deploys the latest branch or commit code for staging, smoke tests, and debugging.
  - Production deploys must use: deploy-jobhunter-release vX.Y.Z

Steps:
  1. Remove known-old server scripts
  2. Fetch origin refs
  3. Resolve the requested branch/ref/commit to an exact commit
  4. Check out that exact commit in detached HEAD
  5. Validate pyproject/lock/UI version integrity
  6. Sync Python dependencies (uv)
  7. Install Playwright Chromium browser + OS system libraries
  8. Install AWS browser session packages and helper commands
  9. Install repo-managed systemd service
 10. Run db_seed --upgrade
 11. Restart job-hunter.service
 12. Wait for health-check
HELP
  exit 0
fi

fail() {
  echo "REF DEPLOY BLOCKED: $*" >&2
  exit 1
}

resolve_ref_commit() {
  local input="$1"
  local -a candidates=()
  local candidate=""
  local commit=""

  if [[ "$input" == origin/* ]]; then
    candidates+=("refs/remotes/$input")
  fi
  candidates+=("refs/remotes/origin/$input" "$input")

  for candidate in "${candidates[@]}"; do
    commit="$(git rev-parse -q --verify "${candidate}^{commit}" 2>/dev/null || true)"
    if [[ -n "$commit" ]]; then
      printf '%s\t%s\n' "$candidate" "$commit"
      return 0
    fi
  done

  return 1
}

DEPLOY_REF="${1:-$DEFAULT_REF}"
shift || true
[[ $# -eq 0 ]] || fail \
  "Latest deploy accepts exactly one branch, remote ref, or commit argument. Example: deploy-jobhunter-latest main"
[[ ! "$DEPLOY_REF" =~ $RELEASE_TAG_PATTERN ]] || fail \
  "Release tags are production-only. Use: deploy-jobhunter-release $DEPLOY_REF"

export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

echo "==> Job Hunter latest deploy $DEPLOY_REF"
echo "==> WARNING: latest deploys are for staging/debug only, not production"

cd "$APP_DIR"

[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail \
  "Working tree is not clean at $APP_DIR. Commit or discard local changes before deploying."

echo "==> Remove old server scripts"
for f in "${OLD_SERVER_SCRIPTS[@]}"; do
  [[ -f "$f" ]] && rm -f "$f" && echo "  removed: $f" || true
done

echo "==> Fetch origin refs"
git fetch --prune origin

resolved="$(resolve_ref_commit "$DEPLOY_REF" || true)"
[[ -n "$resolved" ]] || fail \
  "Could not resolve '$DEPLOY_REF' from origin refs or local reachable commits."
resolved_ref="${resolved%%$'\t'*}"
resolved_commit="${resolved#*$'\t'}"

echo "==> Check out resolved commit"
git checkout --detach "$resolved_commit"

echo "==> Verify internal version integrity"
python3 scripts/check-release-integrity.py \
  || fail "Checked-out code has inconsistent project/lock/UI version metadata."

deployed_commit="$(git rev-parse HEAD)"
[[ "$deployed_commit" == "$resolved_commit" ]] || fail \
  "Checked-out commit $deployed_commit does not match resolved commit $resolved_commit."
echo "  deploying ref:    $DEPLOY_REF"
echo "  resolved source:  $resolved_ref"
echo "  deploying commit: $deployed_commit"

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

echo "==> AWS browser session packages"
sudo bash "$APP_DIR/scripts/ec2/install-aws-browser-session.sh"

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

echo "==> Status"
sudo systemctl status "$SERVICE" --no-pager
sudo journalctl -u "$SERVICE" -n 30 --no-pager

echo "==> Health check"
for attempt in {1..20}; do
  if curl -fsSI "$HEALTH_URL" >/tmp/jobhunter-health-check.$$ 2>/dev/null; then
    head -3 /tmp/jobhunter-health-check.$$
    rm -f /tmp/jobhunter-health-check.$$
    echo "==> Done"
    exit 0
  fi
  sleep 2
done
rm -f /tmp/jobhunter-health-check.$$
echo "ERROR: Health check failed for $HEALTH_URL" >&2
exit 1
