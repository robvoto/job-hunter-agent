# Agent Instructions

Minimal always-loaded routing instructions. This file is not the project manual and must stay small.

## Default workflow

1. Use `docs/INDEX.md` to find the smallest relevant project document.
2. Use `.agents/skills/INDEX.md` to choose the smallest relevant task skill or skill combination.
3. When repository or connected-service access is connector/MCP-mediated, read `.agents/skills/mcp-tooling/SKILL.md` before the first such command. Native local shell/filesystem work does not require MCP tooling.
4. Read the selected task skill before changing code, configuration, instructions, Git state, runtime behaviour, or UI.
5. Inspect the current files/state before editing. Do not load the whole repository unless the task genuinely requires a broad audit.
6. For any branch/worktree, commit, push, PR, merge, or `main` integration action, use `.agents/skills/git-lifecycle/SKILL.md`.

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
- Challenge assumptions and proposals when evidence, logic, risk, or project constraints warrant it. Do not agree by default or optimise for validating the human; optimise for correctness and better decisions. Do not be contrarian when the evidence supports agreement.
- Keep context and changes bounded to what the task requires.
- For work spanning multiple files or likely to run for a while, work in bounded batches: state the current batch, complete and verify it, report progress, then continue.
- Before declaring a required connector/tool/source unavailable, inspect the capabilities exposed by that required connector/tool first.
- Do not hardcode behaviour that belongs in config, schema, profile, knowledge, or another authoritative owner.
- Do not add hidden fallbacks, compatibility shims, dead paths, or broad exception swallowing unless explicitly approved.
- Do not claim completion without validation evidence.
- Before any semantic/product/UX/business-rule/default/workflow/data-interpretation/classification/heuristic/fallback/persistent-data behaviour change: investigate, explain the current finding and exact proposed effect, then wait for Rob's explicit approval. Treat uncertain changes as semantic; mechanical no-behaviour changes may proceed.
- Never claim a preference, rule, memory, or instruction is persisted unless the authoritative persistent source was actually updated and verified.
- Preserve unrelated work when other agents or sessions may be active.
- Before editing, inspect the exact current target file and apply a narrow, context-checked patch.
- If a patch hunk or `old_text` does not match, stop and reread the file before creating a new patch; never retry stale patch text.
- After editing, inspect the diff and run the required validation before reporting completion.
- Route specialised behaviour through its owning skill instead of expanding this file.

## Finish report

Report only what matters:
- what changed;
- validation performed and result;
- remaining risk or follow-up;
- for Git work, the integration state required by `.agents/skills/git-lifecycle/SKILL.md`.
