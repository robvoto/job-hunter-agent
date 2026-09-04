---
name: profile-extraction
description: Use ONLY for CV parsing, profile extraction, candidate capabilities, role history, role duration, and profile normalization. Do NOT use for job-ad learning.
---

# Skill: Profile Extraction

Use before editing CV/onboarding/profile extraction, capability clustering, eligibility facts, or profile updates.

## Rules
- Source documents are human truth; the per-user profile in the DB (`user_profile` table, via `profile_store.load_profile()`) is runtime machine truth.
- Do not silently delete extracted signals.
- Preserve questionable signals with `needs_review: true` where relevant.
- Do not invent capabilities, domains, or evidence not present in source material.
- Keep `candidate_capabilities` for skills/experience and `candidate_eligibility` for explicit true/false facts such as clearances, work rights, licences, registrations, and certifications.
- Eligibility facts must describe a **current claimable state**, not a future possibility. "Eligible to obtain", "able to obtain", willingness, suitability, or generic "X eligibility" are not proof that the candidate holds X.
- Keep independent eligibility facts separate. Do not compress prerequisite/dependency wording into one canonical label; if a prerequisite (for example citizenship) is itself explicitly true, store that separately and do not infer the dependent fact.
- Do not hardcode extraction dictionaries to force outcomes.
- LLM extraction must be inspectable, constrained, and overrideable.
- Semantic eligibility interpretation belongs in the LLM extraction contract/schema, not in Python substring/regex phrase heuristics. Deterministic validation should enforce shape and evidence boundaries only.
- Profile updates should be incremental, not silent regeneration.

## Owners
- `cv_pipeline.py`: CV analysis and extraction.
- `profile_learning.py`: free text to profile updates.
- `profile_store.py`: profile shape and normalisation.
- `capability_matrix.py`: capability clustering/matrix.
- `signal_registry.py`: pending learned signals.

## Role duration freshness (`role_experience[].segments`)

Each `role_experience` family row carries `segments: list[dict]` — one entry per
extracted role segment: `{duration_months, is_current}`, plus `duration_as_of`
(the real extraction date, ISO) only on a still-current segment. This is a
**runtime-only backend field**: not user-editable, not in `collectProfile()`, no
Settings control. `segments` is mandatory on every persisted `role_experience` row.
Pre-live stale rows without it are invalid and disposable; do not preserve or migrate
them. Rebuild the profile from the saved CV if current role history is needed.

- `profile_learning._stamp_current_role_extraction_dates` stamps `duration_as_of`
  only on the genuine (uncached) LLM path, so the date always pairs with a
  freshly extracted `duration_months`.
- Both `_aggregate_role_experience` and `profile_store.normalize_role_experience`
  must preserve segments through their aggregation.
- Effective (accrued) family months live in `role_experience_duration.py`; only
  `experience_requirements.py` and `llm_gate.build_profile_prompt_context` consume
  it. Nothing writes accrued months back onto the profile or into capabilities.
- **Bump `_CV_EXTRACTION_CACHE_CONTRACT_VERSION` whenever the extracted CV shape
  changes** so every cached extraction misses and is genuinely re-run — otherwise
  a stale cached `duration_months` gets paired with a fresh date.

## Known danger zone: normalize_full_profile
`normalize_full_profile` (in `profile_store.py`) is called on every `load_profile()` and `save_profile()`.
It runs `normalize_capability_rules` on `candidate_capabilities`. Any mutation here silently
affects every profile read and write.

**Pre-live schema rule:** do not keep key-renaming migrations, aliases, or old/new profile
shapes in this normalizer. Persist and consume only the current canonical profile keys. If stale
dev/test profile data uses a removed key, discard/rebuild that data instead of teaching runtime
code to understand it.

**No broad exception swallowing in the capability path.** Do not add `except Exception: pass` or
similar fallbacks around capability normalisation. If the optional enhancement import is changed,
catch only the expected import failure and keep unexpected errors visible.

## Checklist
- Is every dropped signal intentionally discarded with a reason?
- Are uncertain capabilities preserved for review?
- Is source evidence retained or traceable?
- Is the profile update incremental?
- Is schema normalised at the owner boundary?
- Does `normalize_full_profile` preserve `candidate_capabilities` through a round-trip?

## Profile-field integration gate

When adding or changing a persisted candidate-profile field, do not stop at the
extractor or runtime normaliser. If the field is user-editable or user-visible,
load `dashboard-ui` (and `css-design-system` for visual changes) and verify the
complete Settings contract:

- profile default, normaliser, and runtime consumer use the same canonical key;
- the Settings partial renders the control/editor;
- `settings-page.js` loads the field and includes it in `collectProfile()`;
- route validation and persistence accept the same shape;
- labels come from the owning knowledge/bootstrap source;
- a save/reload regression test covers the round trip, with a browser test for
  interactive controls where the existing Settings E2E path supports it.

Backend-only profile fields must be explicitly documented as read-only or
runtime-only. Never assume a new profile key will appear in Settings
automatically.
