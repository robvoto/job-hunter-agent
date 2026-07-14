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
- Do not hardcode extraction dictionaries to force outcomes.
- LLM extraction must be inspectable, constrained, and overrideable.
- Profile updates should be incremental, not silent regeneration.

## Owners
- `cv_pipeline.py`: CV analysis and extraction.
- `profile_learning.py`: free text to profile updates.
- `profile_store.py`: profile shape and normalisation.
- `capability_matrix.py`: capability clustering/matrix.
- `signal_registry.py`: pending learned signals.

## Known danger zone: normalize_full_profile
`normalize_full_profile` (in `profile_store.py`) is called on every `load_profile()` and `save_profile()`.
It runs `normalize_capability_rules` on `candidate_capabilities`. Any mutation here silently
affects every profile read and write.

**Migration pattern rule:** the migration block at the end of `normalize_full_profile` is for
renaming the legacy key `capability_profile_rules` → `candidate_capabilities`. The `if` condition
must check the OLD key, not the new one. Checking the new key deletes capabilities on every call.
Test any change here with `test_normalize_full_profile_preserves_candidate_capabilities` and
`test_normalize_full_profile_migrates_legacy_capability_profile_rules_key`.

**No broad except swallowing in the capability path.** `normalize_capability_rules` has a guarded
import of `capability_matrix` functions with `except Exception: pass`. This is acceptable for an
optional enhancement module, but do not add further broad exception swallowing in this path.

## Checklist
- Is every dropped signal intentionally discarded with a reason?
- Are uncertain capabilities preserved for review?
- Is source evidence retained or traceable?
- Is the profile update incremental?
- Is schema normalised at the owner boundary?
- Does `normalize_full_profile` preserve `candidate_capabilities` through a round-trip?
