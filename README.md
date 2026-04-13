# Job Hunter Agent

Local-first job discovery and fit-evaluation system.

The product goal is simple: a user gives the app strong source material about their experience, the app builds a working profile, reviews jobs against that profile, and keeps a meaningful shortlist instead of forcing the user to search manually every day.

Current implemented job source:

- SEEK

The architecture is intentionally broader than a single site. SEEK is the current source connector, not the long-term boundary of the product.

## What Works Now

- guided onboarding at `http://127.0.0.1:8765/start`
- local admin console at `http://127.0.0.1:8765/admin`
- persistent local profile in `data/profile.json`
- deterministic filtering before any LLM review
- optional constrained LLM decision step
- persistent dashboard with fresh, saved, and hidden jobs
- local review tracking for opened, hidden, and applied roles

## Product Model

The system has three main layers:

1. Source documents
   A detailed CV, plus optional extra background or evidence.

2. Runtime profile
   `data/profile.json` is the machine-readable profile used by filtering, matching, and LLM review.

3. Dashboard and outputs
   HTML shortlist, run stats, review data, and later application packs.

The admin UI edits layer 2. The onboarding flow creates layer 2 from layer 1.

## Local Commands

Set up the environment:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

Run the job-source connector:

```powershell
python main.py
```

Rebuild the dashboard from saved local state:

```powershell
python scraper_direct.py --rebuild-dashboard
```

Run the local web UI:

```powershell
python admin_api.py
```

Then open:

- onboarding: `http://127.0.0.1:8765/start`
- admin: `http://127.0.0.1:8765/admin`
- demo/showcase: `http://127.0.0.1:8765/demo`

## Important Files

- `data/profile.json`
  Runtime source of truth for matching.

- `data/capability_profile.txt`
  Local human-readable note file used for imports and updates.

- `data/application_materials.template.json`
  Example local-only source-material manifest.

- `output/seek_results.html`
  Persistent shortlist dashboard generated from the latest run plus local history.

- `output/seek_results.json`
- `output/seek_run_stats.json`
- `output/seek_review_data.json`
  Debugging and tuning outputs.

## Local-Only State

These are intended to stay local and ignored:

- `.venv/`
- `TODO.txt`
- `data/profile.json`
- `data/capability_profile.txt`
- `data/job_history.json`
- `data/llm_cache.json`
- `data/application_inputs/`
- `data/application_materials.json`
- `output/`

## LLM Notes

If `OPENAI_API_KEY` is not set, the app still works, but the live LLM review step is effectively disabled and falls back to deterministic filtering plus `MAYBE`.

## Docs

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- [docs/OPERATIONS.md](docs/OPERATIONS.md)
- [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)
- [SOUL.md](SOUL.md)
