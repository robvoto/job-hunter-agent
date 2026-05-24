# CV text retention decision

## Decision

Do not persist full raw CV text (`cv_text`) in the normal profile lifecycle.

The CV text may be used transiently during onboarding import, but the saved profile must keep only structured profile signals, evidence buckets, and capability rules.

## Candidate profile tiers

`candidate_profile_tiers` are CV evidence buckets:

- Primary: strongest or most recent experience
- Secondary: older or less central experience
- Supplementary: extra background

They should be produced during onboarding import. If missing later, treat that as a profile migration or repair issue, not as a reason to retain full CV text forever.

## Saved profile shape

Persist structured outputs such as:

- target roles
- also-consider roles
- capability profile rules
- candidate evidence buckets
- search and match preferences

Do not save:

- full raw CV body
- original CV file
- full extracted document text

## Runtime use

Scoring and profile normalisation now read `candidate_profile_tiers` only for evidence lookup. They do not read persisted `cv_text`.

## Migration

Legacy saved profiles that still contain `cv_text` are repaired on load by stripping the raw text and keeping the structured fields intact.
