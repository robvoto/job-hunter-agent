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
- **workspace.html (The Shell)**: The main entry point. It contains the navigation, branding, and JavaScript logic to poll for updates.
- **results.html (The Fragment)**: A template used by the server to render the actual job results.

When you load the workspace, the Shell is served first, and the Fragment is fetched and injected dynamically once the data is ready.

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

- `data/profile.json`
  Runtime source of truth for matching.
 
- `data/agent_settings.template.json`
  Starter template for daily-agent scheduling and notification delivery.

- `output/workspace.html`
  Persistent shortlist workspace from the latest run plus local history.

- `output/audit_records.json`
- `output/run_stats.json`
- `output/review_data.json`
  Debugging and tuning outputs.

## Local-Only State

These are intended to stay local and ignored:

- `.venv/`
- `TODO.txt`
- `data/profile.json`
- `data/job_history.json`
- `data/llm_cache.json` 
- `data/agent_settings.json`
- `data/agent_state.json`
- `data/llm_costs.jsonl`
- `output/rejection_rules.json`
- `output/`

## Security

By default, the application is configured for local use on `localhost`. If you access the workspace over a network (e.g., binding to `0.0.0.0`), the system enforces `Secure` and `__Host-` prefixed session cookies. **This requires an HTTPS connection** (usually handled via a reverse proxy like Caddy or Nginx) for the session management to function.

## LLM Notes

The app uses `python-dotenv` to load environment variables. To use the LLM:

1. Create a `.env` file in the root directory.
2. Add your key: `OPENAI_API_KEY=sk-your-key-here`
3. Ensure the dependency is installed: `pip install python-dotenv`.

If the key is not set, the app still works, but the live LLM review step is effectively disabled and falls back to deterministic filtering plus `MAYBE`.

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
