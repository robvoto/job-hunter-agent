---
name: onboarding-ui
description: Use ONLY for onboarding wizard/search-basics UI, onboarding templates/scripts/routes, bootstrap data, reset/resume flow, upload flow, and onboarding validation. Do NOT use for workspace/dashboard UI.
---

# Onboarding UI

Use for onboarding-only behaviour. For CSS/layout/component styling, also load `css-design-system`; for labels/defaults, load `no-hardcoding`. Read `DETAILS.md` only for the relevant module/persistence/reset pattern.

## Rules

- Canonical values stay in the owning server normaliser, DB-backed profile/settings source, or bootstrap source.
- Do not invent defaults, labels, fallback values, or business decisions in page code.
- Preserve the single-term search keyword rule; do not synthesize joined title phrases.
- `?fresh=1` clears user-scoped onboarding draft state and search/salary fields before fresh defaults are loaded.
- Keep onboarding/settings behaviour separate only where the product intentionally differs; shared controls/styles follow their shared owner.
- Remove dead onboarding paths rather than retaining compatibility code.
- Add behaviour to the smallest owning onboarding JS module; do not create a second wizard persistence path.

## Ownership

Detailed module ownership, bootstrap globals, persistence, reset/resume and field-specific patterns live in `DETAILS.md`; do not duplicate that map here.

## Validation

Verify the smallest relevant onboarding browser flow and targeted tests. Use broader validation only when the change crosses shared owners.
