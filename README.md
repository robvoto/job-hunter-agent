# Job Hunter Agent

Autonomous job discovery and decision system designed to reduce or eliminate manual job searching.

This system continuously discovers roles, evaluates them against a structured capability profile, and produces actionable outputs using a combination of deterministic filtering and optional LLM-based review.

The goal is not to scrape jobs — it is to model and automate the decision process a human would normally perform when searching, filtering, and assessing job opportunities.
## Current Focus

The reliable path is the direct-page scraper in [scraper_direct.py](scraper_direct.py). We do not use the old right-pane approach as the main workflow anymore.

## Project Layout

- `main.py`: thin local entry point for the direct scraper
- `admin_api.py`: local admin UI at `http://127.0.0.1:8765/admin`
- `data/`: local knowledge and runtime state
- `output/`: generated HTML, JSON, stats, and review data
- `legacy/`: older drafts and pane-based scraper code kept for reference
- `docs/`: project notes and operational guidance

## How The Data Model Works

- `data/profile.json`: the runtime profile used by the scraper, filters, and LLM
- `data/capability_profile.txt`: a local human-readable note that can be imported into the runtime profile
- admin UI: the ongoing editor for `data/profile.json`
- source CVs / STAR notes / application materials: local source documents that should feed the profile and later application generation

The intended model is: import a strong CV once, generate `profile.json`, then keep refining it from the admin UI.

## Local Commands

Install dependencies:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

Run the scraper:

```powershell
python main.py
```

Rebuild the dashboard from saved local state without scraping:

```powershell
python scraper_direct.py --rebuild-dashboard
```

Run the admin console:

```powershell
python admin_api.py
```

Open the local showcase/demo page:

- `http://127.0.0.1:8765/demo`

## Important Notes

- `data/profile.json` is the runtime source of truth used on every scrape.
- `data/capability_profile.txt` is the local human-readable candidate note used for imports.
- `data/capability_profile.template.txt` is the committed starter template for new users.
- `data/application_materials.template.json` is a starter manifest for local-only application inputs.
- the admin UI now includes a first-pass source-document importer that can build `profile.json` from local CV / STAR files.
- `TODO.txt`, `data/capability_profile.txt`, `data/profile.json`, `data/job_history.json`, and `data/llm_cache.json` are intended to stay local.
- `output/seek_results.html` is a persistent readable dashboard built from the latest scrape plus local keep history.
- `output/seek_results.json`, `output/seek_run_stats.json`, and `output/seek_review_data.json` are for debugging and tuning.
- If `OPENAI_API_KEY` is not set, the app runs without live LLM decisions and falls back to deterministic filtering plus `MAYBE`.

For more detail, see:

- [docs/OPERATIONS.md](docs/OPERATIONS.md)
- [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
- [SOUL.md](SOUL.md)
