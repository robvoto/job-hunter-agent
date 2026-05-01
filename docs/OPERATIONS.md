# Operations Notes

## Runtime Source Of Truth

Filtering, matching, settings editing, and LLM review all depend on `data/profile.json`.

## Profile Creation Model

The intended runtime model is:

1. source documents come in through onboarding
2. onboarding creates or enriches `data/profile.json`
3. settings refines `data/profile.json`
4. the job-source connector and LLM read `data/profile.json`

Current onboarding persists a local source pack under ignored paths and uses that to build the runtime profile.

## Current Source Connector

Current implemented job sources are SEEK and LinkedIn.

Important note:

- the product is broader than SEEK
- the current connector implementation lives in `job_hunter_agent/source_connector.py`

## Local Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m playwright install chromium
```

## Main Commands

Run the current source connector:

```powershell
python -m job_hunter_agent.source_connector
```

Rebuild the dashboard from saved local state:

```powershell
python -m job_hunter_agent.source_connector --rebuild-dashboard
```

Run the local UI:

```powershell
python -m job_hunter_agent.local_server

# test/debug mode
python -m job_hunter_agent.local_server --test-mode
```

## Dashboard Model

`output/dashboard.html` is a persistent local shortlist.

It currently supports:

- fresh jobs from the latest run
- kept jobs from earlier runs
- hidden jobs with unhide review
- older kept jobs collapsed by default
- filtering, sorting, and pagination
- salary-target filtering tied to settings salary preferences
- local viewed/opened tracking

## Files That Can Be Rebuilt

- `output/dashboard.html`
- `output/audit_records.json`
- `output/run_stats.json`
- `output/review_data.json`

## Files That Should Usually Be Kept

- `data/profile.json`
- `data/job_history.json`
- `data/llm_cache.json`
- `data/application_inputs/`
- `data/agent_settings.json`
- `data/agent_state.json`
- `data/llm_costs.json`
- `data/application_materials.json`
- `TODO.txt`

## Moving The Project

The code resolves important paths relative to the repo, not the shell working directory.

If moving to another machine and you want to preserve local state, bring:

- `data/profile.json`
- optionally `data/job_history.json`
- optionally `data/llm_cache.json`
- optionally `data/application_inputs/`
- optionally `data/application_materials.json`

## LLM Runtime

The LLM is optional and constrained.

Current flow:

- title filtering
- content filtering
- optional LLM `KEEP` / `REJECT` / `MAYBE`

The prompt reads from `data/profile.json`, especially:

- candidate summary
- candidate fit brief
- CV/background text
- capability rules
- evidence tiers
- match preferences

If `OPENAI_API_KEY` is missing, the app runs without live LLM review.

## Testing

Use the repo test runner after changes:

```powershell
python -m job_hunter_agent.test_runner
```

## Runner Split

- `python -m job_hunter_agent.source_connector`
  Canonical direct run for refreshing jobs and rebuilding the dashboard.

- `python -m job_hunter_agent.agent_runner`
  Wraps the refresh flow, builds a digest, and optionally sends notifications.
