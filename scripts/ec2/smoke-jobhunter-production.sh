#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
ENV_FILE="${JOB_HUNTER_ENV_FILE:-/etc/job-hunter/job-hunter.env}"
SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
LOCAL_URL="${JOB_HUNTER_HEALTH_URL:-http://127.0.0.1:8765/start}"

fail() {
  echo "SMOKE FAILED: $*" >&2
  exit 1
}

systemctl is-active --quiet "$SERVICE" || fail "$SERVICE is not active"

local_headers="$(mktemp)"
local_body="$(mktemp)"
trap 'rm -f "$local_headers" "$local_body"' EXIT

curl -fsS --max-time 20 -D "$local_headers" -o /dev/null "$LOCAL_URL" || fail "local HTTP check failed: $LOCAL_URL"

cd "$APP_DIR"
[[ -f "$ENV_FILE" ]] || fail "missing environment file: $ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

export JOB_HUNTER_DATA_DIR="${JOB_HUNTER_DATA_DIR:-/var/lib/job-hunter/data}"
export JOB_HUNTER_OUTPUT_DIR="${JOB_HUNTER_OUTPUT_DIR:-/var/lib/job-hunter/output}"
export JOB_HUNTER_DB_PATH="${JOB_HUNTER_DB_PATH:-/var/lib/job-hunter/data/job_hunter.db}"

uv run python - <<'PY'
from job_hunter_agent.global_settings import load_global_settings
from job_hunter_agent.io_utils import load_ui_labels
from job_hunter_agent.server_helpers import load_global_settings_labels

load_global_settings()
load_ui_labels()
load_global_settings_labels()
print("managed runtime validation: ok")
PY

public_url="${JOB_HUNTER_BASE_URL:-}"
if [[ -n "$public_url" ]]; then
  curl -fsSL --max-time 20 "${public_url%/}/" -o "$local_body" || fail "public HTTP check failed: $public_url"
  grep -qi "Job Hunter" "$local_body" || fail "public response is not Job Hunter"
fi

echo "Production smoke test passed."
