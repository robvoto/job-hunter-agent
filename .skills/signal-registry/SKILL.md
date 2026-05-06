# Skill: Signal Registry

Use before editing learning candidates, approval flow, or signal registry behaviour.

## Rules
- Learning is pending first, approved later.
- Pending registry records must not affect runtime filtering/scoring.
- Approved knowledge is the only runtime source for learned behaviour.
- Preserve original text/evidence for review.
- Do not auto-promote suggestions.
- Signal schema must be canonical at the registry boundary; consumers must not guess fields.

## Allowed categories
- `capability_concept`
- `government_context`
- `role_title_token`
- `hard_blocker_pattern`
- `title_normalization_candidate`

## Owners
- `signal_registry.py`: pending signal storage and review flow.
- `signal_schema.py`: signal keys/categories/constants.
- Managed knowledge modules: approved runtime knowledge after review.

## Checklist
- Does the signal include original evidence?
- Is it pending, not runtime-active?
- Is approval explicit?
- Is the category allowed?
- Is schema canonical and validated before consumers use it?
