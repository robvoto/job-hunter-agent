# Operations Notes

## Source Of Truth

- `data/profile.json` is the machine-readable runtime profile.
- `data/capability_profile.txt` is the local human-readable candidate note.
- `data/capability_profile.template.txt` is the committed starter template.
- `data/application_inputs/` should hold local-only source documents if you use CV/application automation later.

The scraper and admin UI read `data/profile.json` on every run. The knowledge text file is not reparsed automatically every scrape; it is imported into the profile when you choose to do that from the admin console. The local note file should stay personal and untracked, while the template is safe to keep in the repo.

The intended long-term model is:

- source documents create or enrich `data/profile.json`
- admin edits and maintains `data/profile.json`
- scraper, filters, and LLM consume `data/profile.json`
- application outputs should be generated from that profile plus source documents, not maintained as separate competing runtime truth

There is now a first-pass source-document import path in the admin UI. It stores local source-document references in `data/application_materials.json` and can import `.docx`, `.md`, and `.txt` source files into `profile.json`.

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
- hidden jobs are reviewable and can be unhidden
- older archive items are hidden by default once they age past the current threshold
- filters support sort, scope, posted age, work mode, score, and pagination
- run stats and efficiency are tucked into a side panel

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
- `data/application_inputs/` if you add local CV or STAR source files
- `data/application_materials.json` if you create a local application-input manifest
- `TODO.txt`

## Moving The Project

The code now resolves important paths relative to the repo folder, not the shell's current working directory. That means starting `python main.py` or `python admin_api.py` from another folder should not create a second accidental `profile.json`.

If you move this project to another machine or another folder, bring these with it:

- `data/profile.json`
- `data/capability_profile.txt`
- optionally `data/job_history.json` if you want to keep seen/applied history
- optionally `data/llm_cache.json` if you want to keep cached LLM decisions
- optionally `data/application_inputs/` if you want your local source documents available for future application generation

## When Defaults Are Used

`data/profile.json` is only initialized from defaults if it does not exist. If the file is present, the project loads it and merges missing fields from the default profile.

## Admin Usage

Main UI:

- `Search` tab: what SEEK is asked for
- `Candidate Profile` tab: CV, fit model, and learned capabilities
- `Review` tab: applied/hidden controls and unknown skill decisions
- `Test` tab: latest run stats and rejected sample inspection

Think of the admin as the editor for the runtime profile, not the original home of your source documents.

For a new person, the desired onboarding path is:

1. import one detailed CV
2. build `data/profile.json`
3. review and refine the generated profile in admin
4. keep improving it over time with learning updates

Extra source files like STAR notes or long-form career history should enrich the profile and later application drafting, but not replace admin as the editing surface.

## LLM Runtime

The LLM is optional and only used after deterministic filters pass.

Current flow:

- title filters
- content filters
- optional LLM `KEEP` / `REJECT` / `MAYBE`

The LLM prompt reads from `data/profile.json`, especially:

- candidate summary
- strengths
- CV/background text
- capability rules
- important fit notes

If `OPENAI_API_KEY` is absent, the project runs with the LLM effectively disabled.

## Why This Matters

The project should be:

- deterministic first
- explainable
- cheap to run
- easy to debug

That is why the runtime profile and generated review artifacts are stored locally in plain files rather than hidden inside code.
