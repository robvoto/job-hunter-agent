---
name: no-hardcoding
description: Use whenever changing thresholds, labels, mappings, schema fields, defaults, business rules, fallback values, or rule IDs. Usually combine with the task domain skill.
---

# Skill: No Hardcoding

Business judgement must live in its managed owner, not feature code. Semantic-change and pre-live compatibility rules are owned by `code-change`.

## Forbidden

- Inline scoring/weight maps, business thresholds, policy caps, or behavioural slices without config ownership.
- Local fallback defaults or fallback display labels for required managed values.
- Consumer-side schema guessing or alternate-field chains instead of one canonical contract.
- Scattered literals for managed schema keys, rule IDs, categories, labels, or decision reasons.
- User-facing labels/sentences embedded in designated owner modules instead of the managed label source.
- Hand-authored phrase/substring/synonym lists used as semantic interpretation.
- New heuristic or hardcoded business/display rules without the explicit semantic approval required by `code-change`.

Examples in tests, bug reports, skills, or conversation are evidence, not generic product rules.

## Required ownership

- Use the owning config/profile/knowledge loader and validate required values at its producer/normaliser boundary.
- Consumers read canonical fields directly; missing required data is fixed at the owner or surfaced explicitly.
- Reused UI copy belongs once in the owning managed label source.
- Source-specific deterministic parsing/cleanup rules belong in managed data/config/knowledge, not Python constants.
- Language interpretation follows the `code-change` semantic boundary; deterministic code may enforce shape/evidence invariants only.
- Admin-tunable global behaviour belongs in global Advanced Settings; do not silently create candidate-specific settings.

## Enforcement

`tests/test_no_hardcoding.py` owns the designated owner-module list and static enforcement. If a new module becomes an owner of profile/business constants, add it to that test in the same change.

## Checklist

Search the changed area for fallback `.get(...)` defaults, `or ...` labels, inline point/weight maps, policy numbers, alternate schema fields, and repeated managed copy.
