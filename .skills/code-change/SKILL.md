---
name: code-change
description: Use for any code/test/runtime implementation change. Do NOT use for backlog-only edits, instruction cleanup, or business-rule ownership questions unless code also changes.
---

# Skill: Code Change

Use before modifying existing code.

## Rules
- Inspect the target file before editing.
- Touch only files required for the task.
- Keep changes small and scoped.
- Temporary helper scripts must be removed before finishing. If a helper script is intentionally kept, it must have a short top-of-file purpose comment explaining what it is for and when to use/delete it.
- New non-obvious modules, functions, flows, ownership boundaries, or integration points must include concise comments explaining intent and ownership. Comments should not repeat the code line-by-line.
- Prefer small, single-purpose modules over large monolithic files.
- If the proposed approach is a workaround, legacy pattern, anti-pattern, or unnecessary monolith, say so before editing: name the pattern, explain why it is suboptimal, and state the professional alternative.
- If a better approach is feasible within scope, ask before using the weaker one.
- Do not refactor unrelated modules.
- Do not introduce legacy/backward-compatibility code unless explicitly requested.
- Do not mask failures with fallback encoders, fallback parsers, fallback labels, guessed config, alternate fields, broad exception swallowing, or default values. Surface the failure unless the human explicitly approves the fallback with a stated reason.
- Do not change business judgement during mechanical cleanup.
- Load `.skills/no-hardcoding/SKILL.md` if the change touches thresholds, mappings, labels, schema fields, defaults, or rule IDs. Do not rely on this trigger alone — it depends on recognizing the change as label-related, which is easy to miss on incidental edits. Any edit to a designated owner module (see `.skills/no-hardcoding/SKILL.md`'s Enforcement section) must run `tests/test_no_hardcoding.py` regardless of what the change looks like.
- If a task is likely owned by one module, search that owner first and stop once you find the source of truth.
- When a symptom is visible in the UI, inspect the rendered template, injected bootstrap data, and owning normaliser in parallel before editing.

## Testing
Use risk-based validation for code changes.

Rules:
- Run the smallest relevant tests that directly cover the changed behaviour.
- Add adjacent/integration validation when the change crosses shared infrastructure, auth, persistence, routing, startup, global settings, shared templates/bootstrap, scoring/filtering core, common utilities, or multiple modules.
- Run the full suite for broad/risky/shared changes or release/merge preparation.
- Add or update tests when behaviour changes.
- Record exact validation commands and results before claiming done.

## Text utility changes
Use this section for reusable text normalization, matching/parsing helpers, scoring source text, and description-trust utilities.

Rules:
- Utility code should stay judgement-free.
- Do not add business categories, labels, thresholds, or scoring policy here.
- Keep helpers small, deterministic, and reusable.
- Do not hide data loss in aggressive cleaning.
- Text utilities may normalise shape; they must not decide fit.
- Consumers should receive predictable canonical output.

Owners:
- `text_processing.py`: whitespace/dedup/text cleanup.
- `scoring_utils.py`: scoring source text and weighted points helper.
- `description_trust.py`: full-description confidence.
- `role_analysis.py`: role text bundles and context helpers.

## Runtime diagnosis
- Human operations log: `output/server.log`. Check it first for the curated per-job/per-board summary.
- Full debug log: `output/server-debug.log`. Use it for raw LLM/API/pipeline detail, interleaved worker activity, and machine-oriented diagnosis.
- Find the last relevant log line before a hang/error, then read the code that runs next.
- Geolocation lookup (`/api/onboarding/lookup-location-by-geolocation`) is a separate network call and can appear to delay extraction.
- **Dependency version regressions**: if a 3rd-party call fails with `unexpected keyword argument` or similar, check `git log -- uv.lock` and diff the old vs new version before touching calling code. The lock may have resolved to a lower version than the one the code was written against. Fix the version constraint; do not rewrite calling code to work around the wrong version.

## Definition of Done
A code change is done only when:
1. Implementation is tested according to the testing rule.
2. Tests are added or updated when behaviour changes.
3. The solution is not an unapproved fallback, hardcoding, heuristic, compatibility shim, or dead path.
4. Current project patterns are followed.
5. Relevant docs, skills, or operations notes are updated when affected.
6. **If the task came from a backlog item (human-supplied JH ID or agent-picked row), the backlog row is always updated before reporting done** — `Implementation State`, `Implementation Date`, `Implemented By`, `Evidence` — via `.skills/backlog-management/SKILL.md`. This is not conditional on whether it seems "affected"; it is a required last step whenever a backlog row exists for the task.

## Finish format
Report:
- Changed
- Removed
- Remaining
- Validation


