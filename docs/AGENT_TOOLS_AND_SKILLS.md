# Agent Tools and Skills

## Purpose

This repo separates instructions from executable capabilities.

## Concepts

### Agent instructions
Files such as `AGENTS.md`, `CLAUDE.md`, and `GEMINI.md` tell an agent how to behave in this project.

They should be short and stable.

### Skills
Files under `.skills/*/SKILL.md` are scoped operating procedures.

Use skills for repeatable workflows such as backlog management, scraping, code changes, instruction maintenance, filtering, scoring, or onboarding UI.

Every skill should have frontmatter:

```yaml
---
name: skill-name
description: Clear sentence explaining when to use the skill.
---
```

The description is important because agent systems often discover skills from names/descriptions before loading the full skill body.

### Details files
Files such as `.skills/*/DETAILS.md` hold long examples, component maps, detailed source-specific rules, or historical traps.

Keep `SKILL.md` compact. Move long material to `DETAILS.md`.

### Tools
Tools are executable capabilities provided by the agent runtime, for example:

- file read/write/search
- shell command execution
- browser or web search
- spreadsheet or Google Sheets API access
- GitHub access
- OpenClaw tool/resource access
- test execution

Tools are not usually documented as project rules unless the project requires a specific local tool or workflow.

A skill may say which tool type is needed, but should not pretend a tool exists if the current agent runtime does not provide it.

### Project docs
Files under `docs/*` explain architecture, operations, rationale, and reusable patterns for humans and agents.

## Repo pattern

- `AGENTS.md`: short project-wide source of truth and skill router.
- `CLAUDE.md` / `GEMINI.md`: thin adapter files.
- `.skills/*/SKILL.md`: scoped operating rules with discovery frontmatter.
- `.skills/*/DETAILS.md`: longer details loaded only when needed.
- `docs/*`: reference and explanation.
- Google Sheet backlog: planning/tracking only.

## Current backlog tool reality

The backlog source of truth is the shared Google Sheet.

Agents should use a Google Sheets-capable tool/API when available. If no such tool is available in the current runtime, the agent must say so instead of editing a local Excel copy or pretending it updated the Sheet.

Local `docs/backlog/backlog_review.xlsx` is archive/export/reference only unless the human explicitly asks to update it.

## Maintenance rule

When adding a new workflow:

1. Put universal constraints in `AGENTS.md` only if every task needs them.
2. Put repeatable area-specific workflow in a skill.
3. Put long examples/details in `DETAILS.md`.
4. Put executable automation in a real tool/API/script, not in prose.
5. Document tool requirements honestly.

