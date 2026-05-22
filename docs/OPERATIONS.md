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

### FastAPI Runtime

Local operational UI.

```powershell
python -m job_hunter_agent.fastapi_app
```

Debug mode:

```powershell
python -m job_hunter_agent.fastapi_app --debug
```

Server logs:

- runtime output is written to `output/server.log`
- each line gets a timestamp
- the terminal still shows the same server output
- browser `console.log` is separate from server logs and only matters for JS running in the page

Session cookie behavior:

- cookie security is transport-aware by default
- `Secure` is enabled when the request is HTTPS
- `http://127.0.0.1:8765` and LAN HTTP access stay usable without a reverse proxy
- set `JOB_HUNTER_SESSION_COOKIE_SECURE=true` or `false` to force a mode explicitly
- for local debug-only testing, set `JOB_HUNTER_DISABLE_AUTH=true` together with `--debug` to bypass login and CSRF checks

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
| `data/users/<uid>/workspace_results.html` | rendered workspace |
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
pip install -r requirements.txt
python -m playwright install chromium
```

## Database Bootstrap

Run once on first deploy (or after a DB reset) to seed knowledge, config, and signal defaults:

```bash
python -m job_hunter_agent.db_seed
```

After deploying a new app version that updates bundled JSON files, re-seed with overwrite to pick up the changes:

```bash
python -m job_hunter_agent.db_seed --overwrite
```

`--overwrite` replaces all DB knowledge entries from the current files. The default (`INSERT OR IGNORE`) preserves any runtime modifications made through the UI.

---

# Testing Operations

## Full Test Suite

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Focused Runtime Validation

```powershell
python -m job_hunter_agent.test_runner
```

Use focused tests when validating:

* filtering
* onboarding
* scoring
* workspace rendering
* learning logic

Avoid unnecessary full-suite execution during targeted changes.

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

When the server is bound to a network-accessible IP (e.g., `0.0.0.0`), it enforces `Secure` and `__Host-` prefixed cookies. 

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
