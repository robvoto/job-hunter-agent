---
name: code-change
description: Use for any code/test/runtime implementation change. Do NOT use for backlog-only edits or instruction-only cleanup.
---

# Skill: Code Change

Use before modifying existing code. Git mechanics are owned by `git-lifecycle`; hardcoding/config/default ownership is owned by `no-hardcoding`.

## Implementation rules

- Inspect the owning source before editing; keep the change scoped and remove temporary helpers before finishing.
- Prefer small, single-purpose modules. Do not refactor unrelated code.
- Add concise rationale comments/docstrings only where business intent, ownership, or lifecycle use would otherwise be unclear; do not narrate obvious code.
- Keep executable/script help current when arguments or behaviour change.
- If the proposed approach is a workaround, anti-pattern, compatibility path, or unnecessary monolith, identify the better approach before implementing the weaker one.
- **Pre-live canonical contract:** until the human explicitly declares Job Hunter live, dev/test legacy data and superseded contracts are disposable. Maintain one current schema/code path; update producers, consumers and tests together, invalidate stale data/caches through the owning version contract, and do not add migrations, aliases, old/new parallel paths, or compatibility shims unless explicitly approved.
- Do not mask failures with fallback parsers/encoders/labels, guessed config, alternate fields, broad exception swallowing, or invented defaults. Fix the owner or surface the failure unless a fallback is explicitly approved.

## Business-semantics gate

If a change can alter what the product discovers, includes, excludes, rejects, accepts, scores, ranks, reprocesses, reuses from cache/history, or interprets from a user value, get explicit human approval before implementation.

Before asking, state the behavioural delta: current vs proposed behaviour, affected user inputs, what can newly appear/disappear, whether scope widens/narrows, and cache/history impact.

- Mechanical cleanup must not change business judgement.
- Do not collapse display labels, canonical identities, machine queries, eligibility/ranking preferences, or cache contracts merely because consolidation is technically convenient.
- If an existing regression expectation changes in one of those areas, treat that as a semantic-change signal, not permission to rewrite the test.
- Language meaning belongs at the owning LLM/schema/managed-knowledge boundary, not in hand-authored regex/phrase/synonym/boolean maps.
- Load `no-hardcoding` when thresholds, mappings, labels, schema fields, defaults, rules, or designated owner modules are touched.

## Validation

- Run the smallest tests that prove the changed behaviour; add adjacent/integration coverage when shared infrastructure or multiple owners are affected.
- Run the full suite for broad/risky/shared changes or release/merge preparation.
- Add/update tests when behaviour changes; record exact validation results.
- For real external/costly validation, use the smallest run that proves the claim.

## Definition of done

- Intended behaviour is implemented and validated.
- No superseded logic, dead paths, stale flags/routes/adapters, or stale comments/docs remain in the touched area.
- Current ownership/patterns are preserved and relevant documentation is updated.
- If the task came from a backlog row, update that row through `backlog-management` before reporting completion.

## Detailed reference

See `DETAILS.md` for text-utility ownership and runtime/incorrect-output diagnosis patterns.
