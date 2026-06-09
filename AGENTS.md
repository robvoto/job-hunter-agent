# Agent Instructions

## Purpose

Keep this file small. It is the always-loaded router for coding agents and should stay mostly project-agnostic.

Project-specific context lives in `docs/PROJECT_CONTEXT.md`.

## Load order

Before searching or editing:

1. Read this file.
2. Read `docs/PROJECT_CONTEXT.md` only when project-specific context, domain routing, or runtime truth is needed.
3. Pick the single most relevant skill from `.skills/`.
4. Read only that `SKILL.md`, then any linked `DETAILS.md` or docs needed for the task.
5. Inspect only the target files needed to make the change.

Do not read every skill, every doc, or the whole repository.

## Tooling rule

Use repo-supported search and targeted file reads.

If a project documents unreliable tools, avoid them and use the documented alternative.

## Source hierarchy

- `AGENTS.md`: reusable global routing and non-negotiables only.
- `docs/PROJECT_CONTEXT.md`: project-specific product, runtime truth, domain routing, and backlog rules.
- Adapter files, if present (`CLAUDE.md`, `GEMINI.md`): thin imports/pointers only; do not duplicate core rules.
- `.skills/*/SKILL.md`: scoped operating rules for one work area.
- `.skills/*/DETAILS.md`: longer examples/patterns referenced by a skill.
- `docs/*`: human/reference documentation.

## Skill selection

Load the most relevant skill from `.skills/`.

Reusable defaults:

- use `code-change` for implementation, tests, or runtime changes.
- use `instruction-maintenance` for AGENTS, adapter files, skills, or instruction docs.
- use `no-hardcoding` when touching config, schema, thresholds, labels, defaults, fallback values, or business rules.
- use `css-design-system` when touching CSS, spacing, layout, reusable visual components, or theme tokens.

For project-specific domain skills, use `docs/PROJECT_CONTEXT.md`.

## Non-negotiables

- Business judgement belongs in managed config, knowledge, profile data, or reviewed learning flows, not feature code.
- Do not hardcode scoring weights, thresholds, labels, schema guesses, hidden defaults, or fallback business values.
- Producers define and normalise schema. Consumers must not guess field names or invent fallback values.
- Weak or uncertain signals are preserved for review, not silently deleted.
- UI/UX changes must follow existing themes, shared components, and owning UI skills.
- New non-obvious user-facing controls need concise help text or inline guidance owned by the relevant source/skill.
- Every Python module starts with a concise top-level docstring stating its purpose.
- Touch only files required for the task. Avoid unrelated refactors.
- Remove unused code and dead paths instead of preserving legacy paths.
- Surface missing or invalid values as explicit degraded/error states.
- Do not mask failures with fallback encoders, parsers, labels, default models, guessed config, alternate fields, broad exception swallowing, or compatibility shims unless the human explicitly approves the fallback and reason.

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