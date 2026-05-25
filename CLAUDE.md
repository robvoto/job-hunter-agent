# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start-of-task protocol

**Do this at the start of every task, in order:**

1. Read `Agents.md` — architecture, commands, non-negotiable rules, and the skills index.
2. Identify which domain(s) the task touches.
3. Read **only** the relevant `.skills/<domain>/SKILL.md` file(s) — not all of them.
4. Then plan and act.

**Never skip step 1.** `Agents.md` is the source of truth.  
**Never read all skills upfront** — they are loaded on demand, one domain at a time, to save tokens.

## Backlog and Definition of Done

Backlog management rules and the Definition of Done are owned by `Agents.md`. Do not duplicate or redefine them here.

## Code quality standard

Before writing any code, assess the approach:

- If it is a workaround, legacy pattern, or known anti-pattern for the language/context — say so first. Name it, explain why it is suboptimal, and state the professional alternative.
- If the better approach is feasible within the task scope, ask before defaulting to the weaker one.
- If the constraint forces the weaker approach (e.g. migration scope, compatibility), say so explicitly so the decision is visible.

This applies to every task. Do not silently write second-best code.

## Commands

Full operational reference is in `docs/OPERATIONS.md`. The most common dev commands:

```powershell
# Run tests
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest -k onboarding   # single area
.\.venv\Scripts\python.exe -m pytest -v               # verbose

# Start server (debug bypasses auth/CSRF)
python -m job_hunter_agent.fastapi_app --debug

# Run full pipeline
python -m job_hunter_agent.source_connector
python -m job_hunter_agent.source_connector --no-llm           # deterministic only
python -m job_hunter_agent.source_connector --rebuild-workspace # rebuild HTML, no scrape

# DB bootstrap (once on first deploy or after a DB reset)
python -m job_hunter_agent.db_seed
python -m job_hunter_agent.db_seed --upgrade   # merge-safe knowledge update
```

Local server: `http://localhost:8765/`. Key routes: `/start` (onboarding), `/settings`, `/workspace`, `/swagger-ui`.

## Architecture

### Pipeline

```
scrape (SEEK / LinkedIn)
  → source normalization + dedup (job_identity.py)
  → hard blockers (hard_blocker_rules.py)
  → title analysis (role_analysis.py)
  → capability matching (capability_matching.py)
  → description evaluation (filters.py, description_trust.py)
  → optional LLM fit review (llm_gate.py)
  → fit scoring (fit_scoring.py)
  → workspace HTML (workspace_renderer.py)
```

Entry point: `source_connector.py` → `source_runner.py` → individual scrapers → `scrape_finalize.py`

### User context and data paths

Active user is resolved per HTTP request via a `ContextVar` in `user_context.py`; all path helpers in `paths.py` read from it. CLI/agent code must call `set_user_id()` before file operations. Calling any path helper without a user set raises `RuntimeError` — there is no silent fallback.

When auth is disabled (debug mode), the active user is explicitly set to `_local` (`LOCAL_USER_ID`).

**Per-user runtime state lives in SQLite** (`JOB_HUNTER_DB_PATH`):
- `user_profile` table — runtime candidate truth (capabilities, preferences, learning state); accessed via `profile_store.load_profile()` / `save_profile()`
- `job_history` table — viewed/applied/hidden state and dedup history
- `workspace_pool` / `run_stats` / `audit_records` / `review_data` tables — scrape run outputs (disposable, rebuildable)

**Filesystem outputs** (per-user):
- `data/users/<user_id>/workspace_results.html` — rendered job shortlist

**Global (non-user) state**:
- `data/config/global_settings.json` — admin-controlled runtime settings seed (committed to git)
- `data/knowledge/*.json` — approved business rules; seeded into the `knowledge` DB table via `db_seed.py`
- `data/signals/signal_registry.json` — pending signals awaiting user review (gitignored; created at runtime)

`paths.py` is the single source of truth for all file and DB locations.

### FastAPI server

`fastapi_app.py` wires the ASGI app. Route handlers live in `job_hunter_agent/routes/`:
- `pages.py` — workspace, settings, global-settings, onboarding HTML pages
- `workspace_api.py` — workspace data and job state API
- `signals.py` — signal review and approval
- `review.py` — review insights
- `onboarding_api.py` — onboarding flow
- `auth_google.py` — Google OAuth flow
- `scrape_debug.py` — debug/diagnostics endpoints

Settings HTML is assembled from partials at `templates/partials/settings/standard/` (per-user) and `templates/partials/settings/global/` (admin). The shell templates use `__JOB_HUNTER_SETTINGS_SECTION_*__` sentinels that `pages.py` replaces with the partial content.

### Job identity and deduplication

`job_identity.normalize_job_key()` is the **only** function that may produce canonical job keys (`source:id`, e.g. `seek:7945621`). Scrapers normalize keys immediately on ingestion. Confirmed duplicates are collapsed; potential duplicates are annotated and preserved.

### Learning and signal flow

Signals flow through `signal_registry.py` and sit in a pending state until the user approves them via the UI. Approval commits the signal to the appropriate knowledge entry in the DB. Unapproved signals never alter runtime filtering.

### Knowledge ownership

All business judgement (scoring weights, thresholds, blocker patterns, capability definitions) lives in `data/knowledge/*.json`, seeded into the DB `knowledge` table. The Python modules that consume these files are consumers only — they never embed fallback business values.

### Auth and CSRF

Google OAuth is the production auth path (`auth.py`). Sessions are cookie-based with HMAC signatures. CSRF tokens are required for all state-changing routes. Debug mode (`--debug` flag or `JOB_HUNTER_DISABLE_AUTH=true`) bypasses both for local development.
