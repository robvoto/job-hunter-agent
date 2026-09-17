#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${JOB_HUNTER_APP_DIR:-/home/ubuntu/job-hunter-agent}"
ENV_FILE="${JOB_HUNTER_ENV_FILE:-/etc/job-hunter/job-hunter.env}"
SERVICE="${JOB_HUNTER_SERVICE:-job-hunter}"
BACKUP_ROOT="${JOB_HUNTER_DEPLOY_BACKUP_ROOT:-/var/lib/job-hunter/backups}"
STATE_DIR="${JOB_HUNTER_DEPLOY_STATE_DIR:-/var/lib/job-hunter/deployments}"
BACKUP_KEEP="${JOB_HUNTER_DEPLOY_BACKUP_KEEP:-5}"
RELEASE_TAG_PATTERN='^v[0-9]+\.[0-9]+\.[0-9]+$'

fail() {
  echo "PRODUCTION DEPLOY BLOCKED: $*" >&2
  exit 1
}

TARGET_RELEASE="${1:-}"
[[ "$TARGET_RELEASE" =~ $RELEASE_TAG_PATTERN ]] || fail "usage: deploy-jobhunter-production vMAJOR.MINOR.PATCH"
shift || true
[[ $# -eq 0 ]] || fail "exactly one release tag is required"

cd "$APP_DIR"
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail "working tree is not clean: $APP_DIR"
[[ -f "$ENV_FILE" ]] || fail "missing environment file: $ENV_FILE"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
DATA_DIR="${JOB_HUNTER_DATA_DIR:-/var/lib/job-hunter/data}"
[[ "$BACKUP_KEEP" =~ ^[1-9][0-9]*$ ]] || fail "JOB_HUNTER_DEPLOY_BACKUP_KEEP must be a positive integer"

sudo mkdir -p "$BACKUP_ROOT" "$STATE_DIR"
sudo chown ubuntu:ubuntu "$BACKUP_ROOT" "$STATE_DIR"

current_release=""
if [[ -s "$STATE_DIR/current-release" ]]; then
  current_release="$(tr -d '[:space:]' < "$STATE_DIR/current-release")"
fi
if [[ -z "$current_release" ]]; then
  current_release="$(git describe --tags --exact-match HEAD 2>/dev/null || true)"
fi
[[ "$current_release" =~ $RELEASE_TAG_PATTERN ]] || fail \
  "current AWS revision is not a recorded release tag; establish a known-good release before production deploy"
actual_release="$(git describe --tags --exact-match HEAD 2>/dev/null || true)"
[[ "$actual_release" == "$current_release" ]] || fail \
  "recorded current release $current_release does not match deployed revision ${actual_release:-untagged}"
[[ "$current_release" != "$TARGET_RELEASE" ]] || fail "$TARGET_RELEASE is already the current release"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="$BACKUP_ROOT/pre-deploy-$timestamp-$current_release"
sudo mkdir -p "$backup_dir"
sudo chown ubuntu:ubuntu "$backup_dir"

echo "==> Snapshot runtime data"
sudo systemctl stop "$SERVICE"
snapshot_ok=false
if sudo tar -C "$(dirname "$DATA_DIR")" -czf "$backup_dir/data.tar.gz" "$(basename "$DATA_DIR")"; then
  snapshot_ok=true
fi
sudo systemctl start "$SERVICE"
$snapshot_ok || fail "runtime snapshot failed"
sha256sum "$backup_dir/data.tar.gz" > "$backup_dir/data.tar.gz.sha256"
printf '%s\n' "$current_release" > "$backup_dir/previous-release"
printf '%s\n' "$TARGET_RELEASE" > "$backup_dir/target-release"

rollback_code_only() {
  echo "==> Rolling back code to $current_release"
  /usr/local/bin/deploy-jobhunter-release "$current_release" && \
    /usr/local/bin/smoke-jobhunter-production
}

restore_snapshot_and_rollback() {
  echo "==> Restoring runtime snapshot and $current_release"
  sudo systemctl stop "$SERVICE" || true
  sudo rm -rf "$DATA_DIR"
  sudo tar -C "$(dirname "$DATA_DIR")" -xzf "$backup_dir/data.tar.gz"
  sudo chown -R ubuntu:ubuntu "$DATA_DIR"
  /usr/local/bin/deploy-jobhunter-release "$current_release"
  /usr/local/bin/smoke-jobhunter-production
}

deploy_failed=false
if ! /usr/local/bin/deploy-jobhunter-release "$TARGET_RELEASE"; then
  deploy_failed=true
elif ! /usr/local/bin/smoke-jobhunter-production; then
  deploy_failed=true
fi

if $deploy_failed; then
  echo "==> New release failed validation; automatic rollback started" >&2
  if rollback_code_only; then
    printf '%s\n' "$current_release" > "$STATE_DIR/current-release"
    printf '%s\n' "$backup_dir" > "$STATE_DIR/last-backup"
    fail "$TARGET_RELEASE failed; restored $current_release using current runtime data"
  fi
  if restore_snapshot_and_rollback; then
    printf '%s\n' "$current_release" > "$STATE_DIR/current-release"
    printf '%s\n' "$backup_dir" > "$STATE_DIR/last-backup"
    fail "$TARGET_RELEASE failed; restored $current_release and the pre-deploy runtime snapshot"
  fi
  fail "$TARGET_RELEASE failed and automatic rollback did not recover production"
fi

printf '%s\n' "$current_release" > "$STATE_DIR/previous-release"
printf '%s\n' "$TARGET_RELEASE" > "$STATE_DIR/current-release"
printf '%s\n' "$backup_dir" > "$STATE_DIR/last-backup"

mapfile -t old_backups < <(ls -1dt "$BACKUP_ROOT"/pre-deploy-* 2>/dev/null | tail -n "+$((BACKUP_KEEP + 1))" || true)
if ((${#old_backups[@]})); then
  sudo rm -rf -- "${old_backups[@]}"
fi

echo "Production deploy passed: $current_release -> $TARGET_RELEASE"
echo "Snapshot: $backup_dir"
