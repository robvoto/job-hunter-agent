---
name: git-lifecycle
description: Use for branch/worktree setup, commit, push, pull request, merge/integration, main verification, and Git cleanup.
---

# Skill: Git Lifecycle

Use for any branch/worktree, commit, push, PR, merge, or `main` integration work.

## Contract

- Work intended for `main` uses: **task branch/worktree -> implement -> validate -> commit -> push -> human review/test and iteration -> final validation -> explicitly authorized integration -> cleanup**.
- Commits and pushes provide stable checkpoints for the human to inspect and test. Keep review changes on the same task branch unless there is a concrete reason to split the work.
- Do not create a PR or integrate the work while implementation or the human's review/test is still in progress.
- A PR is optional. Create one only when the human requests it or repository rules require it. Do not infer a PR request from a pushed branch or from the human saying the work is ready.
- When the human explicitly asks to merge or put the reviewed work in `main`, integrate it directly without a PR unless repository rules require a PR. Do not ask for another approval for the same requested integration.
- If the human approves the review but has not directed integration, keep the branch out of `main` and wait for their integration instruction.
- The authoring agent may perform a safe direct integration after that explicit instruction. If a PR is requested or required, create it only after review is complete and final validation passes, then hand off to the integration owner.
- Never push a normal task branch directly to `main`; direct integration means merging the task branch into current `main`, validating the result, then pushing `main` without force.
- If branch protection, required checks, or repository rules prevent direct integration, follow those rules and report the specific constraint. Never bypass them.
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
5. After review, wait for an explicit integration instruction before changing `main`. A review approval alone does not authorize integration.
6. If the human requests a PR, or repository rules require one, fetch `origin`, reconcile clear drift, run final validation, then create the PR targeting `main` and report its number/URL. Hand it to the integration owner when one is assigned.
7. If the human explicitly requests direct integration and repository rules allow it, follow the direct integration procedure below. Do not create a PR as an extra approval step.
8. Until integration completes, report `MAIN STATUS: NOT IN MAIN — pushed branch <branch>`.

## Direct integration without a PR

1. Fetch `origin`; inspect the task diff and SHA, current `origin/main`, and required checks.
2. If `origin/main` moved, reconcile only clear/safe drift. Return ambiguous conflicts or ownership questions to the human.
3. If both sides changed versioned managed JSON, ensure the integrated version is greater than current `origin/main` when content changes.
4. Merge the task branch into current `main` using the documented strategy; otherwise use a normal non-force merge that preserves both histories. Stop on conflicts or failed checks that cannot be resolved safely.
5. Run required validation on the integrated result, then push `main` without force. If the push is rejected because the remote moved, fetch and reassess; never bypass the rejection with force.
6. Fetch `origin` and verify the task SHA is an ancestor of `origin/main`.

## PR integration owner

1. Fetch `origin`; inspect the PR diff, task SHA, current `origin/main`, mergeability, and required checks.
2. If `origin/main` moved, reconcile only clear/safe drift. Return ambiguous conflicts or ownership questions to the author/human.
3. If both sides changed versioned managed JSON, ensure the integrated version is greater than current `origin/main` when content changes.
4. Run required local validation and wait for hosted PR checks/CI.
5. Merge through the repository PR mechanism using the documented strategy.
6. Fetch `origin` and verify the task SHA is an ancestor of `origin/main`.

## Closed or abandoned PR cleanup

- A closed, unmerged PR is not durable project state. Remove its local/remote task branch when it is no longer needed and safe to delete.
- Remove tracked docs, skills, handoff notes, or links that point specifically to the closed PR or its obsolete branch; keep only durable workflow rules.
- Before reporting cleanup complete, verify the PR-specific branch/reference is gone and search tracked files for stale PR/branch references.

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
