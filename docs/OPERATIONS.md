# Operations Notes

## Source Of Truth

- `data/profile.json` is the machine-readable runtime profile.
- `data/capability_profile.txt` is the local human-readable candidate note.
- `data/capability_profile.template.txt` is the committed starter template.

The scraper and admin UI read `data/profile.json` on every run. The knowledge text file is not reparsed automatically every scrape; it is imported into the profile when you choose to do that from the admin console. The local note file should stay personal and untracked, while the template is safe to keep in the repo.

## Local Setup

Recommended Windows setup:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

Use `.venv\Scripts\python.exe` when you want to be explicit about running inside the project environment.

## Dashboard Model

`output/seek_results.html` is now a persistent local dashboard:

- kept jobs from the latest run stay at the top
- previously kept jobs remain in a local archive
- older archive items are hidden by default once they age past the current threshold

If you want to rebuild the dashboard from saved local data without doing a new scrape, run:

```powershell
python scraper_direct.py --rebuild-dashboard
```

## What Gets Regenerated

These files are safe to regenerate:

- `output/seek_results.html`
- `output/seek_results.json`
- `output/seek_run_stats.json`
- `output/seek_review_data.json`

These are local runtime state files and should normally be kept:

- `data/profile.json`
- `data/job_history.json`
- `data/llm_cache.json`
- `data/capability_profile.txt`
- `TODO.txt`

## Moving The Project

The code now resolves important paths relative to the repo folder, not the shell's current working directory. That means starting `python main.py` or `python admin_api.py` from another folder should not create a second accidental `profile.json`.

If you move this project to another machine or another folder, bring these with it:

- `data/profile.json`
- `data/capability_profile.txt`
- optionally `data/job_history.json` if you want to keep seen/applied history
- optionally `data/llm_cache.json` if you want to keep cached LLM decisions

## When Defaults Are Used

`data/profile.json` is only initialized from defaults if it does not exist. If the file is present, the project loads it and merges missing fields from the default profile.

## Admin Usage

Main UI:

- `Search` tab: what SEEK is asked for
- `Candidate Profile` tab: CV, fit model, and learned capabilities
- `Review` tab: applied/hidden controls and unknown skill decisions
- `Test` tab: latest run stats and rejected sample inspection

## Why This Matters

The project should be:

- deterministic first
- explainable
- cheap to run
- easy to debug

That is why the runtime profile and generated review artifacts are stored locally in plain files rather than hidden inside code.
