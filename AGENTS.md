# Agent Instructions

Minimal always-loaded routing instructions. This file is not the project manual and must stay small.

## Default workflow

1. Use `docs/INDEX.md` to find the smallest relevant project document.
2. Use `.agents/skills/INDEX.md` to choose the smallest relevant task skill or skill combination.
3. Read the selected skill before changing code, configuration, instructions, Git state, runtime behaviour, or UI.
4. Inspect the current files/state before editing. Do not load the whole repository unless the task genuinely requires a broad audit.
5. For any branch/worktree, commit, push, PR, merge, or `main` integration action, use `.agents/skills/git-lifecycle/SKILL.md`.

## Durable rule placement

When a lesson or rule should apply beyond the current chat/session:

- First place it in the existing skill that owns that behaviour.
- If no suitable skill exists, create a focused skill and add it to `.agents/skills/INDEX.md`.
- Add detail to `DETAILS.md` or project docs when it is too large for a skill.
- Do not add implementation-specific, runtime-specific, UI-specific, Git-specific, tooling-specific, or incident-specific detail to this file.
- `AGENTS.md` may point to the owner; it must not duplicate the owner's detailed rules.

Use `.agents/skills/instruction-maintenance/SKILL.md` whenever changing agent instructions, skills, adapters, or instruction structure.

## Navigation

- Project context: `docs/PROJECT_CONTEXT.md`
- Project documentation index: `docs/INDEX.md`
- Task skills: `.agents/skills/INDEX.md`
- Shared project standards pointers: `docs/STANDARDS_INDEX.md`

## Universal rules

- Never guess or invent; inspect the authoritative source first.
- Keep context and changes bounded to what the task requires.
- Do not hardcode behaviour that belongs in config, schema, profile, knowledge, or another authoritative owner.
- Do not add hidden fallbacks, compatibility shims, dead paths, or broad exception swallowing unless explicitly approved.
- Do not claim completion without validation evidence.
- Preserve unrelated work when other agents or sessions may be active.
- Route specialised behaviour through its owning skill instead of expanding this file.

## Finish report

Report only what matters:
- what changed;
- validation performed and result;
- remaining risk or follow-up;
- for Git work, the integration state required by `.agents/skills/git-lifecycle/SKILL.md`.
