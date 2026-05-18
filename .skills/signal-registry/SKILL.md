# Skill: Signal Registry

Use before editing learning candidates, approval flow, or signal registry behaviour.

## Rules
- Learning is pending first, approved later.
- Pending registry records must not affect runtime filtering/scoring.
- Approved knowledge is the only runtime source for learned behaviour.
- Preserve original text/evidence for review.
- Heuristic fallback findings may be logged and stored, but they are not learned unless they go through the approval flow.
- Do not auto-promote suggestions.
- Signal schema must be canonical at the registry boundary; consumers must not guess fields.
- Title-related learning candidates (`role_title_token`, `title_normalization_candidate`, `title_parse_blocker`) are often triage noise in workspace cards; keep them in the registry if needed, but suppress them in user-facing review text instead of inventing new labels.

## Allowed categories
- `capability_concept`
- `government_context`
- `role_title_token`
- `hard_blocker_pattern`
- `title_normalization_candidate`
- `cv_farming_pattern`

## Owners
- `signal_registry.py`: pending signal storage and review flow.
- `signal_schema.py`: signal keys/categories/constants.
- Managed knowledge modules: approved runtime knowledge after review.
- `job_quality.py`: job-quality detection that emits pending review signals.

## Checklist
- Does the signal include original evidence?
- Is it pending, not runtime-active?
- Is approval explicit?
- Is the category allowed?
- Is schema canonical and validated before consumers use it?
