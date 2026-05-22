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
  | `profile_materials.py` | `GET/PATCH/PUT /api/profile` · `GET/PUT /api/source-materials` · `GET/PATCH /api/advance-settings`        |
  | `agent_telegram.py`  | `GET /api/llm-costs` · `GET/PATCH /api/agent-settings` · `GET /api/telegram/connect-link` · `POST /api/telegram/sync` `/api/telegram/test-message` |
  | `signals.py`         | `GET/PATCH /api/signal-registry`                                                                            |
  | `review.py`          | `GET /api/rejection-suggestions` · `POST /api/tuning-decisions` `/api/skill-decisions` `/api/rule/phrase` `/api/rejection-feedback/mandatory-blockers` `/api/rejection-rules` `/api/title-block-preview` `/api/review` · `DELETE /api/rule/title-block` |
  | `onboarding_api.py`  | `POST /api/onboarding/import` `/api/onboarding/confirm-profile-signals`                                     |
  | `scrape_debug.py`    | `POST /api/test/reset-user` `/api/test/reset-learning` `/api/debug/browser-log` `/api/run`                  |
  | `static_docs.py`     | `GET /static/{path}` `/data/{path}` `/docs` `/api/docs`                                                     |

Server logging:

- debug-mode runtime logging writes server output to `output/server.log`; see `docs/OPERATIONS.md` for the command
- logs are timestamped and still mirrored to the terminal
- `/api/debug/browser-log` is for browser-side JS logs only

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

- `job_hunter_agent/cv_pipeline.py`
  Heuristic and LLM-assisted CV analysis and capability mapping.

- `job_hunter_agent/review_insights.py`
  Aggregates audit data and skill observations to suggest profile tuning.

- `job_hunter_agent/capability_matrix.py`
  Logic for alias expansion and deterministic capability matching.

- `job_hunter_agent/agent_runner.py` / `agent_settings.py`
  Orchestration for daily scheduled runs and notification state.

- `job_hunter_agent/source_connector.py`
  Current source connector and workspace renderer for SEEK and LinkedIn.

- `job_hunter_agent/scrapers/seek.py` / `job_hunter_agent/scrapers/linkedin.py`
  Source-specific extraction logic.

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

- Onboarding copy for target roles, also-consider roles, and the search keyword comes from `data/knowledge/ui_labels.json` and is injected into the page as `window.__JOB_HUNTER_TITLE_TIER_LABELS__`.
- The onboarding search keyword is a single term. Do not comma-join multiple title candidates in auto-fill logic.

### Onboarding File Map

| File | Responsibility |
|---|---|
| `templates/onboarding.html` | Onboarding page shell and section placement. |
| `templates/static/onboarding/onboarding-page.js` | Search Basics state, summaries, and import summary wiring. |
| `templates/static/onboarding/onboarding-flow.js` | Review Draft, Check Setup, capability review, and onboarding actions. |
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
- `TODO.txt`
- `.venv/`

## Testing Workflow

Use the smallest relevant validation for the change. Test execution commands live in `docs/OPERATIONS.md`.
