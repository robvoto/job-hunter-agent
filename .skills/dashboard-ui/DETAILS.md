# Skill: Workspace UI

Use before editing FastAPI routes, templates, workspace data, settings UI, or score/highlight display.

## Rules
- Workspace UI displays canonical data; it must not recreate filtering, scoring, or preference logic.
- Keep admin/user display policy configurable when it is tunable behaviour.
- Do not hardcode display counts, labels, thresholds, or fallback text in templates or feature code.
- Do not use silent fallbacks in UI routes or templates. Missing or invalid UI data should fail clearly or be fixed at the owning source.
- Settings UI must save/load through the same profile/settings normalisers as runtime code.
- Missing required settings or labels should fail clearly, not be invented in UI code.
- Route aliases such as `/workspace` and `/` must stay intentional and documented.
- Workspace header actions keep settings and logout in the top-right action cluster; do not move logout into the sidebar or hide it behind a drawer.
- UI structure and visual treatment must come from shared theme tokens/widgets first; page-level CSS is only for screen-specific layout exceptions.
- Reusable component styling must not be added to page CSS. Before adding CSS to a page file, check whether the selector belongs in `templates/static/theme/themes.widgets.css`, `themes.primitives.css`, or `themes.tokens.css`.
- If page-local CSS is genuinely required, add a short comment naming the exception, for example: `/* Local layout exception: onboarding step grid placement only. */`
- Shared blocking overlays must use the existing `job-hunter-wait-*` component from `themes.primitives.css` and `body.job-hunter-wait-active`; do not invent screen-local `ws-wait-*` variants or rename the mount/backdrop/shell classes without updating every consumer.
- If a workspace run is meant to be non-blocking, make that an explicit product decision. Do not let a class mismatch or partial CSS move silently change blocking behavior.
- Reuse existing widget patterns for help, drawers, chips, cards, and settings rows instead of creating new variants for the same job.
- Keep common language consistent across the app; if a screen is called settings or review, do not introduce alternate labels for the same concept.
- If a card shows summary + debug detail, keep the summary human-facing and make the debug detail readable. Do not surface raw matcher tokens, parser fragments, or implementation words in the card itself.
- If the same display text appears in more than one place, centralise it in the owning JSON label source instead of copying it into renderer code.
- If text or layout looks wrong, check the rendered HTML, the server-side copy source, and the CSS constraint together before editing one layer in isolation.
- Prefer adjusting the owning copy/data source over patching a template placeholder when the text is injected server-side.
- If a layout issue is local to one row or field, change only that owning selector; if the selector is a reusable component, change the central component selector rather than adding a page-local override.

## Workspace filter pattern
- Filter options that require data-driven groups are rendered server-side via a `render_*_filter_options()` function in `workspace_renderer.py` and injected as `$..._FILTER_OPTIONS_HTML` placeholders in `results.html`.
- When one filter option covers multiple canonical values, encode the option `value` as pipe-separated lowercase canonical values: `value="contract|temporary"`. JS splits on `|` before comparing against the card's data attribute.
- Card data attributes store the lowercased canonical value, for example `data-work-type="contract"`. Never store display labels in data attributes.
- Filter group definitions live in the relevant JSON data file, for example `data/job_type.json` `filter_groups` key, not in Python or JS.

## Per-user data
- All runtime state (profile, job history, run stats, audit records, review data, workspace pool, source materials, user settings) is stored in SQLite per-user tables. The active user is resolved via a `ContextVar` in `user_context.py`.
- `get_active_user_id()` in `paths.py` is the single resolver. It raises `RuntimeError` if no user is set — there is no silent fallback to a root directory.
- `get_workspace_results_path()` and `get_source_pack_dir()` are the only remaining filesystem path helpers for per-user data.
- Workspace sidebar counts (`This Run`, `Crawler Stats`, `Applications`) are user-scoped. If they show zero after a successful scrape, verify the active request or run context resolved the same `user_id` before assuming the scrape found nothing.
- Test reset tools (`_reset_current_user_state`) call `clear_job_history()`, `clear_review_data()`, `clear_run_stats()`, `clear_audit_rows()` from `io_utils.py` and wipe `USERS_DIR` filesystem subdirectories for source_pack and workspace_results.html.

## Onboarding / settings widget patterns

### Source enable toggles (`seek_enabled`, `linkedin_enabled`)
- Both rendered as `<label class="toggle-switch">` wrapping `<input type="checkbox" role="switch">` with a `<span class="toggle-switch-state" id="*_state">` sibling.
- JS reads/writes via `getToggleChecked(id)` / `setToggleChecked(id, bool)` / `setToggleStateText(stateId, bool)` from `settings-utils.js`.
- `collectProfile()` builds `enabled_sources` using `getToggleChecked('seek_enabled')` and `getToggleChecked('linkedin_enabled')`.
- **Never use `.value === 'true'` for a checkbox toggle** — a checkbox's `.value` is `"on"`, not `"true"`.

### Government preference (two patterns — do not merge them)
- **Settings** uses a choice strip (two checkboxes: Public, Private) via `__JOB_HUNTER_SECTOR_PREFERENCE_CHOICES__` → `render_sector_preference_choices()`. Both checked = "any". JS: `getSectorPreferenceValues()` / `setSectorPreferenceValues()`. Uses `card_class="choice-card--work-mode"` — same styled buttons as work mode and engagement type. Never use `choice-card--sector` (class does not exist).
- **Onboarding** uses `<select id="sector_preference">` with options via `__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__` → `render_sector_preference_select_options()`.
- `window.__JOB_HUNTER_SECTOR_PREFERENCE_OPTIONS__` is injected by `build_bootstrap_script()` — required by onboarding-flow.js for label lookups.
- Do not remove `render_sector_preference_select_options` or its `pages.py` replacement — it powers the onboarding select.

### Work mode (`input[name="work_mode_preference"]`)
- `window.__JOB_HUNTER_TITLE_TIER_LABELS__` is injected by `build_bootstrap_script()` and owns the onboarding labels/help text for target roles, also-consider roles, and the search keyword field.
- The onboarding search keyword is a single term. Do not auto-fill it with comma-joined title lists.
- Rendered by `server_helpers.render_work_mode_preference_choices()` as three `<label class="choice-card--work-mode">` checkboxes inside `<div id="work_mode_preference">`.
- Choice-strip layout may be page-specific, but card visual styling (`.choice-card--work-mode` and related reusable chip/button treatment) belongs in the central theme/widget CSS. Do not add duplicate page-local visual overrides.
- `setWorkModePreferenceValues(values)` in `onboarding-flow.js` and `settings-page.js`: when `values` is empty or none, all checkboxes must default to checked (`selected.size === 0 || selected.has(...)`).
- The min-one constraint, where the user cannot uncheck the last checkbox, is enforced via a `change` listener added at init in both `onboarding-flow.js` and `settings-page.js`. Programmatic unchecking, for example `setWorkModePreferenceValues([])`, does not fire `change`, so the default-all-selected rule in the setter is the only guard there.

### Engagement type (`input[name="engagement_pref"]`)
- Rendered by `server_helpers.render_engagement_type_radio_group()` as hidden radio inputs inside `.choice-card--engagement` labels.
- `getSelectedEngagementType()` reads `refs.engagementInputs`, populated at script-load time. If no radio is checked and `ENGAGEMENT_TYPE_DEFAULT` is falsy, it returns `''`, which fails `validateSearchPreferences`.
- `validateSearchPreferences` guards the engagement-type check with `ENGAGEMENT_TYPE_VALUES.size > 0` so a bootstrap timing issue does not block the user.
- `getSelectedEngagementType()` self-corrects: if the resolved value is not in `ENGAGEMENT_TYPE_VALUES`, it checks the first radio and returns its value.

### Source enable switches
- Source on/off controls in Settings should use the shared `toggle-switch` row pattern, not a dropdown select.
- Keep the control state wired through the same profile/settings normalisers and let the owning source code decide what "disabled" means.
- Apply this pattern one source at a time when the UI needs a focused review, rather than changing every boolean control in one pass.

### Government preference (`input[name="prefer_government"]`)
- Rendered by `render_sector_preference_choices()` as two checkbox cards for public and private.
- Both checked means no sector preference; one checked means the user wants that sector only.
- Keep the constraint logic in the shared settings JS so the UI and saved profile stay aligned.

### Bootstrap globals and validation
- `window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__`, `__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT__`, and related globals are injected by `build_bootstrap_script()` in `<head>`. They must be available before `onboarding-page.js` runs.
- Client-side validators (`validateSearchPreferences`) should guard `Set.size > 0` before treating an absent value as an error, to tolerate any edge case where globals are not yet set.

### LLM model dropdown (`#llm_model`)
- Options come from `global_settings.json → llm_settings.model_options`. On the admin page these are loaded via `GET /api/global-settings` into `loadedGlobalSettings`. On the standard settings page that fetch never runs (non-admin), so `window.__JOB_HUNTER_LLM_MODEL_OPTIONS__` is the source — injected by `build_bootstrap_script()` from the same file at page render.
- `renderLlmModelOptions()` in `settings-page.js` reads `loadedGlobalSettings?.llm_settings?.model_options ?? window.__JOB_HUNTER_LLM_MODEL_OPTIONS__`. The currently saved model (`loadedUserSettings?.llm?.model`) is prepended if it is not already in the list.
- `renderLlmModelOptions()` is called from `loadUserSettings()` (standard page) and `loadGlobalSettings()` (admin page). It is a module-private function — not exported and not on `window`. The `typeof renderLlmModelOptions === 'function'` guard in `settings-alerts.js` is a dead code path; it never fires because the function is not in module scope from that file.
- Do not remove the `window.__JOB_HUNTER_LLM_MODEL_OPTIONS__` bootstrap injection — it is the only model-options source for non-admin users.

### Choice-strip summaries (engagement type, work mode, sector preference)
- Each choice strip (`input[name="engagement_type"]`, `input[name="work_mode_preference"]`, `input[name="prefer_sector"]`) has a sibling `<p id="*_summary" class="summary-line">` that shows an "all selected" label when every option is checked.
- `updateSearchPreferenceSummaries()` in `settings-page.js` drives this. Label strings come from `window.__JOB_HUNTER_ONBOARDING_PAGE_LABELS__` keys: `work_type_summary_all_label`, `work_mode_summary_all_label`, `sector_preference_summary_all_label`. Do not hardcode these strings in JS — they are owned by `ui_labels.json`.
- Called on every change event for those inputs and once after `Promise.all(pageLoads)` on initial load.

## Reset User flow

- The reset redirects to `/start?fresh=1`. `initWizard()` in `onboarding-flow.js` detects `?fresh=1`, calls `clearOnboardingBrowserState()`, strips the param from the URL, explicitly clears the search-keyword and salary fields to `''`, awaits `loadProfileDefaults()`, then sets step 1. Do not change this without preserving all five steps.
- `clearOnboardingBrowserState()` removes sessionStorage key `jobHunter.onboardingWizard`. This function is defined in two places: `onboarding-page.js` for onboarding and inline in `workspace.html` for workspace. Keep them in sync if the key ever changes.
- `setCurrencyFieldValue` and `readCurrencyFieldValue` in `settings-utils.js` accept either a string ID or an HTMLElement. Do not change this back to ID-only, because onboarding callers always pass elements.
- After reset, keywords and location on the Search Basics step will re-populate from fresh CV extraction. That is correct, not stale state.
- `_onboarding_resume_step()` returns 2, Review Draft, only when `candidate_capabilities` is non-empty. A fresh-reset profile has `[]`, so it returns 1 and onboarding always starts at step 1 after reset.
- `applyProfileDefaults()` in `onboarding-page.js` only sets form fields when they are currently empty. After `bindCurrencyInput` runs `sync()` on page load, any non-empty field value is locked in and `applyProfileDefaults` will not override it. The `?fresh=1` handler bypasses this by explicitly resetting field `.value = ''` before `loadProfileDefaults()` runs.

## Theme CSS file map

| File | Purpose |
|---|---|
| `themes.tokens.css` | Per-theme palette tokens only. Edit here for colour, radius, spacing. |
| `themes.widgets.css` | Shared widget surface rules (card, panel, badge, chip, toggle). |
| `themes.primitives.css` | Wait-state overlay; touch before changing blocking behaviour. |
| `themes.css` | Imports the above three in order. |
| `workspace-page.css` | Workspace layout, filter panel, sidebar, pagination. Dark-professional overrides go here. |
| `results-page.css` | Job card, badge, button, block-confirm, rejection panel. Dark-professional badge overrides go here. |
| `settings-page.css` | Settings layout, inputs, capability editor. |
| `onboarding-page.css` | Onboarding-specific layout only. |

## Sidebar search card

The Common Search sidebar card is rendered from `$`-prefixed placeholders in `results.html`. Values are supplied by `workspace_service.py::render_html()`:
- `$SEARCH_KEYWORDS_LABEL`, `$SEARCH_LOCATIONS_LABEL`, `$WORK_TYPE_LABEL`, `$WORK_MODE_LABEL`
- `$GOVERNMENT_PREFERENCE_LABEL` — built by `_format_common_search_preferences()`, displayed as "Sector" (not "Government preference")
- `$DATE_RANGE_LABEL` — computed from `date_range_days` param passed to `render_html()`

If a new sidebar row is needed: add the placeholder to `results.html`, compute the value in `workspace_service.py::render_html()`, and add it to the substitutions dict.

## Dark professional theme conventions

Target aesthetic: Linear / GitHub dark / Vercel dashboard. Enterprise dark SaaS.

**Semantic colour roles (dark professional only):**
- Orange (`--accent`): primary action, active tab, app emphasis
- Blue (`--state-info-*`): source/info only — SEEK badge uses info-blue
- Amber (`--state-warning-*`): advisory signals — Potential Duplicates, Description Issue, block-confirm panel
- Red (`--state-error-*`): destructive or hard blockers only — badge-hidden, error states
- Neutral (`--state-neutral-*`): default labels, LinkedIn badge, Government badge, inactive states
- Neutral (`--state-neutral-*`): default labels, LinkedIn badge, Sector badge, inactive states

**Component-specific rules:**
- `badge-warning` uses warning/amber tokens (not error/red) — it covers advisory signals, not errors
- `block-confirm` (Hide title words panel) uses warning tokens — amber accent, not red background
- `.job-insights` (Fit breakdown) overrides `--insight-bg` to `var(--bg-muted)` — keeps it neutral, not blue
- `.results-helper` gets left orange accent border in dark professional — info callout, not background panel
- `badge-source-seek` uses `--brand-seek-*` tokens (SEEK navy #0d3880; dark-adjusted for dark surfaces)
- `badge-source-linkedin` uses `--brand-linkedin-*` tokens (LinkedIn blue #0a66c2; dark-adjusted for dark surfaces)
- `badge-viewed` uses `--state-viewed-*` tokens (sky-blue, distinct from amber `badge-warning`)
- `badge-archive` is intentionally dim (opacity 0.5, smaller text) — low-priority informational chip
- `badge-new` gets dark-professional override to clean orange-subtle (accent-soft alone is not clean enough in dark)

**Token palette (dark professional) — defined in `themes.tokens.css`:**
```
--bg-page: #0d1117  --bg-surface: #111827  --bg-muted: #161e2b
--text-primary: #f8fafc  --text-muted: #94a3b8
--border-subtle: #263241  --border-strong: #334155
--accent: #ff6b1a  --accent-hover: #ff7a2f
--state-info-text: #60a5fa  --state-warning-text: #fbbf24  --state-error-text: #f87171
```

**Where to add dark-professional CSS overrides:**
- Workspace-specific: `workspace-page.css` (filter focus, Fit breakdown bg, results-helper)
- Card/badge/button: `results-page.css`
- Token values: `themes.tokens.css` only — never hardcode palette hex in component CSS

## Owners
- `routes/`: HTTP routes.
- `templates/`: page rendering.
- `workspace_data.py`: workspace data transformation.
- `history.py`: viewed/applied/hidden state.
- `profile_store.py`: profile/settings normalisation.
- `data/parsing_rules.json`: display labels where already owned there.

## JS debugging: "X is not defined" at a line where X IS defined

This is always a version mismatch, not a code bug. Two causes:

**Browser has cached old JS.** Hard-refresh (Ctrl+Shift+R) first. If the error disappears, it was stale cache.

**Python and JS are out of sync.** The onboarding page JS relies on `window.__JOB_HUNTER_*` bootstrap globals injected by `build_bootstrap_script()` in `server_helpers.py`. If Python changed but the server hasn't restarted, or if JS changed to expect a new global that Python doesn't yet inject, the JS throws at module level. Function declarations are hoisted and still callable, but any `const`/`let` declared after the throw is in TDZ — so calling those hoisted functions produces misleading "X is not defined" errors on variables that look fine in the source.

**Diagnosis steps (in order):**
1. Hard-refresh the browser (Ctrl+Shift+R).
2. Restart the server if any Python file changed since last start.
3. Check that every `window.__JOB_HUNTER_*` the JS reads is actually injected by `build_bootstrap_script()`.
4. Only after confirming fresh Python + fresh browser: read the actual JS source.

**Never start with grep or static file analysis.** The error line and variable name will look wrong because the browser is running a different version than the file on disk.

## Checklist
- Is this display logic, not business judgement?
- Does UI consume canonical data from the owner module?
- Can admin/user-tunable display policy be changed without code?
- Are labels and settings validated before use?
- Is the widget or surface styling owned centrally in the theme unless there is a screen-specific exception?
- Did you run the smallest relevant server or template check?


