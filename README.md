# Job Hunter Agent

Local-first job discovery and fit-evaluation system.

The product goal is simple: a user gives the app strong source material about their experience, the app builds a working profile, reviews jobs against that profile, and keeps a meaningful shortlist instead of forcing the user to search manually every day.

Current implemented job sources:

- SEEK
- LinkedIn

The architecture is intentionally broader than a single site. SEEK is the current source connector, not the long-term boundary of the product.

## What Works Now

- guided onboarding at `http://127.0.0.1:8765/start` (supports `.docx` and plain text)
- local settings console at `http://127.0.0.1:8765/settings`
- local dashboard at `http://127.0.0.1:8765/dashboard`

## Quick Start
Detailed instructions are in the User Guide and Operations.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Run a fresh job collection and rebuild the dashboard:

```powershell
python -m job_hunter_agent.source_connector
```

Useful flags:

- `--no-llm` to stay deterministic and avoid live LLM review
- `--cheap-llm` to force the cheaper review model
- `--debug` to show extra dashboard scoring detail

Search design note:

- keep search keywords broad enough to capture relevant roles
- use title rules, metadata gates, content filters, capability logic, and optional AI review to tighten fit afterward

Rebuild the dashboard from saved local state only:

```powershell
python -m job_hunter_agent.source_connector --rebuild-dashboard
```

Useful flags:
  
Run the local web UI:

```powershell
python -m job_hunter_agent.fastapi_app
```

Optional local web UI test mode:

```powershell
python -m job_hunter_agent.fastapi_app --debug
```

Run the daily local agent once:

```powershell
python -m job_hunter_agent.agent_runner
```

This is the orchestration layer. It can run the connector, rebuild the dashboard, create a digest, and send notifications.

Most users should think of it like this:

- `python -m job_hunter_agent.source_connector` = canonical refresh command
- `python -m job_hunter_agent.agent_runner` = optional automation wrapper around the refresh flow

Useful daily-agent flags:

-- `--send-notification-no-scrape` to rebuild/send from current local state only
- `--no-notify` to build the digest without email or Telegram delivery

Run the daily local agent in loop mode:

```powershell
python -m job_hunter_agent.agent_runner --loop
```

Run the automated test suite:

```powershell
python -m job_hunter_agent.test_runner
```

You can pass normal pytest selectors through the runner, for example:

```powershell
python -m job_hunter_agent.test_runner -k profile_learning -v
```

Then open:

- onboarding: `http://127.0.0.1:8765/start`
- settings: `http://127.0.0.1:8765/settings`
- dashboard: `http://127.0.0.1:8765/dashboard`
- demo/showcase: `http://127.0.0.1:8765/demo`

## Tech Stack

- **Core**: Python 3.11+
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

- `output/dashboard.html`
  Persistent shortlist dashboard from the latest run plus local history.

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

By default, the application is configured for local use on `localhost`. If you access the dashboard over a network (e.g., binding to `0.0.0.0`), the system enforces `Secure` and `__Host-` prefixed session cookies. **This requires an HTTPS connection** (usually handled via a reverse proxy like Caddy or Nginx) for the session management to function.

## LLM Notes

The app uses `python-dotenv` to load environment variables. To use the LLM:

1. Create a `.env` file in the root directory.
2. Add your key: `OPENAI_API_KEY=sk-your-key-here`
3. Ensure the dependency is installed: `pip install python-dotenv`.

If the key is not set, the app still works, but the live LLM review step is effectively disabled and falls back to deterministic filtering plus `MAYBE`.

## Daily Agent Notes

The first daily agent layer is now local-first:

- `job_hunter_agent.agent_runner` runs the current connector, rebuilds the dashboard, and creates a compact digest
- email delivery uses SMTP settings from local `data/agent_settings.json`
- Telegram delivery uses a bot token plus chat id from local `data/agent_settings.json`
- Telegram messages arrive in the user's private chat with their bot, not from their personal Telegram identity
- the digest is also written locally to `output/agent_last_summary.txt`

Recommended beta setup:

1. Copy `data/agent_settings.template.json` to local `data/agent_settings.json`
2. Fill in email and/or Telegram settings
3. Test with `python -m job_hunter_agent.agent_runner --no-notify`
4. If the summary looks right, test live delivery with `python -m job_hunter_agent.agent_runner`
5. Use Windows Task Scheduler for the real daily schedule

## Docs

- application code lives in `job_hunter_agent/`
- tests live in `tests/`

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- [docs/OPERATIONS.md](docs/OPERATIONS.md)
- [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/PRINCIPLES.md](docs/PRINCIPLES.md)
