#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
DEFAULT_REF="${JOB_HUNTER_DEPLOY_DEFAULT_REF:-main}"
RELEASE_TAG_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+$'

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<HELP
Single-command AWS deploy helper for Job Hunter.

Usage:
  jobhunter-deploy
  jobhunter-deploy main
  jobhunter-deploy <branch-or-sha>
  jobhunter-deploy vX.Y.Z

Defaults:
  - no argument deploys: ${DEFAULT_REF}
  - release tags call deploy-jobhunter
  - branches/commits call deploy-jobhunter-ref
HELP
  exit 0
fi

TARGET="${1:-$DEFAULT_REF}"
shift || true
if [[ $# -ne 0 ]]; then
  echo "DEPLOY BLOCKED: jobhunter-deploy accepts at most one ref or tag argument." >&2
  exit 1
fi

if [[ "$TARGET" =~ $RELEASE_TAG_PATTERN ]]; then
  exec bash "$APP_DIR/scripts/ec2/deploy-jobhunter.sh" "$TARGET"
fi

exec bash "$APP_DIR/scripts/ec2/deploy-jobhunter-ref.sh" "$TARGET"
