# Skill: Ad Learning

Use before editing logic that learns from job ads or proposes new knowledge from job descriptions.

## Rules
- Job ads may suggest learning candidates; they must not create approved runtime knowledge directly.
- Suggestions go to `data/signal_registry.json` as pending review first.
- Preserve original ad text/evidence for every suggestion.
- Do not let pending ad-derived patterns affect filtering, scoring, or ranking.
- Do not infer broad/general rules from weak evidence.
- Do not create new learning categories without explicit approval.

## Allowed learning categories
- `capability_concept`: possible capability/skill concept found in ads.
- `government_context`: government/public-sector signal.
- `role_title_token`: role-title token or phrase useful for title matching.
- `hard_blocker_pattern`: explicit requirement that may become a blocker after approval.
- `title_normalization_candidate`: possible title wording/normalisation candidate.

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
