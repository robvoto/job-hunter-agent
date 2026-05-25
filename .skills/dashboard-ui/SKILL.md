# Skill: Workspace UI

Use before editing workspace/dashboard pages, settings UI surfaces, templates, workspace routes, or score/highlight display.

## Load order
1. Read `Agents.md` first.
2. Read this skill.
3. If the change touches a detailed pattern listed below, read `.skills/dashboard-ui/DETAILS.md` for the specific section only.

## Non-negotiable rules
- UI displays canonical data; it must not recreate filtering, scoring, or preference logic.
- Do not hardcode display counts, labels, thresholds, fallback text, or business decisions in templates, JS, or renderer code.
- Missing/invalid UI data should fail clearly or be fixed at the owning source; do not invent silent UI fallbacks.
- Reuse existing theme tokens, widgets, switches, choice strips, chips, cards, drawers, and help patterns before creating new variants.
- Keep labels and copy consistent across the app. If the same text appears in more than one place, centralise it in the owning label/config source.
- Route aliases such as `/workspace` and `/` must stay intentional and documented.
- Workspace UI must preserve explainability: summary for humans, debug/detail readable but not raw implementation noise.
- Keep changes local. If a layout issue is one row or field, change only that block.
- For frontend changes, follow the established modular JS ownership pattern; do not add one-off global scripts unless agreed.

## Detailed patterns moved to DETAILS.md
Read only the relevant section when needed:
- workspace filter pattern
- per-user data and workspace path ownership
- settings/onboarding widget patterns
- source enable toggles
- sector/work-mode/engagement choice strips
- LLM model dropdown
- reset user flow
- theme CSS map and dark-professional conventions
- sidebar search card placeholders
- JS debugging/version mismatch checklist

## Validation
- Check the rendered page or smallest relevant browser/template path.
- Run targeted tests where available.
- Update docs/backlog evidence when the UI behaviour changes.
