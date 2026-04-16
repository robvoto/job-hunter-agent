# SOUL.md - Job Hunter Agent

> This file is the project source of truth for AI assistants working in this repo.
> Keep it updated as the project evolves. Last updated: April 2026.
> Repo target name: `job-hunter-agent`
> Repo URL: https://github.com/robvoto/job-hunter-agent

---

## What this project is

A local-first job-hunting system focused on finding strong-fit Business Analyst roles with as little noise as possible.

Near-term goal:
- reliably scrape and filter BA roles
- learn the candidate profile over time
- produce a clean shortlist with clear reject reasons

Long-term goal:
- become a true autonomous job agent that runs daily and sends only meaningful matches

This project exists to solve a real job-search problem while also becoming a practical agent/automation learning project.

---

## Current stage

### Stage 2 underway

The project is past the initial prototype stage.

### What works now

- SEEK scraping uses the direct-page approach in `source_connector.py`
- deterministic filtering happens before any LLM call
- LLM fallback is constrained to `KEEP`, `REJECT`, or `MAYBE`
- search settings are configurable from the local admin UI
- search supports date window, sort by newest, locations, and classification filters
- runtime profile is persisted in `data/profile.json`
- human-editable candidate note lives in local `data/capability_profile.txt`
- repo-safe starter content lives in `data/capability_profile.template.txt`
- source documents can now be imported into `data/profile.json` from the admin UI
- dashboard is now persistent and rebuilds from the latest scrape plus local job history
- dashboard supports hidden-job review, kept-earlier archive, match filters, salary-target filtering, and pagination
- viewed/opened jobs are tracked locally when the admin API is available
- unknown-skill review exists in admin so the system can learn from repeated concepts in job descriptions
- applied and hidden jobs can be recorded from the review workflow
- outputs are written to `output/` as HTML, JSON, run stats, and review data
- history and cache are persisted locally
- first daily agent runner now exists with email and Telegram notifier hooks

### What is still incomplete

- this is not yet a true agent
- no WhatsApp delivery yet
- no LinkedIn scraper yet
- no authenticated SEEK session reuse yet
- no durable cloud persistence yet
- filtering still needs ongoing tuning to reduce false positives and false rejects
- source-document import now exists as a first pass and still needs tuning for richer extraction quality
- no application-pack workflow yet for tailored CVs, cover letters, and criteria responses

---

## Current product model

This project has now settled into a clearer shape:

- source documents are the human truth
- `data/profile.json` is the runtime machine truth
- admin is the editor and maintenance surface for that runtime truth
- generated application outputs should be derived from source documents and profile data, not treated as primary sources

For a real user, the intended flow is:

1. import one strong detailed CV
2. optionally import richer evidence such as STAR notes or long-form experience
3. generate a distilled runtime profile in `data/profile.json`
4. let the user maintain and refine that profile from the admin UI
5. use that runtime profile for scraping, filtering, LLM review, and later application generation

Important distinction:

- `data/profile.json` is not meant to be hand-authored from zero forever
- it should be generated initially from source documents, then edited incrementally in admin
- government/private CV variants are best treated as derived application outputs or templates, not the main source of truth

This matters for the long-term multi-user design:

- Rob may have several mature source files now
- Maria later should be able to start with one detailed CV and maybe one optional achievements file
- the system should build the rest from there

---

## Current architecture decision

### Preferred scraper path

Use direct job pages, not SEEK's right-hand details pane.

Why:
- pane updates were flaky
- HTML capture could be empty or inconsistent
- direct job pages are easier to reason about and debug

Do not move the project back to pane-based scraping unless there is a very strong reason.

---

## File structure

| Path | Purpose |
|------|---------|
| `source_connector.py` | Main job-source connector and dashboard builder |
| `filters.py` | Deterministic title and content filtering |
| `llm_gate.py` | Optional constrained LLM decision step |
| `local_server.py` | Local web server for admin, dashboard, and API endpoints |
| `agent_runner.py` | Local daily agent runner for collection, digest, and notification delivery |
| `agent_settings.py` | Local agent settings and state helpers |
| `profile_store.py` | Runtime profile loading, defaults, and persistence |
| `profile_learning.py` | Converts free-text knowledge into structured profile updates |
| `review_insights.py` | Unknown skill extraction and rejected-sample review data |
| `source_documents.py` | Local source-document config, parsing, and profile import |
| `utils.py` | Shared parsing and URL helpers |
| `data/profile.json` | Runtime source of truth for the candidate profile |
| `data/capability_profile.txt` | Local human-readable candidate note used for imports |
| `data/capability_profile.template.txt` | Repo-safe starter template for new users |
| `data/application_materials.template.json` | Starter manifest for local-only CV / instructions / application inputs |
| `data/agent_settings.template.json` | Starter template for local agent scheduling and notifier config |
| `data/job_history.json` | Seen/applied/hidden history support |
| `data/llm_cache.json` | Cached LLM decisions |
| `output/dashboard.html` | Human-readable shortlist |
| `output/audit_records.json` | Full audit/debug output |
| `output/run_stats.json` | Latest run metrics |
| `output/review_data.json` | Unknown skills and reject-sample review data |
| `output/agent_last_summary.txt` | Latest plain-text agent digest |
| `legacy/` | Older scraper drafts kept for reference only |
| `docs/OPERATIONS.md` | Persistence and runtime behavior notes |
| `docs/USER_GUIDE.md` | End-user setup and usage guide |

---

## Design principles

1. Deterministic first. Rules before LLM, always.
2. LLM constrained. Output must stay `KEEP`, `REJECT`, or `MAYBE`.
3. Cost-aware. Cache responses, minimize prompt size, and only use LLM when needed.
4. Explainable. A reject should have a visible reason whenever possible.
5. Local-first. The project should run on a personal machine without cloud infrastructure.
6. Learnable. The system should get better through explicit user feedback, not hidden magic.
7. Maintainable. Important runtime state must live in files or storage, not buried in code.

---

## Target job profile

- Primary role family: Business Analyst
- Primary market: Sydney, Australia
- Secondary market: Canberra, configurable
- Primary source: SEEK
- Planned source: LinkedIn
- Preferred domains: tech, digital delivery, transformation, discovery, process improvement, stakeholder-heavy BA work
- Avoid domains: cyber/security-heavy roles, specialist platform admin roles, pure finance/banking ops, ERP-heavy roles unless clearly BA-shaped

The exact live fit model is not fully hardcoded. It is driven by:
- `data/profile.json`
- the imported capability profile
- admin-reviewed unknown skills

---

## Admin model

The admin UI is the main local control surface.

Tabs:
- `Search`: what SEEK gets asked for
- `Candidate Profile`: summary, CV text, capability matrix, title/description rules
- `Review`: applied/hidden controls and unknown skill decisions
- `Test`: latest run stats and rejected samples

Relationship to `profile.json`:

- the admin loads data from `data/profile.json`
- admin edits are saved back into `data/profile.json`
- scraper and LLM both read `data/profile.json`
- the source CV or candidate note should feed into this profile, not compete with it as a second runtime configuration system

Important rule:
- selecting a skill decision does nothing until `Apply Skill Decisions` is pressed

Current dashboard language:

- `Fresh Matches` = kept in the latest run
- `Kept From Earlier Runs` = previously kept and still surfaced from history
- `Hidden Jobs` = manually hidden review list
- `Older Kept Jobs` = older historical keeps collapsed by default

When applied, new knowledge is written into `data/profile.json` and should then appear in the capability matrix.

Current intended future behavior:

- initial profile fields such as summary, strengths, CV text, capability hints, and fit notes should come from imported source documents
- after import, admin becomes the place to refine, correct, and extend them over time
- a first-pass source-document importer now exists in the `Source Documents` panel of admin

---

## LLM model

The LLM is optional and intentionally constrained.

Current behavior:

- deterministic title filters run first
- deterministic content filters run second
- only surviving jobs reach the LLM review step
- the LLM sees job detail text plus profile context from `data/profile.json`
- the response is limited to `KEEP`, `REJECT`, or `MAYBE`
- decisions are cached in `data/llm_cache.json`
- if `OPENAI_API_KEY` is missing, the system behaves as if the LLM is disabled and falls back to `MAYBE`

Profile inputs currently used by the LLM prompt:

- candidate summary
- strengths
- CV/background text
- capability profile rules
- important fit notes

Important design note:

- titles are useful as a cheap first pass, but the long-term fit decision should be driven more by description evidence and profile fit than by title alone
- many roles with a strong title are poor matches after reading the description
- many adjacent titles may still be good matches once the description is read

---

## Dashboard model

`output/seek_results.html` is no longer just a throwaway report. It is a persistent local dashboard.

Current dashboard behavior:

- fresh kept jobs from the latest run appear first
- previously kept jobs stay visible in saved sections
- hidden jobs can be reviewed and unhidden
- older saved jobs are collapsed by default after the stale threshold
- filters support sort, scope, posted age, work mode, score, and pagination
- run snapshot and run efficiency are now in a side panel so the main view stays job-focused

The dashboard is still generated HTML rather than a full live app, but it is now acting as a local memory layer for the job hunt.

The admin server now also serves the dashboard at:

- `http://127.0.0.1:8765/dashboard`

---

## Persistence rules

- `data/profile.json` is the runtime source of truth
- `data/capability_profile.txt` is the local human master note
- `data/capability_profile.template.txt` is the committed starter template
- local source documents for applications should live under ignored paths such as `data/application_inputs/`
- generated outputs under `output/` are disposable and can be recreated
- profile/history/cache under `data/` should be treated as valuable local state
- local agent settings and state also live under `data/`

Keep personal and local-only:

- `data/profile.json`
- `data/capability_profile.txt`
- `data/job_history.json`
- `data/agent_settings.json`
- `data/agent_state.json`
- `data/llm_cache.json`
- `data/application_inputs/`
- `data/application_materials.json`
- `TODO.txt`
- `.venv/`

The code now resolves these files relative to the repo location, not the shell working directory. That is important for local reliability and later cloud migration.

---

## Roadmap

### Stage 2 - Reliable data pipeline

- [x] Switch to direct-page SEEK scraping
- [x] Add structured HTML and JSON output
- [x] Add run stats and reject review data
- [x] Add local admin UI
- [x] Add profile persistence and learning loop
- [x] Add persistent local dashboard with archive and hidden review
- [x] Add first-pass source-document import from CV and STAR material
- [ ] Keep improving title/content filtering quality
- [ ] Add better extraction for hidden or collapsed job requirements
- [ ] Add export/import helpers for profile portability
- [ ] Keep improving document import quality and source normalization

### Stage 3 - Real job agent

- [ ] Add scheduling
- [ ] Add message delivery
- [ ] Add application feedback loop
- [ ] Add `Prepare Application` pack flow with tailored CV and cover letter drafts
- [ ] Add source expansion beyond SEEK
- [ ] Add durable cloud storage model
- [ ] Wrap cleanly for OpenClaw or similar agent runtime

---

## Tech stack

- Python
- Playwright
- OpenAI API
- optional Anthropic-style future agent integration
- local HTML admin UI backed by Python `http.server`
- JSON file persistence

---

## Guardrails for future AI agents

- Do not reintroduce pane-based scraping as the main path.
- Do not replace deterministic filters with a free-form LLM agent.
- Do not hide important runtime state inside prompts only.
- Do not assume the profile is disposable; preserve `data/profile.json`.
- Do not optimize for hype over reliability.
- Do keep the system understandable enough that a human can inspect why a job was kept or rejected.
