---
name: git-lifecycle
description: Use for branch/worktree setup, commit, push, pull request, merge/integration, main verification, and Git cleanup.
---

# Skill: Git Lifecycle

Use for any branch/worktree, commit, push, PR, merge, or `main` integration work.

## Contract

- Work intended for `main` uses: **task branch/worktree -> implement -> validate -> commit -> push -> human/code review and iteration -> final validation -> merge-ready approval -> PR -> integration review -> merge -> cleanup**.
- Commits come before PRs so the human can inspect and test stable checkpoints while work is still being refined.
- A PR is the final integration handoff. Do not create one merely because the first commit is green or the branch has been pushed.
- The authoring agent owns implementation, validation, commits, pushes, and review/fix iterations until the work is explicitly ready to merge. The integration owner takes over once the PR exists.
- The authoring agent does not normally merge its own PR. If no integration owner is available, leave the merge-ready PR open.
- Do not directly merge or push a normal task branch to `main`.
- Disposable experiment branches that are abandoned rather than integrated do not need a PR.
- `commit` or `push` never means the work is in `main`.
- Git approval does not imply runtime lifecycle or deployment approval; follow `docs/PROJECT_CONTEXT.md` and `release-management` for those concerns.

## Before editing

1. Fetch `origin`.
2. Inspect branch/worktree, `git status`, `HEAD`, and `origin/main`.
3. Preserve unrelated dirty work; never stash, reset, overwrite, or commit another agent's changes without coordination.
4. When concurrent work is possible, use an isolated task worktree based on current `origin/main`.

## Authoring agent

1. Implement only the task scope and run the required validation.
2. Commit each stable checkpoint and push the task branch without force so the human can inspect/test it.
3. Report the branch and commit SHA. While the human is checking the work, continue fixes as additional commits on the same task branch.
4. **Do not create a PR while implementation, UI checking, code review, or user acceptance is still in progress.**
5. Do not create a PR until the human has explicitly confirmed the review/test checkpoint is good and the work is ready for merge handoff (for example: `create the PR`, `ready to merge`, or equivalent). Then fetch `origin`, reconcile clear drift, and run final validation on the merge-ready branch.
6. Only after that explicit confirmation and final validation, create the PR targeting `main`, report its number/URL, and hand off to the integration owner.
7. Stop at `MAIN STATUS: NOT IN MAIN — pushed branch <branch>` until integration completes.

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
