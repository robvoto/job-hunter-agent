---
name: instruction-maintenance
description: Use ONLY when editing AGENTS.md, agent adapters, .agents/skills, DETAILS.md, or docs that define agent workflow.
---

# Skill: Instruction Maintenance

Keep agent instructions small, current, single-owned, and easy to interpret.

## Ownership

- `AGENTS.md`: minimal universal routing and stable project-wide rules.
- `.agents/skills/*/SKILL.md`: concise domain operating rules.
- `.agents/skills/*/DETAILS.md`: longer diagnostics, examples, and reference material.
- `docs/*`: project/human reference unless explicitly linked as an operating contract.
- Backlog: planning/tracking, not agent instructions.

## Rules

- Put each durable rule in the narrowest existing owner. Other files should point to that owner instead of restating it.
- Remove duplicate prose, obsolete architecture claims, temporary commentary, incident history, and superseded instructions once the durable rule is clear.
- Keep `SKILL.md` operational. Move detailed diagnostics/examples to `DETAILS.md`; delete detail that no longer helps current operation.
- Do not use `AGENTS.md` as a dumping ground for Git, UI, tooling, runtime, or implementation detail.
- Shared instructions must be runtime-neutral except in the tooling/project-context owner that genuinely needs runtime-specific names or paths.
- Verify current source/tool/runtime truth before changing a claim merely because old instructions say it is true.
- Do not create parallel agent-specific copies of shared domain rules.
- Preserve canonical project constraints by linking to their owner rather than duplicating them.

## Audit checklist

Before finishing an instruction change, check:

- Is every rule actionable and still true?
- Does one file clearly own it?
- Is equivalent prose repeated elsewhere?
- Is any sentence explaining an old incident instead of current behaviour?
- Is a detail better placed in `DETAILS.md` or project docs?
- Did the edit add unnecessary safety prose or compatibility language?
- Are affected instruction files UTF-8/LF (`git ls-files --eol`)?

Use narrow, context-checked edits and inspect the final diff. Update instruction indexes/docs only when ownership or structure actually changes.
