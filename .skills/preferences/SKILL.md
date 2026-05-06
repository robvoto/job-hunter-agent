# Skill: Preferences

Use before editing location, salary, contract, government, work mode, or preference weights.

## Rules
- Preferences adjust fit; they should not create hidden hard rejection unless explicitly configured as blockers.
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
- Is this a score adjustment, warning, or explicit blocker?
- Is the threshold configurable?
- Is the returned signal labelled and canonical?
- Are consumers using the helper instead of duplicating logic?
- Did you run the smallest relevant preference check?
