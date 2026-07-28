---
name: onboarding-ui
description: Use ONLY for onboarding wizard/search-basics UI, onboarding templates/scripts/routes, bootstrap data, reset/resume flow, upload flow, and onboarding validation. Do NOT use for workspace/dashboard UI.
---

# Onboarding UI

See `.skills/onboarding-ui/DETAILS.md` for module ownership notes, UI component maps, reset/resume behaviour, and longer examples.

## Load order
1. Read `AGENTS.md` first.
2. Read this skill.
3. If module ownership or field-specific behaviour matters, read `.skills/onboarding-ui/DETAILS.md` for the relevant section only.

## Non-negotiable rules
- Keep canonical values in the owning server normaliser, DB-backed profile/settings source, or bootstrap source.
- Do not invent defaults, labels, fallback values, or business decisions in page code.
- Preserve the single-term search keyword rule. Do not auto-join title lists or create synthetic search phrases.
- Preserve reset flow: `?fresh=1` clears user-scoped onboarding draft state, blanks search/salary fields, then loads fresh defaults.
- Reuse shared theme tokens, widgets, field-label rows, choice strips, and helper functions first.
- Before changing any token value or control height, read `docs/UI_COMPONENT_MAP.md` — the design standards section documents touch-target minimums, intentional size hierarchy, and the token ownership chain. Some values are accessibility constraints, not style preferences.
- Do not create onboarding-local CSS for reusable UI components. Reusable visual styling belongs in `templates/static/theme/themes.widgets.css` or the relevant central theme/token file.
- Onboarding CSS may only define onboarding-specific layout, wizard flow placement, and responsive exceptions. If adding local CSS, add a comment explaining why it cannot be central.
- Keep onboarding and settings patterns separate where the repo already intentionally does so.
- Centralise repeated copy in `data/knowledge/ui_labels.json` or the owning server copy source.
- Remove dead onboarding paths instead of leaving compatibility code behind.
- Follow the established modular JS ownership pattern; add behaviour to the smallest owning onboarding module.

## Current ownership summary
- `onboarding-page.js`: DOM refs, page state, step navigation, location rendering, display helpers.
- `onboarding-storage.js`: wizard draft persistence, search-basics DB persistence, preference field event handlers.
- `onboarding-search.js`: selected locations and search-basics hydration.
- `onboarding-flow.js`: review rendering, capability cards, step-transition actions, startup orchestration.
- `onboarding-upload.js`: CV validation, drop zone, create-profile availability.
- `server_helpers.py` and `routes/pages.py`: labels/bootstrap globals.
- `profile_store.py`: runtime profile persistence and onboarding-imported state.

## Detailed patterns moved to DETAILS.md
Read only when needed:
- full module ownership notes
- persistence model
- UI component map
- runtime globals
- reset/resume behaviour
- validation details

## Validation
- Check the rendered onboarding page or the smallest relevant browser interaction.
- Prefer targeted checks over full test runs unless the change crosses multiple owners.
- Never add a second persistence path for wizard state.



