---
name: no-hardcoding
description: Use whenever changing thresholds, labels, mappings, schema fields, defaults, business rules, fallback values, or rule IDs. Usually combine with the task domain skill.
---

# Skill: No Hardcoding

Use before adding/changing thresholds, mappings, defaults, labels, scoring values, rule IDs, schema fields, or business judgement.

## Core rule
Business judgement must not hide in feature code.
Silent fallbacks are not acceptable. If required data is missing, surface an explicit error or fix the owner.
**Pre-live canonical-contract rule:** until Rob explicitly declares Job Hunter live for the first time, all existing dev/test data, caches, persisted rows, obsolete fields, old payload shapes, and superseded contracts are disposable. Maintain exactly one current schema/code path. Never preserve or migrate pre-live legacy data, accept aliases for removed fields, support old/new shapes in parallel, or add compatibility shims. Update producers/consumers/tests to the canonical contract and delete stale data/caches instead. Only Rob can explicitly approve an exception.
Do not mask failures with fallback encoders, fallback parsers, fallback labels, default models, guessed config, alternate fields, broad exception swallowing, or compatibility shims. Stop and expose the failure unless the human explicitly approves the fallback with a stated reason.
Any new heuristic or hardcoded business/display rule is a red flag and requires explicit human approval before implementation.
Concrete examples in skills, tests, bug reports, or conversation are diagnostic examples only. Never promote a current user's title, company, location, profile fact, observed job phrase, or one reported record into generic product logic unless the human explicitly approves it as managed knowledge/config.

## Forbidden
- Inline scoring maps, e.g. `{ "strong": 4, "working": 3 }`
- Local fallback defaults, e.g. `.get("bonus", 5)`
- Fallback display labels, e.g. `or "competitive signal"`
- Consumer-side schema guessing, e.g. `signal.get("fit_label") or signal.get("name")`
- Scattered raw strings for schema keys, rule IDs, categories, or decision reasons
- Numeric caps/slices that affect business or display policy without config ownership
- Inline `"label": "..."` dict literals for option lists (e.g. `{"value": X, "label": "Public sector"}`) — the label must come from a `ui_labels.json` lookup, even though the `value` token stays in code
- One hand-authored sentence per enum/category value (e.g. a separate bespoke warning string for every clearance type) — this is hardcoding in disguise even when each string individually lives in `ui_labels.json`. Use one template plus a short data-driven token instead
- Any user-facing sentence/label assigned as a Python string literal in a designated owner module (see Enforcement below), even as a "helper" constant

## Required
- Before editing, inspect the relevant project files, docs, and skills for the area being changed.
- Use managed config/profile/knowledge loaders.
- Add named config only in the correct owner.
- Validate required config at the producer/normalizer boundary.
- Consumers use canonical fields directly, e.g. `signal["label"]`.
- If required data is missing, fix the producer; do not patch around it in consumers.
- When a generic rule is changed because of one reported job/profile/example, add an unrelated regression case where practical so the implementation proves the contract rather than the example.
- Do not add local fallback defaults for business values, decision labels, or display labels in feature code. If the owner does not provide the value, surface an explicit error or fix the owner.
- If the same label or copy is reused across summary, tooltip, and debug views, put it in the owning JSON/data file once and read it from there.
- Source-specific parsing and cleanup rules must live in data/config/knowledge and be loaded by the engine; do not embed them in Python constants.
- Do not implement semantic classification with hand-authored phrase/substring lists in feature code (for example `("eligible to", "able to obtain", ...)`). That is a brittle heuristic and hardcoding even if it is called validation.
- When the distinction requires language understanding, use the LLM/schema/prompt at the owning interpretation boundary and preserve uncertain cases for review. Deterministic code may enforce structural/schema invariants, but must not pretend a growing phrase list is semantic understanding.
- Onboarding title-tier copy and validation messages must come from `data/knowledge/ui_labels.json` via the bootstrap label global; do not hardcode target/also-consider/search keyword text in templates or JS.
- If the requested change would force a workaround, legacy pattern, anti-pattern, or unnecessary monolith, say so before editing: name the pattern, explain why it is suboptimal, and state the professional alternative. Ask before using the weaker approach if a better one is feasible within scope.

## Checklist
- Search for `.get(..., fallback)`.
- Search for `or "..."` fallback labels.
- Search for inline dicts mapping labels to points/weights.
- Search for numeric caps/slices that affect behaviour.
- Search for consumer-side alternate fields like `x or y`.

## Enforcement — owner modules

`tests/test_no_hardcoding.py` owns the current `OWNER_MODULES` enforcement list. Do not duplicate that list or its count in this skill because it changes as modules are cleaned up. The test rejects inline `"label": "..."` literals and top-level ALL_CAPS constants assigned directly to multi-word user-facing text in those owners. This check is unconditional — it runs in every `pytest` run regardless of whether the change "looks like" a labels change. This exists because relying on an agent to notice that a change is label-related is not sufficient enforcement.

When adding a new file whose whole job is holding profile/business constants
(anything like `*_store.py`, `*_settings.py`, workspace/report renderers), add it
to `OWNER_MODULES` in that test as part of the same change — don't wait for a
second pass to catch it.

## Advanced settings ownership

Configurable/admin-tunable behaviour belongs in advanced settings — not feature code.

Rules:
- Global system behaviour belongs in global advanced settings.
- Advanced settings must be manageable from the Advanced Settings UI.
- Do not hardcode admin-tunable behaviour in Python/JS.
- If unsure whether a setting is global or candidate-specific, ask before implementing.
- Do not silently create candidate-specific settings.
