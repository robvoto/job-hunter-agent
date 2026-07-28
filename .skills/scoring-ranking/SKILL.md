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

## Key owners
- `fit_scoring.py`: assembles score entries and highlights. `fit_score_breakdown()` composes three builder functions: `_requirement_fit_entries` (Requirement Fit %), `build_occupation_alignment_breakdown` (occupation alignment adjustment), `build_risk_breakdown` (hard blockers). Hard blockers appear in the risk section and do not short-circuit the full breakdown. Use `has_hard_blockers()` for downstream exclusion.
- `job_review_pipeline.py`: freezes `fit_score`, `fit_score_breakdown`, `fit_label`, and `fit_tone_class` onto kept records before persistence.
- `workspace_renderer.py`: reads frozen score fields from records and should not call scoring functions for card display.
- `profile_store.py`: loads/normalises scoring/profile settings. New top-level `scoring_rules.json` sections must be added to `_load_default_scoring_rules()`'s explicit key whitelist (with a matching `KEY_*` constant) or they are silently dropped and never reach `get_scoring_rules()`.
- `data/knowledge/scoring_rules.json`: managed scoring policy, including `occupation_alignment` (same/adjacent/different adjustments).
- `data/knowledge/match_level_defaults.json`: match band thresholds.
- `data/knowledge/parsing_rules.json`: labels/display text where already owned there.

## Breakdown label ownership
Score breakdown labels shown to users must come from `data/knowledge/ui_labels.json`, never hardcoded:
- `grade_labels`: human-readable LLM grade descriptions (e.g. "The job ad matches your experience well")
- `title_match_labels`: human-readable title match descriptions (e.g. "The job title matches one of your target roles")
- `fit_highlight_labels.capability_match_sentence`: template for capability matches shown in fit reasons

When changing these labels, bump `ui_labels.json` version so `db_seed --upgrade` re-seeds the DB on deploy.

## Checklist
- No `.get(..., fallback)` for scoring business data.
- No inline `{level: points}` maps.
- No hardcoded UI labels in scoring functions.
- No consumer-side guessing like `fit_label or name`.
- No renderer-side `fit_score(...)` / `fit_score_breakdown(...)` calls for workspace cards.
- No `confidence_levels_logged_only` / `confidence_levels_ignored` policy branches in scoring config or code.
- Run the smallest scoring-related test/check.

## LLM output validation

For LLM review data:

- `decision` must be one of `KEEP`, `REJECT`, or `MAYBE`
- `grade` must be present if the scoring path uses it
- missing or invalid values must not silently become neutral/default values
- return an explicit degraded state instead
- log or expose the degraded state in audit output
- add/adjust tests for the degraded path

## LLM call paths - two schemas, two purposes

There are two separate LLM calls with different schemas. Do not conflate them.

**Fit review** (`_LLMFitReviewPayload`, `fit_review=True`):
- Returns: `fit_review` (decision + grade), `job_requirements`, `requirement_coverage`, `debug_reason`, `occupation_alignment`, `occupation_alignment_reason`
- No `learning_candidates` field; the fit-review path does not extract learning signals
- `requirement_coverage` is the single source for capability support — entries must link to profile capability rule names for `supported`/`partially_supported` status
- Do NOT include learning category guidance (`LLM_PROMPT_ROLE_TITLE_PATTERN_GUIDANCE`) in this prompt
- `debug_reason` is a short internal explanation for logs/admin only — not shown in the main UI

**Learning-only** (`_LLMReviewPayload`, `fit_review=False`):
- Returns: `learning_candidates` only
- Called only when deterministic scoring fires AND high-value ambiguous learning candidates exist
- Candidates are validated against `llm_gate.ALLOWED_LEARNING_CATEGORIES`, derived from `signal_schema.VALID_SIGNAL_CATEGORIES`; removed legacy categories must not be reintroduced

**Consequence for `requirement_coverage` in scoring:**
- `fit_scoring.py` is a consumer only - it reads stored LLM output from the record, never calls the LLM
- `requirement_coverage` entries are typed. Use `requirement_type="capability"` for skill coverage and `requirement_type="eligibility"` for explicit facts like clearances or work rights.
- `requirement_coverage` entries with `supported`/`partially_supported` status that lack the matching profile fact name are skipped (logged at WARNING)
- Convergence bonus uses `requirement_coverage` supported count — `min_positive_matches` from `scoring_rules.convergence`
- The learning pipeline handles signal routing via `build_ad_learning_signals` and the learning-only LLM call - do not route from `fit_scoring.py`

**`derive_fit_review_grade` contract (in `llm_gate.py`):**
- `supported` = 1.0, `partially_supported` = 0.5, `not_shown`/`mismatch` = 0.0
- Any `mismatch` present + zero positive coverage → MISMATCH
- Any `mismatch` present + some positive coverage → WEAK (hard cap, cannot be SOLID/STRONG/EXCELLENT)
- No mismatch: EXCELLENT (all supported, ≥3 reqs), STRONG (≥80% support, ≤1 partial), SOLID (≥50% support), WEAK (some support), POOR (no support)
- Grade derivation tests live in `tests/test_llm_gate.py` (section: derive_fit_review_grade contract)

## Occupation alignment scoring

`final_score = requirement_fit + occupation_adjustment`, clamped 0–100.

- The LLM classifies `occupation_alignment` as one of `same`/`adjacent`/`different` (title + dominant duties vs. candidate target roles). It never sets the numeric penalty.
- The adjustment is looked up server-side from `scoring_rules.json` `occupation_alignment` (`same=0`, `adjacent=-10`, `different=-20`) via `_occupation_alignment_adjustments()` in `fit_scoring.py`.
- Missing or invalid values degrade to the `LLM_INVALID_OCCUPATION_ALIGNMENT` sentinel (`_normalize_llm_occupation_alignment` in `llm_gate.py`) — shown as "Needs review (not classified)" with a zero adjustment. This never blocks a KEEP or rejects the job; see `has_complete_llm_keep_data()` in `llm_review_state.py`, which deliberately does not require `occupation_alignment`.
- `occupation_alignment_diagnostics()` / `format_occupation_alignment_diagnostics_block()` in `fit_scoring.py` are the single source for alignment, reason, adjustment, and final-calculation text shown in `server.log` (logged from `_freeze_fit_score_fields()` in `job_review_pipeline.py`) and in the "Debug: LLM fit review" panel (`workspace_renderer.py`).

