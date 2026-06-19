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
- Before changing any token value or control height, read `docs/UI_COMPONENT_MAP.md` — the design standards section documents touch-target minimums, intentional size hierarchy, and the token ownership chain. Some values are accessibility constraints, not style preferences.
- Do not create page-local CSS for reusable UI components. Reusable visual styling belongs in `templates/static/theme/themes.widgets.css` or the relevant central theme/token file.
- Page CSS may only define page-specific layout/positioning/responsive exceptions. If adding CSS outside `templates/static/theme/`, document why it is a real local exception.
- Keep labels and copy consistent across the app. If the same text appears in more than one place, centralise it in the owning label/config source.
- Route aliases such as `/workspace` and `/` must stay intentional and documented.
- Workspace UI must preserve explainability: summary for humans, debug/detail readable but not raw implementation noise.
- Keep changes scoped to the owning component, but not page-local when the style is reusable. Fix the smallest owning central selector instead of adding local overrides.
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
Checked-in per-user snapshots under `data/users/<user_id>/workspace_results.html` can lag behind the renderer and must not be treated as the source of truth.

Workflow:
1. Identify the live output path first:
   - `job_hunter_agent/workspace_service.py::render_html()`
   - `job_hunter_agent/paths.py::get_workspace_results_path()`
   - the current per-user `workspace_results.html` when the user is looking at the rendered page
2. Edit the owning source:
   - `templates/results.html` for template copy/layout
   - `workspace_service.py` for values injected into the template
3. Regenerate the visible output.
4. Verify the live page, not only the source file.

Do not assume `templates/results.html` changes are visible immediately.

## Fit explanation language rules
The job card insight sections use human-friendly copy — do not revert to internal labels:
- Section heading: "Why this looks like a good fit" (not "Why it fits")
- Negative section: "Things to check before applying" (not "What lowers it")
- Signal transparency: "Your approved experience appears in this ad" (not "Matched profile support")
- Capability matches: "The ad asks for {capability}, and your profile includes this." — template lives in `ui_labels.json` → `fit_highlight_labels.capability_match_sentence`
- NV1/clearance risks: converted to plain English by `_humanize_check_item()` in `workspace_renderer.py`
- Work type only appears as a fit reason when the user has a specific work type preference (not when all types are accepted)
- All display label text lives in `data/knowledge/ui_labels.json` (`grade_labels`, `title_match_labels`, `fit_highlight_labels`); never hardcode label strings in renderer or scoring code

## Candidate application history display
When a rejection history match exists, the expanded `<details>` section shows:
1. Company — Date (most prominent)
2. Role (only if non-empty)
3. Evidence (full text, no truncation)
4. Confidence
5. Review reason (only if flagged)

The badge ("Rejected before" / "Possible previous application") is determined by status + confidence. The expanded section must not repeat the status label.

## Validation
- Check the rendered page or smallest relevant browser/template path.
- Run targeted tests where available.
- Update docs/backlog evidence when the UI behaviour changes.



