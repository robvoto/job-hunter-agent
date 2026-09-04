# Developer Guide

## Purpose

This file is for technical contributors.

Use it alongside:

- `AGENTS.md` for AI/dev guardrails and the code map
- `docs/ARCHITECTURE.md` for system design
- `docs/PRINCIPLES.md` for product and decision philosophy
- `docs/OPERATIONS.md` for runtime behavior
- `docs/USER_GUIDE.md` for the end-user flow

## Current Architecture

Core runtime code now lives under `job_hunter_agent/`.

Primary modules:

- `job_hunter_agent/server_helpers.py`
  Shared UI logic (`SettingsHandler`), onboarding helpers, run state, scrape thread helpers.

- `job_hunter_agent/fastapi_app.py` / `job_hunter_agent/routes/`
  FastAPI application, route modules for the settings console, workspace, onboarding pages, and JSON APIs.
  Runtime startup commands live in `docs/OPERATIONS.md`.

  All routers are registered centrally in `routes/__init__.py` → `register_routes()`.
  Routes rarely change — only when a new feature adds an endpoint or a module is renamed.
  To see all routes interactively, open `/docs` in the running app (FastAPI's built-in Swagger UI).

  Route map by module:

  | Module               | Routes                                                                                                      |
  | -------------------- | ----------------------------------------------------------------------------------------------------------- |
  | `pages.py`           | `/` `/workspace` `/admin` `/profile` `/settings` `/start` `/onboarding` (redirects) `/demo`               |
  | `workspace_api.py`   | `GET /api/results-html` `/api/health` `/api/run-stats` `/api/run-status` `/api/review-data` `/api/job-history` |
  | `profile_materials.py` | `GET/PATCH/PUT /api/profile` · `GET/PUT /api/source-materials` · `GET/PATCH /api/advance-settings` · `GET /api/admin/system-warnings` · `PATCH /api/admin/system-warnings/{warning_id}` · `POST /api/admin/scraper-config-validation` |
  | `agent_telegram.py`  | `GET /api/llm-costs` · `GET/PATCH /api/agent-settings` · `GET /api/telegram/connect-link` · `POST /api/telegram/sync` `/api/telegram/test-message` |
  | `signals.py`         | `GET/PATCH /api/signal-registry`                                                                            |
  | `review.py`          | `GET /api/rejection-suggestions` · `POST /api/tuning-decisions` `/api/skill-decisions` `/api/rule/phrase` `/api/rejection-feedback/required-blockers` `/api/rejection-rules` `/api/title-block-preview` `/api/review` · `DELETE /api/rule/title-block` |
  | `onboarding_api.py`  | `POST /api/onboarding/import` `/api/onboarding/confirm-profile-signals`                                     |
  | `scrape_debug.py`    | `POST /api/test/reset-user` `/api/debug/browser-log` `/api/run`                                             |
  | `static_docs.py`     | `GET /static/{path}` `/data/{path}` `/docs` `/api/docs`                                                     |

Server logging:

- application runtime logging writes to a single file, `output/server.log`, timestamped; the terminal mirrors its curated stream
- `./run` shows curated INFO-level job/run summaries; `./run --debug` raises `server.log` to DEBUG for application pipeline/LLM trace — see `docs/OPERATIONS.md` for the command
- raw dependency/API transport chatter (httpx/httpcore/openai wire-level detail) is dropped at every level; it's never written anywhere
- `/api/debug/browser-log` is for browser-side JS logs only
- debug/audit uncertainty events go to `output/uncertainty.jsonl`
- runtime warning/diagnostic records go to SQLite `system_warnings`; backend classification decides whether each unresolved record is an operational System health problem or a read-only technical diagnostic
- the default admin feed contains only operational problems; diagnostics are aggregated by category and source when explicitly requested
- acknowledging an operational problem hides only that occurrence; recurrence of the same fingerprint reopens it
- use `job_hunter_agent.runtime_helpers.build_uncertainty_entry()` and `append_uncertainty_log()` for reusable uncertainty records
- keep the event shape stable: `ts`, `reason_code`, `stage`, `field`, `raw_value`, `normalized_value`, `detail`, `source`, `job_key`, `severity`

- `job_hunter_agent/auth.py`
  Session management and security. 
  - **Transport-aware security:** `Secure` follows the request transport by default, with `JOB_HUNTER_SESSION_COOKIE_SECURE` available to force `true` or `false`.
  - **SameSite Policy:** Enforced as `Strict` to mitigate CSRF.
  - **Configuration:** Cookie names are configurable via `JOB_HUNTER_SESSION_COOKIE_NAME` env var.

- `job_hunter_agent/source_documents.py`
  Local source-pack persistence and source-document import into the runtime profile (DB).

- `job_hunter_agent/profile_store.py`
  Default profile model, load/save, and patch behavior.

- `job_hunter_agent/profile_learning.py`
  Text-to-profile extraction helpers.

### Import-cycle health

Repo health now includes a static import-graph check across the active runtime modules.

Current known allowlisted cycle:

- `job_hunter_agent.llm_gate` <-> `job_hunter_agent.profile_store`

Treat any newly detected active-module cycle as technical debt that needs review before it becomes normal architecture.

- `job_hunter_agent/cv_pipeline.py`
  Heuristic and LLM-assisted CV analysis and capability mapping.

- `job_hunter_agent/review_insights.py`
  Aggregates audit data and skill observations to suggest profile tuning.

### LLM Prompt Context Loading

`llm_gate.build_profile_prompt_context()` is the owner for loading the runtime profile into LLM prompt context.

Current reviewed state:

- `build_system_prompt()` calls `build_profile_prompt_context()` internally.
- `llm_suggest_rejection_blockers()` also calls `build_profile_prompt_context()` directly when it builds its own focused system prompt.
- This can mean separate LLM paths load the profile independently, but there is no confirmed duplicate load inside a single shared prompt-builder call chain.
- The fit-review profile context must stay limited to authoritative structured profile sources: candidate capabilities, Related Skills/levels/fit, candidate eligibility, evidence tiers, relevant matching preferences, and target-role context.

Rule:

- call `build_system_prompt()` when the normal fit-review system prompt is needed
- call `build_profile_prompt_context()` directly only for focused prompts that intentionally do not use the normal full system prompt
- do not call both in the same prompt assembly path unless the caller has a specific reason and documents it
- if duplicate profile loading becomes measurable, extract a request-scoped prompt context object rather than adding hidden caching inside prompt builders

### Suggested Tuning Flow

The Settings > Optimise > Suggested Tuning panel is a confirmation layer, not automatic learning.

Runtime path:

1. A scrape/review run writes saved review data.
2. `GET /api/review-data` in `routes/workspace_api.py` loads that data.
3. `build_review_data()` in `review_insights.py` builds `suggested_tuning` from kept-job evidence and rejection records before the payload is persisted.
4. `templates/static/settings/shared/settings-review-panel.js` renders suggestions into `#tuning_suggestions_panel`.
5. Confirmed capabilities are applied through `POST /api/tuning-decisions` and `apply_capability_tuning_decisions()`.
6. Phrase exclusions are applied through `POST /api/rule/phrase`.

The empty state is valid when no saved review data exists or no repeated signal meets the configured review thresholds. Do not treat the empty state as a UI failure without checking saved review data and thresholds first.

For detailed maintenance rules, see `.skills/suggested-tuning/SKILL.md`.

- `job_hunter_agent/capability_matrix.py`
  Logic for alias expansion and deterministic capability matching.

- `job_hunter_agent/agent_runner.py` / `job_hunter_agent/user_settings.py`
  Orchestration for daily scheduled runs and notification state.

- `job_hunter_agent/source_connector.py`
  Current source connector and workspace renderer for SEEK, LinkedIn, and APSJobs.

- `job_hunter_agent/scrapers/seek.py` / `job_hunter_agent/scrapers/linkedin.py` / `job_hunter_agent/scrapers/apsjobs.py`
  Source-specific extraction logic.

- `job_hunter_agent/posting_utils.py`
  Shared posted-date parsing and display helpers. Use visible relative text from the source page; do not invent hidden fallback date paths.

- `job_hunter_agent/filters.py`
  Deterministic title and content filtering.

- `job_hunter_agent/llm_gate.py`
  Optional constrained LLM decision step.

Standard project folders:

- `job_hunter_agent/` for application code
- `tests/` for test coverage
- `templates/` for HTML templates
- `docs/` for project docs
- `data/` and `output/` for local runtime state

## Naming Note

The code still uses terms like `scraper` because that is how the project evolved.

For product-level docs and future architecture, prefer:

- source connector
- job-source connector
- workspace
- runtime profile

Do not rename major files casually unless there is time to clean the whole project consistently.

 ## Current Onboarding Flow

 1. User visits `/start`
 2. Uploads a detailed CV
  3. Uploaded documents are saved into a local source pack under ignored paths
  4. The source pack is imported into the DB profile (`user_profile` table)
  5. Review Draft, Search Basics, and Check Setup are completed inside the onboarding flow
  6. Settings is then used to refine the runtime profile

- Onboarding and Settings copy for preferred roles, alternative roles, and `Explore adjacent roles` comes from `data/knowledge/ui_labels.json` via `window.__JOB_HUNTER_TITLE_TIER_LABELS__`.
- `profile_store.KEY_EXPLORE_ADJACENT_ROLES` owns the candidate-specific exploration switch and defaults to `False` (strict title behaviour).
- `job_review_pipeline.review_pre_detail_normalized_job()` passes the candidate capability names into `llm_gate.llm_judge_title()` so exploration mode can keep plausible adjacent titles for description review; strict mode ignores those capability signals and preserves the original title contract.
- Confirmed preferred and alternative role lists drive separate source-native search targets; do not expose or invent a separate search-string setting.

### Onboarding File Map

| File | Responsibility |
|---|---|
| `templates/onboarding.html` | Onboarding page shell and section placement. |
| `templates/static/onboarding/onboarding-page.js` | DOM refs, page state, step navigation, display helpers (`saveWizardState` for step/location changes). |
| `templates/static/onboarding/onboarding-flow.js` | Wizard orchestration, Review Draft, Check Setup, capability review, step-transition actions, `initWizard`. |
| `templates/static/onboarding/onboarding-storage.js` | Wizard draft state save/restore, search-basics DB persistence, event handler wiring for all preference fields. |
| `templates/static/onboarding/onboarding-search.js` | `setSelectedLocations`, `hydrateSearchBasics` (populates search-basics fields from a DB profile on step transition). |
| `templates/static/onboarding/onboarding-upload.js` | CV file validation, drop zone handling, `create_profile` button availability. |
| `templates/static/onboarding/onboarding-page.css` | Onboarding-only layout exceptions and spacing. |
| `job_hunter_agent/routes/pages.py` | Route rendering and bootstrap injection. |
| `job_hunter_agent/server_helpers.py` | Onboarding label loading and injected globals. |
| `job_hunter_agent/profile_store.py` | Runtime profile persistence and onboarding-imported state. |
| `data/knowledge/ui_labels.json` | Shared onboarding copy source. |

## Score Presentation

## Job Identification (Job Keys)

All job records MUST include a `job_key` in the `source:id` format.

- Never use raw URLs as keys in the job history or profile (DB-backed; use canonical `job_key` everywhere).
- Always use `job_hunter_agent.job_identity.normalize_job_key(raw_value, source=...)` when creating records.
- Use `RECORD_JOB_KEY` from `record_schema.py` instead of the string literal `"job_key"`.

The workspace now treats scoring as two separate layers:

- internal numeric score
  Used for ranking, shortlist thresholds, filters, and debug output.

- visible match band
  The normal workspace shows four human-facing labels instead of a raw `/100`:
  `Strong match`, `Good match`, `Possible fit`, and `Stretch`.

Design intent:

- the numeric score is useful to the engine and to technical debugging
- the raw `/100` can mislead users into reading the score as a literal probability or percentage
- you can use the `--show-scores` flag to see the raw score on cards and the detailed breakdown for tuning work

Hard blockers:

- some dominant-signal clusters can now be configured as hard blockers
- when a role clearly leans into one of those specialist domains and the profile alignment is weak or partial, the role is rejected before the shortlist
- this is intended for domains that should be treated as effectively out of scope, not merely "slightly lower fit"

Detail-page safety:

- invalid detail fetches such as challenge pages are treated as unusable input, not as job descriptions
- successful full-detail fetches now persist `fit_source_text` into saved snapshots so later workspace rebuilds and history reuse do not lose specialist gap evidence
- kept-job reuse also requires the current `requirement_coverage_contract_version`; when the requirement/profile-learning contract changes, older saved coverage is re-reviewed instead of preserving stale Add/No actions

## Current Product Boundary

Current implemented sources:

- SEEK
- LinkedIn

Design assumption:

- new sources should normalize into the same record shape used by the workspace, review flow, history, and fit logic

## Safe Local State

Do not accidentally commit:

- `data/users/` — all per-user runtime state lives here
- `data/runtime/` — LLM cost tracking and cache
- `output/` — server logs and disposable output
- `.venv/`

## Testing Workflow

Follow `docs/OPERATIONS.md` for validation scope and commands.

The standard local formatting and linting workflow is:

```powershell
uv sync --group dev
uv run python -m ruff check .
uv run python -m ruff format <file-or-folder>
uv run python -m ruff check . --fix
```
