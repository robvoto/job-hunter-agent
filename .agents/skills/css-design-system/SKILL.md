---
name: css-design-system
description: Use when editing CSS, layout spacing, theme tokens, reusable visual components, responsive layout, or UI consistency. Usually combine with dashboard-ui or onboarding-ui for screen-specific changes.
---

# Skill: CSS Design System

Use before changing CSS, spacing, layout rhythm, theme tokens, or reusable UI component styling.

## Core rule

CSS changes must improve the shared design system, not create another one-off page patch.

## Ownership

- Design tokens belong in `templates/static/theme/themes.tokens.css`.
- Shared components belong in `templates/static/theme/themes.widgets.css`.
- Shared primitives/overlays belong in `templates/static/theme/themes.primitives.css`.
- Page CSS is only for page layout, responsive placement, or genuine local exceptions.
- If a rule can be reused by another screen, it is not page-local.
- **Before adding a selector or component to any file, check `docs/UI_COMPONENT_MAP.md`** for the pattern that already owns this look, including which file, which classes, and which consumers use it. Add to that entry rather than creating a parallel selector.
- **If no existing pattern fits, the fix is a new central entry** (theme CSS + a new `UI_COMPONENT_MAP.md` row), not a page-local selector that happens to look right on one screen. If the correct shared extension is unclear or you believe the requirement is genuinely page-specific, stop and ask the human before creating the exception.
- A page CSS file must not redefine or restyle a selector that `UI_COMPONENT_MAP.md` lists as centrally owned. Genuine page-scoped overrides are limited to layout properties (grid placement, width caps, margins) and must carry a one-line comment naming the exception, e.g. `/* Local layout exception: <reason>. */`.

## Interactive states (hover, focus, active)

- Any `:hover`, `:focus-visible`, or `:active` rule for a shared component belongs in `themes.widgets.css` (or `themes.primitives.css` for base primitives like `.btn`), not page CSS.
- `:focus-visible` rules must use the shared tokens — `--focus-ring-width`, `--focus-ring-color` (or `--focus-ring-color-subtle` for controls on an already-tinted surface), `--focus-ring-offset` — instead of a hardcoded outline color or width. See `docs/UI_COMPONENT_MAP.md` for the full token table.
- A page-local hover/focus/active treatment is only a legitimate exception when the control is not a standard input/button (e.g. a branded third-party button, a bespoke step indicator) — document it with a one-line comment naming the reason, same as any other local exception.

## Spacing discipline

- Use existing spacing tokens before adding new values.
- Do not invent one-off margins, padding, gaps, widths, or magic pixel values.
- Prefer parent-owned layout gaps over child-owned ad hoc margins.
- Keep vertical rhythm consistent between cards, rows, field groups, help text, and actions.
- If a spacing value becomes a pattern, promote it to a token or shared component rule.

## Component discipline

- Reuse existing cards, rows, buttons, chips, badges, toggles, choice strips, drawers, alerts, and help patterns.
- **Before creating or styling any action control, search the repo and `docs/UI_COMPONENT_MAP.md` for the same semantic action** (for example remove/delete, add, edit, save, close). If an equivalent exists, reuse its markup/class/component rather than introducing a visually different control.
- A semantic equivalent beats a page-specific preference: a remove action that is an icon elsewhere must not become a text button on a new editor without an explicit product decision.
- Do not duplicate component variants because one screen looks slightly different.
- Fix the smallest owning shared selector when multiple screens share the same visual problem.
- Do not solve overflow by hiding content unless that is the explicit UX requirement.

## Theme discipline

- Themes must change visual treatment only: colours, shadows, borders, surfaces, and tokens.
- Themes must not change structure, content order, or business behaviour.
- Dark/light adjustments must use semantic tokens, not hardcoded colours.

## Required workflow

1. Identify whether the issue is token, component, page layout, or content/data shape.
2. Inspect the existing theme files before adding CSS.
3. Prefer central token/component fixes over page-local overrides.
4. If page-local CSS is unavoidable, add a short comment naming the exception.
5. Validate the rendered screen that the user actually sees.

## Job Hunter Search Basics path

For Settings search preferences and onboarding Step 3, use the existing Job Hunter Settings Search Basics as the in-project visual reference:

1. Check `docs/UI_COMPONENT_MAP.md` and identify the owning shared widgets and each page's layout owner.
2. Compare section width and control arrangement against the reference; fix shared geometry in `themes.widgets.css` and keep page CSS to layout placement.
3. Reuse the composition on onboarding Step 3 while preserving its existing field IDs, labels/data source, hydration, and persistence behavior.
4. Keep Location full-width with its three groups evenly laid out; order the preference groups Work type, Sector preference, then Work mode, with compensation grouped below.
5. Update the component-map entry and inspect both rendered Settings and onboarding screens at desktop and phone widths.

Keep this guidance in the Job Hunter-owned component map and skill. Do not create a cross-project UX standard from this screen-specific pattern.

## Reusable output

When a CSS fix reveals a reusable pattern, update this skill or the owning DETAILS.md so future projects can copy the pattern.