# Skill: Scoring & Ranking

Use before editing `fit_scoring.py`, `capability_matching.py`, `signal_detection.py`, `score_labels.py`, or match bands.

## Rules
- Fit score is transparent, configurable, and explainable.
- Do not add inline weights, thresholds, caps, grade maps, or fallback labels.
- Scoring values come from profile/config/managed knowledge loaders.
- Display policy, such as card highlight counts, belongs in settings/config, not scoring logic.
- Producers normalise schema; scoring consumes canonical fields only.
- Do not bypass hard blockers to increase score.

## Key owners
- `fit_scoring.py`: assembles score entries and highlights. Breakdown is split into four builder functions: `build_core_fit_breakdown`, `build_preference_breakdown`, `build_convenience_breakdown`, `build_risk_breakdown`. Hard blockers appear in the risk section — they no longer short-circuit the full breakdown. Use `has_hard_blockers()` for downstream exclusion.
- `profile_store.py`: loads/normalises scoring/profile settings.
- `data/scoring_rules.json`: managed scoring policy.
- `data/match_level_defaults.json`: match band thresholds.
- `data/parsing_rules.json`: labels/display text where already owned there.

## Checklist
- No `.get(..., fallback)` for scoring business data.
- No inline `{level: points}` maps.
- No hardcoded UI labels in scoring functions.
- No consumer-side guessing like `fit_label or name`.
- Run the smallest scoring-related test/check.

## LLM output validation

For LLM review data:

- `decision` must be one of `KEEP`, `REJECT`, or `MAYBE`
- `grade` must be present if the scoring path uses it
- missing or invalid values must not silently become neutral/default values
- return an explicit degraded state instead
- log or expose the degraded state in audit output
- add/adjust tests for the degraded path
