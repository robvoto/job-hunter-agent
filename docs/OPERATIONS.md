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

Background-service rule:

- the FastAPI server does not auto-start the scheduled agent loop or the shared Telegram poller
- use `python -m job_hunter_agent.agent_runner` for persistent scheduled automation
- desktop mode owns its own Telegram poller while the launcher is open
- server-side background loops are opt-in only via `JOB_HUNTER_ENABLE_SERVER_TELEGRAM_POLLER=true` and/or `JOB_HUNTER_ENABLE_SERVER_SCHEDULED_AGENT_LOOP=true`

Server logs:

- human-readable runtime output is written to `output/server-human.log`
- full technical/debug output is written to `output/server-debug.log`
- both logs are timestamped
- every server start writes a large `NEW SERVER SESSION STARTED` banner into both logs, including the local start time, PID, and startup flags
- on AWS, the EC2 browser-session launcher also prints an `AWS JOB HUNTER SERVICE STARTING` banner directly into `systemd`/`journalctl` before Python starts, so service restarts are obvious even if you are only watching the live service log
- `./run --debug` writes both logs; the terminal mirrors the same human-readable stream
- on AWS, use your service manager or `tail -f output/server-human.log` instead of a separate human-log wrapper
- the AWS service startup path rebuilds saved workspace HTML before serving requests, so `deploy-jobhunter` refreshes rendered workspace output as part of a normal deploy
- browser `console.log` is separate from server logs and only matters for JS running in the page
- debug/audit uncertainty events are appended to `output/uncertainty.jsonl`
- reviewable runtime warnings are stored in SQLite `system_warnings` and shown in the admin settings page
- to emit one, call `job_hunter_agent.runtime_helpers.build_uncertainty_entry()` then `append_uncertainty_log()` with `job_hunter_agent.paths.UNCERTAINTY_LOG_PATH`
- keep `reason_code` stable so the file stays queryable across agents and future runs

Run summary semantics:

- the visible end-of-run summary is an operational diagnostic, not a fit explanation
- `Jobs seen` means source job cards discovered in the audit rows
- `descriptions read` means job details/descriptions successfully fetched using the same definition as `cards_read` in run stats
- source/platform `read` counts must reconcile with the total `descriptions read`
- source/platform `pages` come only from explicit page markers; do not treat every LinkedIn row as a page
- `kept` and `rejected` are collection/review outcomes for the run, not proof of strong fit
- every job block now prints the job URL directly under `SOURCE | job_key` so a role can be traced back quickly in the log
- parallel runs log `SOURCE_START` and `SOURCE_COMPLETE` blocks per source, plus end-of-run `RUN][SOURCE_FINAL_STATS` blocks for each enabled source, including zero-result sources

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

Current scheduler rule:

* the loop must already be running before the configured daily time
* if the process starts after that day's window, the runner records a missed window and waits for the next day instead of replaying a catch-up run

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
* Messaging
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
- Files with `version` but no `entries` list (scoring rules, ui_labels, etc.) — replaced when the file version is newer than the DB version. If the version number is unchanged but the shipped config payload differs, startup now replaces the DB row from the file and logs a warning so stale config does not survive a forgotten version bump.

Global settings are always overwritten by `--upgrade` (no per-entry user approvals exist, so replacement is always safe).

### Retention and runtime-cache defaults

The current managed defaults for history and cache retention live in `data/config/global_settings.json` and are editable from Admin > Global settings:

- `history_settings.job_history_max_entries`: `2000`
- `history_settings.job_history_max_age_days`: `365`
- `cache_settings.llm_cache_max_entries`: `2000`
- `cache_settings.llm_cache_max_age_days`: `30`
- `cache_settings.cv_extraction_cache_max_entries`: `250`
- `cache_settings.cv_extraction_cache_max_age_days`: `30`
- `cache_settings.candidate_application_history_cache_max_entries`: `2000`
- `cache_settings.candidate_application_history_cache_max_age_days`: `30`
- `cache_settings.occupation_title_cache_max_entries`: `10000`
- `cache_settings.occupation_title_cache_max_age_days`: `365`

Behavior:

- Job history is pruned by both age and count.
- The occupation-title cache is pruned by both age and count.
- The file-backed caches are pruned by both age and count.
- Admin > Global settings also exposes maintenance actions to clear shared runtime caches or clear the current user search state immediately.
- Clear current user search state also clears transient runtime caches, per-user agent state, the current workspace HTML, and recruiter/history review state so the next run regenerates from clean runtime state.
- Clear runtime caches also deletes the transient candidate-application history JSON snapshot and any stale runtime-sidecar SQLite file under `data/runtime/`.

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

## Click-Testing (Playwright E2E)

`tests/e2e/` drives the real FastAPI app with a real Chromium browser (via Playwright), the way a human clicking through the app would notice bugs that mocked unit tests miss. If you are looking for "Selenium-style" browser coverage, this is that suite in this repo; it uses Playwright rather than Selenium, but it serves the same full click-path purpose. It boots an isolated seeded server on a free local port, mints a signed session cookie instead of doing a real Google OAuth flow, and captures screenshots plus browser console/network errors on failure (see `tests/e2e/conftest.py`).

It is **not** part of the default test run (`tests/e2e` is excluded via `norecursedirs` in `pyproject.toml`) because it is much slower than the unit suite. The preferred terminal entry point is:

```bash
./scripts/run-e2e.sh
```

To watch the browser instead of running headless:

```bash
./scripts/run-e2e.sh --headed tests/e2e/test_workspace_freshness_flow.py -q
```

First-time setup on a new machine also needs the Chromium browser binary:

```bash
uv run playwright install chromium
```

The wrapper script above can also do that for you:

```bash
./scripts/run-e2e.sh --install-browser
```

Direct pytest still works when needed:

```bash
uv run pytest tests/e2e --confcutdir=tests/e2e
```

`tests/e2e/test_onboarding_flow.py` clicks through the onboarding wizard's upload -> extract -> review-step transition (real upload UI, real route validation, real DOM rendering) with the LLM extraction stubbed to a deterministic canned result, so the actual extraction click is exercised on every default e2e run at zero cost -- not only in the opt-in real-LLM test below. This is the main browser-level guard for onboarding upload regressions.

`tests/e2e/test_workspace_job_actions.py` seeds one KEEP-scored job directly into a dedicated test user's workspace (via the `workspace_job_page` fixture, since the default `candidate_page` workspace is empty) and clicks through the per-job-card actions that `test_workspace_flow.py`'s filter-only coverage never reaches: the visible score/match-tile, saving a job ("applied") and undoing it, and dismissing a job ("hidden") and unhiding it -- including the real full-page reload each review action triggers.

`tests/e2e/test_workspace_freshness_flow.py` seeds one LinkedIn external-apply job and verifies the real workspace card shows the user-facing freshness-risk state, including the `LinkedIn listed` metadata line and the `Freshness may be unreliable` warning.

### Real-LLM onboarding test (costs money, opt-in only)

`tests/e2e/test_onboarding_llm_flow.py` drives the same wizard step with a real, billed OpenAI call instead of a stub. It is skipped at collection time unless both `JOB_HUNTER_E2E_ALLOW_LLM=1` and a real `OPENAI_API_KEY` are set, so it can never fire during a normal e2e run. It forces the cheapest selectable model (resolved live from `data/config/global_settings.json`'s pricing table, not hardcoded), asserts an on-record cost ceiling and exactly one request fired, and has a hard wall-clock timeout.

It must run with `--confcutdir=tests/e2e` so it skips the root `tests/conftest.py`, which unconditionally blanks `OPENAI_API_KEY` for the unit suite (and `job_hunter_agent.llm_gate` builds its OpenAI client once at import time, so a blanked key anywhere earlier in the process stays blanked for the rest of it):

```bash
JOB_HUNTER_E2E_ALLOW_LLM=1 OPENAI_API_KEY=sk-... \
./scripts/run-e2e.sh --llm tests/e2e/test_onboarding_llm_flow.py -v
```

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

# Release Management

`pyproject.toml` is the single application-version source. Do not edit the UI version or create release tags manually.

Use one release command from a clean, synchronized `main` branch:

```bash
./scripts/release-jobhunter.sh patch
```

Meaning:

- `patch`: bug fix or correction, for example `1.5.0 -> 1.5.1`.
- `minor`: backward-compatible functionality, for example `1.5.0 -> 1.6.0`.
- `major`: breaking change, for example `1.5.0 -> 2.0.0`.

To run every gate without changing files, Git history, tags, or GitHub:

```bash
./scripts/release-jobhunter.sh patch --dry-run
```

The release command validates version consistency, runs the full unit suite and non-LLM Playwright suite, commits the version update, creates an annotated tag, and atomically pushes `main` with the tag. After the release succeeds, connect to AWS and run `deploy-jobhunter`.

For a direct metadata diagnosis:

```bash
uv run python scripts/check-release-integrity.py
```

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
