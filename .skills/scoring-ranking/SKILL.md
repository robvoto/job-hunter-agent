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

## LLM call paths — two schemas, two purposes

There are two separate LLM calls with different schemas. Do not conflate them.

**Fit review** (`_LLMFitReviewPayload`, `fit_review=True`):
- Returns: `fit_review` (decision + grade), `contextual_capability_matches`, `job_requirements`
- No `learning_candidates` field exists in this schema
- `contextual_capability_matches` entries must only use names from the profile capability rules list
- Do NOT include learning category guidance (`LLM_PROMPT_ROLE_TITLE_PATTERN_GUIDANCE`) in this prompt — the model will leak category names into capability matches

**Learning-only** (`_LLMReviewPayload`, `fit_review=False`):
- Returns: `learning_candidates` only
- Called only when deterministic scoring fires AND high-value ambiguous learning candidates exist
- This is where `role_title_pattern`, `government_context_pattern`, etc. belong

**Consequence for `contextual_capability_matches` in scoring:**
- `fit_scoring.py` is a consumer only — it reads stored LLM output from the record, never calls the LLM
- Entries in `contextual_capability_matches` that do not match a profile capability rule name are skipped for scoring (logged at WARNING with full context)
- The learning pipeline handles signal routing via `build_ad_learning_signals` and the learning-only LLM call — do not route from `fit_scoring.py`

## Government context scoring

Three separate knowledge sources, each with a distinct role:

- `government_context_rules` (DB key) — regex patterns for APS grades, EL levels, NV/baseline clearances. Used by `has_government_context()` in `role_analysis.py`. Hard detection.
- `government_context_knowledge` (DB key) — approved concept terms ("government", "public sector", etc.). Also used by `has_government_context()` via word-boundary regex. Populated via signal approval.
- `government_context_patterns` (DB key) — approved structural wildcard patterns ("NV[*] clearance"). Populated via signal approval of `government_context_pattern` learning candidates. Currently empty until patterns are approved.

`has_government_context()` → feeds `assess_sector_preference()` → affects fit score bonus/penalty based on user's sector preference setting.
