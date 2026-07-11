# Job Hunter Agent — Operations

# Operational Purpose

This document defines:

* runtime execution flows
* operational commands
* rebuild boundaries
* persistence rules
* local runtime management
* diagnostic workflows
* recovery workflows

This is an operational runtime reference, not a development diary.

---

# Runtime Entry Points

## Main Runtime Commands

### Source Connector

Primary runtime pipeline.

```powershell
python -m job_hunter_agent.source_connector
```

This command runs from the authenticated account context already present in the app. It does not accept a manual account id or scope. If no signed-in account is available, it stops and asks you to log in first.

Responsibilities:

* scrape jobs
* normalize job data
* apply deterministic filtering
* optionally run constrained LLM review
* generate scoring
* update workspace outputs
* persist runtime artifacts

---

### Agent Runner

Persistent automation wrapper.

```powershell
python -m job_hunter_agent.agent_runner
```

Responsibilities:

* orchestrate scheduled execution
* trigger refresh runs
* generate digest summaries
* send notifications
* maintain scheduled runtime loop

Persistent loop:

```powershell
python -m job_hunter_agent.agent_runner --loop
```

---

### Desktop Launcher

System tray app — starts the FastAPI server locally and opens the browser automatically.

#### Install (recommended)

Run the installer — it installs per-user under
`%LOCALAPPDATA%\Programs\JobHunterAgent` and does not require admin rights:

```
installer\dist\JobHunterAgent-Setup.exe
```

If this repo lives in WSL, the built installer is accessible from Windows at
`\\wsl.localhost\Ubuntu\home\robvoto\projects\job-hunter-agent\installer\dist\JobHunterAgent-Setup.exe`
after a successful build. The `installer` folder itself only contains the
Inno Setup source until `Build` creates `dist\JobHunterAgent-Setup.exe`.

The installer bundles its own private Python runtime — no system Python or `uv`
needs to be pre-installed on the client machine. Post-install, the setup script
installs all dependencies and Playwright Chromium into that bundled runtime
automatically (~3 min on first install).

After install: **Start Menu → Job Hunter Agent** or double-click the desktop shortcut.

Uninstall: **Start Menu → Job Hunter Agent → Uninstall Job Hunter Agent**
(or Settings → Apps).

Install layout:

| Location | Contents |
| -------- | -------- |
| `%LOCALAPPDATA%\Programs\JobHunterAgent\` | compiled app code (`.pyc`), templates, seed data, bundled Python runtime (`python\`), project metadata, bootstrap launcher |
| `%APPDATA%\JobHunterAgent\data\` | user DB, knowledge, config, runtime (`JOB_HUNTER_DATA_DIR`) |
| `%APPDATA%\JobHunterAgent\output\` | logs and artefacts (`JOB_HUNTER_OUTPUT_DIR`) |
| Start Menu | Launch + Uninstall shortcuts |

#### Run from repo (development only)

```powershell
.venv\Scripts\pythonw.exe desktop\launcher.py
```

Data is written to `%APPDATA%\JobHunterAgent\` in both modes.

Desktop v1 rule:

> No global keys. No shared learning. No upload without consent.

Behaviour:

- Tray icon shows in the system tray; left-click or double-click to open the app.
- Right-click → Quit stops the server and exits.
- A single-instance mutex prevents double-launches.
- Telegram polling only runs while the desktop launcher is open, so bot commands are unavailable when the app is closed.
- `JOB_HUNTER_PORT` controls the port (default `8765`).
- On first launch the server cold-starts in up to 60 s; subsequent starts are faster.
- If Playwright Chromium is missing a notification appears on launch; SEEK scraping will
  fail until it is installed.
- If SEEK shows a human-verification page, enable Assisted SEEK verification in global settings and use the visible persistent browser to finish the check manually.

Telegram commands while the app is open:

- `/status`
- `/summary` or `/latest`
- `/run`
- `/export`
- `/export fresh`
- `/help`

The desktop installer now asks for the workspace export folder, defaulting to
`%USERPROFILE%\Documents\Job Hunter Workspace`, and stores it in
`%APPDATA%\JobHunterAgent\data\config\desktop.json`.

#### Build the installer (developer task)

Requires [Inno Setup 6](https://jrsoftware.org/isdl.php).

First, prepare the bundled Python runtime (once, and again whenever the
pinned version in `installer/prepare_python.ps1` changes — it is not
committed to git):

```powershell
powershell -ExecutionPolicy Bypass -File installer\prepare_python.ps1
```

Then build it on Windows by opening `installer/setup.iss` in the Inno Setup
Compiler and pressing Build (F9), or run:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\setup.iss
```

Output: `installer\dist\JobHunterAgent-Setup.exe`

On WSL-backed workspaces, you can also open the build output folder in Windows
Explorer with:

```bash
explorer.exe "$(wslpath -w installer/dist)"
```

Regenerate the tray/shortcut icon from the PNG source (run once after icon changes):

```powershell
.venv\Scripts\python.exe -c "
from PIL import Image
import numpy as np
img = Image.open('templates/static/assets/job_hunter_img.png').convert('RGBA')
d = np.array(img); m = (d[:,:,0]>230)&(d[:,:,1]>230)&(d[:,:,2]>230); d[m,3]=0
Image.fromarray(d).save('installer/job_hunter_agent.ico', format='ICO',
    sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
"
```

---

### FastAPI Runtime

Local operational UI.

```powershell
python -m job_hunter_agent.fastapi_app
```

Repo-root launcher:

```bash
./run
```

Debug mode:

```powershell
python -m job_hunter_agent.fastapi_app --debug
```

Repo-root launcher:

```bash
./run --debug
```

Server logs:

- runtime output is written to `output/server.log`
- each line gets a timestamp
- the terminal still shows the same server output
- browser `console.log` is separate from server logs and only matters for JS running in the page
- structured uncertainty events are appended to `output/uncertainty.jsonl` and also logged in the main server log
- to emit one, call `job_hunter_agent.runtime_helpers.build_uncertainty_entry()` then `append_uncertainty_log()` with `job_hunter_agent.paths.UNCERTAINTY_LOG_PATH`
- keep `reason_code` stable so the file stays queryable across agents and future runs

Run summary semantics:

- the visible end-of-run summary is an operational diagnostic, not a fit explanation
- `Jobs seen` means source job cards discovered in the audit rows
- `descriptions read` means job details/descriptions successfully fetched using the same definition as `cards_read` in run stats
- source/platform `read` counts must reconcile with the total `descriptions read`
- source/platform `pages` come only from explicit page markers; do not treat every LinkedIn row as a page
- `kept` and `rejected` are collection/review outcomes for the run, not proof of strong fit

Session cookie behavior:

- cookie security is transport-aware by default
- `Secure` is enabled when the request is HTTPS
- `http://127.0.0.1:8765` and LAN HTTP access stay usable without a reverse proxy
- set `JOB_HUNTER_SESSION_COOKIE_SECURE=true` or `false` to force a mode explicitly
- logout is `POST /logout` only; the account menu submits the CSRF token automatically

Primary routes:

| Route         | Purpose               |
| ------------- | --------------------- |
| `/start`      | onboarding            |
| `/settings`   | runtime configuration |
| `/workspace`  | operational workspace |
| `/swagger-ui` | API diagnostics       |
| `/docs`       | markdown document API |

---

# Runtime Modes

## Deterministic Runtime

Disable live LLM review:

```powershell
python -m job_hunter_agent.source_connector --no-llm
```

Purpose:

* isolate deterministic filtering
* test scoring behaviour
* avoid API costs
* validate rule changes

---

## Workspace Rebuild Runtime

Rebuild workspace only:

```powershell
python -m job_hunter_agent.source_connector --rebuild-workspace
```

Purpose:

* rebuild UI outputs
* validate workspace rendering
* avoid unnecessary scraping
* avoid unnecessary LLM review

---

# Runtime State Model

## Authoritative Runtime State

Critical runtime files:

| Location                   | Purpose                      |
| -------------------------- | ---------------------------- |
| SQLite DB (`JOB_HUNTER_DB_PATH`) | runtime candidate profile, job history, run outputs, user settings |
| `data/runtime/` | LLM cache, costs, and orchestration state |
| `data/config/` | global settings seed (committed defaults) |
| `data/knowledge/` | approved business knowledge |
| `data/signals/` | signal registry and learning review state |

The DB and `data/runtime/` should be preserved. Knowledge and config files are committed to git.

---

## Disposable Runtime Outputs

Rebuildable outputs:

| File                        | Purpose             |
| --------------------------- | ------------------- |
| Account-scoped workspace output | rendered workspace |
| DB `run_stats` table        | runtime diagnostics |
| DB `review_data` table      | review summaries    |
| DB `audit_records` table    | audit output        |

These can be regenerated from the DB or by re-running a scrape.

---

# Operational Workflows

## Standard Refresh Workflow

```powershell
python -m job_hunter_agent.source_connector
```

Operational sequence:

1. load runtime profile
2. load runtime settings
3. scrape configured sources
4. normalize records
5. deduplicate jobs
6. apply deterministic filtering
7. optionally run constrained LLM review
8. generate fit scores
9. persist outputs
10. rebuild workspace

---

## Scheduled Runtime Workflow

```powershell
python -m job_hunter_agent.agent_runner --loop
```

Operational sequence:

1. wait for configured schedule
2. trigger refresh workflow
3. generate digest
4. send notifications
5. persist runtime state
6. continue runtime loop

---

## Workspace-Only Workflow

```powershell
python -m job_hunter_agent.source_connector --rebuild-workspace
```

Purpose:

* validate workspace changes
* validate rendering changes
* inspect current saved state
* avoid scrape overhead

---

# Settings Runtime Model

Primary settings template:

* `templates/settings.html`

Current runtime sections:

* Search
* Profile
* Capability Matrix
* Rules
* Alerts & AI
* Learning
* Optimise

---

## Optimise Runtime Area

`Optimise` is an advanced operational control surface.

Responsibilities:

* diagnostics
* runtime inspection
* scrape analysis
* tuning visibility
* review tooling
* highlight controls
* experimental runtime controls

Not intended for ordinary user preference management.

---

# Learning Operations

Primary runtime modules:

* `signal_registry.py`
* `review_insights.py`
* `profile_learning.py`

Operational rules:

* pending learning signals require review
* runtime learning is inspectable
* learning cannot silently alter filtering
* unapproved signals remain isolated from runtime filtering

---

# Notification Operations

Current notification runtime:

* Telegram

Primary modules:

* `notifiers/telegram_notifier.py`
* `routes/agent_telegram.py`

Agent runner can:

* send digest notifications
* rebuild summaries
* skip scraping when required

Notification-only digest rebuild:

```powershell
python -m job_hunter_agent.agent_runner --send-notification-no-scrape
```

Disable notifications:

```powershell
python -m job_hunter_agent.agent_runner --no-notify
```

---

# Local Runtime Setup

## Environment Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
uv sync --no-dev
python -m playwright install chromium
```

## Database Bootstrap

Run once on first deploy (or after a DB reset) to seed knowledge, config, and signal defaults:

```bash
python -m job_hunter_agent.db_seed
```

### After deploying a new app version

**Knowledge entries** (`data/knowledge/`, `data/signals/`) upgrade automatically on every startup — no manual step is needed after a normal `git pull`.

**Global settings** (`data/config/global_settings.json`) do NOT auto-upgrade on startup. If the global settings schema gains new required fields, run `db_seed --upgrade` manually before restarting the server, otherwise startup will fail with a `ValueError` from `normalize_global_settings`.

`--upgrade` is available for manual runs or scripted deployments:

```bash
python -m job_hunter_agent.db_seed --upgrade
```

`--upgrade` uses version-aware merge logic for knowledge files:
- Files with no `version` field (pure reference data) — always replaced.
- Files with `version` and an `entries` list (capability knowledge, blocker rules, etc.) — new entries appended; existing DB entries (including user-approved ones) are preserved.
- Files with `version` but no `entries` list (scoring rules, ui_labels, etc.) — replaced only when the file version is newer than the DB version.

Global settings are always overwritten by `--upgrade` (no per-entry user approvals exist, so replacement is always safe).

### Hard reset (wipes user-approved additions)

```bash
python -m job_hunter_agent.db_seed --overwrite
```

`--overwrite` replaces all DB knowledge entries from the current bundled files. Use only for a full DB reset or corruption recovery — it will wipe any user-approved signal additions.

`--upgrade` and `--overwrite` are mutually exclusive.

---

# Testing Operations

## Full Test Suite

Run the complete pytest test suite with the project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

This is the clearest command when you want to check the whole project before merging work into `main`.

## Test Runner Wrapper

`job_hunter_agent.test_runner` is a convenience wrapper around pytest. It does not run a separate test system.

```powershell
python -m job_hunter_agent.test_runner
```

Internally, it finds the repo virtual environment and runs pytest from the repository root.

These are equivalent in purpose:

```powershell
.\.venv\Scripts\python.exe -m pytest
python -m job_hunter_agent.test_runner
```

Use the wrapper only when its options make the command easier to read.

Run only tests matching a word, such as onboarding:

```powershell
python -m job_hunter_agent.test_runner -k onboarding
```

Equivalent direct pytest command:

```powershell
.\.venv\Scripts\python.exe -m pytest -k onboarding
```

Run in verbose mode, showing more detail about individual tests:

```powershell
python -m job_hunter_agent.test_runner -v
```

Equivalent direct pytest command:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Use targeted tests when validating a specific area, such as:

* filtering
* onboarding
* scoring
* workspace rendering
* learning logic

For changes that cross modules, auth, UI, persistence, or shared template/bootstrap code, run the targeted tests plus at least one representative integration, end-to-end, or page-render path.

Run the full suite before merging into `main`.

---

# Python Formatting and Linting

Install dev tools:

```powershell
uv sync --group dev
```

Check formatting and linting:

```powershell
python -m ruff check .
```

Format changed Python files:

```powershell
python -m ruff format <file-or-folder>
```

Fix safe lint issues:

```powershell
python -m ruff check . --fix
```

Use these commands on the files you are actively changing unless the task explicitly calls for a wider cleanup.

---

# Operational Constraints

The runtime must:

* remain locally operable
* preserve explainability
* preserve deterministic inspection
* avoid hidden filtering behaviour
* survive LLM disablement
* preserve runtime state integrity
* enforce secure network communication (HTTPS) for any non-local deployment

## Network Deployment & Security

When the server is bound to a network-accessible IP (e.g., `0.0.0.0`), startup requires `JOB_HUNTER_SESSION_COOKIE_SECURE=true`; otherwise the server fails fast before accepting requests. Secure cookies use the `__Host-` prefix. 

**Requirement:** Operations must provide an SSL/TLS termination layer (using a reverse proxy like Caddy or Nginx) to handle HTTPS, otherwise session management will fail.

The session cookie name can be customized via the `JOB_HUNTER_SESSION_COOKIE_NAME` environment variable.

The runtime must not:

* silently discard evidence
* silently apply learning
* hide runtime scoring behaviour
* couple onboarding evidence directly to runtime truth

---

# Recovery Operations

## Workspace Recovery

Rebuild workspace from saved runtime state:

```powershell
python -m job_hunter_agent.source_connector --rebuild-workspace
```

---

## Runtime Reset Visibility

Reset "new-to-you" visibility:

```powershell
python -m job_hunter_agent.source_connector --rebuild-workspace --reset-new-to-you
```

---

# Runtime Architecture Boundaries

Scraping layer:

* collects jobs
* does not determine final fit

Filtering layer:

* deterministic first
* explainable
* reviewable

LLM layer:

* optional
* constrained
* non-authoritative

Learning layer:

* review-gated
* inspectable
* non-silent

Workspace layer:

* operational workspace
* not temporary reporting

---

# Expansion Direction

Operational expansion targets:

* autonomous orchestration
* adaptive runtime diagnostics
* OpenClaw integration
* multi-agent runtime coordination
* application generation workflows
* richer operational telemetry

Expansion must preserve:

* runtime transparency
* deterministic inspection
* explainable filtering
* controlled learning

---

# AWS Deployment Operations

AWS production setup, deployment commands, diagnostics, HTTPS/ngrok notes, systemd details, persistent storage, and production health checks are maintained in:

- `docs/aws-ec2-setup.md`
- `docs/runbooks/aws-seek-assisted-browser-session.md` for SEEK assisted browser troubleshooting

This `OPERATIONS.md` file is the general day-to-day operations guide. Do not duplicate detailed AWS runbook content here.
