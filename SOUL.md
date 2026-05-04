# SOUL.md - Job Hunter Agent

> **ARCHIVED — May 2026.**
> Content has been split into:
> - `AGENTS.md` — AI code map, run commands, guardrails (primary AI context, all tools)
> - `docs/ARCHITECTURE.md` — full architecture, design decisions, scoring model, roadmap
>
> This file is kept for reference only. Do not update it. Edit `AGENTS.md` or `docs/ARCHITECTURE.md` instead.

---

---

## What this project is

A local-first job-hunting system focused on finding strong-fit roles for any candidate with as little noise as possible.

Near-term goal:
- reliably scrape and filter target roles from a configurable candidate profile
- learn the candidate profile over time
- produce a clean shortlist with clear reject reasons

Long-term goal:
- become a true autonomous job agent that runs daily and sends only meaningful matches

This project exists to solve a real job-search problem while also becoming a practical agent/automation learning project.

---

## Current stage

### Stage 2 underway — evolving toward knowledge-managed architecture

The project is past the initial prototype stage and is actively transitioning from hardcoded business logic toward a JSON-backed knowledge management system.

### What works now

- SEEK scraping uses the direct-page approach in `source_connector.py`
- deterministic filtering happens before any LLM call
- LLM fallback is constrained to `KEEP`, `REJECT`, or `MAYBE`
- search settings are configurable from the local settings UI
- search supports date window, sort by newest, locations, and classification filters
- runtime profile is persisted in `data/profile.json`
- source documents can be imported into `data/profile.json` from the admin UI
- dashboard is persistent and rebuilds from the latest scrape plus local job history
- dashboard supports hidden-job review, kept-earlier archive, match filters, salary-target filtering, and pagination
- viewed/opened jobs are tracked locally when the admin API is available
- applied and hidden jobs can be recorded from the review workflow
- outputs are written to `output/` as HTML, JSON, run stats, and review data
- history and cache are persisted locally
- daily agent runner exists with email and Telegram notifier hooks
- LinkedIn scraping is implemented via `python-jobspy`
- capability, hard blocker, and role title knowledge are now JSON-backed managed modules
- match score bands are configurable via `match_level_defaults.json`
- rejection rule categories are configurable via `rejection_rule_categories.json`
- signal registry system exists for surfacing and approving learned patterns
- job deduplication across sources (SEEK + LinkedIn) via `job_identity.py`
- all file paths are centralized in `paths.py`
- workspace UI (`workspace.html`) provides a multi-view dashboard with Potential, Applied, and Hidden tabs
- dashboard data transformation is separated into `dashboard_data.py`

### What is still incomplete

- this is not yet a true agent
- no WhatsApp delivery yet
- no authenticated SEEK session reuse yet
- no durable cloud persistence yet
- filtering still needs ongoing tuning to reduce false positives and false rejects
- source-document import still needs tuning for richer extraction quality
- no application-pack workflow yet for tailored CVs, cover letters, and criteria responses
- many hardcoded judgment items remain in `profile_learning.py` and `cv_pipeline.py` (tracked in `HARD_CODED_JUDGEMENT_BACKLOG.md`)

---

## Current product model

This project has now settled into a clearer shape:

- source documents are the human truth
- `data/profile.json` is the runtime machine truth
- settings is the editor and maintenance surface for that runtime truth
- knowledge JSON files (`capability_knowledge.json`, `hard_blocker_rules.json`, `role_title_knowledge.json`) are the managed rule layer
- generated application outputs should be derived from source documents and profile data, not treated as primary sources

For a real user, the intended flow is:

1. import one strong detailed CV
2. optionally import richer evidence such as STAR notes or long-form experience
3. generate a distilled runtime profile in `data/profile.json`
4. let the user maintain and refine that profile from the settings UI
5. use that runtime profile for scraping, filtering, LLM review, and later application generation

Important distinction:

- `data/profile.json` is not meant to be hand-authored from zero forever
- it should be generated initially from source documents, then edited incrementally in settings
- government/private CV variants are best treated as derived application outputs or templates, not the main source of truth

This matters for the long-term multi-user design:

- Rob may have several mature source files now
- Maria later should be able to start with one detailed CV and maybe one optional achievements file
- the system should build the rest from there

---

## Current architecture decisions

### Preferred scraper path

Use direct job pages, not SEEK's right-hand details pane.

Why:
- pane updates were flaky
- HTML capture could be empty or inconsistent
- direct job pages are easier to reason about and debug

Do not move the project back to pane-based scraping unless there is a very strong reason.

### Knowledge-managed over hardcoded

Business rules are being systematically migrated from sealed Python constants into JSON-backed knowledge modules. The three main knowledge modules are:

- `capability_knowledge.py` / `capability_knowledge.json` — capability entries with aliases and fit levels
- `hard_blocker_rules.py` / `hard_blocker_rules.json` — approved reusable hard-blocker patterns
- `role_title_knowledge.py` / `role_title_knowledge.json` — role title token patterns

The signal registry (`signal_registry.py` / `signal_registry.json`) manages an approval inbox for patterns surfaced during scraping that the user can promote into knowledge.

Do not revert knowledge rules back to hardcoded constants. Use the JSON-backed modules.

---

## File structure

All core code lives in `job_hunter_agent/`.

| Path | Purpose |
|------|---------|
| `job_hunter_agent/` | Core package |
| `source_connector.py` | Launcher for job collection and dashboard rebuilds |
| `filters.py` | Deterministic title and content filtering |
| `llm_gate.py` | Optional constrained LLM decision step (OpenAI) |
| `local_server.py` | Local web server (Settings, Dashboard, Onboarding, Workspace) |
| `agent_runner.py` | Daily agent runner and notification delivery |
| `test_runner.py` | Pytest suite wrapper |
| `agent_settings.py` | Local agent settings and state helpers |
| `profile_store.py` | Runtime profile loading, defaults, and persistence |
| `profile_learning.py` | Converts free-text knowledge into structured profile updates |
| `cv_pipeline.py` | CV parsing and capability clustering |
| `review_insights.py` | Unknown skill extraction and rejected-sample review data |
| `source_documents.py` | Source-document config, parsing, and profile import |
| `scrapers/seek.py` | SEEK-specific scraping and extraction |
| `scrapers/linkedin.py` | LinkedIn scraping via python-jobspy |
| `scrapers/base.py` | Shared base logic for all scrapers |
| `notifiers/email_notifier.py` | Email notification delivery |
| `notifiers/telegram_notifier.py` | Telegram notification delivery |
| `utils.py` | Shared parsing and URL helpers |
| `config.py` | Global configuration and scrape tuning |
| `paths.py` | Centralized path management — all file paths go here |
| `dashboard_data.py` | Builds and manages historical dashboard records |
| `job_identity.py` | Cross-source job deduplication and similarity detection |
| `match_labels.py` | Loads match score bands from `match_level_defaults.json` |
| `capability_knowledge.py` | Managed JSON-backed capability knowledge module |
| `hard_blocker_rules.py` | Managed JSON-backed hard blocker rules |
| `role_title_knowledge.py` | Managed JSON-backed role title patterns |
| `signal_registry.py` | Signal inbox system with category-based knowledge management |
| `title_normalization_rules.py` | Title normalization rules module |
| `capability_matrix.py` | Capability matrix building and scoring |
| `data/profile.json` | Runtime source of truth for the candidate profile |
| `data/capability_knowledge.json` | Managed capability entries and aliases |
| `data/hard_blocker_rules.json` | Managed hard blocker rules |
| `data/role_title_knowledge.json` | Managed role title patterns |
| `data/signal_registry.json` | Signal inbox awaiting user review |
| `data/ignored_signal_archive.json` | Archived/dismissed signals |
| `data/match_level_defaults.json` | Configurable match score band thresholds |
| `data/rejection_rule_categories.json` | Rejection rule category definitions |
| `data/government_context_rules.json` | Government context detection rules |
| `data/agent_settings.template.json` | Starter template for agent scheduling and notifier config |
| `data/job_history.json` | Seen/applied/hidden history |
| `data/llm_cache.json` | Cached LLM decisions |
| `templates/settings.html` | Settings UI template |
| `templates/onboarding.html` | Onboarding flow template |
| `templates/results.html` | Job results display template |
| `templates/workspace.html` | Multi-view workspace/dashboard template |
| `output/dashboard.html` | Human-readable shortlist |
| `output/audit_records.json` | Full audit/debug output |
| `output/run_stats.json` | Latest run metrics |
| `output/review_data.json` | Unknown skills and reject-sample review data |
| `output/agent_last_summary.txt` | Latest plain-text agent digest |
| `docs/OPERATIONS.md` | Persistence and runtime behavior notes |
| `docs/USER_GUIDE.md` | End-user setup and usage guide |
| `docs/DEVELOPER_GUIDE.md` | Technical architecture guide |
| `HARD_CODED_JUDGEMENT_BACKLOG.md` | Tracked list of hardcoded business logic to migrate |
| `SCORING_RATIONALE.md` | Fit score component rationale and budget |
| `CAPABILITY_AGING_RATIONALE.md` | Capability strength assignment logic |
| `ALIAS_LOGIC_RATIONALE.md` | Alias validation rules |
| `Agents.md` | Project spec and canonical run commands |
| `BACKLOG.md` | OpenClaw/agent runtime integration planning |

---

## Design principles

1. Deterministic first. Rules before LLM, always.
2. LLM constrained. Output must stay `KEEP`, `REJECT`, or `MAYBE`.
3. Cost-aware. Cache responses, minimize prompt size, and only use LLM when needed.
4. Explainable. A reject should have a visible reason whenever possible.
5. Local-first. The project should run on a personal machine without cloud infrastructure.
6. Learnable. The system should get better through explicit user feedback, not hidden magic.
7. Maintainable. Important runtime state must live in files or storage, not buried in code.
8. Knowledge-managed. Business rules belong in JSON-backed modules, not sealed Python constants.

---

## Targeting model

- role family, locations, salary targets, and title patterns should come from `data/profile.json` and `role_title_knowledge.json`
- default code paths should stay candidate-agnostic
- source-specific settings can exist, but candidate fit assumptions belong in the profile and knowledge modules, not in code

The exact live fit model is driven by:
- `data/profile.json`
- the capability knowledge rules (`capability_knowledge.json`)
- hard blocker rules (`hard_blocker_rules.json`)
- role title patterns (`role_title_knowledge.json`)
- admin-reviewed signals from the signal registry

---

## Settings model

The settings UI is the main local control surface (served by `local_server.py`).

The UI serves several templates:
- `settings.html` — main settings editor
- `onboarding.html` — onboarding flow for new users / CV import
- `workspace.html` — multi-view dashboard (Potential / Applied / Hidden tabs)
- `results.html` — job results display

Settings tabs:
- `Search`: what SEEK gets asked for
- `Candidate Profile`: summary, CV text, capability matrix, title/description rules
- `Review`: applied/hidden controls and unknown skill decisions
- `Signal Registry`: review and approve patterns surfaced during scraping
- `Test`: latest run stats and rejected samples

Relationship to `profile.json`:

- the settings UI loads data from `data/profile.json`
- settings edits are saved back into `data/profile.json`
- scraper and LLM both read `data/profile.json`
- the source CV or candidate note should feed into this profile, not compete with it

Important rules:
- selecting a skill decision does nothing until `Apply Skill Decisions` is pressed
- signal registry decisions do nothing until the user approves them

Current dashboard language (workspace.html):

- `Potential Jobs` = kept in the latest run and from recent history
- `Applied` = jobs where application has been recorded
- `Hidden Jobs` = manually hidden review list

When applied, new knowledge is written into `data/profile.json` and the appropriate knowledge JSON files.

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
- if `OPENAI_API_KEY` is missing, the system falls back to `MAYBE`
- current LLM provider is OpenAI (`gpt-4o-mini` for cheap pass, `gpt-4o` configurable)

Profile inputs currently used by the LLM prompt:

- candidate fit brief
- capability profile rules
- match preferences such as location and permanent/contract preference
- evidence tiers with weighted primary, secondary, and background context

Important design note:

- titles are useful as a cheap first pass, but the long-term fit decision should be driven more by description evidence and profile fit than by title alone
- many roles with a strong title are poor matches after reading the description
- many secondary titles may still be good matches once the description is read

---

## Dashboard model

The dashboard is a persistent local workspace, not a throwaway report.

Current dashboard behavior:

- served via `workspace.html` at `http://127.0.0.1:8765/dashboard`
- multi-view: Potential Jobs, Applied, Hidden Jobs tabs
- fresh kept jobs from the latest run appear first
- previously kept jobs stay visible in saved sections
- hidden jobs can be reviewed and unhidden
- older saved jobs are collapsed by default after the stale threshold
- filters support sort, scope, posted age, work mode, score, and pagination
- run snapshot and run efficiency are in a side panel
- `dashboard_data.py` handles data transformation and historical record persistence separately from the connector

### Scoring Model

The fit score is a 0–100 integer built as a weighted sum of signals. For full rationale see `SCORING_RATIONALE.md`.

| Component | Range | Weight category |
|-----------|-------|-----------------|
| Title signal (direct match / secondary) | 0–15 | `fit` |
| LLM description grade | −8–25 | `fit` |
| Content filter pass | 0–3 | `fit` |
| Full description confidence penalty | 0 or −8 | `fit` |
| Capability evidence score | 0–20 | `fit` |
| Convergence bonus | 0, 3, or 5 | `fit` |
| Competitive signal adjustments | variable | `fit` |
| Freshness | 0–10 | `freshness` |
| Location preference | −5–8 | `location` |
| Contract preference | −5–10 | `contract` |
| Government preference | 0–4 | `government` |
| Work mode | −2–5 | `work_mode` |
| Salary signal | −5–7 | `salary` |
| Already viewed penalty | −3 | unweighted |

Preference weights (default 1.0, max 2.0) multiply all points in their category. They are set from the settings UI.

**Capability evidence score** is the evidence-based component. For each capability rule that matches the job description (fit = core or supporting, level = strong/working/basic):

```
combined     = max(rule_strength, evidence_tier_alignment_score)
contribution = combined × fit_weight   # fit_weight: 4 for core, 2 for supporting
```

`evidence_tier_alignment_score` is computed from the candidate's profile text — recency, how many roles mention it, and how many alias hits appear.

### Match Score Bands

Match band thresholds are now loaded from `data/match_level_defaults.json` via `match_labels.py` (not hardcoded). Defaults:

| Band | Score |
|------|-------|
| Strong match | 85–100 |
| Good match | 70–84 |
| Possible fit | 55–69 |
| Stretch | 0–54 |

---

## Persistence rules

- `data/profile.json` is the runtime source of truth
- knowledge JSON files under `data/` are the managed rule layer — treat them as valuable state
- local source documents for applications should live under ignored paths such as `data/application_inputs/`
- generated outputs under `output/` are disposable and can be recreated
- profile/history/cache/knowledge under `data/` should be treated as valuable local state

Keep personal and local-only:

- `data/profile.json`
- `data/job_history.json`
- `data/agent_settings.json`
- `data/agent_state.json`
- `data/llm_cache.json`
- `data/llm_costs.jsonl`
- `data/capability_knowledge.json`
- `data/hard_blocker_rules.json`
- `data/role_title_knowledge.json`
- `data/signal_registry.json`
- `data/ignored_signal_archive.json`
- `TODO.txt`
- `.venv/`

All paths are resolved via `paths.py` relative to the repo root, not the shell working directory.

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
- [x] Migrate match bands to configurable JSON (`match_level_defaults.json`)
- [x] Migrate rejection rule categories to configurable JSON
- [x] Add knowledge-managed capability, hard blocker, and role title modules
- [x] Add signal registry for reviewing and approving learned patterns
- [x] Add cross-source job deduplication (`job_identity.py`)
- [x] Centralize all paths in `paths.py`
- [x] Add workspace multi-view dashboard (`workspace.html`)
- [ ] Keep improving title/content filtering quality
- [ ] Add better extraction for hidden or collapsed job requirements
- [ ] Add export/import helpers for profile portability
- [ ] Keep improving document import quality and source normalization
- [ ] Migrate remaining hardcoded judgment items (see `HARD_CODED_JUDGEMENT_BACKLOG.md`)

### Stage 3 - Real job agent

- [ ] Add scheduling
- [ ] Add message delivery
- [ ] Add application feedback loop
- [ ] Add `Prepare Application` pack flow with tailored CV and cover letter drafts
- [x] Add source expansion beyond SEEK (LinkedIn implemented via jobspy)
- [ ] Add durable cloud storage model
- [ ] Wrap cleanly for OpenClaw or similar agent runtime (see `BACKLOG.md`)

---

## Tech stack

- Python 3.11+
- Playwright (browser automation for SEEK)
- OpenAI API (LLM analysis and fit evaluation — `gpt-4o-mini` / `gpt-4o`)
- python-jobspy (LinkedIn and multi-board scraping)
- python-docx (CV and document parsing)
- pandas (data manipulation and CSV handling)
- requests (notifications and external API integration)
- python-dotenv (environment variable management)
- local HTML/JS settings UI backed by Python `http.server`
- JSON file persistence for all runtime state and knowledge

---

## Parked Decisions

These are intentional choices to defer features. Do not re-add without reading the reason.

### star_evidence_text — parked April 2026

- Field exists in `data/profile.json` and is populated by onboarding/import.
- Removed from admin UI (no textarea) and excluded from LLM fit-scoring prompt.
- Reason: adds prompt tokens without meaningfully improving KEEP/REJECT/MAYBE decisions. The evidence tiers already carry the CV substance.
- Where it belongs: application generation — cover letters, selection criteria responses, tailored CVs. Build that feature, then re-expose this field.
- Code comment in `llm_gate.py` → `build_profile_prompt_context()` explains the exclusion.
- Code comment in `local_server.py` HTML and `collectProfile()` explains why the UI field is absent.

---

## Guardrails for future AI agents

- Do not reintroduce pane-based scraping as the main path.
- Do not replace deterministic filters with a free-form LLM agent.
- Do not hide important runtime state inside prompts only.
- Do not assume the profile is disposable; preserve `data/profile.json`.
- Do not revert knowledge modules to hardcoded constants; use the JSON-backed modules.
- Do not optimize for hype over reliability.
- Do keep the system understandable enough that a human can inspect why a job was kept or rejected.
- Do read `HARD_CODED_JUDGEMENT_BACKLOG.md` before adding new hardcoded business logic — the backlog tracks where to put it instead.
