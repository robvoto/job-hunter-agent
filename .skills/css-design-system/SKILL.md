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

## Spacing discipline

- Use existing spacing tokens before adding new values.
- Do not invent one-off margins, padding, gaps, widths, or magic pixel values.
- Prefer parent-owned layout gaps over child-owned ad hoc margins.
- Keep vertical rhythm consistent between cards, rows, field groups, help text, and actions.
- If a spacing value becomes a pattern, promote it to a token or shared component rule.

## Component discipline

- Reuse existing cards, rows, buttons, chips, badges, toggles, choice strips, drawers, alerts, and help patterns.
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

## Reusable output

When a CSS fix reveals a reusable pattern, update this skill or the owning DETAILS.md so future projects can copy the pattern.