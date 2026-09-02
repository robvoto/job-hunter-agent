#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

task_sha=""
branch=""
worktree=""
strict_repo=false

while (($#)); do
  case "$1" in
    --task-sha) task_sha="${2:?missing value}"; shift 2 ;;
    --branch) branch="${2:?missing value}"; shift 2 ;;
    --worktree) worktree="${2:?missing value}"; shift 2 ;;
    --strict-repo) strict_repo=true; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

git fetch origin --prune >/dev/null
fail=0

if [[ -n "$task_sha" ]] && ! git merge-base --is-ancestor "$task_sha" origin/main; then
  echo "FAIL: task commit $task_sha is not in origin/main" >&2
  fail=1
fi

if [[ -n "$branch" ]]; then
  if git show-ref --verify --quiet "refs/heads/$branch"; then
    echo "FAIL: local task branch still exists: $branch" >&2
    fail=1
  fi
  if git show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    echo "FAIL: remote task branch still exists: origin/$branch" >&2
    fail=1
  fi
fi

if [[ -n "$worktree" ]] && git worktree list --porcelain | grep -Fxq "worktree $worktree"; then
  echo "FAIL: task worktree still exists: $worktree" >&2
  fail=1
fi

if $strict_repo; then
  while IFS= read -r wt; do
    [[ -z "$wt" ]] && continue
    if [[ -n "$(git -C "$wt" status --porcelain)" ]]; then
      echo "FAIL: dirty worktree: $wt" >&2
      fail=1
    fi
  done < <(git worktree list --porcelain | awk '$1=="worktree"{print $2}')

  while IFS= read -r merged_branch; do
    [[ -z "$merged_branch" ]] && continue
    case "$merged_branch" in
      main|rescue/*) continue ;;
    esac
    echo "FAIL: merged local branch still exists: $merged_branch" >&2
    fail=1
  done < <(git for-each-ref --format='%(refname:short)' --merged=origin/main refs/heads)
fi

if ((fail)); then
  exit 1
fi

echo "Git closure check passed."
