---
name: preferences
description: Use ONLY for candidate preference inputs and settings such as location, contract, government, salary, work mode, source settings, and preference-to-filter handoff. Do NOT use for scoring implementation.
---

# Skill: Preferences

Use before editing location, salary, contract, government, work mode, or preference weights.

## Rules
- Explicitly incompatible work type, sector, work mode, minimum contract length, and salary minimum are **hard eligibility filters**, not score adjustments. Each passes through when the job value is unknown or cannot be compared safely.
- The hard filter entry point is `passes_preference_filters(record, profile)` — returns `(bool, reason_code)`. Salary comparison must stay neutral unless the source provides an explicit comparable pay period.
- Do not infer compensation or pay period from free-text ad prose or work type alone. If the source salary is missing or ambiguous, keep salary `N/A` and skip salary comparison.
- Any new heuristic or hardcoded preference/comparison rule is a red flag and requires explicit human approval before implementation.
- `assess_location_preference()` supplies the canonical location-preference signal, and `salary_fit_adjustment()` handles the remaining salary scoring path. Do not reference removed contract or government scoring helpers.
- Thresholds, aliases, labels, and scoring impacts come from profile/config/parsing rules, not feature code.
- Preference helpers should return canonical labelled signals for consumers.
- Consumers must not recreate preference logic.
- Missing required labels/settings should fail clearly at the owner boundary.

## Owners
- `preferences.py`: preference assessment functions.
- `profile_store.py`: preference settings and normalisation.
- `data/knowledge/scoring_rules.json`: scoring impacts.
- `data/knowledge/parsing_rules.json`: parsing labels/keywords where already owned there.

## Checklist
- Is this a hard eligibility block (known incompatible) or a score adjustment (unknown/partial)?
- Does it correctly pass through when the value is missing or unlisted?
- Is the threshold configurable?
- Is the returned signal labelled and canonical?
- Are consumers using the helper instead of duplicating logic?
- Did you run the smallest relevant preference check?
