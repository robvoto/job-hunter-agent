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

## Current unfinished work

- `JH-279 — Show live run elapsed time and bounded stop completion` is intentionally in progress and currently uncommitted.
- The partial implementation introduces structured progress state in:
  - `job_hunter_agent/run_control.py`
  - `job_hunter_agent/routes/workspace_api.py`
  - `job_hunter_agent/source_runner.py`
  - `job_hunter_agent/scrape_finalize.py`
  - `job_hunter_agent/scrapers/seek_runner.py`
  - `job_hunter_agent/scrapers/linkedin.py`
  - `job_hunter_agent/scrapers/apsjobs.py`
- Do not discard those files. Before continuing, read the live JH-279 row and inspect `git diff -w` to separate semantic changes from line-ending noise.
- The current slice is incomplete: it still needs the approved UI/screen integration, last-progress timestamp, bounded stop/timeout behaviour, preserved partial results, tests, and live backlog update.

## Self-edit restriction

Do not edit `AGENTS.md`, `.clinerules/`, `docs/CLINE_MEMORY.md`, `docs/AGENT_OPERATING_MODEL.md`, `docs/DOC_INDEX.md`, or `.skills/` unless the human explicitly requested instruction maintenance. Product work must not rewrite the agent's own instructions.
