# Skill: Code Change

Use before modifying existing code.

## Rules
- Inspect the target file before editing.
- Touch only files required for the task.
- Keep changes small and scoped.
- Do not refactor unrelated modules.
- Do not introduce legacy/backward-compatibility code unless explicitly requested.
- Do not change business judgement during mechanical cleanup.
- Load `.skills/no-hardcoding/SKILL.md` if the change touches thresholds, mappings, labels, schema fields, defaults, or rule IDs.

## Finish format
Report:
- Changed
- Removed
- Remaining
- Validation

## Checklist
- Are imports still needed?
- Did any unrelated file change?
- Did the change preserve existing ownership boundaries?
- Did you run the smallest relevant validation?
