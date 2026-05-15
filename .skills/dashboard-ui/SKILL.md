# Skill: Workspace UI

Use before editing FastAPI routes, templates, workspace data, settings UI, or score/highlight display.

## Rules
- Workspace UI displays canonical data; it must not recreate filtering, scoring, or preference logic.
- Keep admin/user display policy configurable when it is tunable behaviour.
- Do not hardcode display counts, labels, thresholds, or fallback text in templates or feature code.
- Settings UI must save/load through the same profile/settings normalisers as runtime code.
- Missing required settings or labels should fail clearly, not be invented in UI code.
- Route aliases such as `/workspace` and `/` must stay intentional and documented.
- UI structure and visual treatment must come from shared theme tokens/widgets first; page-level CSS is only for screen-specific layout exceptions.
- Reuse existing widget patterns for help, drawers, chips, cards, and settings rows instead of creating new variants for the same job.
- Keep common language consistent across the app; if a screen is called settings or review, do not introduce alternate labels for the same concept.

## Workspace filter pattern
- Filter options that require data-driven groups (e.g., work type) are rendered server-side via a `render_*_filter_options()` function in `workspace_renderer.py` and injected as `$..._FILTER_OPTIONS_HTML` placeholders in `results.html`.
- When one filter option covers multiple canonical values (e.g., "Contract / Temp" covers "contract" and "temporary"), encode the option `value` as pipe-separated lowercase canonical values: `value="contract|temporary"`. JS splits on `|` before comparing against the card's data attribute.
- Card data attributes store the lowercased canonical value (e.g., `data-work-type="contract"`). Never store display labels in data attributes.
- Filter group definitions live in the relevant JSON data file (e.g., `data/job_type.json` `filter_groups` key), not in Python or JS.

## Per-user data paths
- All runtime data lives under `data/users/{uid}/` when a user is authenticated; path helpers (`get_profile_path()`, `get_source_pack_dir()`, etc.) return the per-user path automatically via `get_user_id()` ContextVar.
- When `get_user_id()` returns `None` (unauthenticated or no Google auth configured), every path helper falls back to root `data/` files. This means operations that call helpers without an active user silently hit the wrong files.
- Test reset tools (`_reset_current_user_state`) must wipe `USERS_DIR` subdirectories directly — do **not** rely on path helpers, which are context-dependent. Also reset root fallback files explicitly. Preserve `data/users.json` (auth accounts).

## Onboarding / settings widget patterns

### Work mode (`input[name="work_mode_preference"]`)
- Rendered by `server_helpers.render_work_mode_preference_choices()` as three `<label class="choice-card--work-mode">` checkboxes inside `<div id="work_mode_preference">`.
- CSS grid (`#work_mode_preference`) and card styles (`.choice-card--work-mode`) already exist in `onboarding-page.css` and `settings-page.css`. Do not re-create them.
- `setWorkModePreferenceValues(values)` in `onboarding-flow.js` and `settings-page.js`: when `values` is empty/none, **all checkboxes must default to checked** (`selected.size === 0 || selected.has(...)`). The same rule applies to the legacy `<select>` path — keep them consistent.
- The min-one constraint (user cannot uncheck the last checkbox) is enforced via a `change` listener added at init in both `onboarding-flow.js` and `settings-page.js`. Programmatic unchecking (e.g. `setWorkModePreferenceValues([])`) does **not** fire `change`, so the "default all selected" rule in the setter is the only guard there.

### Engagement type (`input[name="engagement_pref"]`)
- Rendered by `server_helpers.render_engagement_type_radio_group()` as hidden radio inputs inside `.choice-card--engagement` labels.
- `getSelectedEngagementType()` reads `refs.engagementInputs` (populated at script-load time). If no radio is checked and `ENGAGEMENT_TYPE_DEFAULT` is falsy, it returns `''` — which fails `validateSearchPreferences`.
- `validateSearchPreferences` guards the engagement-type check with `ENGAGEMENT_TYPE_VALUES.size > 0` so a bootstrap timing issue does not block the user.
- `getSelectedEngagementType()` self-corrects: if the resolved value is not in `ENGAGEMENT_TYPE_VALUES`, it checks the first radio and returns its value.

### Bootstrap globals and validation
- `window.__JOB_HUNTER_ENGAGEMENT_TYPE_OPTIONS__`, `__JOB_HUNTER_ENGAGEMENT_TYPE_DEFAULT__`, and related globals are injected by `build_bootstrap_script()` in `<head>`. They must be available before `onboarding-page.js` runs.
- Client-side validators (`validateSearchPreferences`) should guard `Set.size > 0` before treating an absent value as an error, to tolerate any edge case where globals are not yet set.

## Owners
- `routes/`: HTTP routes.
- `templates/`: page rendering.
- `workspace_data.py`: workspace data transformation.
- `history.py`: viewed/applied/hidden state.
- `profile_store.py`: profile/settings normalisation.
- `data/parsing_rules.json`: display labels where already owned there.

## Checklist
- Is this display logic, not business judgement?
- Does UI consume canonical data from the owner module?
- Can admin/user-tunable display policy be changed without code?
- Are labels/settings validated before use?
- Is the widget/surface styling owned centrally in the theme unless there is a screen-specific exception?
- Did you run the smallest relevant server/template check?
