---
name: scoring-ranking
description: Use ONLY for fit score calculation, ranking, score explanations, score weights, and score regression tests. Do NOT use for hard rejection filters; use job-filtering.
---

# Skill: Scoring & Ranking

Use before editing `fit_scoring.py`, `capability_matching.py`, `signal_detection.py`, `score_labels.py`, or match bands.

## Rules
- Fit score is transparent, configurable, and explainable.
- Do not add inline weights, thresholds, caps, grade maps, or fallback labels.
- Scoring values come from profile/config/managed knowledge loaders.
- Display policy, such as card highlight counts, belongs in settings/config, not scoring logic.
- Producers normalise schema; scoring consumes canonical fields only.
- Do not bypass hard blockers to increase score.
- Workspace rendering consumes frozen score fields stored on the record; do not reintroduce live score recomputation there.
- A valid canonical profile capability name is necessary but not sufficient evidence that a requirement is covered. The mapped capability must prove a substantive element stated in the requirement itself.
- Broad transferable capabilities must not act as universal partial-match fallbacks. Transferability may be useful context, but it receives zero requirement-fit credit unless the profile proves part of the defining domain, technology, activity, qualification, methodology, or responsibility.
- When multiple related requirements define the specialist nature of the role, treat them as a role-defining group. Generic occupation duties must not produce a Strong Match while that specialist group is substantially uncovered.

## Key owners
- `fit_scoring.py`: assembles score entries and highlights. `fit_score_breakdown()` composes three builder functions: `_requirement_fit_entries` (Requirement Fit %), `build_occupation_alignment_breakdown` (occupation alignment adjustment), `build_risk_breakdown` (hard blockers). Hard blockers appear in the risk section and do not short-circuit the full breakdown. Use `has_hard_blockers()` for downstream exclusion.
- `job_review_pipeline.py`: freezes `fit_score`, `fit_score_breakdown`, `fit_label`, and `fit_tone_class` onto kept records before persistence.
- `workspace_renderer.py`: reads frozen score fields from records and should not call scoring functions for card display.
- `profile_store.py`: loads/normalises scoring/profile settings. New top-level `scoring_rules.json` sections must be added to `_load_default_scoring_rules()`'s explicit key whitelist (with a matching `KEY_*` constant) or they are silently dropped and never reach `get_scoring_rules()`.
- `data/knowledge/scoring_rules.json`: managed scoring policy, including `occupation_alignment` (same/adjacent/different adjustments).
- `data/knowledge/match_level_defaults.json`: match band thresholds.
- `data/knowledge/parsing_rules.json`: labels/display text where already owned there.

## Checklist
- No `.get(..., fallback)` for scoring business data.
- No inline `{level: points}` maps.
- No hardcoded UI labels in scoring functions.
- No consumer-side guessing like `fit_label or name`.
- No renderer-side `fit_score(...)` / `fit_score_breakdown(...)` calls for workspace cards.
- No `confidence_levels_logged_only` / `confidence_levels_ignored` policy branches in scoring config or code.
- Run the smallest scoring-related test/check.

## Detailed reference
See `DETAILS.md` for score-label ownership, requirement-evidence validation, LLM schema contracts, and occupation-alignment details.
