#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

usage() {
  cat <<'EOF'
Create a tested Job Hunter release from main.

Usage:
  ./scripts/release-jobhunter.sh patch
  ./scripts/release-jobhunter.sh patch --publish-main-first
  ./scripts/release-jobhunter.sh minor
  ./scripts/release-jobhunter.sh major
  ./scripts/release-jobhunter.sh patch --dry-run

Meaning:
  patch  X.Y.Z -> X.Y.(Z+1)  Bug fix or small correction
  minor  X.Y.Z -> X.(Y+1).0  Backward-compatible functionality
  major  X.Y.Z -> (X+1).0.0  Breaking change

The real release command:
  - requires a clean local main matching origin/main
  - can optionally push an ahead-only local main first with --publish-main-first
  - requires the current pyproject version to match the latest release tag
  - allows unreleased ordinary commits after the latest tag while version files stay unchanged
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
publish_main_first=0

while (($#)); do
  case "$1" in
    patch|minor|major)
      [[ -z "$bump" ]] || fail "Choose only one bump type: patch, minor, or major."
      bump="$1"
      ;;
    --dry-run)
      dry_run=1
      ;;
    --publish-main-first)
      publish_main_first=1
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
if [[ "$local_head" != "$remote_head" ]]; then
  read -r ahead_count behind_count <<<"$(git rev-list --left-right --count HEAD...origin/main)"

  if ((publish_main_first)); then
    ((dry_run == 0)) || fail \
      "--publish-main-first cannot be combined with --dry-run because dry-run must not change GitHub."

    if ((behind_count > 0)); then
      fail \
        "Local main is behind or diverged from origin/main. Pull/rebase first, then rerun the release."
    fi
    if ((ahead_count <= 0)); then
      fail \
        "Local main does not contain releasable commits ahead of origin/main."
    fi

    echo "==> Publish ahead-only local main before release"
    git push origin "$local_head:refs/heads/main"
    git fetch --tags origin main
    remote_head="$(git rev-parse origin/main)"
    [[ "$local_head" == "$remote_head" ]] || fail \
      "Failed to synchronize origin/main to the intended local main commit."
  else
    fail "Local main does not exactly match origin/main. Pull or push the intended main first."
  fi
fi

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
  echo "==> Run unit and Playwright E2E release gates"
  # The two suites use isolated test state, so they can run concurrently. Unit
  # tests use xdist internally; Playwright E2E itself remains sequential because
  # its browser fixtures share candidate/workspace state within that suite.
  unit_log="$(mktemp)"
  e2e_log="$(mktemp)"

  set +e
  (
    echo "==> Unit tests"
    uv run pytest -n 6
  ) >"$unit_log" 2>&1 &
  unit_pid=$!

  (
    echo "==> Playwright E2E tests (non-LLM by default)"
    ./scripts/run-e2e.sh -q
  ) >"$e2e_log" 2>&1 &
  e2e_pid=$!

  wait "$unit_pid"
  unit_status=$?
  wait "$e2e_pid"
  e2e_status=$?
  set -e

  cat "$unit_log"
  cat "$e2e_log"
  rm -f "$unit_log" "$e2e_log"

  ((unit_status == 0)) || fail "Unit test release gate failed."
  ((e2e_status == 0)) || fail "Playwright E2E release gate failed."
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

rollback_version_files=1
release_tag=""
release_tag_created=0
cleanup_on_error() {
  exit_code=$?
  if ((exit_code != 0)); then
    if ((release_tag_created)) && [[ -n "$release_tag" ]]; then
      echo "==> Release failed after tag creation; removing local tag $release_tag" >&2
      git tag -d "$release_tag" >/dev/null 2>&1 || true
    fi
    if ((rollback_version_files)); then
      echo "==> Release failed before commit; restoring pyproject.toml and uv.lock" >&2
      git restore -- pyproject.toml uv.lock
    fi
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

assert_only_version_files_changed

run_tests
assert_release_base_unchanged
assert_only_version_files_changed
uv run python scripts/check-release-integrity.py --expected-version "$next_version"

release_tag="v$next_version"
git rev-parse -q --verify "refs/tags/$release_tag" >/dev/null 2>&1 \
  && fail "Tag $release_tag already exists."

echo "==> Commit $release_tag"
git add pyproject.toml uv.lock
git commit -m "Release $release_tag"
rollback_version_files=0

release_commit="$(git rev-parse HEAD)"
echo "==> Create annotated tag $release_tag"
git tag -a "$release_tag" "$release_commit" -m "Job Hunter $release_tag"
release_tag_created=1

[[ "$(git rev-parse HEAD)" == "$release_commit" ]] || fail \
  "Local HEAD changed after the release commit. Another agent may have committed; do not publish this release."
[[ -z "$(git status --porcelain --untracked-files=all)" ]] || fail \
  "The working tree changed after the release commit. Another agent may be editing it."

echo "==> Push exact release commit and $release_tag atomically"
git push --atomic origin "$release_commit:refs/heads/main" "refs/tags/$release_tag"

trap - EXIT
echo "==> Released $release_tag"
