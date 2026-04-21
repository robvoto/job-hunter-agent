# User Guide

## What This App Does

This app helps a candidate build a profile once, review jobs against that profile, and keep a local shortlist that gets better over time.

Current live job source:

- SEEK
- LinkedIn

That is the current source connector, not the final limit of the product.

## First-Time Use

1. Start the local web UI:

```powershell
python -m job_hunter_agent.local_server
```

2. Open:

- `http://127.0.0.1:8765/start`

3. Upload:

- one strong detailed CV (supports .docx and plain text)
- optionally extra notes in plain English

4. Click `Create Profile`

5. Then open settings:

- `http://127.0.0.1:8765/settings`

The app will create or enrich `data/profile.json`, which becomes your working profile for job matching.

## What Onboarding Creates

The onboarding flow creates a runtime profile from your source documents.

That profile includes:

- candidate summary
- fit brief
- CV/background text
- evidence tiers
- capability rules
- title targeting hints

You can then refine those fields from the settings UI.

## What Settings Is For

Use the settings UI to maintain the runtime profile and review controls.

Tabs:

- `Search`: controls the current job-source query
- `Candidate Profile`: profile summary, fit brief, evidence text, search preferences, and rules
- `Review`: hidden jobs, applied jobs, and skill-review decisions
- `Test`: latest run stats and rejected samples

Think of settings as the maintenance surface for your profile, not the place where you upload raw source files every time.

## What The Main Profile Fields Mean

`Candidate summary`

- the short top-level positioning statement
- created from onboarding, then edited over time

`Fit brief`

- the short machine-facing positioning brief used by the LLM prompt
- can be generated automatically from profile rules or edited manually

`CV / background text`

- the larger background context used for matching and LLM review
- this should reflect what you uploaded during onboarding
- you can edit it, but it should stay consistent with your real experience

`Evidence tiers`

- primary, secondary, and background evidence blocks used for matching and LLM review
- lets the profile weight recent direct evidence above older or optional context

`Capability rules`

- structured capability names with level, fit, and aliases
- used by deterministic filtering and the LLM prompt

`Title targeting`

- target and adjacent title patterns plus search keywords
- used to keep role targeting configurable per candidate instead of hardcoded in code

`Minimum annual salary` / `Minimum daily rate`

- optional salary targets used as light fit signals
- if a role lists pay, the dashboard can show whether it meets your target
- these targets also power the salary filter in the dashboard

## Running A Job Review

Run the current source connector:

```powershell
python -m job_hunter_agent.source_connector
```

Then open the dashboard at:

- `http://127.0.0.1:8765/dashboard`

## Match Score Bands

The dashboard groups jobs by their calculated fit score:

- **Strong match** (80-100): High alignment with core capabilities and experience.
- **Good match** (65-79): Solid alignment, perhaps missing secondary criteria.
- **Worth a look** (50-64): Borderline fit or adjacent role.
- **Stretch** (0-49): Low alignment or significant requirement gaps.

The dashboard groups jobs into:

- `Potential Jobs`
- `Applied`
- `Hidden`

The dashboard can filter by:

- match score
- posted age
- work mode
- salary state

## LLM Use

The LLM is optional and requires an OpenAI API key.

Current behavior:

- deterministic filters run first
- only surviving job descriptions reach the LLM
- the LLM reads from `data/profile.json`
- it returns only `KEEP`, `REJECT`, or `MAYBE`

To enable:
1. Create a `.env` file in the project root.
2. Add `OPENAI_API_KEY=sk-your-actual-key`

If the variable is not found in the environment or the `.env` file, the app runs without live LLM review.

## Testing

Install development dependencies:

```powershell
pip install -r requirements-dev.txt
```

Run the local test suite:

```powershell
python -m job_hunter_agent.test_runner
```

## Which Command Does What

`python -m job_hunter_agent.source_connector`

- refreshes jobs
- rebuilds the dashboard
- updates local run outputs

`python -m job_hunter_agent.source_connector --rebuild-dashboard`

- rebuilds the dashboard from saved local state only
- useful when UI behavior changed and you want the latest HTML without a fresh scrape

`python -m job_hunter_agent.source_connector --wide-scrape`

- runs a wider scrape to catch borderline matches
- widens both SEEK and LinkedIn source windows
- lowers the shortlist threshold

Important:

- some specialist-domain requirements can now hard-block a role entirely
- if a source page comes back as a challenge or invalid detail page, the app rejects it instead of scoring it from bad text

`python -m job_hunter_agent.source_connector --rebuild-dashboard --test-dashboard-mode`

- rebuilds the dashboard in test view only
- does not run a fresh scrape

`python -m job_hunter_agent.source_connector --show-scores`

- shows raw score numbers (e.g. 72/100) directly on cards
- expands the fit breakdown section showing exactly how points were added/subtracted

`python -m job_hunter_agent.source_connector --max-pages 1`

- limits the scraper to checking only the first page of results per location
- overrides the maximum pages setting in your profile temporarily
- highly recommended for testing new filters quickly without doing a full run

`python -m job_hunter_agent.agent_runner`

- runs the refresh flow and then creates a digest
- can also send that digest by email or Telegram if configured

Simple rule:

- if you just want fresh jobs, run `python -m job_hunter_agent.source_connector`
- if you want automation and notifications, use `python -m job_hunter_agent.agent_runner`

## Local Files To Keep

- `data/profile.json`
- `data/job_history.json`
- `data/llm_cache.json`
- `TODO.txt`

These are also local-only if used:

- `data/application_inputs/`
- `data/application_materials.json`
- `.venv/`
