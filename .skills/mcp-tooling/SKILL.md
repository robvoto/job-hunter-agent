---
name: mcp-tooling
description: Use when accessing the Job Hunter repo, WSL, Human MCP, Google services, or when an MCP/tool call fails or returns transport/encoding errors.
---

# Skill: MCP Tooling

Use for project filesystem/tool access and whenever MCP execution is unreliable.

## Source of truth
- Job Hunter WSL repo: `/home/robvoto/projects/job-hunter-agent`.
- Prefer `Local_Project_Files_Access` for repo/filesystem work.
- If that connector fails, retry through `Human_MCP_Access` before claiming access is unavailable.
- For the canonical backlog, use the authorised Google Sheet/service-account route defined by the backlog-management skill; do not fall back to stale local exports.

## Failure handling
- One failed MCP call does **not** prove the connector or resource is unavailable.
- Inspect the actual error and retry with a smaller, safer command.
- If `run_command` fails with Windows `cp1252`/`UnicodeDecodeError`, treat it as an output-decoding failure, not a repo-access failure.
- For commands likely to emit non-ASCII text, prefer bounded ASCII-safe output, e.g. `PYTHONIOENCODING=ascii` for Python diagnostics, or explicitly sanitize/escape output before returning it.
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

## Do not
- Do not test or depend on an ngrok hostname when the project connectors are available.
- Do not say WSL, Google Drive, the backlog, or Human MCP is unavailable without attempting the relevant connector.
- Do not replace live connected data with memory or stale local copies after a connector error.
- Do not repeat a known failing broad-output command unchanged.
