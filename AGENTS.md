# Agent Instructions

## Purpose

Always-loaded agent loader. Keep this file project-agnostic and small.

Project-specific context lives in `docs/PROJECT_CONTEXT.md`.

Shared setup/standards pointers live in `docs/STANDARDS_INDEX.md`.

Persistent Cline session memory lives in `docs/CLINE_MEMORY.md`.

## Load only what is needed

1. Read this file.
2. If project context is needed, read `docs/PROJECT_CONTEXT.md`.
3. Read `docs/CLINE_MEMORY.md` for durable cross-session context (backlog, conventions, recent work).
4. If changing project setup, docs, AGENTS.md, skills, config, runtime commands, tests, env examples, packaging, templates, AI model/provider defaults, cost logging, approval workflows, or long-running workflows, read `docs/STANDARDS_INDEX.md` first.
5. Load the relevant skill or smallest necessary combination of skills from `.skills/`. Use one domain skill plus reusable skills such as `code-change`, `no-hardcoding`, or `css-design-system` when the task crosses those boundaries.
6. Read only linked details, docs, code, or git history needed for the task.

Do not read every skill, every doc, or the whole repo.

## Skill selection

Use each skill's YAML frontmatter `name` and `description`.

Reusable defaults:

- `code-change`: code, tests, runtime implementation.
- `instruction-maintenance`: AGENTS, adapter files, skills, instruction docs.
- `no-hardcoding`: config, schema, thresholds, labels, defaults, fallback values, business rules.
- `css-design-system`: CSS, spacing, layout, reusable components, theme tokens.

### UI task routing (required, not optional)

Any task touching templates, CSS, JS, or a rendered screen must load the UI-domain skill (`dashboard-ui` or `onboarding-ui`, whichever owns the surface) **together with** `css-design-system`, not either alone. If the page also has its own skill, load that too. Before writing a new selector, class, or component markup, check `docs/UI_COMPONENT_MAP.md` for an existing pattern to reuse. A missing reusable pattern is a reason to add it centrally (theme file + map entry), not to invent a page-local one-off.

Project-specific skills live in `docs/PROJECT_CONTEXT.md`.

## Universal rules

- Keep changes small and scoped.
- Assume multiple clients or agents may be editing this worktree in parallel. Before editing, tell the user, inspect `git status`, and preserve unexpected changes; do not overwrite, revert, stash, or commit another client's work without explicit coordination.
- Do not add hidden fallbacks, dead paths, compatibility shims, or broad exception swallowing unless explicitly approved.
- Do not silently drop, default, or reclassify required data into invisibility; if a match cannot be proven, keep the item visible with an explicit unresolved status or fail loudly if the pipeline requires a hard stop.
- Do not hardcode business behaviour when config, schema, profile, or knowledge should own it.
- Surface missing or invalid required data clearly.
- Prefer small, single-purpose modules over monoliths.
