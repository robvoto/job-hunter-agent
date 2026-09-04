---
name: mcp-tooling
description: Use for repository/filesystem access, connected Google/browser/Gmail tooling, or tool/transport failure recovery; apply runtime-specific MCP connector names only when that runtime exposes them.
---

# Skill: MCP Tooling

Use for project filesystem/tool access and whenever MCP execution is unreliable.

## Source of truth
- Job Hunter WSL repo: `/home/robvoto/projects/job-hunter-agent`.
- In a connector-based ChatGPT runtime, use `HUMAN_MCP_SECURE` as the canonical Job Hunter repo/filesystem connector. Do not use `Human_MCP_Server` or `Local_Project_Files_Access` for Job Hunter repo access; both are obsolete for this project and may resolve to stale or unintended transport. If `HUMAN_MCP_SECURE` is not exposed or fails after one bounded corrective retry, report that specific secure-MCP registration/runtime failure and stop. Do not silently switch connectors. The only approved fallback is `Human_MCP_SERVER_NGROK_UNSAFE`, and it may be used only after the human explicitly authorises that fallback in the current conversation.
- In Codex, Claude Code, Cline, or another local coding runtime that already has direct repository shell/filesystem access, use that native access instead of pretending ChatGPT connector namespaces exist. The shared safety rules still apply.
- For the canonical backlog, follow `.skills/backlog-management/SKILL.md`. In a ChatGPT connector runtime, use the authorised `Google_Drive` / Google Sheets connector and approved `HUMAN_MCP_SECURE` Google-service fallback when exposed. In other runtimes, use their authorised live-Sheets capability if available. Never substitute stale local exports.

## Failure handling
- One failed MCP call does **not** prove the connector or resource is unavailable.
- Inspect the actual error and retry with a smaller, safer command.
- For every Python command in the Job Hunter repository, use `uv run python ...`, `uv run pytest ...`, or another `uv run ...` command. Never invoke bare `python`, `python3`, `pytest`, or `ruff`, and never retry a known-missing bare command unchanged. If a bare command returns 127, classify it as a command-launch failure—not a database, application, or repository-access failure. For SQLite inspection, use `uv run python` with the standard-library `sqlite3` module or the project's DB helpers instead of requiring a system package.
- If `run_command` fails with Windows `cp1252`/`UnicodeDecodeError`, treat it as an output-decoding failure, not a repo-access failure.
- For commands likely to emit non-ASCII text, prefer bounded ASCII-safe output, e.g. `PYTHONIOENCODING=ascii:backslashreplace` for Python diagnostics, or explicitly sanitize/escape output before returning it.
- Avoid broad `grep` over binary caches or huge generated files. Exclude `__pycache__`, binary files, generated workspace HTML, and other noisy paths unless they are the target.
- Keep command output bounded (`head`, focused `sed`, exact paths, small Python summaries). Large output increases MCP transport/decoding risk.
- If a command produces a wrapper-side `NoneType` error after a decode/thread failure, fix the output encoding/size and retry; do not interpret the wrapper error as project failure.
- Only report Job Hunter repo access failure after the authorised `HUMAN_MCP_SECURE` connector has been attempted with a minimal diagnostic command.

## Safe command pattern
1. Start with a tiny command such as `pwd`, `git status --short`, or a focused `sed`/Python query.
2. Confirm the expected repo/path.
3. Run the smallest command that answers the question.
4. If output may contain arbitrary Unicode, make it ASCII-safe or escaped.
5. If `HUMAN_MCP_SECURE` fails, retry once with a smaller/minimal diagnostic through the same connector. Do not switch Job Hunter repo connectors unless the human explicitly authorises the documented ngrok fallback.
6. Report the exact failing layer: connector, command, path, encoding, permission, or application logic.

## Human MCP external contract stability — explicit exception
- This section applies only to the published Human MCP tool interface consumed outside Job Hunter. It is an explicit exception to Job Hunter's pre-live canonical-contract rule; it must never be used to justify compatibility code in Job Hunter business logic, persistence, payloads, caches, UI contracts, or internal APIs.
- Treat exposed Human MCP action names and schemas as a stable versioned external interface for ChatGPT.
- Do not rename or remove an existing published action, change an existing required argument, or change an existing argument type without an explicit versioned external-contract change.
- For that external interface only, prefer additive changes such as optional arguments or new actions, or change only the internal implementation behind an unchanged published action contract.
- Internal Human MCP implementation may evolve freely while the published external tool contract remains stable.

## Existing signed-in browser control
Runtime-specific: use only when Human MCP browser tools are exposed.

- Server: `E:\Programming\MCP-server\mcp_fileserver.py`; bridge: `127.0.0.1:8766`; design notes: `E:\Programming\MCP-server\docs\BROWSER_CONTROL.md`.
- Control the human's existing signed-in Chrome session. Do not launch a clean automation profile or copy cookies unless explicitly requested.
- `browser_status` proves only that an extension is polling. Prove usable control with `browser_list_pages` and, when needed, `browser_snapshot`.
- For deterministic actions: `browser_list_pages` -> `browser_select_page` -> navigate/snapshot/click. `browser_list_pages` itself does not require a selected tab.
- Browser queue names are extension identities, not Chrome folder names. Each Chrome profile must load only its matching unpacked extension: Rob -> `chrome-human-mcp` (`PROFILE="rob"`), Maria -> `chrome-human-mcp-maria` (`PROFILE="maria"`). If two Chrome profiles poll the same queue, commands can be consumed by the wrong browser and produce impossible-looking tab/select/snapshot failures.
- If status is healthy but tab results are inconsistent, verify the loaded extension path in each Chrome profile before blaming the MCP server or retrying commands.
- Rob's unpacked extension lives at `E:\\Programming\\MCP-server\\chrome-human-mcp`. Its manifest currently includes `tabs`, `activeTab`, `scripting`, and `alarms`. Do not claim `activeTab` is missing without reading the live manifest first.
- `activeTab` is **not** a blanket permission for arbitrary future sites. Chrome grants it temporarily only after a qualifying user gesture on the extension. MCP-initiated navigation alone does not make every new host scriptable.
- `chrome.scripting.executeScript` therefore still requires either a matching durable `host_permissions` entry or a currently granted `activeTab` permission for that tab. A site may navigate successfully yet snapshot/click/fill fail with a host-permission error.
- Rob's browser extension now uses `"<all_urls>"` in `host_permissions`. New job/application sites must not require per-domain manifest edits. If navigation succeeds but `browser_snapshot` reports a host-permission error, inspect the live manifest first. If `"<all_urls>"` is present, treat the failure as a stale loaded extension copy and ask for one extension reload, then verify with `browser_snapshot`. Do not add another site-specific permission unless the live manifest has genuinely regressed away from `"<all_urls>"`.
- Treat "navigation worked but snapshot failed" as a permissions/configuration problem until proven otherwise, not as bot detection, login failure, browser-control unavailability, or a reason to launch another browser profile.
- If `run_command` / local file tools are exposed in the current connector schema, use them for these diagnostics and manifest edits instead of claiming local access is unavailable. Verify tool exposure before saying a capability is missing.
- Browser reload race: the Chrome extension long-polls `/next`. If Rob reloads the unpacked extension while a browser command is being delivered, the HTTP client may abort (`WinError 10053` / broken pipe / reset). Historically the server had already removed that command from the queue, so the MCP caller then waited 30 seconds and reported `Chrome profile 'rob' did not answer` even though the profile was healthy. Treat that sequence as a bridge delivery race, not proof the extension is absent. The bridge must requeue an undelivered command on aborted/reset writes; after a reload, verify with one browser status check and then the actual requested browser action rather than repeatedly probing status/list-pages unless needed.
- A stale ChatGPT connector catalogue can hide newly added browser actions. Refresh/discover the connector before inventing a fallback.
- Opening a URL externally is not proof of DOM control. Do not claim browser control until the MCP can read the target tab.
- If Windows output fails on Unicode/emoji, treat it as output encoding and retry with bounded escaped output.

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

## Career/application resource routing

This section applies when a connector-based agent is helping Rob with a CV, cover letter, job application, interview preparation, application outcome, rejection history, or application log update.

- Start from the authoritative career instructions, not generic search. Read the current live `ROB_VOTO_INSTRUCTIONS` and `ROB_VOTO_PERSONA` using their exact known Google document IDs before application/CV/interview work.
- Treat the CV-System index inside `ROB_VOTO_INSTRUCTIONS` as the router for named career resources. If the index already identifies the resource or exact Google Doc/Sheet ID, invoke that direct Docs/Sheets action. Do not search Gmail, browse Drive, search the local filesystem, or use generic Files search merely to rediscover a canonical resource whose identity is already known.
- `ROB_VOTO_JOB_APPLICATIONS_LOG` is the canonical active application-status store. When Rob says an application was submitted, rejected, interviewed, withdrawn, or otherwise changed status, update this log before starting the next application unless Rob explicitly tells you not to.
- If a canonical resource is named by the index but its exact connector identity is missing from the loaded instructions, do not guess and do not fan out across unrelated search tools. Ask Rob once for the exact link/ID, then add that identity to the authoritative instructions/index so later sessions can resolve it directly.
- Browser control is for the application website itself. It is not the default discovery mechanism for CV-System Docs/Sheets.
- Generic `files.search`, Gmail search, local filesystem search, and browser Drive search are fallbacks only when the authoritative index does not resolve the requested resource and the task genuinely requires discovery.

## Do not
- Do not test or depend on an ngrok hostname when `HUMAN_MCP_SECURE` is available. Do not invoke `Human_MCP_Server` or `Local_Project_Files_Access` for Job Hunter, even as a diagnostic fallback. If an old ngrok/Local Project reference appears in legacy configuration or logs, treat it as obsolete. Use `Human_MCP_SERVER_NGROK_UNSAFE` only when the human explicitly authorises that fallback in the current conversation.
- Do not say WSL, Google Drive, the backlog, Human MCP, or browser control is unavailable without attempting the relevant connector/tool path.
- Do not replace live connected data with memory or stale local copies after a connector error.
- Do not repeat a known failing broad-output command unchanged.
