---
name: instruction-maintenance
description: Use ONLY when editing agent instruction files: AGENTS.md, adapter files, .skills, DETAILS.md, or docs that define agent workflow. Do NOT use for product/code changes.
---

# Skill: Instruction Maintenance

Use when editing `AGENTS.md`, agent-specific instruction files, `.skills/*/SKILL.md`, or important project markdown that guides agents.

## Purpose
Keep agent instructions useful, small, current, and non-contradictory.

## Source hierarchy
- `AGENTS.md`: project-wide rules all agents should read first.
- Agent-specific files such as `CLAUDE.md` or `GEMINI.md`: thin pointers/adapters only. Do not duplicate core rules there.
- `.skills/*/SKILL.md`: compact domain rules loaded only for that work area.
- `.skills/*/DETAILS.md`: longer reference material split out of a noisy skill.
- `docs/*`: human/reference documentation, not agent operating rules unless explicitly linked.
- Google Sheet backlog: planning/tracking only, not instructions.

## Cleanup rules
- Prefer deleting or moving noise over adding more instructions.
- Keep `SKILL.md` files concise. If a skill grows too large, move detailed examples/patterns to `DETAILS.md` and keep `SKILL.md` as the loader/rule summary.
- Remove stale architecture claims when verified wrong.
- Do not edit agent-specific files to redefine rules owned by `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, or `.skills/*/SKILL.md`; point back to the owning file instead.
- Avoid duplicating the same rule across many files.
- Preserve important project constraints: no hardcoding, Google Sheet backlog source of truth, Excel export compatibility only when explicitly used, Definition of Done, and do-not-pick-Done-items.
- If unsure whether information is stale, mark it for review instead of rewriting as fact.

## Audit checklist
When cleaning instructions, check:
- Does this rule still match current architecture?
- Is it actionable for an agent?
- Is it in the right file according to the source hierarchy?
- Is it duplicated elsewhere?
- Is it too verbose for a `SKILL.md`?
- Does it conflict with `AGENTS.md`?
- Does it accidentally encourage hardcoding, fallbacks, or broad rewrites?

## Safe edit pattern
1. Inspect current files first.
2. Make small targeted edits.
3. Preserve long useful content by moving it to `DETAILS.md`, not deleting it outright.
4. Report exactly what changed and what was left alone.

## Ongoing maintenance
- When new instructions are added, check whether they made the wrong file bigger.
- If a rule is universal, keep it short in `AGENTS.md`.
- If a rule is area-specific, move it to the relevant skill.
- If a rule needs examples or long explanation, move those details to `DETAILS.md` or `docs/*`.
- After any instruction-structure cleanup, update `docs/AGENT_OPERATING_MODEL.md` and `docs/DOC_INDEX.md` if ownership or structure changed.

## Do not
- Do not rewrite all instructions in one pass.
- Do not update `GEMINI.md` unless the human explicitly asks.
- Do not add broad inspirational guidance.
- Do not turn backlog rows into operating rules.
- Do not add rules that conflict with the project Definition of Done.


