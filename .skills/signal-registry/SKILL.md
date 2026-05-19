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
- `sector`
- `role_title_token`
- `role_title_pattern` — structural title pattern using `[*]` wildcard; routes to `role_title_rules.json` via `upsert_role_title_rule()`
- `sector_pattern` — structural clearance/agency pattern using `[*]` wildcard; routes to `sector_patterns.json` via `upsert_sector_pattern()`
- `hard_blocker_pattern`
- `title_normalization_candidate`
- `cv_farming_pattern`
- `profile_section_label` — CV section heading the LLM couldn't confidently route; `suggested_values[0]` holds the bucket (`primary`/`secondary`/`supplementary`); approval calls `upsert_profile_section_label()` which appends the word to the correct list in `parsing_rules.json`

## Auto-promotion exception
`profile_section_label` is the only category where confident LLM classification bypasses the registry and writes directly to `parsing_rules.json` via `upsert_profile_section_label()`. This is intentional and user-approved. All other categories must go through pending → review → approve.

## Naming
- The canonical Python constant for the CV-parsing title blocker list is `KEY_TITLE_PARSE_BLOCKERS` (in `parsing_schema.py`), JSON key `title_parse_blockers` in `parsing_rules.json`
- This list is static config — it is NOT a signal category and cannot be edited via the registry
- Role titles are now extracted by the LLM during CV processing, not by heuristic parsing

## Owners
- `signal_registry.py`: pending signal storage and review flow.
- `signal_schema.py`: signal keys/categories/constants.
- `parsing_schema.py`: JSON key constants for `parsing_rules.json`.
- Managed knowledge modules: approved runtime knowledge after review.
- `job_quality.py`: job-quality detection that emits pending review signals.

## Checklist
- Does the signal include original evidence?
- Is it pending, not runtime-active?
- Is approval explicit?
- Is the category allowed?
- Is schema canonical and validated before consumers use it?
