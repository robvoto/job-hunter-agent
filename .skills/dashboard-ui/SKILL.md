# Skill: Dashboard UI

Use before editing FastAPI routes, templates, dashboard data, settings UI, or score/highlight display.

## Rules
- Dashboard UI displays canonical data; it must not recreate filtering, scoring, or preference logic.
- Keep admin/user display policy configurable when it is tunable behaviour.
- Do not hardcode display counts, labels, thresholds, or fallback text in templates or feature code.
- Settings UI must save/load through the same profile/settings normalisers as runtime code.
- Missing required settings or labels should fail clearly, not be invented in UI code.
- Route aliases such as `/dashboard`, `/workspace`, and `/` must stay intentional and documented.
- UI structure and visual treatment must come from shared theme tokens/widgets first; page-level CSS is only for screen-specific layout exceptions.
- Reuse existing widget patterns for help, drawers, chips, cards, and settings rows instead of creating new variants for the same job.
- Keep common language consistent across the app; if a screen is called settings or review, do not introduce alternate labels for the same concept.

## Dashboard filter pattern
- Filter options that require data-driven groups (e.g., work type) are rendered server-side via a `render_*_filter_options()` function in `dashboard_renderer.py` and injected as `$..._FILTER_OPTIONS_HTML` placeholders in `results.html`.
- When one filter option covers multiple canonical values (e.g., "Contract / Temp" covers "contract" and "temporary"), encode the option `value` as pipe-separated lowercase canonical values: `value="contract|temporary"`. JS splits on `|` before comparing against the card's data attribute.
- Card data attributes store the lowercased canonical value (e.g., `data-work-type="contract"`). Never store display labels in data attributes.
- Filter group definitions live in the relevant JSON data file (e.g., `data/job_type.json` `filter_groups` key), not in Python or JS.

## Per-user data paths
- All runtime data lives under `data/users/{uid}/` when a user is authenticated; path helpers (`get_profile_path()`, `get_source_pack_dir()`, etc.) return the per-user path automatically via `get_user_id()` ContextVar.
- When `get_user_id()` returns `None` (unauthenticated or no Google auth configured), every path helper falls back to root `data/` files. This means operations that call helpers without an active user silently hit the wrong files.
- Test reset tools (`_reset_current_user_state`) must wipe `USERS_DIR` subdirectories directly — do **not** rely on path helpers, which are context-dependent. Also reset root fallback files explicitly. Preserve `data/users.json` (auth accounts).

## Owners
- `routes/`: HTTP routes.
- `templates/`: page rendering.
- `dashboard_data.py`: dashboard data transformation.
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
