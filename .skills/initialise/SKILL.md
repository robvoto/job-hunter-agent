---
name: initialise
description: Repository bootstrap and workflow guardrails for this project. Use when the user says initialise/init, when starting any task in this repo, or when you need to establish the required local workflow before editing code.
---

# Initialise

## Hard start sequence — no exceptions

Before any Grep, Glob, Read, or Bash:
1. Read `AGENTS.md`
2. Identify the skill domain(s) from the task description alone
3. Read the relevant SKILL.md(s)
4. Only then search or read code

If you cannot identify the domain without reading code first, ask the user — do not start searching.

The skill's owner list tells you which files to touch. A broad Grep hunt before loading the skill wastes tokens on files the owner list already rules out.

## Workflow

1. Read `AGENTS.md` first.
2. Load the relevant project skill before any codebase search or edit.
3. Follow the repo's named owners and touch only required files.
4. Do not invent data, labels, thresholds, defaults, or fallback values.
5. Do not duplicate existing logic or add compatibility/legacy code.
6. Remove unused code instead of leaving dead paths in place.
7. Ask the user before adding heuristic data or random-word filters.
8. If something is unclear, ask before changing it.
9. If the task touches workspace/results UI, load `.skills/dashboard-ui/SKILL.md` and `.skills/workspace-output-sync/SKILL.md`, then verify the generated per-user `workspace_results.html` as well as the source template.
10. Before writing code, check whether the approach is a workaround, legacy pattern, anti-pattern, or unnecessary monolith. If so, say that explicitly before editing: name the pattern, explain why it is suboptimal, and state the professional alternative. Ask before using the weaker approach if a better one is feasible within scope.

## Editing Rules

- Keep changes small and targeted.
- Centralise reused values in the owning module or config.
- Preserve common language across the app.
- Use the smallest relevant validation, not a full test pass unless needed.
- Prefer small, single-purpose modules over large monolithic files.

## When To Stop

- If the task depends on missing context or risky assumptions, stop and ask.
- If a change would require new business judgement, ask first.
