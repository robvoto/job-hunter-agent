# Agent Instructions

## Purpose

Always-loaded agent loader. Keep this file project-agnostic and small.

Project-specific context lives in `docs/PROJECT_CONTEXT.md`.

## Load only what is needed

1. Read this file.
2. If project context is needed, read `docs/PROJECT_CONTEXT.md`.
3. Load the single most relevant skill from `.skills/`.
4. Read only linked details, docs, code, or git history needed for the task.

Do not read every skill, every doc, or the whole repo.

## Skill selection

Use each skill's YAML frontmatter `name` and `description`.

Reusable defaults:

- `code-change`: code, tests, runtime implementation.
- `instruction-maintenance`: AGENTS, adapter files, skills, instruction docs.
- `no-hardcoding`: config, schema, thresholds, labels, defaults, fallback values, business rules.
- `css-design-system`: CSS, spacing, layout, reusable components, theme tokens.

Project-specific skills live in `docs/PROJECT_CONTEXT.md`.

## Universal rules

- Keep changes small and scoped.
- Do not add hidden fallbacks, dead paths, compatibility shims, or broad exception swallowing unless explicitly approved.
- Do not hardcode business behaviour when config, schema, profile, or knowledge should own it.
- Surface missing or invalid required data clearly.
- Prefer small, single-purpose modules over monoliths.
