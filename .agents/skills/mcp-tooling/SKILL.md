---
name: mcp-tooling
description: Use for repository/filesystem access, connected Google/browser/Gmail tooling, or tool/transport failure recovery; apply runtime-specific MCP connector names only when that runtime exposes them.
---

# Skill: MCP Tooling

Use for project filesystem/tool access and whenever MCP execution is unreliable.

## Multi-agent Human MCP rule
- Many ChatGPT chats, Claude agents and MCP processes are expected and supported. Do not diagnose their mere presence as a conflict.
- There is one shared Rob-Chrome browser broker: the canonical Human MCP server owns `127.0.0.1:8001` and `127.0.0.1:8766`; secondary MCP processes proxy browser calls and must not bind `8766`.
- Human MCP lifecycle is protected by the runtime lifecycle rule in `docs/PROJECT_CONTEXT.md`. Do **not** run `mcp_fileserver.py`, `ensure-human-mcp.ps1`, stop/kill commands, or any other MCP/broker lifecycle action unless Rob explicitly approves that exact action. For diagnosis, use read-only health/status checks; if MCP is absent or unhealthy, report it and request lifecycle approval rather than starting/restarting it.
- WinError 10048 on `127.0.0.1:8766` after a manual start means a duplicate canonical launch was attempted or port ownership is inconsistent; it does not mean MCP is missing. Do not kill arbitrary agents or create another browser profile.
- For browser trouble, run `E:\Programming\MCP-server\scripts\check-browser-broker-health.ps1` and follow `E:\Programming\MCP-server\.agents\skills\browser-session-recovery\SKILL.md`.
- Signed-in browser workflows reuse Rob's existing Chrome and each workflow owns its own tab. Server-side MCP session isolation protects cached/older schemas; explicit `page_id` targeting is preferred when the tool schema exposes it.
- WSL processes must not assume Windows `127.0.0.1` services are reachable as WSL `127.0.0.1`. If a Windows-local Human MCP/browser broker is intentionally loopback-only, do **not** rebind it to `0.0.0.0`, open firewall ports, or start another broker just to reach it from WSL. Use the approved secure connector or a project-owned Windows-interoperability adapter that keeps the broker loopback-only.
- Job-market collection is separated from Job Hunter policy in `/home/robvoto/projects/job-market-map`. For JMM HTTP/consumer/JD/identity integration rules, load `.agents/skills/job-market-map-integration/SKILL.md`; tooling rules here do not redefine that contract.

## Source of truth
- Job Hunter WSL repo: `/home/robvoto/projects/job-hunter-agent`.
- In a connector-based ChatGPT runtime, use `HUMAN_MCP_SECURE` as the canonical Job Hunter repo/filesystem connector. Do not use `Human_MCP_Server` or `Local_Project_Files_Access` for Job Hunter repo access; both are obsolete for this project and may resolve to stale or unintended transport. If `HUMAN_MCP_SECURE` is not exposed or fails after one bounded corrective retry, report that specific secure-MCP registration/runtime failure and stop. Do not silently switch connectors. The only approved fallback is `Human_MCP_SERVER_NGROK_UNSAFE`, and it may be used only after the human explicitly authorises that fallback in the current conversation.
- In Codex, Claude Code, Cline, or another local coding runtime that already has direct repository shell/filesystem access, use that native access instead of pretending ChatGPT connector namespaces exist. The shared safety rules still apply.
- For the canonical backlog, follow `.agents/skills/backlog-management/SKILL.md`. In a ChatGPT connector runtime, `HUMAN_MCP_SECURE` is the primary Job Hunter path for both repository work and the canonical backlog when its live Google Sheets operations are exposed. The backlog spreadsheet ID and sheet name are pinned in the backlog skill, so use the secure MCP Sheets operations directly; do **not** invoke the native `Google_Drive` connector merely to read or update the backlog. Keep the same secure connector path for the whole repo/backlog investigation instead of casually switching between connector families.
- `HUMAN_MCP_SECURE` does not currently expose general Google Drive file discovery/listing. Use the native `Google_Drive` connector only as a deliberate, isolated escalation when the task genuinely requires a Drive-native operation that the secure MCP cannot perform, such as discovering an unknown Drive document ID. Do not use Drive as a routine backlog fallback. If an isolated Drive step is required, make the boundary explicit and complete/record MCP-dependent repo work first because connector availability may change after switching.

## Failure handling
- One failed MCP call does **not** prove the connector or resource is unavailable.
- A rejected file patch (`old_text not found`, failed hunk, or equivalent) is a validation stop. Re-read the exact current file, construct a new context-checked patch, and verify the diff; never retry stale patch text.
- Inspect the actual error and retry with a smaller, safer command.
- Match command syntax to the shell selected by `cwd`. In the current Human MCP route, Windows drive-letter paths such as `E:\\...` execute through Windows PowerShell, while the Job Hunter WSL path executes through the WSL shell. Do not send Bash chaining such as `&&`/`||` to the Windows PowerShell route; use PowerShell-native sequencing/error checks there, and do not send PowerShell syntax to WSL. A parser error caused by the wrong shell dialect is a command-shape error, not an MCP availability failure.
- Avoid fragile giant PowerShell one-liners for multiline text edits or replacement content containing apostrophes, quotes, backticks, or nested escaping. Prefer a small temporary script/file with literal content, execute it with the repo-appropriate runtime, verify the diff, then delete the temporary file. Treat PowerShell parser errors from quoting/escaping as command-construction errors; do not classify them as MCP failures and do not keep adding escape layers to the same broken one-liner.
- Keep optional discovery probes from poisoning the whole diagnostic. Before reading an optional file/path, check whether it exists or isolate that probe so expected absence is reported as `NONE`/not present rather than a tool failure. Likewise, `rg`/`grep` exit code 1 means no match and is not an error when no match is an allowed outcome; do not suppress genuine parser, permission, I/O, or required-file failures. A required file that is missing remains a real failure.
- In ChatGPT, `HUMAN_MCP_SECURE.run_command` accepts only `cwd` and `command`. Never add a tool-level `timeout` argument; if a command needs bounding, use a shell-level mechanism inside `command` or run it asynchronously and poll its output. Treat an invalid-arguments response for `timeout` as a call-shape error and retry once without that field.
- For every Python command in the Job Hunter repository, use `uv run python ...`, `uv run pytest ...`, or another `uv run ...` command. Never invoke bare `python`, `python3`, `pytest`, or `ruff`, and never retry a known-missing bare command unchanged. A failure from system Python must never be reported as a Job Hunter dependency/environment failure unless the equivalent repository-runtime command also fails. If a bare command returns 127, classify it as a command-launch failure—not a database, application, repository-access, or dependency failure. For SQLite inspection, use `uv run python` with the standard-library `sqlite3` module or the project's DB helpers instead of requiring a system package.
- `uv run ...` is the canonical worktree-safe runtime. Let `uv` create/reuse the current worktree's `.venv`; never reach into another worktree's `.venv` to run tests or Python.
- In the ChatGPT `HUMAN_MCP_SECURE.run_command` contract, pass only the fields the discovered schema exposes (`command` and `cwd` in the current contract). **Do not invent or pass a `timeout` argument.** The connector itself currently enforces an approximately 100-second command cap.
- For browser JavaScript files that use ES-module `import`/`export` syntax while the repo is not declared as Node ESM, validate syntax with `node --input-type=module --check < path/to/file.js`. **Never use plain `node --check path/to/file.js` for these files**; Node will parse them as CommonJS and report a false syntax failure.
- Therefore, in ChatGPT/Human MCP, **never run the entire pytest suite in one connector call**, and do not background it: the secure connector can reap child processes when the call ends. Run the proven serial validation slices as three separate calls: `./scripts/run-pytest-mcp.sh 1 3`, then `2 3`, then `3 3`. The helper uses contiguous top-level test-file ranges and no xdist, avoiding both the connector timeout and the cross-test interference observed with parallel sliced runs. Focused tests may still be run directly with `uv run pytest ...`.
- Auth-bound Job Hunter loaders such as `profile_store.load_profile()` and user-scoped workspace/history loaders require an active user context. In standalone diagnostics, establish that context explicitly before calling them; otherwise use a direct SQLite query with the verified user ID or a test fixture. Do not treat a missing signed-in context as an application failure.
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

## Do not
- Do not test or depend on an ngrok hostname when `HUMAN_MCP_SECURE` is available. Do not invoke `Human_MCP_Server` or `Local_Project_Files_Access` for Job Hunter, even as a diagnostic fallback. If an old ngrok/Local Project reference appears in legacy configuration or logs, treat it as obsolete. Use `Human_MCP_SERVER_NGROK_UNSAFE` only when the human explicitly authorises that fallback in the current conversation.
- Do not say WSL, Google Drive, the backlog, Human MCP, or browser control is unavailable without attempting the relevant connector/tool path.
- Do not replace live connected data with memory or stale local copies after a connector error.
- Do not repeat a known failing broad-output command unchanged.

## Detailed reference
See `DETAILS.md` for browser/Gmail control, external Human MCP contract rules, and career-resource routing.
