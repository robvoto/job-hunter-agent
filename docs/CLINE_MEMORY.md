# Cline Memory (Persistent Session Context)

> Auto-generated persistent memory file for Cline coding sessions. Read this file at the start of every task so Cline stays oriented to the codebase, conventions, and backlog without losing context across model/switch sessions.

## Quick start for Cline

1. Read `AGENTS.md` (always-loaded entry point).
2. Read `docs/PROJECT_CONTEXT.md` if context is needed.
3. Read **`docs/CLINE_MEMORY.md`** (this file) for durable memory.
4. If touching config, docs, AGENTS.md, templates, CI, tests, or workflows, read `docs/STANDARDS_INDEX.md` first.
5. Load the relevant skill from `.skills/` (`code-change`, `no-hardcoding`, `css-design-system`, `dashboard-ui`, `onboarding-ui`, `backlog-management`).

## Backlog management

- **Sheet URL:** https://docs.google.com/spreadsheets/d/1-D7RzYB3R39dOmUFZvvsDlWpDfIVn3eRajEae9b7OX0/edit#gid=218702820
- **Access method:** `curl -sL "https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv&gid=<GID>"` (public-read CSV export; no auth needed).
- **Columns:** ID, Title, Epic, Type, Priority, Size, Problem, Outcome, Acceptance Criteria, Notes, Implementation State, Evidence, Review Category, Review Reason, etc.
- **Work types:** `Permanent`, `Contract`, `FTC` are selected by default in the engagement-type choice strip.
- **When editing rows:** update the `Implementation State` column (Not Done / Partially Done / Done) and fill `Evidence` with a PR/commit reference.
- **Row IDs** follow `JH-NNN` format.

## Project conventions (relevant to UI work)

- **CSS ownership:** `themes.widgets.css` owns reusable component styling (label, spacing, control width, background, border, hover, focus-visible). Page CSS (e.g. `settings-page.css`, `onboarding-page.css`) may only add layout-positioning exceptions.
- **Component pattern:** `field-label-row` wraps `<label>` + `<details class="field-info-drawer">` for consistent help-icon placement.
- **Choice strip:** rendered server-side via `render_choice_strip()` helpers; wired in JS via `settings-utils.js` (`get/setEngagementTypeValues`, etc.).
- **Conditional fields:** use `.conditional-preference-field` class. Visibility is derived from selected work types via `syncContractDurationState()`.

## Recently completed work

- **Contract-duration fix** (commit `29b7812`): Replaced the floating absolute-positioned popover with a shared `.conditional-preference-field` component in `themes.widgets.css`. Both `settings-search.html` and `onboarding.html` now use identical markup (label + help drawer + full-width select). JS replaced branch-heavy `updateMinContractMonthState`/`updateContractChipLabel` with a single `syncContractDurationState()` that derives visibility from selected work types. The Contract chip no longer renames itself to `Contract (all)` or `Contract (6+)`.
</arg_value></tool_call>