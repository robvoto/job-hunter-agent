# Agent Operating Model

This document defines how agent instructions, skills, tools, and project context are organised for Job Hunter.

## Purpose

Keep always-loaded instructions small and reliable. Agents should load only the context needed for the current task instead of reading every instruction, every skill, or the whole repository.

## Instruction layers

1. `AGENTS.md`
   - Always-loaded reusable loader only.
   - Project-agnostic and small.
   - Contains purpose, load order, skill selection, and universal rules only.
   - Must not contain backlog workflow, testing workflow, Definition of Done, runtime paths, startup protocol, product context, Google Sheet details, or domain-specific Job Hunter rules.

2. `docs/PROJECT_CONTEXT.md`
   - Job Hunter-specific context.
   - Owns product goal, runtime truth, repo-root and OpenClaw paths, project-specific source hierarchy, project-specific skill routing, non-negotiables, startup/run notes, and a pointer to backlog workflow.
   - Points to `.skills/backlog-management/SKILL.md` for backlog details instead of duplicating the full workflow.

3. Agent adapter files: `CLAUDE.md`
   - Thin adapters for a specific agent environment.
   - Point to `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, and the relevant skill owner.
   - Must not redefine project rules, commands, architecture, backlog workflow, testing workflow, or Definition of Done.

4. `.skills/*/SKILL.md`
   - Compact scoped instructions for one work area.
   - Each active skill must include YAML frontmatter with `name` and `description`.
   - Should answer: when to use, what must not be violated, where ownership lives, and how to validate.

5. `.skills/*/DETAILS.md`
   - Longer reference content split out of a skill.
   - Use for examples, patterns, component maps, source-specific details, and historical traps.

6. `docs/*`
   - Human/reference documentation.
   - Architecture, operations, setup, rationale, and detailed explanations.

7. Backlog tracker
   - Current source of truth is the shared Google Sheet backlog.
   - Planning and tracking only.
   - Not an instruction source.
   - Local `docs/backlog/backlog_review.xlsx` is archive/export/reference only unless the human explicitly asks to update it.

## Tools vs skills

Instructions describe behaviour. Tools execute work.

Examples of tools:
- file read/write/search
- shell command execution
- browser or web search
- spreadsheet or Google Sheets API access
- GitHub access
- OpenClaw tool/resource access
- test execution

A skill may state which tool type is needed, but must not pretend a tool exists if the current runtime does not provide it.

## Skill discovery rule

Every active skill must have frontmatter:

```yaml
---
name: skill-name
description: Clear sentence explaining when to use the skill.
---
```

The description is important because agent systems often discover skills from names/descriptions before loading the full skill body.

## Active skills

| Skill | Purpose |
|---|---|
| `ad-learning` | Pending job-ad learning candidates. |
| `backlog-management` | Google Sheet backlog rows, JH IDs, priorities, duplicates, implementation state, evidence, and human review flags. |
| `code-change` | Code/test/runtime implementation workflow, validation, and Definition of Done. |
| `css-design-system` | CSS, spacing, layout, reusable components, and theme tokens. |
| `dashboard-ui` | Workspace and settings UI, including workspace output sync. |
| `history-dedup` | Job history, saved/viewed/applied/hidden state, duplicate identity. |
| `instruction-maintenance` | AGENTS, adapter files, skills, and instruction docs. |
| `job-filtering` | Deterministic pass/fail filters, hard blockers, and reject reasons. |
| `knowledge-management` | Managed knowledge/config/source-of-truth ownership. |
| `no-hardcoding` | Config, schema, thresholds, labels, defaults, fallback values, rule IDs, and business-rule ownership. |
| `onboarding-ui` | Onboarding wizard, upload, reset/resume flow, and search-basics UI. |
| `preferences` | Candidate preferences and preference-to-filter handoff. |
| `profile-extraction` | CV/profile extraction and normalization. |
| `scoring-ranking` | Fit scoring, ranking, and score explanations. |
| `scraping` | SEEK/LinkedIn scraping and source data shape. |
| `signal-registry` | Signal lifecycle, approval, and governance. |
| `suggested-tuning` | Settings > Optimise > Suggested Tuning workflow. |

## Archived skills

Archived skills are kept only as historical reference under `docs/archived-skills/`.

| Archived skill | Reason | Preserved where |
|---|---|---|
| `workspace-output-sync` | Narrow UI support rule; should not be a first-class routing choice. | Merged into `.skills/dashboard-ui/SKILL.md`. |
| `text-utilities` | Small generic utility guidance; should not compete with code-change/no-hardcoding. | Merged into `.skills/code-change/SKILL.md`. |
| `signal-review-map` | Narrow capability alias diagnostic map. | Merged into `.skills/signal-registry/SKILL.md`. |
| `initialise` | Startup protocol duplicated `AGENTS.md`; historical OpenAI config notes preserved in archive. | Startup/routing rules now in `AGENTS.md` and `docs/PROJECT_CONTEXT.md`. |

## Backlog tool reality

The backlog source of truth is the shared Google Sheet.

Agents should use a Google Sheets-capable tool/API when available. If no such tool is available in the current runtime, the agent must say so instead of editing a local Excel copy or pretending it updated the Sheet.

Local `docs/backlog/backlog_review.xlsx` is archive/export/reference only unless the human explicitly asks to update it.

## Maintenance rules

- Prefer moving detail from `AGENTS.md` into a relevant skill or doc.
- Prefer moving long skill examples into `DETAILS.md`.
- Avoid duplicating the same rule across files.
- Do not let adapter files redefine project rules.
- Remove stale architecture claims once verified wrong.
- Preserve hard project constraints by keeping them in the owning file, not by duplicating them everywhere.
- Put executable automation in a real tool/API/script, not in prose.
- Document tool requirements honestly.

## Current decisions

- `AGENTS.md` is the tiny reusable loader.
- Project-specific routing and runtime truth live in `docs/PROJECT_CONTEXT.md`.
- Testing rules and Definition of Done live in `.skills/code-change/SKILL.md`.
- Backlog workflow lives in `.skills/backlog-management/SKILL.md`.
- Hardcoding/config/schema/default/fallback ownership lives in `.skills/no-hardcoding/SKILL.md`.
- Skills use discovery frontmatter (`name` and `description`) so agents can route by skill metadata instead of hardcoded trigger lists in `AGENTS.md`.
- `CLAUDE.md` is a thin adapter only.
