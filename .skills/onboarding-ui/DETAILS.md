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
- Keep reset flow behaviour intact: `?fresh=1` must clear the user-scoped onboarding draft state, blank the search and salary fields, then load fresh defaults.
- Reuse shared theme tokens, widgets, and helper functions first. Add page-level CSS only for onboarding-specific layout exceptions.
- Reusable visual styling belongs in `templates/static/theme/themes.widgets.css`, `themes.primitives.css`, or `themes.tokens.css`; do not add onboarding-local CSS for reusable chips, cards, buttons, inputs, icons, or typography.
- If onboarding-local CSS is required, comment the rule as a local layout exception and keep it layout-only.
- Shared field labels and spacing come from the theme layer. Do not add page-local `label` baselines when the field uses `.field-label-row`; use the shared field-label tokens and widget rules instead.
- Keep common language stable across the app. Use the existing screen names and labels instead of introducing new jargon.
- Centralise repeated copy in the owning label JSON or server copy source. Do not duplicate labels in renderer code.
- Remove dead onboarding paths instead of leaving compatibility code behind.

## Module ownership

### `onboarding-page.js`
Owns: all DOM refs (`refs`), page-level state (currentStep, reviewCapabilityRules, etc.), step navigation (`setStep`), location rendering, capability layout observation, `saveWizardState` (called from `setStep` and `setSelectedLocation`), and display helpers (`showStatus`, `hideStatus`, `updateSearchPreferenceSummaries`, `updateCompensationVisibility`, `applyProfileDefaults`).

Does NOT own: event handler wiring for preference fields, search-basics DB persistence, or wizard state restore.

### `onboarding-storage.js`
Owns: wizard draft state save/restore (`saveWizardState`, `restoreWizardState`), search-basics DB persistence (`scheduleSearchBasicsPersistence`, `flushSearchBasicsPersistence`, `buildSearchBasicsProfilePatch`), AND event handler wiring for all search-basics preference fields (location, sector, minContractMonths, engagement type, work mode preference). Event handlers are wired at module-load time.

Imports from page.js (one-way dependency only â€” page.js must not import storage.js). All page state is accessed via `onboardingPage.*`.

### `onboarding-search.js`
Owns: `setSelectedLocations` (sets location from an array, called by flow.js) and `hydrateSearchBasics` (populates all search-basics fields from a DB profile, called by flow.js when step 3 needs a profile-backed fallback during review-to-search transitions or resume restores).

### `onboarding-flow.js`
Owns: review draft rendering, capability card rendering, check setup, all step-transition actions (continue buttons, upload submit, finalize), and `initWizard` (startup/restore orchestration).

Capability state on page load comes from:
1. `onboardingStorage.restoreWizardState()` â€” localStorage draft (user-scoped key)
2. `hydrateDraftStep(profile)` â€” falls back to DB profile if localStorage draft has no capabilities
3. `hydrateSearchBasics(profile)` â€” seeds step 3 from the best available profile source when search basics need to be restored or derived from review data.

### `onboarding-upload.js`
Owns: CV file validation, drop zone handling, and `create_profile` button availability.

## Data persistence model

| Layer | What is stored | When used |
|---|---|---|
| SQLite (DB) | Committed profile: capabilities, preferences, titles, salary | Authoritative; written on finalize or auto-sync |
| localStorage (`WIZARD_STATE_KEY`) | In-progress wizard draft: form fields not yet committed | Survives page refresh during active onboarding session |
| In-memory page state | Current step state while page is open | Lost on refresh; restored from localStorage or DB |

`WIZARD_STATE_KEY` is always user-scoped: `jobHunter.onboardingWizard:<USER_ID>`. Both `onboarding-page.js` and `onboarding-storage.js` reference `onboardingPage.WIZARD_STATE_KEY` â€” never a bare string key.

## Main files
- `templates/onboarding.html` - page shell and onboarding sections.
- `templates/static/onboarding/onboarding-page.js` - state, refs, step navigation, display helpers, `saveWizardState`.
- `templates/static/onboarding/onboarding-flow.js` - wizard orchestration, review/check step rendering, step-transition actions.
- `templates/static/onboarding/onboarding-storage.js` - wizard state save/restore, search-basics DB persistence, preference field event handlers.
- `templates/static/onboarding/onboarding-search.js` - `setSelectedLocations`, `hydrateSearchBasics` (called by flow.js for step transitions).
- `templates/static/onboarding/onboarding-upload.js` - CV validation, drop handling, and create-profile availability.
- `templates/static/onboarding/onboarding-page.css` - onboarding-only layout exceptions and spacing; not reusable component styling.
- `job_hunter_agent/routes/pages.py` - route rendering and bootstrap injection.
- `job_hunter_agent/server_helpers.py` - onboarding label loading and injected globals.
- `job_hunter_agent/profile_store.py` - runtime profile persistence and onboarding-imported state.
- `data/knowledge/ui_labels.json` - shared onboarding copy source.

## UI Component Map
- `primary_cv`, `cv_drop_zone`, `cv_drop_zone_content` - CV import and file state, owned by `onboarding-upload.js`.
- `wizard_step*`, `wizard_progress_fill`, `wizard_progress_step` - step navigation and progress, owned by `onboarding-page.js` and `onboarding-flow.js`.
- `review_search_keywords`, `min_contract_months`, salary inputs - search basics fields; hydrated by `onboarding-search.js` on step transitions, event handlers wired by `onboarding-storage.js`.
- `review_capability_*` - capability review rendering and filtering, owned by `onboarding-flow.js`.
- `location_search` and location summaries - location preferences; rendered by `onboarding-page.js`, hydrated by `onboarding-search.js`, change events wired by `onboarding-storage.js`.
- `onboarding_import_helper` - import helper copy and visibility, owned by page wiring and flow actions.
- `create_profile`, `continue_to_review`, and other continue buttons - action availability and transitions, owned by `onboarding-upload.js` plus flow handlers.

## Runtime globals
- `__JOB_HUNTER_ONBOARDING_FLOW_LABELS__` - review-flow copy and action labels.
- `__JOB_HUNTER_ONBOARDING_PAGE_LABELS__` - Search Basics copy and summaries.
- `__JOB_HUNTER_ONBOARDING_IMPORT_SUMMARY_LABELS__` - import summary copy and preview count.
- `__JOB_HUNTER_TITLE_TIER_LABELS__` - title-tier onboarding copy.
- `__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__` - onboarding sector select options.
- `__JOB_HUNTER_ONBOARDING_RESUME_STEP__` - server-computed step to resume from DB profile (1 or 2+).
- `__JOB_HUNTER_USER_ID__` - used to build scoped localStorage keys.

## Validation
- Check the rendered onboarding page or the smallest relevant browser interaction for the changed screen.
- Prefer targeted checks over full test runs unless the change crosses multiple owners.
- Keep module boundaries explicit. Add new onboarding behavior to the smallest owning module instead of growing `onboarding-page.js`.
- Never add a second `saveWizardState` function or a second persistence path â€” one in page.js (called from step/location changes), one in storage.js (called from preference field changes). Both write to the same scoped key.


