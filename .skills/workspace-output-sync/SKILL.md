---
name: workspace-output-sync
description: Keep workspace UI edits aligned between the source template, the renderer, and the generated per-user HTML output. Use when changing workspace/results text or layout, especially if the browser shows stale content, `templates/results.html` is edited, or the visible page comes from `data/users/*/workspace_results.html`.
---

# Workspace Output Sync

## Rule

The browser reads the generated workspace HTML, not just the source template.

## Workflow

1. Identify the live output path first.
   - Check `job_hunter_agent/workspace_service.py::render_html()`.
   - Check `job_hunter_agent/paths.py::get_workspace_results_path()`.
   - Check the current per-user `workspace_results.html` if the user is looking at the rendered page.
2. Edit the owning source.
   - Use `templates/results.html` for template copy and layout.
   - Use `workspace_service.py` for values injected into the template.
3. Regenerate the visible output.
   - Rebuild the workspace or update the generated `workspace_results.html` that the browser is actually serving.
4. Verify the live page, not only the source file.

## Notes

- Do not assume `templates/results.html` changes are visible immediately.
- Do not change support text in backend logs/docs when the request is only about the user-facing workspace.
- Keep shared labels consistent. If a visible label changes, update every live workspace surface that renders the same label.
