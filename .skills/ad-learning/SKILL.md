---
name: ad-learning
description: Use ONLY for extracting learning candidates from job ads after scraping/review. Do NOT use for approved signal storage; use signal-registry instead.
---

# Skill: Ad Learning

Use before editing logic that learns from job ads or proposes new knowledge from job descriptions.

## Rules
- Job ads may suggest learning candidates; they must not create approved runtime knowledge directly.
- Suggestions go to the SQLite knowledge entry `signal_registry` through `signal_registry.register_signals()` as pending review first.
- Preserve original ad text/evidence for every suggestion.
- Do not let pending ad-derived patterns affect filtering, scoring, or ranking.
- Do not infer broad/general rules from weak evidence.
- Do not create new learning categories without explicit approval.

## Allowed learning categories
The canonical list is `signal_schema.VALID_SIGNAL_CATEGORIES`:
- `capability_concept`: possible capability, tool, method, or domain concept found in ads.
- `job_type_normalization_candidate`: employment-type wording that may need canonical mapping.
- `hard_blocker_pattern`: explicit requirement that may become a blocker after approval.
- `cv_farming_pattern`: learned job-quality phrase or regex that suggests CV collection behaviour.
- `profile_section_label`: CV-section routing label; this is produced by profile extraction, not job-ad learning.

Do not emit removed title, sector, or government-context categories.

## Boundaries
- Ad learning suggests; signal registry owns review state.
- Approved knowledge files own runtime behaviour.
- Consumers must read approved knowledge only, not pending suggestions.
- Learning output must use canonical schema; no consumer-side field guessing.

## Checklist
- Is the suggestion backed by exact ad evidence?
- Is the suggested category one of the approved categories?
- Is the signal pending review only?
- Is original text preserved for user review?
- Can the user approve/reject before runtime use?
