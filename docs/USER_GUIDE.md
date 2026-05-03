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

Test/debug mode:

```powershell
python -m job_hunter_agent.local_server --debug-mode
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

- structured capability names with strength and aliases
- used by deterministic filtering and the LLM prompt

`Title targeting`

- target and secondary title patterns plus search keywords
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

- **Strong match** (85-100): High alignment with core capabilities and experience.
- **Good match** (70-84): Solid alignment, perhaps missing secondary criteria.
- **Possible fit** (55-69): Plausible fit worth reviewing.
- **Stretch** (0-54): Low alignment or significant requirement gaps.

The dashboard groups jobs into:

- `Potential Jobs`
- `Applied`
- `Hidden`

The dashboard can filter by:

- match score
- posted age
- work mode
- salary state

## Improving Accuracy (Rejection Learning)

If the agent keeps suggesting roles with a specific requirement you don't have (e.g., a specific security clearance or software tool), use the **Not For Me** button on the job card.

- It will prompt you to select the "mandatory blockers" found in that job description.
- Once saved, the agent learns to automatically reject future roles that list those terms as mandatory requirements.
- You can review and delete these rules in the **Settings > Review** tab.

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

Use Settings to widen source coverage instead.

- raise `How far back to search` for SEEK if you want a broader SEEK pass
- raise `How far back to search (hours)` for LinkedIn if you want a broader LinkedIn pass
- lower `Dashboard results minimum score` if you want more borderline roles to stay visible

Important:

- some specialist-domain requirements can now hard-block a role entirely
- if a source page comes back as a challenge or invalid detail page, the app rejects it instead of scoring it from bad text

`python -m job_hunter_agent.source_connector --rebuild-dashboard

- does not run a fresh scrape

`python -m job_hunter_agent.source_connector --rebuild-dashboard --debug-dashboard`

- rebuilds the dashboard from saved local state only
- shows expanded score/debug details and borderline roles
- shows raw score numbers (e.g. 72/100) directly on cards
- does not run a fresh scrape or AI review

`python -m job_hunter_agent.source_connector --reset-new-to-you`

- resets the 'Viewed' status for all jobs so they appear as "New To You"
- useful for testing how roles evaluate visually

- expands the fit breakdown section showing exactly how points were added/subtracted

Set `SEEK -> Max pages to check` in Settings.

- saved in your profile and used by both manual and scheduled runs
- clamped server-side to 1..10 even if someone sends a larger value manually
- use `1` there when you want a fast SEEK test run

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
 
- `.venv/`
