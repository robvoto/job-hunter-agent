# Operations Notes

## Runtime Source Of Truth

- `data/profile.json` is the machine-readable runtime profile
- `data/capability_profile.txt` is the human-readable local note
- `data/capability_profile.template.txt` is the committed starter template

Filtering, matching, admin editing, and LLM review all depend on `data/profile.json`.

## Profile Creation Model

The intended runtime model is:

1. source documents come in through onboarding
2. onboarding creates or enriches `data/profile.json`
3. admin refines `data/profile.json`
4. the job-source connector and LLM read `data/profile.json`

Current onboarding persists a local source pack under ignored paths and uses that to build the runtime profile.

## Current Source Connector

The current implemented job source is SEEK.

Important note:

- the product is broader than SEEK
- the current connector code lives in `scraper_direct.py` for historical reasons
- do not treat that filename as the intended long-term product naming model

## Local Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

## Main Commands

Run the current source connector:

```powershell
python run_jobs.py
```

Rebuild the dashboard from saved local state:

```powershell
python scraper_direct.py --rebuild-dashboard
```

Run the local UI:

```powershell
python admin_api.py
```

## Dashboard Model

`output/seek_results.html` is a persistent local shortlist.

It currently supports:

- fresh jobs from the latest run
- kept jobs from earlier runs
- hidden jobs with unhide review
- older kept jobs collapsed by default
- filtering, sorting, and pagination
- salary-target filtering tied to admin salary preferences
- local viewed/opened tracking

## Files That Can Be Rebuilt

- `output/seek_results.html`
- `output/seek_results.json`
- `output/seek_run_stats.json`
- `output/seek_review_data.json`

## Files That Should Usually Be Kept

- `data/profile.json`
- `data/job_history.json`
- `data/llm_cache.json`
- `data/capability_profile.txt`
- `data/application_inputs/`
- `data/application_materials.json`
- `TODO.txt`

## Moving The Project

The code resolves important paths relative to the repo, not the shell working directory.

If moving to another machine and you want to preserve local state, bring:

- `data/profile.json`
- `data/capability_profile.txt`
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
- strengths
- CV/background text
- capability rules
- fit notes

If `OPENAI_API_KEY` is missing, the app runs without live LLM review.

## Runner Split

- `python run_jobs.py`
  Refreshes jobs and rebuilds the dashboard.

- `python agent_runner.py`
  Wraps the refresh flow, builds a digest, and optionally sends notifications.
