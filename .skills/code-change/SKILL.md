# Skill: Code Change

Use before modifying existing code.

## Rules
- Inspect the target file before editing.
- Touch only files required for the task.
- Keep changes small and scoped.
- Prefer small, single-purpose modules over large monolithic files.
- If the proposed approach is a workaround, legacy pattern, anti-pattern, or unnecessary monolith, say so before editing: name the pattern, explain why it is suboptimal, and state the professional alternative.
- If a better approach is feasible within scope, ask before using the weaker one.
- Do not refactor unrelated modules.
- Do not introduce legacy/backward-compatibility code unless explicitly requested.
- Do not change business judgement during mechanical cleanup.
- Load `.skills/no-hardcoding/SKILL.md` if the change touches thresholds, mappings, labels, schema fields, defaults, or rule IDs.
- If a task is likely owned by one module, search that owner first and stop once you find the source of truth.
- Prefer the smallest relevant validation over broad test runs unless the change crosses multiple owners or the user asks for a full pass.
- When a symptom is visible in the UI, inspect the rendered template, injected bootstrap data, and owning normaliser in parallel before editing.

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
