# Cline Memory

Cline-specific durable context for this repository. This file is loaded only through `.clinerules/00-project-memory.md`; it is not a shared instruction source for other agents.

## Start every task

1. Read `AGENTS.md`.
2. Read this file.
3. Read `docs/PROJECT_CONTEXT.md` only when product context, runtime truth, or domain routing is needed.
4. Read `docs/STANDARDS_INDEX.md` before changing setup, instructions, docs, config, templates, tests, packaging, providers, costs, approvals, or long-running workflows.
5. Load only the relevant `.skills/*/SKILL.md` files.

## Repository and runtime

- WSL repository and runtime path: `/home/robvoto/projects/job-hunter-agent`.
- Do not use the obsolete Windows path `E:\Programming\job-hunter-agent`.
- Inspect the real WSL worktree before answering about files, implementation state, or uncommitted changes.
- Preserve unrelated worktree changes. Never reset, restore, stash, stage, or commit files outside the agreed task scope.

## Backlog

- Canonical backlog: `https://docs.google.com/spreadsheets/d/1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0/edit?gid=218702820#gid=218702820`.
- Follow `.skills/backlog-management/SKILL.md`.
- Use the authorised Human MCP / Google Sheets tools for reads and writes.
- Never substitute public CSV export, a local workbook, copied data, GitHub issues, or memory for the live sheet.
- A backlog task is not done until the live row is updated and re-read for verification.

## UI rules

- Reuse existing components, classes, tokens, labels, spacing, typography, and interaction patterns.
- Read `docs/UI_COMPONENT_MAP.md` and the relevant UI skill before changing UI.
- Shared widget styling belongs in `templates/static/theme/themes.widgets.css`; page CSS may own page-specific layout only.
- Do not introduce a new font, colour, size, badge geometry, help pattern, or local component when an existing shared pattern owns it.
- Inspect rendered markup, owning JavaScript, shared CSS, labels, and tests before editing.

## Current clean baseline

- Commit `d510378` restored the approved compact contract-duration interaction:
  - `Contract (all)` / selected-duration text remains in the Contract chip;
  - clicking Contract opens a compact anchored native light-dismiss popover;
  - outside click and Escape close it;
  - Settings and Onboarding reuse the same component and theme CSS.
- The same commit fixed Job Requirements rows:
  - the actual matched capability is inside `.req-coverage-tag`;
  - empty status pills are not rendered;
  - importance and match-status badges share typography, padding, height, and alignment.
- Do not restore the rejected large persistent contract-length field from commit `29b7812`.

## Recent completed work

- `JH-279 — Show live run elapsed time and bounded stop completion` is complete.
- Commit `d42ab72` added structured source/stage progress, shared source badges, accessible progress visuals, elapsed rendering, and common Workspace/Settings wait-state ownership.
- The follow-up implementation bounds cooperative stop cleanup, detaches unresponsive source workers from the active run, preserves completed-source results, exposes terminal `stopped`, and retains the final total elapsed time.
- Late detached workers keep their original scoped stop event and cannot overwrite progress for a later run.
- No unfinished JH-279 worktree changes should remain after the completion commit and live backlog update.

## Self-edit restriction

Do not edit `AGENTS.md`, `.clinerules/`, `docs/CLINE_MEMORY.md`, `docs/AGENT_OPERATING_MODEL.md`, `docs/DOC_INDEX.md`, or `.skills/` unless the human explicitly requested instruction maintenance. Product work must not rewrite the agent's own instructions.
