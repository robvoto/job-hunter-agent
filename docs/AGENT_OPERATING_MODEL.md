# Agent Operating Model

This document defines how agent instructions, skills, tools, and project context are organised for Job Hunter.

## Purpose

Keep always-loaded instructions small and reliable. Agents should load only the context needed for the current task instead of reading every instruction, every skill, or the whole repository.

## Instruction layers

1. `AGENTS.md`
   - Always-loaded reusable loader only.
   - Project-agnostic and small.
   - Contains purpose, load order, skill selection, and universal rules only.
   - Must not contain backlog workflow, testing workflow, Definition of Done, runtime paths, startup protocol, product context, Google Sheet details, domain-specific Job Hunter rules, or agent-specific memory.

2. `docs/PROJECT_CONTEXT.md`
   - Job Hunter-specific context.
   - Owns product goal, runtime truth, repo-root and LangGraph orchestration details, project-specific source hierarchy, project-specific skill routing, non-negotiables, startup/run notes, and a pointer to backlog workflow.
   - Points to `.agents/skills/backlog-management/SKILL.md` for backlog details instead of duplicating the full workflow.

3. Agent-specific adapter files, when present
   - Each adapter owns only that runtime's bootstrap/integration behaviour.
   - Shared project instructions must not enumerate, require, test, or depend on specific agent adapter filenames.
   - An adapter may point to `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, or `.agents/skills/INDEX.md`, but shared owners must not point back to the adapter.
   - Do not duplicate shared project rules, commands, architecture, testing workflow, or Definition of Done inside an adapter.

4. `.agents/skills/*/SKILL.md`
   - Compact scoped instructions for one work area.
   - Each active skill must include YAML frontmatter with `name` and `description`.
   - Should answer: when to use, what must not be violated, where ownership lives, and how to validate.

5. `.agents/skills/*/DETAILS.md`
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
- agent workflow and project-resource access
- test execution

A skill may state which tool type is needed, but must not pretend a tool exists if the current runtime does not provide it. Shared skills describe required capabilities first; runtime-specific tool namespaces belong only in explicitly scoped tooling instructions.

## Skill discovery rule

Use `.agents/skills/INDEX.md` as the routing map. Keep one short entry per active skill so agents can choose the smallest relevant owner without loading every skill.

Every active skill must have frontmatter:

```yaml
---
name: skill-name
description: Clear sentence explaining when to use the skill.
---
```

The description is important because agent systems often discover skills from names/descriptions before loading the full skill body.

## Active skills

`.agents/skills/INDEX.md` is the single current catalogue of active skills and their routing descriptions. Do not maintain a second active-skill list here.

## Archived skills

Archived skills are kept only as historical reference under `docs/archived-skills/`.

| Archived skill | Reason | Preserved where |
|---|---|---|
| `workspace-output-sync` | Narrow UI support rule; should not be a first-class routing choice. | Merged into `.agents/skills/dashboard-ui/SKILL.md`. |
| `text-utilities` | Small generic utility guidance; should not compete with code-change/no-hardcoding. | Merged into `.agents/skills/code-change/SKILL.md`. |
| `signal-review-map` | Narrow capability alias diagnostic map. | Merged into `.agents/skills/signal-registry/SKILL.md`. |
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
- Testing rules and Definition of Done live in `.agents/skills/code-change/SKILL.md`.
- Backlog workflow lives in `.agents/skills/backlog-management/SKILL.md`.
- Hardcoding/config/schema/default/fallback ownership lives in `.agents/skills/no-hardcoding/SKILL.md`.
- Job Hunter/JMM integration ownership and consumer paging contracts live in `.agents/skills/job-market-map-integration/SKILL.md`.
- Skills use discovery frontmatter (`name` and `description`) so agents can route by skill metadata instead of hardcoded trigger lists in `AGENTS.md`.
