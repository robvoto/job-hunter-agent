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
python -m job_hunter_agent.local_server --debug-mode
```


## JOB HUNTER AGENT - QUICK RUN COMMANDS
===================================== 


TESTS
=====

Run all tests:
  .\.venv\Scripts\python.exe -m pytest

Run focused checks:
  .\.venv\Scripts\python.exe -m pytest tests/test_cv_pipeline.py tests/test_profile_learning_parser.py tests/test_title_extraction.py tests/test_source_documents.py

To avoid spending credits on test runs, run them locally from:
  E:\Programming\job-hunter-agent

If you want me not to run tests at all, say:
  don't run tests; I'll verify locally.


PRIMARY COMMANDS
================

Normal manual refresh:
  python -m job_hunter_agent.source_connector

What it does:
  Scrapes fresh jobs using your profile settings, reviews them, saves the run,
  and rebuilds the dashboard.

Useful flags:
  python -m job_hunter_agent.source_connector --no-llm
  python -m job_hunter_agent.source_connector --cheap-llm
  python -m job_hunter_agent.source_connector --debug-mode
  

Automated agent run:
  python -m job_hunter_agent.agent_runner

What it does:
  Runs the full agent pipeline: refresh jobs, create a digest, and send
  notifications.

Useful flags:
  python -m job_hunter_agent.agent_runner --skip-collection
  python -m job_hunter_agent.agent_runner --no-notify


Local web server:
  python -m job_hunter_agent.local_server

What it does:
  Starts the browser UI.

Test mode:
  python -m job_hunter_agent.local_server --debug-mode

Open:
  Onboarding: http://127.0.0.1:8765/start
  Settings:  http://127.0.0.1:8765/settings
  Dashboard: http://127.0.0.1:8765/dashboard


SOURCE CONNECTOR FLAGS
======================

Use these with:
  python -m job_hunter_agent.source_connector


--no-llm
--------

What it does:
  Disables live LLM review for the current scrape and keeps the run
  deterministic.

Use when:
  You want to avoid API use or isolate deterministic filtering behaviour.

Example:
  python -m job_hunter_agent.source_connector --no-llm


--rebuild-dashboard
-------------------

What it does:
  Rebuilds output/dashboard.html from the last saved run. It does not scrape
  job sites and does not run AI review.

Use when:
  You changed dashboard UI/code and want to see the result quickly.

Example:
  python -m job_hunter_agent.source_connector --rebuild-dashboard


--cheap-llm
-----------

What it does:
  Forces the use of the cheaper gpt-4o-mini model while reviewing jobs.

Use when:
  You want to save costs on API usage, especially during larger scrapes.

Example:
  python -m job_hunter_agent.source_connector --cheap-llm


--reset-new-to-you
------------------

What it does:
  Makes jobs appear unread/new-to-you again in the generated dashboard.

Use when:
  You want to re-check the current saved jobs as if this is your first look.

Example:
  python -m job_hunter_agent.source_connector --rebuild-dashboard --reset-new-to-you


--no-llm
--------

What it does:
  Skips the AI fit review step, even if an API key is configured.

Use when:
  You only want to test deterministic scraping, title filters, exclusions, and
  dashboard generation.

Example:
  python -m job_hunter_agent.source_connector --no-llm


AGENT RUNNER FLAGS
==================

Use these with:
  python -m job_hunter_agent.agent_runner


--loop
------

What it does:
  Keeps the agent running and triggers once per day at the configured local time.

Example:
  python -m job_hunter_agent.agent_runner --loop


--skip-collection
-----------------

What it does:
  Does not fetch new jobs. It rebuilds the dashboard and sends a digest from
  current local state.

Example:
  python -m job_hunter_agent.agent_runner --skip-collection


--no-notify
-----------

What it does:
  Builds the digest without sending email or Telegram notifications.

Example:
  python -m job_hunter_agent.agent_runner --no-notify


QUICK WORKFLOWS
===============

Fast UI/dashboard check, no scrape:
  python -m job_hunter_agent.source_connector --rebuild-dashboard

Fresh cheaper AI model:
  python -m job_hunter_agent.source_connector --cheap-llm

Fresh smaller SEEK scrape:
  Set SEEK "Max pages to check" to 1 in Settings, then run:
  python -m job_hunter_agent.source_connector


QUICK NOTES
===========

- If the right panel says "Debug mode ON", you are looking at a debug-mode dashboard.
- Run `python -m job_hunter_agent.source_connector` to get back to a normal dashboard.
- Console logs show whether dashboard debug mode, cheap LLM mode, or LLM disablement are active.
- If you save profile changes in settings, the next scrape will use them.
- If settings save feedback does not look right, restart the local server with `python -m job_hunter_agent.local_server`.

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
- `data/agent_settings.json`
- `data/agent_state.json`
- `data/llm_costs.jsonl` 
- `TODO.txt`

## Moving The Project

The code resolves important paths relative to the repo, not the shell working directory.

If moving to another machine and you want to preserve local state, bring:

- `data/profile.json`
- optionally `data/job_history.json`
- optionally `data/llm_cache.json` 

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
