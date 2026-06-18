# Job Hunter Agent — Operations

## Operational Purpose

This document defines the supported runtime commands, local WSL workflow, production deploy workflow, persistence rules, diagnostics, and recovery paths.

This is an operational runtime reference, not a development diary.

---

## Runtime rule

The supported developer runtime is now **WSL + uv**.

Normal local commands should go through:

```bash
./scripts/run-jobhunter.sh <command>
```

Do not use ad-hoc `pip install`, manual `.venv` activation, or copied one-off `python -m ...` commands as the normal workflow. The runner script installs uv if missing, syncs the project from `pyproject.toml`, installs Playwright Chromium when needed, and then runs the requested app command.

The Windows desktop installer is separate packaging work. It may keep a legacy bootstrap path until the desktop installer is explicitly migrated and tested.

---

## WSL local runtime

From the WSL repo path:

```bash
cd /mnt/e/Programming/job-hunter-agent
```

First setup / dependency sync:

```bash
./scripts/run-jobhunter.sh sync
```

Run the local app in debug mode:

```bash
./scripts/run-jobhunter.sh debug
```

Run the local app normally:

```bash
./scripts/run-jobhunter.sh app
```

Useful local commands:

| Command | Purpose |
|---|---|
| `./scripts/run-jobhunter.sh sync` | Create/update `.venv` from `pyproject.toml`. |
| `./scripts/run-jobhunter.sh update-uv` | Install uv if missing and try to update uv itself. |
| `./scripts/run-jobhunter.sh playwright` | Install Playwright Chromium. |
| `./scripts/run-jobhunter.sh debug` | Run FastAPI with debug endpoints/logging. |
| `./scripts/run-jobhunter.sh app` | Run FastAPI normally. |
| `./scripts/run-jobhunter.sh scrape` | Run the source connector. |
| `./scripts/run-jobhunter.sh no-llm` | Run source connector with live LLM review disabled. |
| `./scripts/run-jobhunter.sh rebuild` | Rebuild workspace only from saved runtime state. |
| `./scripts/run-jobhunter.sh agent` | Run the scheduled-agent wrapper once. |
| `./scripts/run-jobhunter.sh agent-loop` | Run the scheduled-agent wrapper loop. |
| `./scripts/run-jobhunter.sh test` | Run pytest. |
| `./scripts/run-jobhunter.sh lint` | Run ruff checks. |

Primary local routes after startup:

| Route | Purpose |
|---|---|
| `/start` | onboarding |
| `/settings` | runtime configuration |
| `/workspace` | operational workspace |
| `/swagger-ui` | API diagnostics |
| `/docs` | markdown document API |

---

## Runtime entry points under the runner

### FastAPI runtime

```bash
./scripts/run-jobhunter.sh app
```

Debug mode:

```bash
./scripts/run-jobhunter.sh debug
```

### Source connector

Primary scrape/review pipeline:

```bash
./scripts/run-jobhunter.sh scrape
```

Deterministic no-LLM run:

```bash
./scripts/run-jobhunter.sh no-llm
```

### Workspace rebuild

```bash
./scripts/run-jobhunter.sh rebuild
```

### Agent runner

Single run:

```bash
./scripts/run-jobhunter.sh agent
```

Persistent loop:

```bash
./scripts/run-jobhunter.sh agent-loop
```

---

## Dependency model

Dependency source of truth:

```text
pyproject.toml
```

Runtime dependencies live under `[project].dependencies`.

Developer-only dependencies live under:

```text
[dependency-groups]
dev = [...]
```

The project intentionally sets:

```toml
[tool.uv]
package = false
```

Reason: Job Hunter is currently a flat application repo. It is run from the repo root and does not need to be packaged and installed as a library for local WSL development.

Expected generated environment:

```text
.venv/
```

Expected generated lock file after local uv resolution:

```text
uv.lock
```

If `uv.lock` is generated or changed after `uv sync`, review and commit it once validated so other environments resolve the same dependency set.

---

## Server logs

Server logs:

- runtime output is written to `output/server.log`
- each line gets a timestamp
- the terminal still shows the same server output
- browser `console.log` is separate from server logs and only matters for JS running in the page
- structured uncertainty events are appended to `output/uncertainty.jsonl` and also logged in the main server log
- to emit one, call `job_hunter_agent.runtime_helpers.build_uncertainty_entry()` then `append_uncertainty_log()` with `job_hunter_agent.paths.UNCERTAINTY_LOG_PATH`
- keep `reason_code` stable so the file stays queryable across agents and future runs

---

## Session cookie behavior

- cookie security is transport-aware by default
- `Secure` is enabled when the request is HTTPS
- `http://127.0.0.1:8765` and LAN HTTP access stay usable without a reverse proxy
- set `JOB_HUNTER_SESSION_COOKIE_SECURE=true` or `false` to force a mode explicitly
- logout is `POST /logout` only; the account menu submits the CSRF token automatically

---

## Runtime state model

### Authoritative runtime state

| Location | Purpose |
|---|---|
| SQLite DB (`JOB_HUNTER_DB_PATH`) | runtime candidate profile, job history, run outputs, user settings |
| `data/runtime/` | LLM cache, costs, and orchestration state |
| `data/config/` | global settings seed |
| `data/knowledge/` | approved business knowledge |
| `data/signals/` | signal registry and learning review state |

The DB and `data/runtime/` should be preserved. Knowledge and config files are committed to git as baseline seeds.

### Disposable runtime outputs

| Location | Purpose |
|---|---|
| `data/users/<uid>/workspace_results.html` | rendered workspace |
| DB `run_stats` table | runtime diagnostics |
| DB `review_data` table | review summaries |
| DB `audit_records` table | audit output |

These can be regenerated from the DB or by re-running a scrape.

---

## AWS production deploy

AWS production also uses uv for dependency sync.

Normal deploy command on EC2:

```bash
deploy-jobhunter
```

The repo-managed script is:

```bash
scripts/ec2/deploy-jobhunter.sh
```

Production deploy sequence:

1. pull latest GitHub code with `git pull --ff-only`
2. ensure uv is available
3. run `uv sync --no-dev`
4. install/update Playwright Chromium with `uv run playwright install chromium`
5. load `/etc/job-hunter/job-hunter.env`
6. apply production data/output/DB paths
7. run `uv run python -m job_hunter_agent.db_seed --upgrade`
8. restart `job-hunter.service`
9. show service status, recent logs, and HTTP health check

Do not manually pip install production dependencies on AWS. Add dependencies to `pyproject.toml`, commit them, push, then deploy.

Production service still executes `.venv/bin/python` directly. That is intentional: uv prepares `.venv`, and systemd uses the stable interpreter path created by uv.

---

## Desktop launcher note

The Windows desktop launcher remains a packaging flow, not the WSL development flow.

Current desktop layout:

| Location | Contents |
|---|---|
| `%LOCALAPPDATA%\Programs\JobHunterAgent\` | app code, templates, seed data, `.venv` |
| `%APPDATA%\JobHunterAgent\data\` | user DB, knowledge, config, runtime (`JOB_HUNTER_DATA_DIR`) |
| `%APPDATA%\JobHunterAgent\output\` | logs and artefacts (`JOB_HUNTER_OUTPUT_DIR`) |

Desktop migration to uv should be handled as a separate packaging task because installer behavior must be tested on Windows, not only in WSL.

---

## Validation workflow

After dependency or runtime-command changes:

```bash
./scripts/run-jobhunter.sh sync
./scripts/run-jobhunter.sh test
./scripts/run-jobhunter.sh debug
```

For scraper-focused changes:

```bash
./scripts/run-jobhunter.sh no-llm
```

For UI-only workspace changes:

```bash
./scripts/run-jobhunter.sh rebuild
```

---

## Recovery notes

If uv is missing in WSL:

```bash
./scripts/run-jobhunter.sh sync
```

The script installs uv using the official Astral Linux installer when uv is not found.

If Playwright is missing:

```bash
./scripts/run-jobhunter.sh playwright
```

If the app starts but the browser shows stale JavaScript, hard-refresh first. If Python changed, restart the server.
