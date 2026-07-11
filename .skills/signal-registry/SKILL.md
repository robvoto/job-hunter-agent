---
name: signal-registry
description: Use ONLY for approved learning signal lifecycle: pending/approved/ignored signals, promotion into runtime knowledge, and signal governance. Do NOT use for raw ad extraction; use ad-learning.
---

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
- Role titles are now extracted by the LLM during CV processing, not by heuristic parsing
- Do not document or reintroduce heuristic CV title blocker lists unless they exist in code and have an approved owner. Stale references should be removed rather than treated as architecture.

## Owners
- `signal_registry.py`: pending signal storage and review flow.
- `signal_schema.py`: signal keys/categories/constants.
- `parsing_schema.py`: JSON key constants for `parsing_rules.json`.
- Managed knowledge modules: approved runtime knowledge after review.
- `job_quality.py`: job-quality detection that emits pending review signals.

## When learning signals are generated

**Deterministic path** (scoring decides without LLM):
- `build_ad_learning_signals()` in `source_learning.py` runs deterministically and produces `ad_learning_signals`
- If high-value ambiguous candidates exist, a separate learning-only LLM call (`fit_review=False`) is made → `learning_candidates`
- Both are merged and registered

**Full LLM path** (LLM is called for fit decision):
- Only `ad_learning_signals` (deterministic) are registered — no LLM learning candidates
- The fit review LLM schema (`_LLMFitReviewPayload`) has no `learning_candidates` field
- Do not add learning category guidance to the fit review prompt; the fit-review schema has no learning fields and category names must not leak into capability names

**Consequence:** `government_context_pattern`, `role_title_pattern`, and similar signals are only generated for jobs decided by the deterministic path. Jobs decided by the full LLM review produce no LLM-proposed learning candidates.

## Capability alias review map
Use this section only when tracing capability alias mapping between `dominant_signal_clusters`, `candidate_capabilities`, DB `user_profile`, and onboarding review screens.

Keep this split clear:
- `dominant_signal_clusters` are raw CV-derived evidence clusters.
- `candidate_capabilities` are approved capability rules saved for runtime use.
- The two lists are related but not the same.

Core map:
- Start at `job_hunter_agent/source_documents.py`.
- `run_onboarding()` builds both deterministic `pipeline_patch` from `cv_pipeline.py` and learning `learning_patch` from `profile_learning.py`.
- Final saved `candidate_capabilities` currently come from the learning path.
- `profile_store.normalize_capability_rules()` only cleans and dedupes aliases. It does not create new ones.

If aliases look sparse, inspect `profile_learning._llm_extract_from_cv()`.
If the review screen shows the wrong layer, inspect onboarding UI bindings.
Do not invent aliases or add heuristic alias expansion unless explicitly requested.

## Checklist
- Does the signal include original evidence?
- Is it pending, not runtime-active?
- Is approval explicit?
- Is the category allowed?
- Is schema canonical and validated before consumers use it?
