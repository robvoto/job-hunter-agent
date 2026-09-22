---
name: git-lifecycle
description: Use for branch/worktree setup, commit, push, pull request, merge/integration, main verification, and Git cleanup.
---

# Skill: Git Lifecycle

Use for any branch/worktree, commit, push, PR, merge, or `main` integration work.

## Contract

- Work intended for `main` uses: **task branch/worktree -> validate -> commit -> push -> PR -> integration review -> merge -> cleanup**.
- The authoring agent owns implementation through PR creation. The integration owner owns PR review, merge, verification, and cleanup.
- The authoring agent does not normally merge its own PR. If no integration owner is available, leave the PR open.
- Do not directly merge or push a normal task branch to `main`.
- Disposable experiment branches that are abandoned rather than integrated do not need a PR.
- `commit` or `push` never means the work is in `main`.
- If integration intent is unclear and the session is not explicitly acting as integration owner, ask once before merging.
- Git approval does not imply runtime lifecycle or deployment approval; follow `docs/PROJECT_CONTEXT.md` and `release-management` for those concerns.

## Before editing

1. Fetch `origin`.
2. Inspect branch/worktree, `git status`, `HEAD`, and `origin/main`.
3. Preserve unrelated dirty work; never stash, reset, overwrite, or commit another agent's changes without coordination.
4. When concurrent work is possible, use an isolated task worktree based on current `origin/main`.

## Authoring agent

1. Implement only the task scope and run the required validation.
2. Commit the validated change.
3. Fetch `origin` again and inspect drift from `origin/main`.
4. Push the task branch without force.
5. Create a PR targeting `main` and report its number/URL.
6. Stop at `MAIN STATUS: NOT IN MAIN — pushed branch <branch>` unless this session is separately assigned integration ownership for a different author's PR.

## Integration owner

1. Fetch `origin`; inspect the PR diff, task SHA, current `origin/main`, mergeability, and required checks.
2. If `origin/main` moved, reconcile only clear/safe drift. Return ambiguous conflicts or ownership questions to the author/human.
3. If both sides changed versioned managed JSON, ensure the integrated version is greater than current `origin/main` when content changes.
4. Run required local validation and wait for hosted PR checks/CI.
5. Merge through the repository PR mechanism using the documented strategy; otherwise prefer a normal non-force merge.
6. Fetch `origin` and verify the task SHA is an ancestor of `origin/main`.

## Post-merge cleanup

1. Re-check the task worktree. Never delete a dirty/unmerged worktree.
2. Remove the clean task worktree.
3. Delete the merged local and remote task branches.
4. Run `git worktree prune`.
5. Run `./scripts/check-git-closure.sh --task-sha <sha> --branch <branch> --worktree <path>`.
6. For repository-wide cleanup/`merge all`, add `--strict-repo`.

`tests/test_git_hygiene.py` enforces removal of clean local branches already merged into `main`.

## Reporting

End Git work with:

- `MAIN STATUS: NOT IN MAIN — <uncommitted|committed on branch|pushed branch>`; or
- `MAIN STATUS: IN MAIN — verified on origin/main at <sha>`.

For integrated work also report:

- `CLEANUP STATUS: COMPLETE — merged task worktree removed`; or `BLOCKED — <reason>`.
- `BRANCH STATUS: DELETED — local and remote task branches removed`; or `RETAINED — <reason>`.

Do not call the whole repository clean unless every active worktree was checked and the shared checkout is current with `origin/main`.
