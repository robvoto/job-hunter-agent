# job-hunter-agent

Local SEEK job scraper for Business Analyst-style roles, using deterministic filters first and optional LLM review second.

## Current Focus

The reliable path is the direct-page scraper in [scraper_direct.py](scraper_direct.py). We do not use the old right-pane approach as the main workflow anymore.

## Project Layout

- `main.py`: thin local entry point for the direct scraper
- `admin_api.py`: local admin UI at `http://127.0.0.1:8765/admin`
- `data/`: local knowledge and runtime state
- `output/`: generated HTML, JSON, stats, and review data
- `legacy/`: older drafts and pane-based scraper code kept for reference
- `docs/`: project notes and operational guidance

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

## Important Notes

- `data/profile.json` is the runtime source of truth used on every scrape.
- `data/capability_profile.txt` is the local human-readable candidate note used for imports.
- `data/capability_profile.template.txt` is the committed starter template for new users.
- `TODO.txt`, `data/capability_profile.txt`, `data/profile.json`, `data/job_history.json`, and `data/llm_cache.json` are intended to stay local.
- `output/seek_results.html` is a persistent readable dashboard built from the latest scrape plus local keep history.
- `output/seek_results.json`, `output/seek_run_stats.json`, and `output/seek_review_data.json` are for debugging and tuning.

For more detail on persistence, moving the project, and what gets regenerated, see [docs/OPERATIONS.md](docs/OPERATIONS.md).
