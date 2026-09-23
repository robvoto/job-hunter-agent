---
name: dashboard-ui
description: Use ONLY for workspace/dashboard/settings UI routes, templates, scripts, rendered results, score/highlight display, and visible UI behaviour. Do NOT use for onboarding UI; use onboarding-ui.
---

# Skill: Workspace UI

Use for workspace/dashboard/settings UI. For CSS/layout/component styling, also load `css-design-system`; for labels/defaults, load `no-hardcoding`. Read `DETAILS.md` only for the specific detailed pattern needed.

## Rules

- UI displays canonical data; it must not recreate filtering, scoring, preference, or persistence logic.
- Missing/invalid UI data is fixed at the owning source or surfaced clearly; do not invent page-level fallbacks.
- Shared control structure follows `docs/UI_COMPONENT_MAP.md`; CSS ownership/visual reuse follows `css-design-system`.
- Standard toggles communicate state through the switch itself; do not add redundant visible On/Off/Enabled/Disabled text.
- Route aliases such as `/workspace` and `/` must remain intentional and documented.
- Preserve explainability: concise human summary first; diagnostics/details must remain readable without exposing raw implementation noise.
- Follow existing modular JS ownership; do not add one-off global scripts.

## Responsive and reuse guardrails

- Settings and dashboard controls must not overlap, clip, or escape their cards at any supported viewport or narrow content pane.
- Reuse the shared JH component and token owner identified in `docs/UI_COMPONENT_MAP.md`; do not recreate orange choice buttons, toggles, inputs, or cards in page CSS.
- Work type, Contract, FTC, Sector, Work mode, quick filters, and result/page-limit choices are one selectable-control family. FTC has no special visual or layout exception.
- Long labels must wrap or trigger a deliberate group stack before they collide with adjacent controls. Validate the rendered page at desktop, tablet, narrow-pane, and phone widths.

## Workspace output

Generated per-user `workspace_results.html` is output, not source of truth. Edit the owning template/renderer, regenerate when required, and verify the live rendered page rather than assuming a source-template edit is already visible.

## Detailed reference

Use `DETAILS.md` for workspace filters, per-user paths, settings widgets, reset flow, theme/component maps, sidebar patterns, and JS/version debugging.

## Validation

- Verify the smallest relevant rendered/browser path.
- Run targeted tests for the changed UI contract.
- Update docs/backlog evidence only when the owning behaviour actually changed.
