# CV text retention decision

## Decision

Do not persist full raw CV text (`cv_text`) by default.

The CV text may be used transiently during onboarding import, but the saved profile should keep only structured profile signals and minimal evidence needed for matching.

## Candidate profile tiers

`candidate_profile_tiers` are CV evidence buckets:

- Primary: strongest or most recent experience
- Secondary: older or less central experience
- Supplementary: extra background

They should be produced during onboarding import. If missing later, treat that as a profile migration or repair issue, not as a reason to retain full CV text forever.

## Replacement direction

Save structured outputs such as:

- target roles
- also-consider roles
- capability profile rules
- candidate evidence buckets
- capability recency metadata
- search and match preferences

Do not save:

- full raw CV body
- original CV file
- full extracted document text

## Current after-onboarding dependencies

The main dependency that still needs replacement is scoring recency lookup. It currently scans `profile.cv_text` to find recent/old skill usage. Replace this with structured recency evidence on capability rules.
