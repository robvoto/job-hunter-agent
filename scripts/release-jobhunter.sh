#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Create a tested Job Hunter release from main.

Usage:
  ./scripts/release-jobhunter.sh patch
  ./scripts/release-jobhunter.sh minor
  ./scripts/release-jobhunter.sh major
  ./scripts/release-jobhunter.sh patch --dry-run

Meaning:
  patch  1.5.0 -> 1.5.1  Bug fix or small correction
  minor  1.5.0 -> 1.6.0  Backward-compatible functionality
  major  1.5.0 -> 2.0.0  Breaking change

The real release command:
  - requires a clean local main matching origin/main
  - requires the current pyproject version to match the latest release tag
  - updates pyproject.toml and uv.lock through `uv version`
  - validates package, lock, UI, and tag version ownership
  - runs the full unit suite and non-LLM Playwright E2E suite
  - commits the version, creates an annotated tag, and atomically pushes both

--dry-run runs the clean-tree, sync, integrity, unit, and E2E gates without
changing the version, committing, tagging, or pushing.
EOF
}

fail() {
  echo "RELEASE BLOCKED: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

bump=""
dry_run=0

while (($#)); do
  case "$1" in
    patch|minor|major)
      [[ -z "$bump" ]] || fail "Choose only one bump type: patch, minor, or major."
      bump="$1"
      ;;
    --dry-run)
      dry_run=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      fail "Unknown argument: $1"
      ;;
  esac
  shift
done

[[ -n "$bump" ]] || { usage >&2; fail "Choose patch, minor, or major."; }

require_command git
require_command uv

[[ "$(git branch --show-current)" == "main" ]] || fail "Switch to main before releasing."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail \
  "The working tree is not clean. Commit or discard all changes before releasing."

printf '%s\n' "==> Refresh GitHub main and release tags"
git fetch --tags origin main

local_head="$(git rev-parse HEAD)"
remote_head="$(git rev-parse origin/main)"
[[ "$local_head" == "$remote_head" ]] || fail \
  "Local main does not exactly match origin/main. Pull or push the intended main first."

current_version="$(uv version --short)"
latest_tag="$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-version:refname | head -n 1)"
[[ -n "$latest_tag" ]] || fail "No release tag exists. Create the initial release deliberately."
[[ "$latest_tag" == "v$current_version" ]] || fail \
  "Current project version $current_version does not match latest tag $latest_tag. Repair release metadata first."

echo "==> Validate current release metadata"
uv run python scripts/check-release-integrity.py \
  --expected-version "$current_version" \
  --tag "$latest_tag"

next_version="$(uv version --bump "$bump" --dry-run --short)"
echo "==> Planned release: v$current_version -> v$next_version"

run_tests() {
  echo "==> Unit tests"
  uv run pytest

  echo "==> Playwright E2E tests (non-LLM by default)"
  ./scripts/run-e2e.sh -q
}

if ((dry_run)); then
  run_tests
  echo "==> Dry run passed. No files, commits, tags, or remote branches were changed."
  exit 0
fi

rollback_version_files=1
cleanup_on_error() {
  exit_code=$?
  if ((exit_code != 0 && rollback_version_files)); then
    echo "==> Release failed before commit; restoring pyproject.toml and uv.lock" >&2
    git restore -- pyproject.toml uv.lock
  fi
  exit "$exit_code"
}
trap cleanup_on_error EXIT

echo "==> Update project version and lock"
uv version --bump "$bump" --no-sync
actual_version="$(uv version --short)"
[[ "$actual_version" == "$next_version" ]] || fail \
  "uv produced $actual_version, expected $next_version."

uv run python scripts/check-release-integrity.py --expected-version "$next_version"

unexpected_changes="$(
  git status --porcelain --untracked-files=all \
    | awk '{print $2}' \
    | grep -Ev '^(pyproject\.toml|uv\.lock)$' \
    || true
)"
[[ -z "$unexpected_changes" ]] || fail \
  "Version bump changed unexpected files: $unexpected_changes"

run_tests
uv run python scripts/check-release-integrity.py --expected-version "$next_version"

release_tag="v$next_version"
git rev-parse -q --verify "refs/tags/$release_tag" >/dev/null 2>&1 \
  && fail "Tag $release_tag already exists."

echo "==> Commit $release_tag"
git add pyproject.toml uv.lock
git commit -m "Release $release_tag"
rollback_version_files=0

echo "==> Create annotated tag $release_tag"
git tag -a "$release_tag" -m "Job Hunter $release_tag"

echo "==> Push main and $release_tag atomically"
git push --atomic origin main "$release_tag"

trap - EXIT
echo "==> Released $release_tag"
