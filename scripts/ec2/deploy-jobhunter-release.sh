#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
ENV_FILE="${JOB_HUNTER_ENV_FILE:-/etc/job-hunter/job-hunter.env}"
SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
HEALTH_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"
RELEASE_TAG_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+$'

# Old one-off scripts that used to live on the server but are no longer needed.
OLD_SERVER_SCRIPTS=(
  "$APP_DIR/scripts/ec2/restartServer.sh"
  "$APP_DIR/scripts/ec2/start-ngrok.sh"
  "$APP_DIR/scripts/ec2/status-ngrok.sh"
  "$APP_DIR/scripts/ec2/stop-ngrok.sh"
)

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<HELP
Deploy an explicit Job Hunter release tag on AWS EC2.

Usage:
  deploy-jobhunter-release vX.Y.Z

Examples:
  deploy-jobhunter-release v1.5.2

Notes:
  - This command is for production release tags only.
  - To deploy latest branch or commit code for testing, use: deploy-jobhunter-latest [branch-or-sha]

Steps:
  1. Remove known-old server scripts
  2. Fetch and verify the requested GitHub release tag
  3. Check out the exact tagged commit
  4. Sync Python dependencies (uv)
  5. Install Playwright Chromium browser + OS system libraries
  6. Install AWS browser session packages and launcher scripts
  7. Install repo-managed helper commands into /usr/local/bin
  8. Install repo-managed systemd service (AWS browser session wrapper)
  9. Run db_seed --upgrade
 10. Restart job-hunter.service
 11. Startup rebuild refreshes saved workspace output
 12. Wait for health-check
HELP
  exit 0
fi

fail() {
  echo "DEPLOY BLOCKED: $*" >&2
  exit 1
}

RELEASE_TAG="${1:-}"
[[ -n "$RELEASE_TAG" ]] || fail \
  "Missing release tag. Example: deploy-jobhunter-release v1.5.2"
shift || true
[[ $# -eq 0 ]] || fail \
  "Deploy accepts exactly one release tag argument. Example: deploy-jobhunter-release v1.5.2"
[[ "$RELEASE_TAG" =~ $RELEASE_TAG_PATTERN ]] || fail \
  "Release tag must use vMAJOR.MINOR.PATCH format. Example: deploy-jobhunter-release v1.5.2"

# uv installs per-user; ensure it's on PATH
export PATH="$HOME/.local/bin:/usr/local/bin:$PATH"

echo "==> Job Hunter deploy $RELEASE_TAG"

cd "$APP_DIR"

[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail \
  "Working tree is not clean at $APP_DIR. Commit or discard local changes before deploying."

echo "==> Remove old server scripts"
for f in "${OLD_SERVER_SCRIPTS[@]}"; do
  [[ -f "$f" ]] && rm -f "$f" && echo "  removed: $f" || true
done

echo "==> Fetch exact release tag"
remote_tag_ref="refs/tags/$RELEASE_TAG"
git ls-remote --tags --refs origin "$remote_tag_ref" | grep -q "$remote_tag_ref" \
  || fail "Remote tag $RELEASE_TAG does not exist on origin."
git fetch origin "$remote_tag_ref:$remote_tag_ref"

tag_commit="$(git rev-parse "${RELEASE_TAG}^{commit}")"

echo "==> Check out tagged commit"
git checkout --detach "$tag_commit"

echo "==> Verify tag matches project version"
python3 scripts/check-release-integrity.py --expected-version "${RELEASE_TAG#v}" --tag "$RELEASE_TAG" \
  || fail "Checked-out code does not match release tag $RELEASE_TAG."

deployed_commit="$(git rev-parse HEAD)"
[[ "$deployed_commit" == "$tag_commit" ]] || fail \
  "Checked-out commit $deployed_commit does not match tag commit $tag_commit."
echo "  deploying tag:    $RELEASE_TAG"
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
