---
name: dashboard-ui
description: Use ONLY for workspace/dashboard/settings UI routes, templates, scripts, rendered results, score/highlight display, and visible UI behaviour. Do NOT use for onboarding UI; use onboarding-ui.
---

# Skill: Workspace UI

Use before editing workspace/dashboard pages, settings UI surfaces, templates, workspace routes, or score/highlight display.

See `.skills/dashboard-ui/DETAILS.md` for component maps, layout patterns, and longer examples.

## Load order
1. Read `AGENTS.md` first.
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

## Workspace output sync
The browser reads the generated workspace HTML, not just the source template.

Workflow:
1. Identify the live output path first:
   - `job_hunter_agent/workspace_service.py::render_html()`
   - `job_hunter_agent/paths.py::get_workspace_results_path()`
   - current per-user `workspace_results.html` when the user is looking at the rendered page
2. Edit the owning source:
   - `templates/results.html` for template copy/layout
   - `workspace_service.py` for values injected into the template
3. Regenerate the visible output.
4. Verify the live page, not only the source file.

Do not assume `templates/results.html` changes are visible immediately.

## Validation
- Check the rendered page or smallest relevant browser/template path.
- Run targeted tests where available.
- Update docs/backlog evidence when the UI behaviour changes.

