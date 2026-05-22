---
name: onboarding-ui
description: Onboarding wizard, search-basics, and onboarding page UI. Use when editing onboarding templates, scripts, routes, or bootstrap data, especially around reset flow, shared widgets, copy ownership, or onboarding-specific validation.
---

# Onboarding UI

Use before editing the onboarding wizard, search-basics step, or any onboarding template, script, or route bootstrap data.

## Rules
- Keep canonical values in the owning server normaliser or bootstrap source. Do not invent defaults, labels, or fallback values in page code.
- Treat onboarding and settings as different UI patterns when the repo already does so. Do not merge the onboarding sector select with the settings choice strip, or replace shared work-mode and engagement widgets with one-off controls.
- Preserve the single-term search keyword rule. Do not auto-join title lists or create synthetic search phrases.
- Keep reset flow behaviour intact: `?fresh=1` must clear onboarding browser state, blank the search and salary fields, then load fresh defaults.
- Reuse shared theme tokens, widgets, and helper functions first. Add page-level CSS only for onboarding-specific layout exceptions.
- Keep common language stable across the app. Use the existing screen names and labels instead of introducing new jargon.
- Centralise repeated copy in the owning label JSON or server copy source. Do not duplicate labels in renderer code.
- Remove dead onboarding paths instead of leaving compatibility code behind.

## Main files
- `templates/onboarding.html` - page shell and onboarding sections.
- `templates/static/onboarding/onboarding-page.js` - onboarding state, shared refs, page wiring, and step orchestration.
- `templates/static/onboarding/onboarding-flow.js` - review draft, check setup, capability review, and onboarding actions.
- `templates/static/onboarding/onboarding-search.js` - search basics state and location/search hydration.
- `templates/static/onboarding/onboarding-storage.js` - wizard state save/restore and search-basics persistence.
- `templates/static/onboarding/onboarding-upload.js` - CV validation, drop handling, and create-profile availability.
- `templates/static/onboarding/onboarding-page.css` - onboarding-only layout exceptions and spacing.
- `job_hunter_agent/routes/pages.py` - route rendering and bootstrap injection.
- `job_hunter_agent/server_helpers.py` - onboarding label loading and injected globals.
- `job_hunter_agent/profile_store.py` - runtime profile persistence and onboarding-imported state.
- `data/knowledge/ui_labels.json` - shared onboarding copy source.

## UI Component Map
- `primary_cv`, `cv_drop_zone`, `cv_drop_zone_content` - CV import and file state, owned by `onboarding-upload.js`.
- `wizard_step*`, `wizard_progress_fill`, `wizard_progress_step` - step navigation and progress, owned by `onboarding-page.js` and `onboarding-flow.js`.
- `review_search_keywords`, `min_contract_months`, salary inputs - search basics and compensation, owned by `onboarding-search.js` with page orchestration.
- `review_capability_*` - capability review rendering and filtering, owned by `onboarding-flow.js`.
- `location_search` and location summaries - location preferences and hydration, owned by `onboarding-search.js`.
- `onboarding_import_helper` - import helper copy and visibility, owned by page wiring and flow actions.
- `create_profile`, `continue_to_review`, and other continue buttons - action availability and transitions, owned by `onboarding-upload.js` plus flow handlers.

## Runtime globals
- `__JOB_HUNTER_ONBOARDING_FLOW_LABELS__` - review-flow copy and action labels.
- `__JOB_HUNTER_ONBOARDING_PAGE_LABELS__` - Search Basics copy and summaries.
- `__JOB_HUNTER_ONBOARDING_IMPORT_SUMMARY_LABELS__` - import summary copy and preview count.
- `__JOB_HUNTER_TITLE_TIER_LABELS__` - title-tier onboarding copy.
- `__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__` - onboarding sector select options.

## Validation
- Check the rendered onboarding page or the smallest relevant browser interaction for the changed screen.
- Prefer targeted checks over full test runs unless the change crosses multiple owners.
- Keep module boundaries explicit. Add new onboarding behavior to the smallest owning module instead of growing `onboarding-page.js`.
