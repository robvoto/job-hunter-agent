# Developer Guide

## Purpose

This file is for technical contributors.

Use it alongside:

- `SOUL.md` for project memory and product intent
- `docs/OPERATIONS.md` for runtime behavior
- `docs/USER_GUIDE.md` for the end-user flow

## Current Architecture

Core runtime code now lives under `job_hunter_agent/`.

Primary modules:

- `job_hunter_agent/local_server.py`
  Local web server for the admin console, dashboard, onboarding UI, and API endpoints.

- `job_hunter_agent/source_documents.py`
  Local source-pack persistence and source-document import into `profile.json`.

- `job_hunter_agent/profile_store.py`
  Default profile model, load/save, and patch behavior.

- `job_hunter_agent/profile_learning.py`
  Text-to-profile extraction helpers.

- `job_hunter_agent/cv_pipeline.py`
  Heuristic and LLM-assisted CV analysis and capability mapping.

- `job_hunter_agent/source_connector.py`
  Current source connector and dashboard renderer for SEEK and LinkedIn.

- `job_hunter_agent/scrapers/seek.py` / `job_hunter_agent/scrapers/linkedin.py`
  Source-specific extraction logic.

- `job_hunter_agent/filters.py`
  Deterministic title and content filtering.

- `job_hunter_agent/llm_gate.py`
  Optional constrained LLM decision step.

Compatibility launchers kept at the repo root:

- `local_server.py`
- `source_connector.py`
- `agent_runner.py`
- `test_runner.py`

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
- dashboard
- runtime profile

Do not rename major files casually unless there is time to clean the whole project consistently.

## Current Onboarding Flow

1. User visits `/start`
2. Uploads a detailed CV
3. Uploaded documents are saved into a local source pack under ignored paths
4. The source pack is imported into `data/profile.json`
5. Admin is then used to refine the runtime profile

## Current Runner Split

- `source_connector.py`
  Compatibility launcher for `job_hunter_agent/source_connector.py`.

- `agent_runner.py`
  Compatibility launcher for `job_hunter_agent/agent_runner.py`.

## Score Presentation

The dashboard now treats scoring as two separate layers:

- internal numeric score
  Used for ranking, shortlist thresholds, filters, and debug output.

- visible match band
  The normal dashboard shows four human-facing labels instead of a raw `/100`:
  `Strong match`, `Good match`, `Worth a look`, and `Stretch`.

Design intent:

- the numeric score is useful to the engine and to technical debugging
- the raw `/100` can mislead users into reading the score as a literal probability or percentage
- test mode may still show the raw score on cards for tuning work

Current band mapping:

- `80-100` -> `Strong match`
- `65-79` -> `Good match`
- `50-64` -> `Worth a look`
- `0-49` -> `Stretch`

Hard blockers:

- some dominant-signal clusters can now be configured as hard blockers
- when a role clearly leans into one of those specialist domains and the profile alignment is weak or partial, the role is rejected before the shortlist
- this is intended for domains that should be treated as effectively out of scope, not merely "slightly lower fit"

Detail-page safety:

- invalid detail fetches such as challenge pages are treated as unusable input, not as job descriptions
- successful full-detail fetches now persist `fit_source_text` into saved snapshots so later dashboard rebuilds and history reuse do not lose specialist gap evidence

## Current Product Boundary

Current implemented sources:

- SEEK
- LinkedIn

Design assumption:

- new sources should normalize into the same record shape used by the dashboard, review flow, history, and fit logic

## Safe Local State

Do not accidentally commit:

- `data/profile.json`
- `data/job_history.json`
- `data/llm_cache.json`
- `data/capability_profile.txt`
- `data/agent_settings.json`
- `data/agent_state.json`
- `data/llm_costs.jsonl`
- `data/application_inputs/`
- `data/application_materials.json`
- `TODO.txt`
- `.venv/`

## Testing Workflow

Use the repo test runner for repeatable local validation:

```powershell
python test_runner.py
```

The runner resolves the local virtualenv automatically when present and forwards normal pytest selectors such as `-k` and `-m`.
