# Job Hunter Agent

Local-first job discovery and fit-evaluation system.

Deployment target:

- AWS EC2 with a small EBS-backed root volume
- production-style operation, not prototype-only handling
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

Do not duplicate setup or runtime commands in this README.

- For day-to-day use, follow [docs/USER_GUIDE.md](docs/USER_GUIDE.md).
- For setup, runtime execution, rebuild flows, flags, diagnostics, recovery, and validation commands, follow [docs/OPERATIONS.md](docs/OPERATIONS.md).

Search design note:

- keep search keywords broad enough to capture relevant roles
- use title rules, metadata gates, content filters, capability logic, and optional AI review to tighten fit afterward

## Architecture Note: Shell & Fragment

The workspace UI uses a decoupled pattern for performance and maintainability:
- **templates/workspace.html (the shell)**: The main entry point. It contains the navigation, branding, and JavaScript logic to poll for updates.
- **templates/results.html (the fragment)**: A template used by the server to render the actual job results.

When you load the workspace, the shell is served first, and the fragment is fetched and injected dynamically once the data is ready.

## Tech Stack

- **Core**: Python 3.12+
- **Automation**: Playwright (SEEK scraping)
- **Multi-Source**: `python-jobspy` (LinkedIn)
- **Intelligence**: OpenAI API (GPT-4o / GPT-4o-mini)
- **Parsing**: `python-docx` and `pandas`
- **UI**: FastAPI + uvicorn; HTML/JS templates under `templates/` and `static/` (routes in `job_hunter_agent/routes/`)
- **Environment**: `python-dotenv`

Logic and core modules reside in the `job_hunter_agent/` package.

## Important Files

- `job_hunter_agent/profile_store.py`
  Runtime profile persistence, defaults, and normalization.

- `job_hunter_agent/database.py`
  SQLite schema and runtime tables.

- `templates/workspace.html`
  Workspace shell.

- `templates/results.html`
  Workspace results fragment.

- `data/users/<user_id>/workspace_results.html`
  Per-user rendered workspace output.

- `data/config/global_settings.json`
  Committed global settings seed.

- `data/knowledge/ui_labels.json`
  Shared UI labels and copy.

## Local-Only State

These are intended to stay local and ignored:

- `.venv/`
- `data/users/`
- `data/runtime/`
- `output/`
- `debug/`

## Security

By default, the application is configured for local use on `localhost`. If you access the workspace over a network (e.g., binding to `0.0.0.0`), the system enforces `Secure` and `__Host-` prefixed session cookies. **This requires an HTTPS connection** (usually handled via a reverse proxy like Caddy or Nginx) for the session management to function.

## LLM Notes

Desktop v1 ignores `OPENAI_API_KEY` and any other global/provider key source. The rule is:

> No global keys. No shared learning. No upload without consent.

Live LLM review stays disabled until user-owned provider-key support is added.

## Daily Agent Notes

The first daily agent layer is now local-first:

- `job_hunter_agent.agent_runner` runs the current connector, rebuilds the workspace, and creates a compact digest
- email delivery uses the DB-backed user settings managed by `job_hunter_agent/user_settings.py`
- Telegram delivery uses the DB-backed user settings managed by `job_hunter_agent/user_settings.py`
- Telegram messages arrive in the user's private chat with their bot, not from their personal Telegram identity
- the digest is also written locally to `output/agent_last_summary.txt`

Recommended beta setup is covered in [docs/OPERATIONS.md](docs/OPERATIONS.md).

## Docs

- application code lives in `job_hunter_agent/`
- tests live in `tests/`

- [docs/INDEX.md](docs/INDEX.md)
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- [docs/OPERATIONS.md](docs/OPERATIONS.md)
- [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md)
