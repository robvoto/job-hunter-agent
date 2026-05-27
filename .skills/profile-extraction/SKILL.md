---
name: profile-extraction
description: Use ONLY for CV parsing, profile extraction, candidate capabilities, role history, role duration, and profile normalization. Do NOT use for job-ad learning.
---

# Skill: Profile Extraction

Use before editing CV/onboarding/profile extraction, capability clustering, or profile updates.

## Rules
- Source documents are human truth; the per-user profile in the DB (`user_profile` table, via `profile_store.load_profile()`) is runtime machine truth.
- Do not silently delete extracted signals.
- Preserve questionable signals with `needs_review: true` where relevant.
- Do not invent capabilities, domains, or evidence not present in source material.
- Do not hardcode extraction dictionaries to force outcomes.
- LLM extraction must be inspectable, constrained, and overrideable.
- Profile updates should be incremental, not silent regeneration.

## Owners
- `cv_pipeline.py`: CV analysis and extraction.
- `profile_learning.py`: free text to profile updates.
- `profile_store.py`: profile shape and normalisation.
- `capability_matrix.py`: capability clustering/matrix.
- `signal_registry.py`: pending learned signals.

## Checklist
- Is every dropped signal intentionally discarded with a reason?
- Are uncertain capabilities preserved for review?
- Is source evidence retained or traceable?
- Is the profile update incremental?
- Is schema normalised at the owner boundary?
