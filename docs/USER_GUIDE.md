# User Guide

## What This App Does

This app helps a candidate build a profile once, review jobs against that profile, and keep a local shortlist that gets better over time.

Current live job source:

- SEEK

That is the current source connector, not the final limit of the product.

## First-Time Use

1. Start the local web UI:

```powershell
python admin_api.py
```

2. Open:

- `http://127.0.0.1:8765/start`

3. Upload:

- one strong detailed CV
- optionally extra notes in plain English

4. Click `Create Profile`

5. Then open admin:

- `http://127.0.0.1:8765/admin`

The app will create or enrich `data/profile.json`, which becomes your working profile for job matching.

## What Onboarding Creates

The onboarding flow creates a runtime profile from your source documents.

That profile includes:

- candidate summary
- strengths
- CV/background text
- capability rules
- fit notes

You can then refine those fields from admin.

## What The Admin Is For

Use the admin UI to maintain the runtime profile and review controls.

Tabs:

- `Search`: controls the current job-source query
- `Candidate Profile`: profile summary, strengths, background text, fit notes, and rules
- `Review`: hidden jobs, applied jobs, and skill-review decisions
- `Test`: latest run stats and rejected samples

Think of admin as the maintenance surface for your profile, not the place where you upload raw source files every time.

## What The Main Profile Fields Mean

`Candidate summary`

- the short top-level positioning statement
- created from onboarding, then edited over time

`Strengths`

- important things the app should emphasize when evaluating fit
- initially created from imported source material
- can be refined later as you learn what should stand out

`CV / background text`

- the larger background context used for matching and LLM review
- this should reflect what you uploaded during onboarding
- you can edit it, but it should stay consistent with your real experience

`Important fit notes`

- high-signal rules or context
- for example domain preferences, known gaps, role boundaries, and honest exclusions
- starts from imported material and can be refined later

`Minimum annual salary` / `Minimum daily rate`

- optional salary targets used as light fit signals
- if a role lists pay, the dashboard can show whether it meets your target
- these targets also power the salary filter in the dashboard

## Running A Job Review

Run the current source connector:

```powershell
python scraper_direct.py
```

Then open the dashboard at:

- `http://127.0.0.1:8765/dashboard`

The dashboard groups jobs into:

- `Fresh Matches`
- `Kept From Earlier Runs`
- `Hidden Jobs`
- `Older Kept Jobs`

The dashboard can filter by:

- match score
- posted age
- work mode
- salary state

## LLM Use

The LLM is optional.

Current behavior:

- deterministic filters run first
- only surviving job descriptions reach the LLM
- the LLM reads from `data/profile.json`
- it returns only `KEEP`, `REJECT`, or `MAYBE`

If `OPENAI_API_KEY` is not set, the app runs without live LLM review.

## Which Command Does What

`python scraper_direct.py`

- refreshes jobs
- rebuilds the dashboard
- updates local run outputs

`python agent_runner.py`

- runs the refresh flow and then creates a digest
- can also send that digest by email or Telegram if configured

Simple rule:

- if you just want fresh jobs, run `python scraper_direct.py`
- if you want automation and notifications, use `python agent_runner.py`

## Local Files To Keep

- `data/profile.json`
- `data/capability_profile.txt`
- `data/job_history.json`
- `data/llm_cache.json`
- `TODO.txt`

These are also local-only if used:

- `data/application_inputs/`
- `data/application_materials.json`
- `.venv/`
