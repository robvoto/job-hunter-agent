# Skill: Job Filtering

Use before editing `filters.py`, reject reasons, title/content filters, or hard blocker behaviour.

## Rules
- Deterministic filters run before LLM.
- Hard rejection is only for explicit blockers backed by approved rules.
- Do not reject just because evidence is weak/basic/old.
- Weak or uncertain signals become score impacts, warnings, or review signals.
- Do not add hidden false-negative gates.
- Do not hardcode rejected terms or title dictionaries in Python.
- Use approved knowledge files and profile settings.

## Boundaries
- Title filters are cheap first-pass narrowing, not final fit judgement.
- Content filters handle explicit job requirements and candidate blockers.
- Learning suggestions go to signal registry first; pending signals are not runtime rules.

## Checklist
- Is this an explicit blocker or inferred weakness?
- Is the rule approved/configured, not invented inline?
- Is the rejection reason visible to the user?
- Are uncertain signals preserved for review?
