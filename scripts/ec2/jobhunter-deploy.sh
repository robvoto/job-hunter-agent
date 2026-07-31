#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
DEFAULT_REF="${JOB_HUNTER_DEPLOY_DEFAULT_REF:-main}"
RELEASE_TAG_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+$'

fail() {
  echo "DEPLOY BLOCKED: $*" >&2
  exit 1
}

ensure_repo_ready_for_ref() {
  local target="$1"
  local branch="$target"

  cd "$APP_DIR"
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || fail "$APP_DIR is not a git repository."

  echo "==> Sync repo state"
  git fetch --prune origin

  if [[ "$branch" == origin/* ]]; then
    branch="${branch#origin/}"
  fi

  if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    echo "==> Re-anchor local repo to origin/$branch"
    git checkout -B "$branch" "origin/$branch"
    return 0
  fi

  if [[ "$target" == "$DEFAULT_REF" ]] && git show-ref --verify --quiet "refs/remotes/origin/$DEFAULT_REF"; then
    echo "==> Re-anchor local repo to origin/$DEFAULT_REF"
    git checkout -B "$DEFAULT_REF" "origin/$DEFAULT_REF"
    return 0
  fi

  echo "==> Repo sync note: '$target' is not a remote branch; continuing with ref deploy resolution"
}

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
  fail "jobhunter-deploy accepts at most one ref or tag argument."
fi

if [[ "$TARGET" =~ $RELEASE_TAG_PATTERN ]]; then
  exec bash "$APP_DIR/scripts/ec2/deploy-jobhunter.sh" "$TARGET"
fi

ensure_repo_ready_for_ref "$TARGET"
exec bash "$APP_DIR/scripts/ec2/deploy-jobhunter-ref.sh" "$TARGET"
