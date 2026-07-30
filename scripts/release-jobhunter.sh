#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Create a tested Job Hunter release from main.

Usage:
  ./scripts/release-jobhunter.sh current
  ./scripts/release-jobhunter.sh patch
  ./scripts/release-jobhunter.sh minor
  ./scripts/release-jobhunter.sh major
  ./scripts/release-jobhunter.sh patch --dry-run

Meaning:
  current  Publish the version already declared in pyproject.toml without bumping it
  patch    1.5.0 -> 1.5.1  Bug fix or small correction
  minor    1.5.0 -> 1.6.0  Backward-compatible functionality
  major    1.5.0 -> 2.0.0  Breaking change

Use `current` only when the application version was intentionally updated but
its matching release tag has not been published yet.

The real release command:
  - requires a clean local main matching origin/main
  - validates pyproject.toml, uv.lock, UI metadata, and release-tag history
  - updates pyproject.toml and uv.lock through `uv version` for version bumps
  - runs the full unit suite and non-LLM Playwright E2E suite
  - aborts if another agent changes local HEAD, origin/main, or unrelated files
  - creates an annotated tag and atomically pushes the exact release commit

--dry-run runs all applicable gates without changing the version, committing,
tagging, or pushing.
EOF
}

fail() {
  echo "RELEASE BLOCKED: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

version_is_greater() {
  local left_major left_minor left_patch right_major right_minor right_patch
  IFS=. read -r left_major left_minor left_patch <<<"$1"
  IFS=. read -r right_major right_minor right_patch <<<"$2"
  ((
    left_major > right_major
    || (left_major == right_major && left_minor > right_minor)
    || (left_major == right_major && left_minor == right_minor && left_patch > right_patch)
  ))
}

mode=""
dry_run=0

while (($#)); do
  case "$1" in
    current|patch|minor|major)
      [[ -z "$mode" ]] || fail "Choose only one release mode: current, patch, minor, or major."
      mode="$1"
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

[[ -n "$mode" ]] || { usage >&2; fail "Choose current, patch, minor, or major."; }

require_command git
require_command uv

[[ "$(git branch --show-current)" == "main" ]] || fail "Switch to main before releasing."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail \
  "The working tree is not clean. Commit or discard all changes before releasing."

echo "==> Refresh GitHub main and release tags"
git fetch --tags origin main

local_head="$(git rev-parse HEAD)"
remote_head="$(git rev-parse origin/main)"
[[ "$local_head" == "$remote_head" ]] || fail \
  "Local main does not exactly match origin/main. Push or pull the intended main first."

current_version="$(uv version --short)"
latest_tag="$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-version:refname | head -n 1)"

if [[ "$mode" == "current" ]]; then
  next_version="$current_version"
  release_tag="v$current_version"
  git rev-parse -q --verify "refs/tags/$release_tag" >/dev/null 2>&1 \
    && fail "Tag $release_tag already exists."
  if [[ -n "$latest_tag" ]]; then
    latest_version="${latest_tag#v}"
    version_is_greater "$current_version" "$latest_version" || fail \
      "Current project version $current_version must be newer than latest tag $latest_tag."
  fi
  echo "==> Validate current release metadata"
  uv run python scripts/check-release-integrity.py --expected-version "$current_version"
  echo "==> Planned release: publish existing $release_tag"
else
  [[ -n "$latest_tag" ]] || fail \
    "No release tag exists. Use `current` to publish the intentionally declared initial version."
  [[ "$latest_tag" == "v$current_version" ]] || fail \
    "Current project version $current_version does not match latest tag $latest_tag. Use `current` only if the newer version is intentional."

  echo "==> Validate current release metadata"
  uv run python scripts/check-release-integrity.py \
    --expected-version "$current_version" \
    --tag "$latest_tag"

  next_version="$(uv version --bump "$mode" --dry-run --short)"
  release_tag="v$next_version"
  echo "==> Planned release: v$current_version -> $release_tag"
fi

run_tests() {
  echo "==> Unit tests"
  uv run pytest

  echo "==> Playwright E2E tests (non-LLM by default)"
  ./scripts/run-e2e.sh -q
}

assert_release_base_unchanged() {
  current_head="$(git rev-parse HEAD)"
  [[ "$current_head" == "$local_head" ]] || fail \
    "Local HEAD changed while release checks were running. Another agent may have committed; restart the release."

  git fetch origin main
  current_remote_head="$(git rev-parse origin/main)"
  [[ "$current_remote_head" == "$remote_head" ]] || fail \
    "origin/main changed while release checks were running. Refresh main and restart the release."
}

assert_only_version_files_changed() {
  unexpected_changes="$(
    git status --porcelain --untracked-files=all \
      | awk '{print $2}' \
      | grep -Ev '^(pyproject\.toml|uv\.lock)$' \
      || true
  )"
  [[ -z "$unexpected_changes" ]] || fail \
    "Unexpected files changed during release checks: $unexpected_changes"
}

if ((dry_run)); then
  run_tests
  assert_release_base_unchanged
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail \
    "The working tree changed while release checks were running. Another agent may be editing it."
  echo "==> Dry run passed. No files, commits, tags, or remote branches were changed."
  exit 0
fi

rollback_version_files=0
created_tag=""
cleanup_on_error() {
  exit_code=$?
  if ((exit_code != 0)); then
    if ((rollback_version_files)); then
      echo "==> Release failed before commit; restoring pyproject.toml and uv.lock" >&2
      git restore -- pyproject.toml uv.lock
    fi
    if [[ -n "$created_tag" ]]; then
      git tag -d "$created_tag" >/dev/null 2>&1 || true
    fi
  fi
  exit "$exit_code"
}
trap cleanup_on_error EXIT

if [[ "$mode" == "current" ]]; then
  run_tests
  assert_release_base_unchanged
  [[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail \
    "The working tree changed while release checks were running. Another agent may be editing it."
  uv run python scripts/check-release-integrity.py --expected-version "$next_version"
  release_commit="$local_head"
else
  rollback_version_files=1
  echo "==> Update project version and lock"
  uv version --bump "$mode" --no-sync
  actual_version="$(uv version --short)"
  [[ "$actual_version" == "$next_version" ]] || fail \
    "uv produced $actual_version, expected $next_version."

  uv run python scripts/check-release-integrity.py --expected-version "$next_version"
  assert_only_version_files_changed

  run_tests
  assert_release_base_unchanged
  assert_only_version_files_changed
  uv run python scripts/check-release-integrity.py --expected-version "$next_version"

  git rev-parse -q --verify "refs/tags/$release_tag" >/dev/null 2>&1 \
    && fail "Tag $release_tag already exists."

  echo "==> Commit $release_tag"
  git add pyproject.toml uv.lock
  git commit -m "Release $release_tag"
  rollback_version_files=0
  release_commit="$(git rev-parse HEAD)"
fi

echo "==> Create annotated tag $release_tag"
git tag -a "$release_tag" "$release_commit" -m "Job Hunter $release_tag"
created_tag="$release_tag"

[[ "$(git rev-parse HEAD)" == "$release_commit" ]] || fail \
  "Local HEAD changed after the release commit. Another agent may have committed; do not publish this release."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail \
  "The working tree changed after the release commit. Another agent may be editing it."

echo "==> Push exact release commit and $release_tag atomically"
git push --atomic origin "$release_commit:refs/heads/main" "refs/tags/$release_tag"
created_tag=""

trap - EXIT
echo "==> Released $release_tag"
