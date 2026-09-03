"""Fail the suite when merged task branches are left behind.

`.skills/git-lifecycle/SKILL.md` already requires deleting a task branch and
worktree once the work is in main, and `scripts/check-git-closure.sh` already
implements the check. Neither stopped seventeen stale worktrees accumulating,
because both rely on an agent choosing to run them at the right moment.

This test removes that choice. It runs on every `pytest` invocation, the same
enforcement model `tests/test_no_hardcoding.py` uses for managed labels.

Deliberately narrow: it only flags branches fully merged into main, which have
no reason to exist. Uncommitted work, unmerged branches and active worktrees are
normal mid-task states and are not touched here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTECTED = {"main", "master"}


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip(f"git unavailable or not a repository: {result.stderr.strip()}")
    return result.stdout


def test_no_local_branch_fully_merged_into_main_is_left_behind():
    # git marks the current branch with "*" and a branch checked out in another
    # worktree with "+"; strip either before comparing names.
    merged = {
        line.strip().lstrip("*+").strip()
        for line in _git("branch", "--merged", "main").splitlines()
        if line.strip()
    }
    stale = merged - PROTECTED

    # A worktree still holding a merged branch is not an excuse: post-merge
    # cleanup is `git worktree remove` followed by `git branch -d`. Excusing it
    # here is how the worktrees accumulated in the first place, and it would
    # disagree with scripts/check-git-closure.sh, which already flags it.
    assert not stale, (
        "These branches are fully merged into main and must be deleted "
        "(remove any worktree holding them, then git branch -d <name>), "
        f"per .skills/git-lifecycle post-merge cleanup: {sorted(stale)}"
    )
