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
pip install -r requirements.txt
```

Run the scraper:

```powershell
python main.py
```

Run the admin console:

```powershell
python admin_api.py
```

## Important Notes

- `data/profile.json` is the runtime source of truth used on every scrape.
- `data/rob_capability_profile.txt` is the human-readable master note you can import from admin.
- `output/seek_results.html` is the readable shortlist.
- `output/seek_results.json`, `output/seek_run_stats.json`, and `output/seek_review_data.json` are for debugging and tuning.

For more detail on persistence, moving the project, and what gets regenerated, see [docs/OPERATIONS.md](docs/OPERATIONS.md).
