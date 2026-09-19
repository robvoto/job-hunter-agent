---
name: git-lifecycle
description: Use for branch/worktree setup, commit, push, pull request, merge/integration, main-branch verification, or whenever Git state is unclear.
---

# Skill: Git Lifecycle

Use this whenever code work is started or finished, or whenever the user asks about commit/push/PR/merge/main/deploy state.

## Operator contract

The human should not need to remember Git mechanics.

- Completed intended work is committed and pushed automatically after validation unless the human explicitly says not to push.
- Stop and ask only for a genuine safety gate: unrelated changes, destructive actions, force-pushes, deployment/restart, credentials/external messages, or unresolved conflicting work.
- A pushed task branch is **not** the same as integration to `main`.
- `commit` or `push` alone never means "merge to main".
- `approved`, `merge it`, `put it in main`, `ship it`, or equivalent approval referring to the current completed task authorizes integration to `main`.
- If integration intent is unclear, ask one concise question before merging: `Work is ready on <branch> but is NOT in main. Merge to main now?`
- A pull request is optional unless the repository explicitly requires one or the human explicitly asks for one. Do not create a PR merely because a branch was pushed.
- Git work targets the latest repository state, not the version currently running on AWS. Commit, integrate, and push approved work to `main` normally even when production is intentionally on an older release.
- Never treat commit, merge, push, or release approval as permission to deploy AWS. Production deployment requires an explicit AWS instruction from the human.

## Before editing

1. Fetch `origin`.
2. Inspect `git status`, current branch/worktree, `HEAD`, and `origin/main`.
3. Preserve unrelated dirty work. Never stash, reset, overwrite, or commit another agent's changes without explicit coordination.
4. When concurrent work is possible, use an isolated task branch + worktree based on current `origin/main`; do not code in the shared `main` checkout.

## Failure handling

- Any failed tool call, shell command, merge, or validation is a stop condition: report the failure immediately and do not silently continue down the same line of work.
- Diagnose the root cause before retrying. If the human has already authorised fixing the task, fix the root cause and add a durable guard/instruction/test when the failure reveals a repeatable process gap.
- In WSL worktrees, use the repository runtime (`uv run ...`) rather than assuming a bare Python/test executable exists. In a ChatGPT/Human MCP connector run, never run the whole pytest suite in one connector call; use the three separate serial `./scripts/run-pytest-mcp.sh N 3` calls owned by `mcp-tooling`.
- For browser JavaScript that uses ES-module syntax in a repo where `.js` is not declared as Node ESM, validate with `node --input-type=module --check < path/to/file.js`; do not run plain `node --check path/to/file.js`, which will misparse valid `export`/`import` syntax as CommonJS.

## Before integration

1. Confirm the exact task commit SHA and that validation passed.
2. Fetch `origin` again and compare the task branch with current `origin/main`.
   - Capture exact commit IDs with `git rev-parse`; never reconstruct or guess a full SHA from a short display SHA when guarding integration state.
3. If `origin/main` advanced since the task branch was cut, do not blindly push, force-push, or pretend it is a fast-forward.
4. Build the integration result from the **current** `origin/main` plus the task branch, using the repository's documented merge strategy. If none is documented, prefer a normal non-force merge that preserves both histories.
5. If there are conflicts, unrelated-history surprises, unclear ownership, failed tests, or ambiguity about how to reconcile changes, stop and ask the human instead of improvising.
6. Before validation, inspect any versioned managed JSON changed by both sides. If merged content differs from current `origin/main`, its integrated `version` must be strictly greater than the version on current `origin/main`; independent branches can legitimately collide on the same version number.
7. Re-run the required validation on the integrated result before updating `main`.
8. Push `main` without force. If the remote moved again and rejects the push, fetch and reassess; never bypass the rejection with force.

## Required verification

After any claimed integration, prove it instead of inferring it:

- Fetch `origin`.
- Verify the task commit is an ancestor of `origin/main` (for example with `git merge-base --is-ancestor <task-sha> origin/main`).
- Record the resulting `origin/main` SHA.
- Do not claim deployment merely because `main` was pushed; verify the repository's actual deployment mechanism separately when deployment matters.

## Mandatory status wording

Never leave the human guessing. End Git-related work with exactly one clear integration state:

- `MAIN STATUS: NOT IN MAIN — uncommitted work`;
- `MAIN STATUS: NOT IN MAIN — committed on <branch>`;
- `MAIN STATUS: NOT IN MAIN — pushed branch <branch>`; or
- `MAIN STATUS: IN MAIN — verified on origin/main at <sha>`.

If the state is not `IN MAIN`, say what single action is still required. Do not use `done`, `shipped`, `merged`, or `deployed` ambiguously.

## Repository-state reporting

- `MAIN STATUS` reports remote integration only; `CLEANUP STATUS` reports only the merged task's temporary branch and worktree.
- Do not call a repository `clean` unless the shared checkout and every active worktree have been checked clean, and the shared checkout is current with `origin/main`.
- Otherwise state the verified scope precisely, for example: `task worktree clean; other worktrees not assessed`.

## Mandatory post-merge cleanup

A successful integration is **not complete** until the task worktree/branch cleanup is completed or explicitly reported as blocked.

After the task commit is verified as an ancestor of `origin/main`:

1. Re-check the task worktree with `git status --porcelain`.
2. If it has modified, staged, conflicted, or untracked files, **do not delete it**. Report the exact worktree path and why cleanup is blocked. Never stash, reset, or discard that work merely to make cleanup pass.
3. If it is clean, remove the task worktree with `git worktree remove <path>`.
4. Delete the merged local task branch with `git branch -d <branch>`.
5. If the same remote task branch exists, is fully merged into `origin/main`, and is not still needed by an active worktree/session, delete it with `git push origin --delete <branch>`.
6. Run `git worktree prune`.
7. Verify the task worktree no longer appears in `git worktree list` and the merged task branch no longer appears locally.
8. Run `./scripts/check-git-closure.sh --task-sha <task-sha> --branch <branch> --worktree <path>`. This executable gate must pass before reporting `MAIN STATUS: IN MAIN`.
9. When the human says `merge all`, asks for repository cleanup, or Git state was already unclear/dirty, also run the same command with `--strict-repo`; do not report repository cleanup complete while it reports dirty worktrees or merged local branches left behind.

Never leave a clean, fully merged task worktree or branch behind "for later". Parallel worktrees are temporary execution spaces, not permanent project folders.

This is enforced, not trusted: `tests/test_git_hygiene.py` fails the whole suite
while any local branch fully merged into main still exists. The rule and
`scripts/check-git-closure.sh` both predate seventeen stale worktrees, because
both depended on an agent choosing to run them. The test does not.

For any integration reported as `IN MAIN`, also report exactly one cleanup state:

- `CLEANUP STATUS: COMPLETE — merged task worktree removed`; or
- `CLEANUP STATUS: BLOCKED — <exact dirty/unmerged reason and worktree path>`.

Always add one explicit branch state after cleanup:

- `BRANCH STATUS: DELETED — local and remote task branches removed`; or
- `BRANCH STATUS: RETAINED — <exact branch name and why it cannot be deleted>`.

`CLEANUP STATUS: COMPLETE` is forbidden while any task-related local or remote branch still exists. `rescue/*` branches are not exempt from strict repository closure; if one must be retained to preserve unmerged work, strict closure must fail and the final response must say `BRANCH STATUS: RETAINED` with the branch name and reason.
