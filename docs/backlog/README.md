# Backlog

This folder is the product and engineering backlog for the Job Hunter agent system.

## Bot usage rules

Bots must not choose work directly from the backlog.

Use this order:

1. Read `NEXT_RUN.md` at the repository root.
2. Work only on the items promoted there.
3. Use these backlog files only as supporting context.
4. If work is completed, update `docs/backlog/DONE.md`.
5. Do not silently delete backlog items unless explicitly instructed.

## Backlog areas

- `openclaw.md` — OpenClaw runtime, scheduling, auth, operations, local-first agent concerns.
- `learning.md` — outcome learning, feedback loops, memory, profile evolution.
- `filtering.md` — filtering, scoring, parsing, blockers, salary, location, capability rules.
- `ui.md` — workspace, settings, onboarding, terminology, UX, user-facing product work.

## Item handling

When promoting backlog work into `NEXT_RUN.md`, copy only the specific story or stories to be handled next.

Each promoted item should include:

- source file
- task title
- goal
- constraints
- acceptance checks

The backlog is allowed to be large. `NEXT_RUN.md` is intentionally small.

