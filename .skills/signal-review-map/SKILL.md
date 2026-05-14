---
name: signal-review-map
description: Understand capability alias flow in job_hunter_agent, especially dominant_signal_clusters vs capability_profile_rules, where aliases are created, where they are saved, and where they are dropped. Use when tracing why aliases appear, disappear, or look sparse in profile.json or onboarding review screens.
---

# Signal Review Map

Use this skill when you need the capability alias path, not the UI wording.

Keep this split straight:

- `dominant_signal_clusters` are raw CV-derived evidence clusters.
- `capability_profile_rules` are the approved capability rules saved for runtime use.
- The two lists are related but not the same.

## Core map

- Start at `job_hunter_agent/source_documents.py`.
- `run_onboarding()` builds both:
  - deterministic `pipeline_patch` from `cv_pipeline.py`
  - learning `learning_patch` from `profile_learning.py`
- The final saved `capability_profile_rules` currently come from the learning path.
- `profile_store.normalize_capability_rules()` only cleans and dedupes aliases. It does not create new ones.

## Alias path

- If you want more aliases, check `profile_learning._llm_extract_from_cv()`.
- If a richer deterministic alias set exists but does not show up in the saved profile, it was dropped before save.
- If the question is "what should the review screen show?", trace the UI binding, not the storage shape.

## What to check first

- If aliases look sparse, inspect `profile_learning._llm_extract_from_cv()`.
- If the reviewed screen is showing the wrong layer, inspect the onboarding UI bindings.
- If rich deterministic aliases exist but do not appear in the saved profile, trace `source_documents.run_onboarding()` and the overwrite of `capability_profile_rules`.

## Rules

- Do not confuse admin learning review material with candidate/job review material.
- Do not invent aliases.
- Do not add heuristic alias expansion unless explicitly requested.
- Remove dead or duplicate paths if one layer is no longer used.
