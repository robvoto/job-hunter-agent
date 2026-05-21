# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start-of-task protocol

**Do this at the start of every task, in order:**

1. Read `AGENTS.md` — architecture, commands, non-negotiable rules, and the skills index.
2. Identify which domain(s) the task touches.
3. Read **only** the relevant `.skills/<domain>/SKILL.md` file(s) — not all of them.
4. Then plan and act.

**Never skip step 1.** `AGENTS.md` is the source of truth.  
**Never read all skills upfront** — they are loaded on demand, one domain at a time, to save tokens.

## Code quality standard

Before writing any code, assess the approach:

- If it is a workaround, legacy pattern, or known anti-pattern for the language/context — say so first. Name it, explain why it is suboptimal, and state the professional alternative.
- If the better approach is feasible within the task scope, ask before defaulting to the weaker one.
- If the constraint forces the weaker approach (e.g. migration scope, compatibility), say so explicitly so the decision is visible.

This applies to every task. Do not silently write second-best code.

## Commands

| Task | Command |
|---|---|
| Scrape + build workspace | `python -m job_hunter_agent.source_connector` |
| Rebuild workspace only | `python -m job_hunter_agent.source_connector --rebuild-workspace` |
| Local web UI | `python -m job_hunter_agent.fastapi_app` |
| Web UI (debug, no auth) | `python -m job_hunter_agent.fastapi_app --debug` |
| Daily agent | `python -m job_hunter_agent.agent_runner` |
| Run all tests | `python -m pytest` |
| Run a single test | `python -m pytest tests/test_<name>.py -k "<selector>" -v` |

**Scraper CLI flags:** `--no-llm`, `--debug`, `--rebuild-workspace`, `--reset-new-to-you`  
**Auth bypass:** `JOB_HUNTER_DISABLE_AUTH=true` env var (also set automatically by `--debug`)  
**Full flag reference:** `docs/OPERATIONS.md`

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

All per-user data lives under `data/users/<user_id>/`. The active user is resolved per HTTP request via a `ContextVar` in `user_context.py`, which all path helpers in `paths.py` read from. CLI/agent code must call `set_user_id()` explicitly before file operations.

When auth is disabled (debug mode), the active user is explicitly set to `_local` (`LOCAL_USER_ID`). There is no silent fallback — calling any path helper without a user set raises a `RuntimeError`. Key per-user files:
- `profile.json` — runtime candidate truth (capabilities, preferences, learning state)
- `job_history.json` — viewed/applied/hidden state and dedup history
- `settings.json` — per-user workspace settings
- `workspace_results.html` — rendered job shortlist

Global (non-user) data:
- `data/config/global_settings.json` — admin-controlled runtime settings
- `data/knowledge/*.json` — approved business rules (capability knowledge, hard blockers, scoring rules, etc.)
- `data/signals/signal_registry.json` — pending signals awaiting user review/approval

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

Signals flow through `signal_registry.py` and sit in a pending state until the user approves them via the UI. Approval commits the signal to the appropriate knowledge file (e.g. `capability_knowledge.json`, `hard_blocker_rules.json`). Unapproved signals never alter runtime filtering.

### Knowledge ownership

All business judgement (scoring weights, thresholds, blocker patterns, capability definitions) lives in `data/knowledge/*.json`. The Python modules that consume these files are consumers only — they never embed fallback business values. `paths.py` is the single source of truth for all file locations.

### Auth and CSRF

Google OAuth is the production auth path (`auth.py`). Sessions are cookie-based with HMAC signatures. CSRF tokens are required for all state-changing routes. Debug mode (`--debug` flag or `JOB_HUNTER_DISABLE_AUTH=true`) bypasses both for local development.
