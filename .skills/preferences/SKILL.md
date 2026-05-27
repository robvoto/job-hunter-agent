---
name: preferences
description: Use ONLY for candidate preference inputs and settings such as location, contract, government, salary, work mode, source settings, and preference-to-filter handoff. Do NOT use for scoring implementation.
---

# Skill: Preferences

Use before editing location, salary, contract, government, work mode, or preference weights.

## Rules
- Three preferences are **hard eligibility filters**, not score adjustments: work type (contract/permanent), sector (private only), and salary minimum. All use the same principle: exclude only when the value is explicitly known and incompatible; pass through when unknown or unlisted.
- The hard filter entry point is `passes_preference_filters(record, profile)` — returns `(bool, reason_code)`. Called after full salary extraction in the scrape pipeline.
- Scoring functions (`assess_contract_preference`, `assess_government_preference`, `salary_fit_adjustment`) still apply to records that passed the hard filter, for positive signals and edge cases.
- Thresholds, aliases, labels, and scoring impacts come from profile/config/parsing rules, not feature code.
- Preference helpers should return canonical labelled signals for consumers.
- Consumers must not recreate preference logic.
- Missing required labels/settings should fail clearly at the owner boundary.

## Owners
- `preferences.py`: preference assessment functions.
- `profile_store.py`: preference settings and normalisation.
- `data/scoring_rules.json`: scoring impacts.
- `data/parsing_rules.json`: parsing labels/keywords where already owned there.

## Checklist
- Is this a hard eligibility block (known incompatible) or a score adjustment (unknown/partial)?
- Does it correctly pass through when the value is missing or unlisted?
- Is the threshold configurable?
- Is the returned signal labelled and canonical?
- Are consumers using the helper instead of duplicating logic?
- Did you run the smallest relevant preference check?
