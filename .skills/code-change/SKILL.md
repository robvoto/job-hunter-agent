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
- During implementation, use targeted tests for fast feedback. Before declaring done, always finish with the full suite (`pytest tests/`).
- When a symptom is visible in the UI, inspect the rendered template, injected bootstrap data, and owning normaliser in parallel before editing.

## Finish format
Report:
- Changed
- Removed
- Remaining
- Validation

## Diagnosing runtime issues
- Server log: `output/server.log` — timestamped, written for every server run. Check this before grep-hunting for a bug visible in the UI or logs.
- All log lines from the app use `print()` or the app logger. Search for the last log line before a hang, then read what runs next in code.
- Geolocation lookup (`/api/onboarding/lookup-location-by-geolocation`) is a separate network call — slow network or missing provider will make it appear as part of extraction.

## Checklist
- Are imports still needed?
- Did any unrelated file change?
- Did the change preserve existing ownership boundaries?
- Did you run the full suite (`pytest tests/`)?
