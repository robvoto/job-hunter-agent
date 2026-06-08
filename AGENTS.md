# Job Hunter Agent - Agent Instructions

## Purpose

Keep this file small. It is the always-loaded router for coding agents.

Job Hunter is a local-first job discovery system:

`scrape -> deterministic filters -> optional LLM -> fit score -> workspace`

## Load order

Before searching or editing:

1. Read this file.
2. Pick the single most relevant skill from the routing table.
3. Read only that `SKILL.md`, then any linked `DETAILS.md` or docs needed for the task.
4. Inspect only the target files needed to make the change.

Do not read every skill, every doc, or the whole repository.

## Tooling rule

Do not use `rg` in this repo. It is unreliable in the current shell.

Use repo-supported search instead:

- project file search tool
- PowerShell `Select-String`
- targeted file reads
- git history only when needed

## Source hierarchy

- `AGENTS.md`: global routing and non-negotiables only.
- Adapter files, if present (`CLAUDE.md`, `GEMINI.md`): thin imports/pointers only; do not duplicate core rules.
- `.skills/*/SKILL.md`: scoped operating rules for one work area.
- `.skills/*/DETAILS.md`: longer examples/patterns referenced by a skill.
- `docs/ARCHITECTURE.md`: system design, runtime layers, module ownership.
- `docs/PRINCIPLES.md`: product and decision philosophy.
- `docs/OPERATIONS.md`: commands, flags, diagnostics, recovery.
- Google Sheet backlog: planning/tracking only, not instruction source.

## Skill routing

Choose the best matching skill. Combine with `no-hardcoding` when touching config, schema, thresholds, labels, defaults, or business rules.

| Skill | Use for |
|---|---|
| `.skills/code-change/SKILL.md` | Code, tests, runtime implementation |
| `.skills/instruction-maintenance/SKILL.md` | AGENTS, adapter files, skills, instruction docs |
| `.skills/backlog-management/SKILL.md` | Google Sheet backlog rows, state, evidence |
| `.skills/no-hardcoding/SKILL.md` | Config ownership, defaults, thresholds, labels, schema |
| `.skills/job-filtering/SKILL.md` | Deterministic filters, hard blockers, reject reasons |
| `.skills/scoring-ranking/SKILL.md` | Fit score, ranking, scoring explanations |
| `.skills/profile-extraction/SKILL.md` | CV/profile extraction and normalization |
| `.skills/signal-registry/SKILL.md` | Approved learning signal lifecycle |
| `.skills/preferences/SKILL.md` | Location, contract, government, salary, work mode preferences |
| `.skills/dashboard-ui/SKILL.md` | Workspace/dashboard/settings UI |
| `.skills/onboarding-ui/SKILL.md` | Onboarding wizard, upload, reset/resume flow |
| `.skills/scraping/SKILL.md` | SEEK/LinkedIn scraping and raw evidence capture |
| `.skills/ad-learning/SKILL.md` | Extracting learning candidates from job ads |
| `.skills/knowledge-management/SKILL.md` | Managed knowledge/config sources and loaders |
| `.skills/history-dedup/SKILL.md` | Job history, viewed/applied/hidden state, deduplication |
| `.skills/suggested-tuning/SKILL.md` | Settings > Optimise > Suggested Tuning |

## Runtime truth

- Runtime state lives in SQLite via `JOB_HUNTER_DB_PATH`.
- Per-user rendered workspace output lives under `data/users/<user_id>/`.
- Approved knowledge seeds live in `data/knowledge/*.json`.
- Global admin settings seed lives in `data/config/global_settings.json`.
- Runtime signal files live in `data/signals/*.json` and are gitignored.

## Non-negotiables

- Deterministic filters run before LLM.
- Business judgement belongs in managed config, knowledge, profile data, or reviewed learning flows, not feature code.
- Do not hardcode scoring weights, thresholds, labels, schema guesses, hidden defaults, or fallback business values.
- Hard rejection is only for explicit blockers backed by approved rules.
- Producers define and normalise schema. Consumers must not guess field names or invent fallback values.
- Weak or uncertain signals are preserved for review, not silently deleted.
- Learning flows through the signal registry before becoming runtime knowledge.
- UI/UX changes must follow existing themes, shared components, and owning UI skills.
- New non-obvious user-facing controls need concise help text or inline guidance owned by the relevant source/skill.
- Every Python module starts with a concise top-level docstring stating its purpose.
- Touch only files required for the task. Avoid unrelated refactors.
- Remove unused code and dead paths instead of preserving legacy paths.
- Surface missing or invalid values as explicit degraded/error states.
- Do not mask failures with fallback encoders, parsers, labels, default models, guessed config, alternate fields, broad exception swallowing, or compatibility shims unless the human explicitly approves the fallback and reason.

## Backlog rule

For backlog work, read `.skills/backlog-management/SKILL.md` first. Do not implement rows marked `Implementation State = Done` unless the human explicitly asks to audit, reopen, correct, or revise them.

## Testing rule

Use risk-based validation.

- Run the smallest relevant tests that directly cover the changed behaviour.
- Add adjacent validation when the change crosses shared infrastructure, auth, persistence, routing, startup, global settings, shared templates/bootstrap, scoring/filtering core, common utilities, or multiple modules.
- Run the full suite for broad/risky/shared changes or release/merge preparation.
- Record exact validation before claiming done.

## Definition of Done

A change is done only when:

1. Implementation is tested according to the testing rule.
2. Tests are added or updated when behaviour changes.
3. The solution is not an unapproved fallback, hardcoding, heuristic, compatibility shim, or dead path.
4. Current project patterns are followed.
5. Relevant docs, skills, backlog evidence, or operations notes are updated when affected.

## Design standard

Prefer small, single-purpose modules. If the requested approach is a workaround, legacy pattern, anti-pattern, or unnecessary monolith, say so before editing and propose the professional alternative.