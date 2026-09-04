---
name: code-change
description: Use for any code/test/runtime implementation change. Do NOT use for backlog-only edits, instruction cleanup, or business-rule ownership questions unless code also changes.
---

# Skill: Code Change

Use before modifying existing code.

## Rules
- Before starting any code change, work in an isolated git branch + worktree dedicated to that change (not the shared/main worktree), so multiple agents/sessions can work on this repo concurrently without touching each other's uncommitted files. Delete the branch and worktree once the change is merged or abandoned — do not let them accumulate.
- Inspect the target file before editing.
- Touch only files required for the task.
- Keep changes small and scoped.
- Temporary helper scripts must be removed before finishing. If a helper script is intentionally kept, it must have a short top-of-file purpose comment explaining what it is for and when to use/delete it.
- New non-obvious modules, functions, flows, ownership boundaries, or integration points must include concise comments explaining intent and ownership. Comments should not repeat the code line-by-line.
- Prefer small, single-purpose modules over large monolithic files.
- If the proposed approach is a workaround, legacy pattern, anti-pattern, or unnecessary monolith, say so before editing: name the pattern, explain why it is suboptimal, and state the professional alternative.
- If a better approach is feasible within scope, ask before using the weaker one.
- Do not refactor unrelated modules.
- **PRE-LIVE CANONICAL-CONTRACT RULE (mandatory until Rob explicitly declares the product live for the first time):** Job Hunter has one current schema and one current code path. Existing dev/test data, caches, persisted rows, obsolete fields, old payload shapes, and superseded contracts are disposable. Do not preserve, migrate, alias, round-trip, fall back to, or support legacy formats. When a contract changes, update every producer/consumer/test to the canonical shape, invalidate/delete stale dev data or caches as needed, and remove the old path completely. Do not add one-time migration machinery merely to preserve pre-live data. Only Rob can explicitly approve an exception.
- Do not introduce legacy/backward-compatibility code unless explicitly requested.
- Do not mask failures with fallback encoders, fallback parsers, fallback labels, guessed config, alternate fields, broad exception swallowing, or default values. Surface the failure unless the human explicitly approves the fallback with a stated reason. (Example: JH-288 — the qualification save path must reject a coverage item missing `canonical_requirement` rather than fall back to the unvetted `matched_candidate_fact`.)
- Do not change business judgement during mechanical cleanup.
- **Business-semantics approval gate:** if a proposed change can alter what the product discovers, includes, excludes, rejects, accepts, scores, ranks, reprocesses, reuses from cache/history, or treats as the meaning of a user-selected value, stop before implementation and get explicit human approval. This applies even when the change is described as a refactor, cleanup, deduplication, schema simplification, ownership change, or cache/version change.
- Before asking for that approval, show the behavioural delta concisely: current behaviour; proposed behaviour; which user-visible inputs/meanings change; what could newly appear or disappear; whether discovery/eligibility/fit widens or narrows; and which cache/history/results would be invalidated or reprocessed. Approval for the surrounding technical task does not implicitly approve a semantic change discovered during it.
- Do not collapse related concepts into one source of truth merely to simplify code. A user/display label, canonical classification or identity, machine-facing query, ranking/eligibility preference, and cache invalidation contract are separate unless the product explicitly defines them as equivalent.
- Treat changed regression-test expectations as a warning signal, not automatic evidence that the implementation is correct. If a refactor requires changing an existing expectation about discovery, rejection, scoring, user intent, or cache reuse, apply the business-semantics approval gate before updating the test.
- If code is deciding what human language means, classify that as semantic interpretation before coding. Do not implement semantic interpretation with regexes, keyword/phrase lists, substring checks, hand-authored synonym tables, or string-to-boolean word maps; use the owning LLM/schema/managed-knowledge path, or fail/log for review when meaning is unresolved. (Example: JH-286 — `profile_fact_resolved` is an explicit LLM-owned bool, not a text-equality heuristic, gating whether `canonical_requirement` is trusted as a single resolved concept.)
- Load `.agents/skills/no-hardcoding/SKILL.md` if the change touches thresholds, mappings, labels, schema fields, defaults, or rule IDs. Do not rely on this trigger alone — it depends on recognizing the change as label-related, which is easy to miss on incidental edits. Any edit to a designated owner module (see `.agents/skills/no-hardcoding/SKILL.md`'s Enforcement section) must run `tests/test_no_hardcoding.py` regardless of what the change looks like.
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
- When a fix can only be proven against a real external run (live scrape, real LLM call, anything with real cost/time), scope that run to the minimum that proves the claim — a reduced page/date range, or a direct check against already-persisted state for a handful of keys — before defaulting to a full end-to-end run, and especially before running a second full one to observe cache/reuse behaviour.

## Definition of Done
A code change is done only when:
1. Implementation is tested according to the testing rule.
2. Tests are added or updated when behaviour changes.
3. The solution is not an unapproved fallback, hardcoding, heuristic, compatibility shim, or dead path.
4. Current project patterns are followed.
5. Relevant docs, skills, or operations notes are updated when affected.
6. **If the task came from a backlog item (human-supplied JH ID or agent-picked row), the backlog row is always updated before reporting done** — `Implementation State`, `Implementation Date`, `Implemented By`, `Evidence` — via `.agents/skills/backlog-management/SKILL.md`. This is not conditional on whether it seems "affected"; it is a required last step whenever a backlog row exists for the task.

## Finish format
Report:
- Changed
- Removed
- Remaining
- Validation

## Detailed reference
See `DETAILS.md` for text-utility ownership, incorrect-output diagnosis, and runtime-diagnosis patterns.
