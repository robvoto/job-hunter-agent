# Job Hunter Agent

Local-first job discovery and fit-evaluation system.

Deployment target:

- WSL-based local development on the PC
- AWS EC2 production operation
- desktop packaging as a separate distribution flow
- keep runtime state and deployment notes aligned with server operation

The product goal is simple: a user gives the app strong source material about their experience, the app builds a working profile, reviews jobs against that profile, and keeps a meaningful shortlist instead of forcing the user to search manually every day.

Current implemented job sources:

- SEEK
- LinkedIn

The architecture is intentionally broader than a single site. SEEK is the current source connector, not the long-term boundary of the product.

## What Works Now

- guided onboarding at `http://127.0.0.1:8765/start` (supports `.docx` and plain text)
- local settings console at `http://127.0.0.1:8765/settings`
- local workspace at `http://127.0.0.1:8765/workspace`

## Quick Start

The supported local developer runtime is **WSL + uv**.

From WSL:

```bash
cd /mnt/e/Programming/job-hunter-agent
./scripts/run-jobhunter.sh debug
```

Common commands:

```bash
./scripts/run-jobhunter.sh sync
./scripts/run-jobhunter.sh test
./scripts/run-jobhunter.sh no-llm
./scripts/run-jobhunter.sh rebuild
```

Do not duplicate setup or runtime commands in this README.

- For day-to-day use, follow [docs/USER_GUIDE.md](docs/USER_GUIDE.md).
- For setup, runtime execution, rebuild flows, flags, diagnostics, recovery, and validation commands, follow [docs/OPERATIONS.md](docs/OPERATIONS.md).

Search design note:

- keep search keywords broad enough to capture relevant roles
- use title rules, metadata gates, content filters, capability logic, and optional AI review to tighten fit afterward

## Architecture Note: Shell & Fragment

The workspace UI uses a decoupled pattern for performance and maintainability:

- **workspace.html (The Shell)**: The main entry point. It contains the navigation, branding, and JavaScript logic to poll for updates.
- **results.html (The Fragment)**: A template used by the server to render the actual job results.

When you load the workspace, the Shell is served first, and the Fragment is fetched and injected dynamically once the data is ready.

## Tech Stack

- **Core**: Python 3.12+
- **Dependency/runtime management**: uv with `pyproject.toml`
- **Automation**: Playwright (SEEK scraping)
- **Multi-Source**: `python-jobspy` (LinkedIn)
- **Intelligence**: OpenAI API where user-owned provider keys are enabled
- **Parsing**: `python-docx` and `pandas`
- **UI**: FastAPI + uvicorn; HTML/JS templates under `templates/` and `static/` (routes in `job_hunter_agent/routes/`)
- **Environment**: `python-dotenv`

Logic and core modules reside in the `job_hunter_agent/` package.

## Important Files

- `pyproject.toml`  
  Dependency source of truth for uv.

- `scripts/run-jobhunter.sh`  
  WSL runner for sync, app startup, scraping, tests, linting, and Playwright setup.

- SQLite DB (`JOB_HUNTER_DB_PATH`)  
  Runtime source of truth for profile, history, user settings, and run outputs.

- `data/agent_settings.template.json`  
  Starter template for daily-agent scheduling and notification delivery.

- `data/knowledge/`  
  Baseline business knowledge seeds.

- `data/config/`  
  Global/default config seeds.

## Local-Only State

These are intended to stay local and ignored:

- `.venv/`
- `uv.lock` until generated/reviewed and intentionally committed
- `TODO.txt`
- `data/app.db`
- `data/app.db-shm`
- `data/app.db-wal`
- `data/runtime/`
- `data/users/`
- `output/`
- local/private env files and API keys

## Security

By default, the application is configured for local use on `localhost`. If you access the workspace over a network, put it behind a proper HTTPS reverse proxy and keep session-cookie settings aligned with `docs/OPERATIONS.md`.

## LLM Notes

Desktop v1 ignores `OPENAI_API_KEY` and any other global/provider key source. The rule is:

> No global keys. No shared learning. No upload without consent.

Live LLM review stays disabled until user-owned provider-key support is added.

## Daily Agent Notes

The first daily agent layer is now local-first:

- `job_hunter_agent.agent_runner` runs the current connector, rebuilds the workspace, and creates a compact digest
- email delivery uses SMTP settings from local `data/agent_settings.json`
- Telegram delivery uses a bot token plus chat id from local `data/agent_settings.json`
- Telegram messages arrive in the user's private chat with their bot, not from their personal Telegram identity
- the digest is also written locally to `output/agent_last_summary.txt`

Recommended beta setup is covered in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Docs

- application code lives in `job_hunter_agent/`
- tests live in `tests/`

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- [docs/OPERATIONS.md](docs/OPERATIONS.md)
- [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md)
