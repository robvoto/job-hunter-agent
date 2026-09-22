"""Enforce post-merge cleanup of local task branches.

Dirty or explicitly locked worktrees remain exempt because deleting them could
destroy active work.
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



def _branches_with_work_in_progress() -> set[str]:
    """Branches whose worktree is still in use, so the branch cannot be deleted.

    Two signals, both explicit:

    * locked - a session has deliberately marked the worktree as in use.
    * dirty  - the worktree holds uncommitted changes.

    `.agents/skills/git-lifecycle` says outright that a worktree with modified, staged,
    conflicted or untracked files must not be deleted, and that its work must
    never be discarded to make cleanup pass. Flagging those here would push
    exactly that. `scripts/check-git-closure.sh` still reports them, so they stay
    visible; they just do not fail an unrelated test run.
    """
    in_use: set[str] = set()
    branch: str | None = None
    path: str | None = None

    def _finish() -> None:
        if not branch or not path:
            return
        if subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip():
            in_use.add(branch)

    for line in _git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            _finish()
            branch, path = None, line.split(" ", 1)[1].strip()
        elif line.startswith("branch "):
            branch = line.split("/", 2)[-1].strip()
        elif line.startswith("locked") and branch:
            in_use.add(branch)
    _finish()
    return in_use


def test_no_local_branch_fully_merged_into_main_is_left_behind():
    # git marks the current branch with "*" and a branch checked out in another
    # worktree with "+"; strip either before comparing names.
    merged = {
        line.strip().lstrip("*+").strip()
        for line in _git("branch", "--merged", "main").splitlines()
        if line.strip()
    }
    stale = merged - PROTECTED - _branches_with_work_in_progress()

    # Merely having a worktree is not an excuse: post-merge cleanup is
    # `git worktree remove` followed by `git branch -d`, and excusing every
    # worktree is how they accumulated in the first place.
    #
    # A worktree that is locked or dirty is different: a session is working in
    # it, and deleting it would destroy uncommitted work. The exemption lasts
    # exactly as long as that state - once the work is committed and the
    # worktree is clean and unlocked, the branch is flagged again.
    assert not stale, (
        "These branches are fully merged into main and must be deleted "
        "(remove any worktree holding them, then git branch -d <name>), "
        f"per .agents/skills/git-lifecycle post-merge cleanup: {sorted(stale)}"
    )
