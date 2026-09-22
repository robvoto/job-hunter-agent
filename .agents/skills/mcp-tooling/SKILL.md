---
name: mcp-tooling
description: Use for connector/MCP-mediated repository/filesystem access, connected services, or connector transport/command failures. Native local coding agents use their own shell/filesystem.
---

# Skill: MCP Tooling

## Routing

- Local coding runtimes with direct repository access use their native shell/filesystem.
- Connector-based ChatGPT uses `HUMAN_MCP_SECURE` for Job Hunter repository/filesystem access. Do not silently switch to alternate Job Hunter connectors.
- `Human_MCP_SERVER_NGROK_UNSAFE` is only an explicit, current-conversation fallback authorised by the human.
- Human MCP/JH/JMM lifecycle actions are governed by `docs/PROJECT_CONTEXT.md`; diagnostics do not authorise lifecycle changes.
- Use `job-market-map-integration` for JH/JMM data-contract semantics and `backlog-management` for backlog operations.
- Use Google Drive only when the task genuinely needs a Drive-native operation not exposed by the authorised secure path.

## Read-only repository inspection first

- In connector-based ChatGPT, use `repo_status`, `repo_diff`, `repo_log`, `repo_show`, `repo_search`, `repo_remote_ref`, `search`, `fetch`, `read_directory`, and `file_info` for routine repository/file inspection. These are published by Human MCP as read-only tools.
- Do **not** use `run_command` merely for `pwd`, `git status`, `git diff`, `git log`, `git show`, `git worktree list`, `git rev-parse`, `rg`/`grep`, `sed`, `cat`, or equivalent reads when the dedicated tools can answer the question. `run_command` is a general shell capability and may require user approval.
- Use `repo_remote_ref` to check whether a remote branch changed without modifying local refs. Run `git fetch` only when the task genuinely needs local remote-tracking refs updated.
- Use `repo_search` for tracked source/code search and `search`/`fetch` for ordinary filesystem content, including potentially untracked files. Keep reads bounded to the relevant repo/path.
- If an already-open ChatGPT chat exposes `run_command` but not the `repo_*` tools, treat that as a stale connector schema. Refresh/reconnect the canonical `HUMAN_MCP_SECURE` tool catalogue rather than silently falling back to repeated shell approvals for routine reads.
- Local coding runtimes with native shell/filesystem access are not required to use these MCP read tools.

## Command contract

- Match syntax to the shell selected by `cwd`: WSL paths use shell syntax; Windows drive paths use PowerShell syntax.
- `HUMAN_MCP_SECURE.run_command` accepts the discovered schema only. Do not invent or pass a `timeout` argument.
- Use `uv run ...` for Job Hunter Python/pytest/ruff commands; never rely on system Python or another worktree's `.venv`.
- For repo JavaScript using ES-module syntax, use `node --input-type=module --check < path/to/file.js`; never use plain `node --check path/to/file.js` for those files.
- In ChatGPT/Human MCP, never run the entire pytest suite in one connector call and do not background it. Use `./scripts/run-pytest-mcp.sh 1 3`, then `2 3`, then `3 3`; focused tests may use `uv run pytest ...`.
- Keep output bounded and ASCII-safe when arbitrary Unicode may cross the Windows connector boundary.

## Failure handling

- One failed call does not prove the connector/resource is unavailable. Read the actual error and retry once with the smallest relevant read-only tool, or a smaller safe command only when command execution is genuinely required.
- Classify shell parser errors, missing system binaries, output-decoding errors, and missing auth context at their actual layer; do not relabel them as repository/application failures.
- Optional probes may report absence/no match without failing the whole diagnostic; required files/permissions remain real failures.
- Never replace failed live connected data with memory or stale local copies.
- Report the exact failing layer and stop rather than switching connectors or inventing a workaround.

## Detailed reference

Read `DETAILS.md` only for Human MCP external-contract stability, signed-in browser control, Gmail OAuth, browser side-effect safety, or career-resource routing.
