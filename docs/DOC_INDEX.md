# Documentation Index

Use this file to decide where information belongs. Do not create a new markdown file unless none of these owners fit.

## Root files

| File | Owner |
|---|---|
| `README.md` | Project overview, quick start, and links to deeper docs. |
| `AGENTS.md` | Tiny reusable agent loader only. |
| `CLAUDE.md` | Thin Claude adapter only. |
| `GEMINI.md` | Thin Gemini adapter only. |

## Core docs

| File | Owner |
|---|---|
| `docs/PROJECT_CONTEXT.md` | Job Hunter product context, runtime truth, paths, project-specific skill routing, startup/run notes, backlog pointer. |
| `docs/AGENT_OPERATING_MODEL.md` | Agent instruction layering, skill discovery, adapter ownership, tool-vs-skill rules, active/archived skill summary. |
| `docs/ARCHITECTURE.md` | System design, runtime layers, and module ownership. |
| `docs/PRINCIPLES.md` | Product and decision philosophy. |
| `docs/DEVELOPER_GUIDE.md` | Developer workflow and code ownership map. |
| `docs/OPERATIONS.md` | Commands, flags, diagnostics, recovery, and deployment operations. |
| `docs/USER_GUIDE.md` | User-facing application behaviour and usage. |
| `docs/aws-ec2-setup.md` | Current AWS EC2 production setup. |

## Domain/reference docs

| File | Owner |
|---|---|
| `docs/CONFIG_AND_RULES_GOVERNANCE.md` | Config, rule, knowledge, and governance ownership. |
| `docs/SOURCE_REGISTER.md` | External/internal source inventory and source-specific notes. |
| `docs/SCORING_RATIONALE.md` | Fit score rationale, scoring model explanation, and scoring decision history. |
| `docs/UI_COMPONENT_MAP.md` | UI component ownership and reusable UI map. |
| `docs/ALIAS_LOGIC_RATIONALE.md` | Alias/title matching rationale. Candidate to merge into a future decision log. |
| `docs/CAPABILITY_AGING_RATIONALE.md` | Capability aging/strength rationale. Candidate to merge into a future decision log. |

## Backlog docs

| File/folder | Owner |
|---|---|
| `docs/backlog/backlog_extraction_notes.md` | Notes from extracting backlog items. Historical/reference only. |
| `docs/backlog/backlog_source_audit.md` | Backlog source coverage audit. Historical/reference only. |
| `docs/backlog/CV_TEXT_RETENTION_DECISION.md` | Specific decision record for CV text retention. |
| `docs/backlog/archive/` | Historical backlog exports and retired backlog docs. Not active planning truth. |

Backlog source of truth is the shared Google Sheet. Backlog workflow rules live in `.skills/backlog-management/SKILL.md`.

## Skills

| Folder | Owner |
|---|---|
| `.skills/*/SKILL.md` | One active agent workflow/domain each. Must include YAML `name` and `description`. |
| `.skills/*/DETAILS.md` | Longer examples/details loaded only when the parent skill points to them. |
| `docs/archived-skills/` | Retired skills kept for history only. Not active routing. |

## Rules for new docs

- Prefer updating an existing owner before creating a new doc.
- If a doc is historical, put it under an `archive/` folder or mark it clearly as historical.
- If a rule tells agents how to act, it usually belongs in `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, or one `.skills/*/SKILL.md`.
- If a doc repeats another owner, merge or link instead of duplicating.
