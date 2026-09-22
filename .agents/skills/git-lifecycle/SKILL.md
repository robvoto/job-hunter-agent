---
name: git-lifecycle
description: Use for branch/worktree setup, commit, push, pull request, merge/integration, main verification, and Git cleanup.
---

# Skill: Git Lifecycle

Use for any branch/worktree, commit, push, PR, merge, or `main` integration work.

## Contract

- Work intended for shared `origin/main` uses: **task branch/worktree -> implement and self-check -> commit/push task branch -> fast-forward local `main` for Rob's app testing -> iterate until Rob is satisfied -> open PR -> independent agent cross-check and required checks -> merge PR to `origin/main` -> sync local `main` -> cleanup**.
- The authoring agent commits work on the task branch. Local `main` is Rob's app-testing lane: fast-forward it to tested checkpoints so he can run the app in his normal setup without checking out task branches.
- Local test integrations are not shared integrations. Never push those test checkpoints from local `main` to `origin/main`.
- Rob is the manual app tester and product/technical lead. Give him concise app test instructions and findings; do not ask him to review code diffs.
- Keep the task branch as the source for the eventual PR. Fast-forward local `main` from the task branch when possible so the task commits and PR ancestry are preserved.
- Do not create the PR while implementation and Rob's app testing are still in progress. Create it once Rob says the app change is good and ready for integration.
- Every normal integration to `origin/main` requires a PR with an independent agent cross-check. The authoring agent cannot count its own review as the independent cross-check. Resolve review findings and required checks before merging.
- Rob's confirmation that the app change is good authorizes the PR and, once the independent cross-check and required checks pass, its merge. Do not ask for another `put it in main` instruction. Honor any instruction to hold or stop.
- If the PR cross-check finds a defect, fix it on the task branch, fast-forward the checkpoint into local `main` when needed for Rob to retest, update the PR, and repeat the cross-check.
- Do not push a task branch directly to `origin/main` or bypass a required PR/check. `commit` or `push` alone never means the work is in shared `origin/main`.
- Git approval does not imply runtime lifecycle or deployment approval; follow `docs/PROJECT_CONTEXT.md` and `release-management` for those concerns.

## Before editing

1. Fetch `origin`.
2. Inspect branch/worktree, `git status`, `HEAD`, and `origin/main`.
3. Preserve unrelated dirty work; never stash, reset, overwrite, or commit another agent's changes without coordination.
4. When concurrent work is possible, use an isolated task worktree based on current `origin/main`.

## Authoring agent

1. Implement only the task scope and run the required validation.
2. Commit stable checkpoints on the task branch and push them without force. Report the branch, commit SHA, validation performed, and how Rob can test the app from local `main`.
3. To expose a checkpoint in Rob's normal app setup, fetch `origin` and confirm the local `main` checkout is clean and contains current `origin/main`. Fast-forward local `main` to the task branch when possible. If local `main` has commits not on the task branch, preserve them and use a normal local merge only when it is conflict-free and keeps the task branch as the PR source. Do not commit separate test changes on local `main` or push test integrations to `origin`. Keep the task worktree locked while its clean branch is included in local `main` but is still awaiting Rob's testing or PR integration; this protects the required PR source from merged-branch cleanup.
4. Continue implementation and feedback on the task branch. For each checkpoint Rob needs to test, fast-forward or safely merge the updated task branch into local `main`, following step 3. Stop if local `main` is dirty, conflicts occur, or the histories cannot be reconciled without rewriting or losing work.
5. Do not create a PR during implementation or app-testing iterations. When Rob confirms the app change is good, fetch `origin`, reconcile only clear/safe drift, run final validation, and create a PR from the task branch targeting `main`. Return ambiguous conflicts or ownership questions to Rob. If both sides changed versioned managed JSON, ensure the integrated version is greater than current `origin/main` when content changes.
6. Keep the PR open for an independent agent cross-check and required checks. Wait for hosted PR checks/CI. If the reviewer requests a fix, update the task branch and PR; fast-forward or safely merge the checkpoint into local `main` for retesting when the app behavior changes.
7. Once the independent cross-check and required checks pass, merge the PR through the repository PR mechanism using its documented strategy. Fetch `origin` and verify the task changes are represented in `origin/main`. Bring local `main` up to date without losing unrelated local work; remove only local test-merge history after verifying its content is present on `origin/main`. If unrelated local commits prevent exact synchronization, preserve them and report the difference rather than resetting them.
8. Verify the task changes are represented in `origin/main`. Report local app-test state separately from shared remote integration state.

## PR cross-check

1. The reviewer must be a different agent from the authoring agent.
2. Review the PR changes against the task request, relevant project contracts, and test evidence. Report concrete findings; do not treat opening a PR as proof that cross-checking happened.
3. Resolve blocking findings and rerun affected checks before merging. If no independent reviewer is available, leave the PR unmerged and report that blocker.

## Closed or abandoned PR cleanup

- A closed, unmerged PR is not durable project state. Remove its local/remote task branch when it is no longer needed and safe to delete.
- Remove tracked docs, skills, handoff notes, or links that point specifically to the closed PR or its obsolete branch; keep only durable workflow rules.
- Before reporting cleanup complete, verify the PR-specific branch/reference is gone and search tracked files for stale PR/branch references.

## Post-merge cleanup

1. Re-check the task worktree. Never delete a dirty/unmerged worktree.
2. Unlock the task worktree, then remove it once clean and integrated or abandoned.
3. Delete the merged local and remote task branches.
4. Run `git worktree prune`.
5. Run `./scripts/check-git-closure.sh --task-sha <sha> --branch <branch> --worktree <path>`.
6. For repository-wide cleanup/`merge all`, add `--strict-repo`.

`tests/test_git_hygiene.py` enforces removal of clean local branches already merged into `main`.

## Reporting

Report local testing and shared integration separately:

- `LOCAL TEST STATUS: NOT IN LOCAL MAIN — <reason>`; or
- `LOCAL TEST STATUS: IN LOCAL MAIN — app-test checkpoint at <sha>`.
- `ORIGIN MAIN STATUS: NOT IN ORIGIN/MAIN — PR <number|not created>, branch <branch> at <sha>`; or
- `ORIGIN MAIN STATUS: IN ORIGIN/MAIN — verified at <sha>`.

For integrated work also report:

- `CLEANUP STATUS: COMPLETE — merged task worktree removed`; or `BLOCKED — <reason>`.
- `BRANCH STATUS: DELETED — local and remote task branches removed`; or `RETAINED — <reason>`.

Do not call the whole repository clean unless every active worktree was checked and the shared checkout is current with `origin/main`.
