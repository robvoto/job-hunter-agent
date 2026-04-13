# User Guide

## What This App Does

This project is a local-first SEEK job finder for Business Analyst-style roles.

It helps you:

- scrape fresh jobs from SEEK
- filter out obvious bad fits
- keep a persistent shortlist locally
- remember jobs you already liked, hid, or applied for
- maintain a candidate profile that improves matching over time

## The Simple Mental Model

Think of the system in three layers:

1. Your source documents
   Your detailed CV and any extra notes, achievements, or STAR examples.

2. Your runtime profile
   `data/profile.json` is the machine-readable version of your profile that the app uses on every scrape.

3. Your dashboard and outputs
   The HTML dashboard, run stats, and later application drafts.

The admin page exists to edit layer 2.

## First-Time Setup

Create the local environment:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

## Running The App

Run a scrape:

```powershell
python main.py
```

Rebuild the dashboard without scraping:

```powershell
python scraper_direct.py --rebuild-dashboard
```

Run the admin console:

```powershell
python admin_api.py
```

Then open:

- `http://127.0.0.1:8765/admin`
- `http://127.0.0.1:8765/demo`

## What The Admin Is For

Use the admin page to maintain your runtime profile and review controls.

Tabs:

- `Search`: keywords, locations, classifications, date window, sort order
- `Candidate Profile`: summary, strengths, CV/background text, fit notes, rules
- `Review`: hidden jobs, applied jobs, and unknown-skill decisions
- `Test`: latest run stats and rejected sample review

Inside `Candidate Profile`, the `Source Documents` panel is now the first-pass import path for local CV and STAR files.

Important point:

- the admin should be the ongoing editor for your profile
- it is not meant to replace your original source documents

## How Profile Data Should Work

For a new user, the intended flow is:

1. Start with one strong detailed CV
2. Import it into the app
3. Let the app generate `data/profile.json`
4. Refine that profile from the admin page over time

Optional later inputs:

- a long-form career history document
- STAR examples
- writing preferences for cover letters or selection criteria

These richer files should improve the profile and later application drafting, but they should not become competing runtime systems.

## LLM Usage

The LLM is optional.

Current behavior:

- deterministic filters run first
- only surviving job descriptions go to the LLM
- the LLM reads your runtime profile from `data/profile.json`
- it returns only `KEEP`, `REJECT`, or `MAYBE`
- decisions are cached in `data/llm_cache.json`

If `OPENAI_API_KEY` is not set, the app treats the LLM as disabled.

## Local Files You Should Keep

These files are valuable local state:

- `data/profile.json`
- `data/capability_profile.txt`
- `data/job_history.json`
- `data/llm_cache.json`
- `TODO.txt`

These are also local-only if you use them:

- `data/application_inputs/`
- `data/application_materials.json`
- `.venv/`

## Dashboard Meaning

The dashboard is a persistent local shortlist.

It shows:

- fresh matches from the latest run
- saved jobs from earlier runs
- hidden jobs you can unhide
- older saved jobs in a collapsed section

It also tracks whether you opened a job, but that is only a light ranking hint, not a hard rule.

## What Is Coming Next

Planned next step:

- import source documents cleanly into `profile.json`

Planned later step:

- `Prepare Application` packs with tailored CVs, cover letters, and supporting notes per job
