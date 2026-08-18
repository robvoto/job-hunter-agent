---
name: mcp-tooling
description: Use for repository/filesystem access, connected Google/browser/Gmail tooling, or tool/transport failure recovery; apply runtime-specific MCP connector names only when that runtime exposes them.
---

# Skill: MCP Tooling

Use for project filesystem/tool access and whenever MCP execution is unreliable.

## Source of truth
- Job Hunter WSL repo: `/home/robvoto/projects/job-hunter-agent`.
- In a connector-based ChatGPT runtime, prefer `Local_Project_Files_Access` for repo/filesystem work; if it fails, retry through `Human_MCP_Server` before claiming access is unavailable.
- In Codex, Claude Code, Cline, or another local coding runtime that already has direct repository shell/filesystem access, use that native access instead of pretending ChatGPT connector namespaces exist. The shared safety rules still apply.
- For the canonical backlog, follow `.skills/backlog-management/SKILL.md`. In a ChatGPT connector runtime, use the authorised `Google_Drive` / Google Sheets connector and approved `Human_MCP_Server` fallback when exposed. In other runtimes, use their authorised live-Sheets capability if available. Never substitute stale local exports.

## Failure handling
- One failed MCP call does **not** prove the connector or resource is unavailable.
- Inspect the actual error and retry with a smaller, safer command.
- If `run_command` fails with Windows `cp1252`/`UnicodeDecodeError`, treat it as an output-decoding failure, not a repo-access failure.
- For commands likely to emit non-ASCII text, prefer bounded ASCII-safe output, e.g. `PYTHONIOENCODING=ascii:backslashreplace` for Python diagnostics, or explicitly sanitize/escape output before returning it.
- Avoid broad `grep` over binary caches or huge generated files. Exclude `__pycache__`, binary files, generated workspace HTML, and other noisy paths unless they are the target.
- Keep command output bounded (`head`, focused `sed`, exact paths, small Python summaries). Large output increases MCP transport/decoding risk.
- If a command produces a wrapper-side `NoneType` error after a decode/thread failure, fix the output encoding/size and retry; do not interpret the wrapper error as project failure.
- Only report access failure after both the primary connector and approved fallback have been attempted with a minimal diagnostic command.

## Safe command pattern
1. Start with a tiny command such as `pwd`, `git status --short`, or a focused `sed`/Python query.
2. Confirm the expected repo/path.
3. Run the smallest command that answers the question.
4. If output may contain arbitrary Unicode, make it ASCII-safe or escaped.
5. If the connector fails, retry through the approved fallback.
6. Report the exact failing layer: connector, command, path, encoding, permission, or application logic.

## Existing logged-in browser control
This section is runtime-specific: it applies only when the Human MCP/browser bridge capability is exposed. Local Codex/Claude/Cline sessions must not assume they can control the signed-in browser merely because these tools exist in another runtime.

- Human MCP server source: `E:\Programming\MCP-server\mcp_fileserver.py`.
- Browser bridge extension source: `E:\Programming\MCP-server\chrome-human-mcp`.
- Browser bridge design notes: `E:\Programming\MCP-server\docs\BROWSER_CONTROL.md`.
- The human uses the normal signed-in Chrome session for sites such as LinkedIn. Do not launch a clean automation profile, copy cookies, or ask for another login unless the human explicitly requests a separate browser profile.
- Current control path is the local Chrome extension bridge, not Chrome remote-debugging autoConnect. The extension bridge listens on `127.0.0.1:8766`, talks only to localhost, and preserves the existing signed-in session.
- Human MCP exposes browser tools including `browser_status`, `browser_list_pages`, `browser_select_page`, `browser_navigate`, `browser_snapshot`, `browser_click`, `browser_fill`, and `browser_wait_for` after the connector catalogue refreshes.
- In an already-open ChatGPT session the connector schema may be stale and not surface newly added browser tools. In that case, `Human_MCP_Server.run_command` may use a local FastMCP client against `http://127.0.0.1:8001/mcp` as a temporary catalogue bridge. A new ChatGPT session should discover the tools directly.
- Opening a URL with `Start-Process` is not proof of DOM/browser control. Before claiming browser control, verify bridge health and successfully read `browser_list_pages` or `browser_snapshot`.
- If Windows output fails on LinkedIn Unicode/emoji, treat it as an output-encoding issue. Use `PYTHONIOENCODING=ascii:backslashreplace` or bounded escaped output rather than assuming the browser read failed.

### Gmail OAuth access
- Human MCP now contains read-only Gmail tools: `gmail_auth_status`, `gmail_search`, `gmail_read_message`, and `gmail_read_thread`.
- Gmail uses the authenticated user's OAuth desktop-client flow, not the Google service account used for Docs/Sheets.
- OAuth bootstrap script: `E:\Programming\MCP-server\gmail_oauth_setup.py`.
- OAuth client JSON must be stored outside the repo at `C:\Users\thewr\.config\human-mcp\gmail\credentials.json` unless overridden by `HUMAN_MCP_GMAIL_CREDENTIALS_PATH`.
- The bootstrap script writes the refresh/access token to `C:\Users\thewr\.config\human-mcp\gmail\token.json` unless overridden by `HUMAN_MCP_GMAIL_TOKEN_PATH`.
- Current Gmail scope is read-only: `https://www.googleapis.com/auth/gmail.readonly`.
- After first-time OAuth setup, restart Human MCP so ChatGPT can discover/use the Gmail tools. In an already-open ChatGPT session the connector tool catalogue may remain stale until a new chat/session.
- Do not add Gmail send/draft scopes or sending tools without explicit user request. If added later, preserve the same explicit-per-send approval rule used for LinkedIn/browser actions.

### Browser action safety
- Read-only actions such as listing tabs, navigating, searching, opening profiles, and taking snapshots are allowed when they are part of the user's request.
- Drafting text in chat is allowed. Avoid filling a browser message/form field unless the human explicitly asks, because it can create accidental state even before submission.
- **Never send a LinkedIn message, connection request, application, email, form submission, invitation acceptance, or other external action without the human's explicit approval in the current turn.**
- Do not interpret an earlier general request such as "contact people for me" as approval to click Send later. Show the human the exact target and final wording first, then wait for explicit approval.
- When there is any ambiguity about whether a click could submit, send, apply, connect, accept, delete, purchase, or otherwise create an external side effect, stop before the click and ask the human.

## Do not
- Do not test or depend on an ngrok hostname when the project connectors are available. If `Local_Project_Files_Access` reports an old ngrok 404, treat that as connector transport failure and switch to `Human_MCP_Server`; do not probe the hostname itself.
- Do not say WSL, Google Drive, the backlog, Human MCP, or browser control is unavailable without attempting the relevant connector/tool path.
- Do not replace live connected data with memory or stale local copies after a connector error.
- Do not repeat a known failing broad-output command unchanged.
