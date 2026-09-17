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

## Command rule

For all WSL/Linux and EC2 commands in this document, run Python through the
project environment: `uv run python ...`, `uv run pytest ...`, or another
`uv run ...` command. Do not use bare `python`, `python3`, `pytest`, or `ruff`.
A missing bare executable is a command-launch failure; it is not a database,
application, or repository-access failure.

---

# Runtime Entry Points

## Main Runtime Commands

### Source Connector

Primary runtime pipeline.

```powershell
uv run python -m job_hunter_agent.source_connector
```

Use `--force-refresh` on the source connector when a live-board refresh is
deliberately required. The `/api/run` endpoint accepts the equivalent boolean
`force_refresh` request field. Otherwise, recent identical source searches may
reuse normalized discovery snapshots; the current profile filters and review
pipeline still run on every invocation.

This command runs from the authenticated account context already present in the app. It does not accept a manual account id or scope. If no signed-in account is available, it stops and asks you to log in first. Normal discovery is Job Market Map-backed; configure `JOB_HUNTER_MARKET_MAP_BASE_URL` to the deployed JMM `/v3` API before running it. If JMM is unavailable or misconfigured, the run fails clearly and does not fall back to Job Hunter's old collectors or market cache.

Responsibilities:

* consume canonical market jobs from Job Market Map
* request current JDs from Job Market Map when detail review needs them
* normalize job data
* apply deterministic filtering
* optionally run constrained LLM review
* generate scoring
* update workspace outputs
* persist runtime artifacts

---

### Agent Ad-Hoc Search (JH-292)

Lets an external agent (Claude, etc. via CLI/MCP shell access) trigger a
one-off search with custom keywords, salary floor, locations, and enabled
sources -- for example an urgent broad "any role" search that deliberately
differs from the signed-in user's saved profile settings.

```powershell
uv run python -m job_hunter_agent.agent_search --base-user-id <real-user-id> --keywords "business analyst" "business support officer" --min-salary 0 --print-results
```

Safety model: the command reuses `scrape_jobs_direct()` completely
unchanged. It never writes to `--base-user-id`'s own persisted profile row --
it reads that profile once (read-only) for candidate background/capability
context, then scopes the actual run to a separate, deterministic
`<base-user-id>::agent-adhoc` user_id via `user_context.set_user_id()`.
Results land in that ephemeral user_id's own `workspace_pool` row, never
merged into the real user's normal saved results. Re-running for the same
`--base-user-id` reuses the same ephemeral profile/workspace row rather than
accumulating a new one per call.

Read results from a prior ad-hoc run without triggering a new scrape:

```python
from job_hunter_agent.agent_search import get_ad_hoc_results
get_ad_hoc_results("<real-user-id>")
```

Local/CLI use only. A proper authenticated HTTP endpoint exposing the same
capability is tracked separately as JH-293.

---

### Agent Runner

Standalone CLI wrapper for direct/manual agent execution and scheduler diagnostics. Normal local app scheduling is owned by the FastAPI runtime; operators do not need to launch this as a second process for Settings → Run & Schedule to work.

```powershell
uv run python -m job_hunter_agent.agent_runner
```

Responsibilities:

* trigger direct refresh runs
* generate digest summaries
* send notifications
* provide a standalone scheduler loop for diagnostics or deliberately separate runtimes

Standalone loop (diagnostic/separate-runtime use only):

```powershell
uv run python -m job_hunter_agent.agent_runner --loop
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
- SEEK persistent browser mode uses a SEEK-only Playwright profile, separate from APSJobs, so a completed SEEK sign-in can be reused on later searches. The first persistent run may ask you to sign in once.
- If SEEK shows sign-in or human verification in a visible browser, the workspace pins a `SEEK needs you` state and raises a one-shot browser alert. Complete the prompt in that same SEEK browser; Job Hunter waits once for the configured manual-verification window, then either resumes or records a clear partial-source warning with retry guidance.

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
uv run python -m job_hunter_agent.fastapi_app
```

For local JMM-backed discovery, the repo `.env` should contain:

```text
JOB_HUNTER_MARKET_MAP_BASE_URL=http://127.0.0.1:8770/v3
```

JMM is a separate service and must be running on port `8770`; this setting only tells Job Hunter where to call it. A safe template is provided in `.env.example`. Non-local deployments must set their own reachable JMM `/v3` URL and must not assume `127.0.0.1`.

Repo-root launcher:

```bash
./run
```

Debug mode:

```powershell
uv run python -m job_hunter_agent.fastapi_app --debug
```

Repo-root launcher:

```bash
./run --debug
```

Background-service rule:

- the normal FastAPI runtime owns the local scheduled-agent loop so Settings → Run & Schedule works without a second hidden process
- the saved per-user `schedule.enabled` and `daily_time_local` settings remain the scheduler source of truth and are read live by the loop
- desktop mode does not start this web-owned scheduler thread because the desktop launcher owns its process lifecycle
- the shared Telegram poller remains opt-in via `JOB_HUNTER_ENABLE_SERVER_TELEGRAM_POLLER=true`
- a future AWS/external scheduler can replace the in-process clock watcher without changing the normal search pipeline (tracked separately as JH-264)

Server logs:

- application runtime output is written to a single file, `output/server.log`, timestamped
- `./run` shows curated INFO-level lines (per-job results, run summaries, session banners, settings/auth changes); `./run --debug` raises `server.log` to DEBUG, adding application trace (LLM calls, pipeline stage detail, scraper card detail)
- raw dependency/API transport chatter (httpx/httpcore/openai wire-level detail — headers, connection open/close, retry bookkeeping) is dropped at every level, in and out of `--debug`; it's never actionable and only clutters the file. Genuine errors from those libraries still surface as WARNING+
- the terminal mirrors the curated `server.log` stream
- every server start writes a large `NEW SERVER SESSION STARTED` banner into the log, including the local start time, PID, and startup flags
- on AWS, the EC2 browser-session launcher also prints an `AWS JOB HUNTER SERVICE STARTING` banner directly into `systemd`/`journalctl` before Python starts, so service restarts are obvious even if you are only watching the live service log
- on AWS, `jobhunter-logs` shows `journalctl` plus the app log, accepts `--since "YYYY-MM-DD HH:MM:SS"` / `--until "YYYY-MM-DD HH:MM:SS"` when you need the pre-restart window, and `jobhunter-logs --follow` tails the app log by default
- the AWS service startup path rebuilds saved workspace HTML before serving requests, so `deploy-jobhunter-release` refreshes rendered workspace output as part of a normal deploy
- browser `console.log` is separate from server logs and only matters for JS running in the page
- debug/audit uncertainty events are appended to `output/uncertainty.jsonl`
- runtime events are stored in SQLite `system_warnings`; Admin → Global settings → System health shows unresolved operational problems by default and groups routine uncertainty into an optional read-only diagnostics drill-down
- acknowledging an operational problem hides the current occurrence only; the same fingerprint returns to the active list if the fault recurs
- supported source failures/timeouts can run the existing scraper-configuration validation from System health; incidents without an automated check remain visible for developer investigation
- to emit one, call `job_hunter_agent.runtime_helpers.build_uncertainty_entry()` then `append_uncertainty_log()` with `job_hunter_agent.paths.UNCERTAINTY_LOG_PATH`
- keep `reason_code` stable so the file stays queryable across agents and future runs
- run-progress updates are also written into `output/server.log` (at DEBUG level, under `./run --debug`) as `RUN_PROGRESS` markers, so a stuck overlay can be matched to the backend timeline after the fact

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
uv run python -m job_hunter_agent.source_connector --no-llm
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
uv run python -m job_hunter_agent.source_connector --rebuild-workspace
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
uv run python -m job_hunter_agent.source_connector
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

The normal local FastAPI runtime starts the scheduler watcher automatically. The standalone command below is only for diagnostics or a deliberately separate runtime:

```powershell
uv run python -m job_hunter_agent.agent_runner --loop
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
uv run python -m job_hunter_agent.source_connector --rebuild-workspace
```

Purpose:

* validate workspace changes
* validate rendering changes
* inspect current saved state
* avoid scrape overhead

## Candidate application history cutover

The legacy rejection-sheet sync is retired from normal runtime and the Admin
settings UI. The configured `Job_Rejections` sheet, existing local structured
history, and legacy SQLite events are read only by the explicit JH-308
cutover command. The sheet remains audit provenance; it is not an active
canonical store and no broad Gmail import is performed.

Run a plan first, then apply only after reviewing its private report:

```powershell
uv run python -m job_hunter_agent.jh308_cutover \
  --db /var/lib/job-hunter/data/app.db \
  --target-user-id <rob-user-id>
```

Applying requires an explicit rollback snapshot path:

```powershell
uv run python -m job_hunter_agent.jh308_cutover \
  --db /var/lib/job-hunter/data/app.db \
  --target-user-id <rob-user-id> \
  --apply \
  --backup /var/lib/job-hunter/data/jh308-pre-cutover.sqlite
```

Exact identities are written to JH-305 through the supported activity owner.
When deliberate historical reconstruction confirms an application but no trustworthy
vacancy or requisition ID can be recovered, a unique explicit Gmail candidate-process
message for that employer + role may be used as `gmail:<message-id>` for the
deterministic historical job key. Suitable evidence includes an application
confirmation, recruiter submission/authority, interview invitation, or rejection;
generic correspondence is not sufficient. Attach later evidence for the same role to
that same key. Never synthesize an identity from employer/title/date text. A job's current
application disposition is mutually exclusive: it is either applied, rejected, or
neither. The ledger may retain both applied and rejected events as chronology, but a
later rejection supersedes applied state and a later re-application supersedes
rejected state. Unresolved outcomes go to `historical_application_evidence`, which
has no job identity and is bounded by
`history_settings.historical_application_evidence_max_entries`. Junk and duplicates
go to the body-free quarantine table. A failed JMM exact lookup leaves the evidence
unresolved rather than using legacy or fuzzy matching.

## JH-307 legacy cutover audit

Run this before any JH-308 reconciliation or retirement work. It opens the
existing database read-only, reads the configured `Job_Rejections` CSV when
enabled, inspects the existing local history JSON, and scans current runtime
references to legacy market/history mechanisms. It does not run Gmail search,
LLM extraction, JMM lookup, workspace rebuild, migration, or cleanup.

```powershell
JOB_HUNTER_DATA_DIR=/var/lib/job-hunter/data \
JOB_HUNTER_OUTPUT_DIR=/var/lib/job-hunter/output \
uv run python -m job_hunter_agent.jh307_audit \
  --db /var/lib/job-hunter/data/app.db \
  --target-user-id <rob-user-id> \
  --local-history-user-id <rob-user-id> \
  --sheet-user-id <rob-user-id>
```

The user IDs for the three personal scopes must be supplied explicitly. Use
`--ownership <ignored-private-json>` for known non-personal agent, automation,
system, test, or other users; unlisted non-target users remain unclassified and
are never attributed to Rob. The default report is
`output/jh307_cutover_audit.json`, which is ignored runtime state. Do not move
that report into tracked source or commit its personal evidence.

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
uv run python -m job_hunter_agent.agent_runner --send-notification-no-scrape
```

Disable notifications:

```powershell
uv run python -m job_hunter_agent.agent_runner --no-notify
```

---

# Local Runtime Setup

## Environment Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
uv sync --no-dev
uv run python -m playwright install chromium
```

## Database Bootstrap

Run once on first deploy (or after a DB reset) to seed knowledge, config, and signal defaults:

```bash
uv run python -m job_hunter_agent.db_seed
```

### After deploying a new app version

**Knowledge entries** (`data/knowledge/`, `data/signals/`) upgrade automatically on every startup — no manual step is needed after a normal `git pull`.

**Global settings** (`data/config/global_settings.json`) do NOT auto-upgrade on startup. If the global settings schema gains new required fields, run `db_seed --upgrade` manually before restarting the server, otherwise startup will fail with a `ValueError` from `normalize_global_settings`.

`--upgrade` is available for manual runs or scripted deployments:

```bash
uv run python -m job_hunter_agent.db_seed --upgrade
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
- `history_settings.historical_application_evidence_max_entries`: `2000`
- `cache_settings.llm_cache_max_entries`: `2000`
- `cache_settings.llm_cache_max_age_days`: `30`
- `cache_settings.cv_extraction_cache_max_entries`: `250`
- `cache_settings.cv_extraction_cache_max_age_days`: `30`
- `cache_settings.candidate_application_history_cache_max_entries`: `2000`
- `cache_settings.candidate_application_history_cache_max_age_days`: `30`
- `cache_settings.occupation_title_cache_max_entries`: `10000`
- `cache_settings.occupation_title_cache_max_age_days`: `365`
- `cache_settings.source_discovery_cache_max_entries`: `10000`
- `cache_settings.source_discovery_cache_max_age_minutes`: `60`
- `cache_settings.search_plan_max_age_minutes`: `10080`
- `cache_settings.linkedin_failure_backoff_minutes`: `15`
- `cache_settings.linkedin_max_consecutive_target_failures`: `6`

Behavior:

- Job history is pruned by both age and count.
- The occupation-title cache is pruned by both age and count.
- Source discovery snapshots are retained per account and reused only for a
  matching source signature within the configured freshness window.
- Learned search plans use their own freshness window. When that window expires,
  each configured role term is run in a bounded complete probe; only a healthy
  complete probe can replace the remembered plan. Source-result cache reuse does
  not refresh the plan.
- A fully failed LinkedIn search records a temporary bounded backoff state; it does not suppress future retries permanently.
- LinkedIn stops submitting new search targets after the configured number of consecutive target failures. Already-running bounded workers are drained, successful partial results are preserved, and an incomplete/failed collection is not written as a successful discovery snapshot.
- A LinkedIn search that completes successfully with zero rows is `healthy`; zero rows alone are not a source failure.
- Source health is explicit: `healthy`, `partial_failure`, `full_failure`, or `stopped`. `SOURCE_COMPLETE` means only that the source worker finished; `SOURCE_FAILED` / `SOURCE_PARTIAL` and the structured source result describe collection health.
- The file-backed caches are pruned by both age and count.
- Admin > Global settings also exposes maintenance actions to clear shared runtime caches or clear the current user search state immediately.
- Clear current user search state also clears transient runtime caches, per-user agent state, the current workspace HTML, and recruiter/history review state so the next run regenerates from clean runtime state.
- Managed historical application evidence is retained separately from current job history and is bounded by `history_settings.historical_application_evidence_max_entries`. The retired rejection-sheet sync and its destructive clear action are not part of normal runtime.

### Hard reset (wipes user-approved additions)

```bash
uv run python -m job_hunter_agent.db_seed --overwrite
```

`--overwrite` replaces all DB knowledge entries from the current bundled files. Use only for a full DB reset or corruption recovery — it will wipe any user-approved signal additions.

`--upgrade` and `--overwrite` are mutually exclusive.

---

### Interrupted server shutdown during an active search

If Uvicorn receives a shutdown request while a job search is active, Job Hunter records the run as `interrupted` before normal server shutdown continues. The terminal/server log emits a `[RUN_INTERRUPTED]` warning with the active run ID, current source/progress, timestamp, and SIGINT/SIGTERM when Uvicorn exposes the signal. For shutdown paths where no reliable signal is available, the signal is reported as unknown rather than guessed.

Operational invariants:

- an interrupted search is never reported as a successful completed run;
- active run state is cleared so the UI does not remain stuck on `running`;
- source-discovery snapshots collected by the interrupted run are not committed as successful snapshots;
- the next server startup reports the previous interrupted run so the operator can see that the prior search did not finalize;
- intentional Ctrl+C/SIGTERM still shuts the server down normally after the interruption is recorded. Job Hunter does not ignore or fight an explicit shutdown request.

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
uv run python -m job_hunter_agent.test_runner
```

Internally, it finds the repo virtual environment and runs pytest from the repository root.

These are equivalent in purpose:

```powershell
.\.venv\Scripts\python.exe -m pytest
uv run python -m job_hunter_agent.test_runner
```

Use the wrapper only when its options make the command easier to read.

Run only tests matching a word, such as onboarding:

```powershell
uv run python -m job_hunter_agent.test_runner -k onboarding
```

Equivalent direct pytest command:

```powershell
.\.venv\Scripts\python.exe -m pytest -k onboarding
```

Run in verbose mode, showing more detail about individual tests:

```powershell
uv run python -m job_hunter_agent.test_runner -v
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
uv run python -m ruff check .
```

Format changed Python files:

```powershell
uv run python -m ruff format <file-or-folder>
```

Fix safe lint issues:

```powershell
uv run python -m ruff check . --fix
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
uv run python -m job_hunter_agent.source_connector --rebuild-workspace
```

---

## Runtime Reset Visibility

Reset "new-to-you" visibility:

```powershell
uv run python -m job_hunter_agent.source_connector --rebuild-workspace --reset-new-to-you
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

It is normal for `main` to contain ordinary unreleased commits after the latest release tag. Those commits keep the same application version until the next intentional release is cut.

Use one release command from a clean, synchronized `main` branch:

```bash
./scripts/release-jobhunter.sh patch
```

Repo-root shortcut:

```bash
./release
```

`./release` defaults to `patch --publish-main-first`. It also accepts `minor`, `major`, and `--dry-run`.

If local `main` is intentionally ahead of `origin/main` and you want one command to publish that commit and immediately cut the next patch release:

```bash
./scripts/release-jobhunter.sh patch --publish-main-first
```

Meaning:

- `patch`: bug fix or correction, for example `X.Y.Z -> X.Y.(Z+1)`.
- `minor`: backward-compatible functionality, for example `X.Y.Z -> X.(Y+1).0`.
- `major`: breaking change, for example `X.Y.Z -> (X+1).0.0`.

To run every gate without changing files, Git history, tags, or GitHub:

```bash
./scripts/release-jobhunter.sh patch --dry-run
```

The release command validates version consistency, runs the full unit suite and non-LLM Playwright suite, commits the version update, creates an annotated tag, and atomically pushes `main` with the tag. After the release succeeds, connect to AWS and run `deploy-jobhunter-production vX.Y.Z`.

Production AWS deploys use an explicit release tag through the guarded production deploy command:

```bash
deploy-jobhunter-production vX.Y.Z
```

The production deploy command records the current known-good release, creates a timestamped runtime-data snapshot, deploys the requested release, runs production smoke checks, and automatically rolls back to the previous release if validation fails. Runtime data is restored from the snapshot only if code rollback alone does not recover production. Successful deploy state is recorded under `/var/lib/job-hunter/deployments`; deployment snapshots are stored under `/var/lib/job-hunter/backups`, retaining the newest five by default.

`deploy-jobhunter-release vX.Y.Z` remains the low-level exact-tag deploy primitive used by the production command.

For AWS smoke tests or debugging without cutting a release, use the separate non-production helper:

```bash
deploy-jobhunter-latest
deploy-jobhunter-latest <branch-or-sha>
```

Use `deploy-jobhunter-latest` only for staging/test/debug work. With no argument it deploys the latest commit from `main`. Do not treat it as the normal production deploy path, and do not reuse old production tags to move newer code.

For a direct metadata diagnosis:

```bash
uv run python scripts/check-release-integrity.py
```

---

# Expansion Direction

Operational expansion targets:

* autonomous orchestration
* adaptive runtime diagnostics
* LangGraph workflow integration
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
